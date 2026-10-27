"""ROM object meshes and vertex animation. No Qt/OpenGL dependencies.

References: structs.h:ObjectModel; object_models.c:model_anim_init;
src/hasm/obj_animate.s (the mapping is s16, despite its C pointer type).
Preview actors use initial node transforms; this does not execute game scripts.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

import numpy as np
from numpy.typing import NDArray

from src.core.level_model import (BATCH_STRUCT, VERTEX_DTYPE, TRIANGLE_DTYPE,
    Bounds, LevelModel, LevelModelSegment, ModelError, TextureInfo, TriangleBatchInfo, _readonly)
from src.core.objects import LevelObject, ObjectDatabase, ObjectDefinition
from src.core.rom import AssetType, DecompAssets, RomImage
from src.core.textures import (Texture, SpriteAsset, SpriteInstance, load_model_textures,
    load_sprite, load_texture, sprite_tiles)


@dataclass(frozen=True)
class ObjectModel:
    mesh: LevelModel
    animated_indices: NDArray[np.int16]
    animated_count: int
    raw_data: bytes

    @property
    def normal_vertex_count(self) -> int:
        """model_init_normals: lit groups and environment maps allocate normals."""
        segment = self.mesh.segments[0]
        return sum(end.vertices_offset-batch.vertices_offset
                   for batch, end in zip(segment.batches, (*segment.batches[1:], segment.terminal_batch))
                   if batch.misc_data != 255 or batch.flags & 0x8000)

    @property
    def uses_normals(self) -> bool:
        return self.normal_vertex_count > 0

    @classmethod
    def from_bytes(cls, data: bytes, model_id: int = 0) -> ObjectModel:
        if len(data) < 0x58:
            raise ModelError('Truncated ObjectModel header')
        size = struct.unpack_from('>I', data, 0x2C)[0]
        if not 0x58 <= size <= len(data):
            raise ModelError('ObjectModel fileSize outside asset')

        def span(offset: int, count: int, stride: int) -> memoryview:
            if count < 0 or offset < 0 or offset > size or count * stride > size-offset:
                raise ModelError('ObjectModel array outside fileSize')
            if count and offset < 0x58:
                raise ModelError('ObjectModel array overlaps header')
            return memoryview(data)[offset:offset+count*stride]

        tp, vp, fp = struct.unpack_from('>3I', data)
        nt, nv, nf, nb = struct.unpack_from('>4h', data, 0x22)
        if nv <= 0 or nb < 0:
            raise ModelError('ObjectModel has invalid vertex/batch count')
        textures = tuple(TextureInfo(*v) for v in struct.iter_unpack('>IBBBb', span(tp, nt, 8)))
        vertices = np.frombuffer(span(vp, nv, 10), dtype=VERTEX_DTYPE)
        triangles = np.frombuffer(span(fp, nf, 16), dtype=TRIANGLE_DTYPE)
        batches = tuple(TriangleBatchInfo(*v) for v in BATCH_STRUCT.iter_unpack(
            span(struct.unpack_from('>I', data, 0x38)[0], nb+1, 12)))
        if (batches[0].vertices_offset, batches[0].faces_offset) != (0, 0):
            raise ModelError('ObjectModel first batch must start at zero')
        if (batches[-1].vertices_offset, batches[-1].faces_offset) != (nv, nf):
            raise ModelError('ObjectModel sentinel counts disagree')
        indices = triangles['indices'].astype(np.uint32)
        colors = vertices['color'].copy()
        for batch, following in zip(batches, batches[1:]):
            if not (0 <= batch.vertices_offset <= following.vertices_offset <= nv
                    and 0 <= batch.faces_offset <= following.faces_offset <= nf):
                raise ModelError('ObjectModel invalid batch range')
            if batch.texture_index != 255 and batch.texture_index >= nt:
                raise ModelError('ObjectModel texture index outside table')
            faces = indices[batch.faces_offset:following.faces_offset]
            if faces.size and faces.max() >= following.vertices_offset-batch.vertices_offset:
                raise ModelError('ObjectModel face outside batch vertices')
            faces += batch.vertices_offset
            # Lit groups contain packed normals rather than baked RGB. Use a
            # neutral white material; game lighting/environment mapping is separate.
            if batch.misc_data != 255:
                colors[batch.vertices_offset:following.vertices_offset] = 255
        positions = _readonly(vertices['position'].astype(np.float32))
        bounds = Bounds.from_vertices(positions)
        segment = LevelModelSegment(0, positions, _readonly(vertices['color'].copy()),
            _readonly(colors), _readonly(indices), _readonly(triangles['flags'].copy()),
            _readonly(triangles['uv'].astype(np.int16)), batches[:-1], batches[-1],
            bounds, bounds, 0, 0, nb)
        mesh = LevelModel(model_id, (segment,), textures, (), bounds, bounds,
            _readonly(np.column_stack((positions, colors.astype(np.float32)/255))),
            segment.indices, size)
        n = struct.unpack_from('>h', data, 0x4A)[0]
        if n < 0 or n > nv:
            raise ModelError('Invalid animated vertex count')
        mapping = (np.frombuffer(span(struct.unpack_from('>I', data, 0x4C)[0], nv, 2), dtype='>i2').astype(np.int16)
                   if n else np.full(nv, -1, np.int16))
        if np.any(mapping < -1) or np.any(mapping >= n):
            raise ModelError('Animated vertex group outside mapping')
        for group in range(n):
            base = positions[mapping == group]
            if len(base) == 0 or np.any(base != base[0]):
                raise ModelError('Animated group has inconsistent base positions')
        return cls(mesh, _readonly(mapping), n, data)


@dataclass(frozen=True)
class AnimationClip:
    animation_id: int
    frame_count: int
    positions: NDArray[np.int16]  # group XYZ per keyframe, including interpolation endpoint
    raw_data: bytes

    @classmethod
    def from_bytes(cls, data: bytes, model: ObjectModel, animation_id: int = 0) -> AnimationClip:
        if len(data) < 4:
            raise ModelError('Truncated animation length')
        frames = struct.unpack_from('>I', data)[0]
        n = model.animated_count
        stride = 12+3*n
        expected = 4+12+6*n+(frames-1)*stride
        if n <= 0 or frames < 2 or expected > len(data) or len(data)-expected > 15 or any(data[expected:]):
            raise ModelError('Invalid animation frame count, data span or alignment')
        offsets = np.frombuffer(data, dtype='>i2', count=3*n, offset=16).reshape(n, 3).astype(np.int32)
        bases = np.array([model.mesh.segments[0].vertices[np.flatnonzero(model.animated_indices == g)[0]]
                          for g in range(n)], np.int32)
        positions = np.empty((frames, n, 3), np.int16)
        positions[0] = (bases+offsets).astype(np.int16)
        start = 16+6*n
        for frame in range(1, frames):
            delta = np.frombuffer(data, np.int8, 3*n, start+12+(frame-1)*stride).reshape(n, 3)
            positions[frame] = (positions[frame-1].astype(np.int32)+delta).astype(np.int16)
        return cls(animation_id, frames, _readonly(positions), data)

    def pose(self, model: ObjectModel, frame16: int) -> NDArray[np.float32]:
        """Match the assembly's signed deltas and 1/16-frame integer rounding."""
        frame16 = max(0, min(int(frame16), (self.frame_count-1)*16-1))
        frame, fraction = divmod(frame16, 16)
        a = self.positions[frame].astype(np.int32)
        # Recover signed8 increment, including s16 wrap at keyframe boundaries.
        delta = (self.positions[frame+1].astype(np.int32)-a).astype(np.int8).astype(np.int32)
        groups = (a+(delta*fraction >> 4)).astype(np.int16)
        vertices = model.mesh.segments[0].vertices.copy()
        moving = model.animated_indices >= 0
        vertices[moving] = groups[model.animated_indices[moving]]
        return vertices


class ObjectLibrary:
    def __init__(self, source: RomImage | DecompAssets) -> None:
        self.source = source
        self.models: dict[int, ObjectModel] = {}
        self.clips: dict[tuple[int, int], AnimationClip] = {}
        self.textures: dict[int, Texture] = {}
        if isinstance(source, RomImage):
            count = source.count(AssetType.OBJECT_MODELS)+1
            table = source.section(AssetType.ANIMATION_IDS)
        else:
            count = source.count(AssetType.OBJECT_MODELS)+1
            table = source.read_asset(AssetType.ANIMATION_IDS, 0)
        if len(table) < count*2:
            raise ModelError('Truncated model animation ID table')
        self.animation_ids = struct.unpack_from(f'>{count}h', table)
        if (self.animation_ids[0] != 0 or any(a > b for a,b in zip(self.animation_ids,self.animation_ids[1:]))
                or self.animation_ids[-1] > source.count(AssetType.OBJECT_ANIMATIONS)):
            raise ModelError('Invalid model animation ID ranges')

    def model(self, model_id: int) -> ObjectModel:
        if model_id not in self.models:
            model = ObjectModel.from_bytes(self.source.read_asset(AssetType.OBJECT_MODELS, model_id, decompress=True), model_id)
            load_model_textures(self.source, model.mesh, self.textures)
            self.models[model_id] = model
        return self.models[model_id]

    def clip_count(self, model_id: int) -> int:
        if not 0 <= model_id < len(self.animation_ids)-1:
            raise ModelError('Model outside animation ID table')
        return self.animation_ids[model_id+1]-self.animation_ids[model_id]

    def clip(self, model_id: int, clip_index: int) -> AnimationClip | None:
        count = self.clip_count(model_id)
        if count == 0:
            return None
        clip_index = min(max(clip_index, 0), count-1)
        key = model_id, clip_index
        if key not in self.clips:
            animation_id = self.animation_ids[model_id]+clip_index
            self.clips[key] = AnimationClip.from_bytes(self.source.read_asset(
                AssetType.OBJECT_ANIMATIONS, animation_id, decompress=True), self.model(model_id), animation_id)
        return self.clips[key]


@dataclass(frozen=True)
class ModelInstance:
    object_index: int
    definition: ObjectDefinition
    model_id: int
    position: tuple[float, float, float]
    scale: float
    angles: tuple[float, float, float]  # yaw, pitch, roll radians
    clip_index: int = 0
    initial_frame: int = 0
    frame_speed: float = 1.0  # raw sixteenths per 60 Hz tick; preview for ordinary actors
    sampled_frame: float | None = None  # cinematic timeline, in source sixteenths
    visible: bool = True

    @property
    def transform(self) -> NDArray[np.float32]:
        """Transpose of math_util.c:mtxf_from_transform (column-vector GL)."""
        y,x,z = self.angles
        sy,sx,sz = math.sin(y),math.sin(x),math.sin(z)
        cy,cx,cz = math.cos(y),math.cos(x),math.cos(z)
        matrix = np.eye(4, dtype=np.float32)
        matrix[:3,:3] = np.array(((sx*sy*sz+cz*cy, sx*sy*cz-sz*cy, cx*sy),
            (sz*cx, cz*cx, -sx), (sx*cy*sz-cz*sy, sx*cy*cz+sz*sy, cx*cy)), np.float32)*self.scale
        matrix[:3,3] = self.position
        return matrix


# Physical model behaviors present in the maps; helpers reference debug meshes
# and must remain gizmos. object_functions.c contains their individual init rules.
PHYSICAL_MODELS: frozenset[int] = frozenset((2,12,14,31,36,38,50,57,62,64,67,74,79,93,95,99,100,109,111))


def animation_sprites(source: RomImage | DecompAssets, objects: tuple[LevelObject,...], database: ObjectDatabase,
                      channel: int, sprites: dict[int,SpriteAsset], textures: dict[int,Texture]) -> tuple[SpriteInstance,...]:
    result: list[SpriteInstance] = []
    from src.core.cinematics import build_tracks
    owners = {track.owner: track.target for track in build_tracks(objects, database, channel)}
    for index,obj in enumerate(objects):
        if index not in owners or owners[index] is None:
            continue
        definition = owners[index]
        if definition.model_type != 1 or not definition.model_ids:
            continue
        sprite_id = definition.model_ids[0]
        if sprite_id not in sprites:
            sprites[sprite_id] = load_sprite(source,sprite_id)
        sprite = sprites[sprite_id]
        for texture_id in range(sprite.base_texture_id,sprite.base_texture_id+sprite.frame_offsets[-1]):
            if texture_id not in textures:
                textures[texture_id] = load_texture(source,texture_id,asset_type=AssetType.TEXTURES_2D)
        frames = tuple(sprite_tiles(sprite,textures,frame) for frame in range(sprite.frame_count))
        scale = definition.scale*max(int(obj.value('scale',64)),1)/64
        initial = int(obj.value('unk16',0))
        result.append(SpriteInstance(index,sprite_id,obj.position,scale,frames[0],frames,float(obj.value('objAnimSpeed',0)),initial))
    return tuple(result)


def model_instances(objects: tuple[LevelObject,...], database: ObjectDatabase, channel: int = 0) -> tuple[ModelInstance,...]:
    result: list[ModelInstance] = []
    from src.core.cinematics import build_tracks
    owners = {track.owner: track.target for track in build_tracks(objects, database, channel)}
    for index,obj in enumerate(objects):
        definition = obj.definition
        behavior = definition.behavior_id
        actor = behavior == 49
        if actor:
            if index not in owners or owners[index] is None:
                continue
            definition = owners[index]
            if definition.behavior_id == 51:
                continue
        elif behavior not in PHYSICAL_MODELS:
            continue
        if definition.model_type != 0 or not definition.model_ids:
            continue
        selection = int(obj.value('modelIndex',0)) if not actor else 0
        if behavior == 109:
            selection = int(bool(obj.value('drumstick',0)))
        if not 0 <= selection < len(definition.model_ids):
            selection = 0
        scale = definition.scale
        yaw = obj.yaw or 0.0
        pitch = roll = 0.0
        if actor:
            scale *= max(int(obj.value('scale',64)),1)/64
            yaw,pitch,roll = (int(obj.value(k,0))*math.tau/256 for k in ('y_rotation','x_rotation','z_rotation'))
        elif behavior in (2,57,67,93,99,100):
            scale *= max(int(obj.value('radius',64)),10)/64
        elif behavior == 14:
            scale *= max(int(obj.value('scale',64)),10)/64
            yaw = int(obj.value('closedRotation',0))*math.tau/64
        result.append(ModelInstance(index,definition,definition.model_ids[selection],obj.position,scale,(yaw,pitch,roll),
            int(obj.value('objAnimIndex',0)) if actor else 0, int(obj.value('unk16',0)) if actor else 0,
            float(obj.value('objAnimSpeed',1)) if actor else 1.0))
    return tuple(result)


def ray_model_distance(origin: NDArray[np.float32], direction: NDArray[np.float32],
                       vertices: NDArray[np.float32], indices: NDArray[np.uint32]) -> float | None:
    """Double-sided Möller–Trumbore picking of the displayed pose."""
    if len(indices) == 0:
        return None
    a,b,c = vertices[indices].transpose(1,0,2)
    e1,e2 = b-a,c-a
    p = np.cross(direction,e2); det = np.einsum('ij,ij->i',e1,p)
    valid = np.abs(det) > 1e-7
    inv = np.divide(1.,det,out=np.zeros_like(det),where=valid)
    t = origin-a; u = np.einsum('ij,ij->i',t,p)*inv
    q = np.cross(t,e1); v = q@direction*inv
    distance = np.einsum('ij,ij->i',e2,q)*inv
    valid &= (u >= 0) & (v >= 0) & (u+v <= 1) & (distance > 0)
    return float(distance[valid].min()) if valid.any() else None


def preview_colors(model: ObjectModel, pose: NDArray[np.float32]) -> NDArray[np.float32]:
    """Neutral preview light, using the source's smoothing groups (not game lighting)."""
    segment = model.mesh.segments[0]
    colors = segment.render_colors.astype(np.float32)/255
    # model_init_normals joins coincident vertices only within the same group;
    # 0xFE is unsmoothed and 0xFF uses baked vertex colors.
    groups = np.full(len(pose),-1,np.int32)
    keys: dict[tuple[float,...],int] = {}
    cursor = 0
    for batch,following in zip(segment.batches,(*segment.batches[1:],segment.terminal_batch)):
        if batch.misc_data == 255:
            continue
        for index in range(batch.vertices_offset,following.vertices_offset):
            key = (*segment.vertices[index],batch.misc_data) if batch.misc_data < 254 else (float(index),)
            if key not in keys:
                keys[key] = cursor
                cursor += 1
            groups[index] = keys[key]
    if cursor:
        faces = pose[segment.indices]
        normals = np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        lengths = np.linalg.norm(normals,axis=1,keepdims=True)
        normals = np.divide(normals,lengths,out=np.zeros_like(normals),where=lengths>0)
        summed = np.zeros((cursor,3),np.float32)
        for corner in range(3):
            mapping = groups[segment.indices[:,corner]]
            valid = mapping >= 0
            np.add.at(summed,mapping[valid],normals[valid])
        lengths = np.linalg.norm(summed,axis=1,keepdims=True)
        summed = np.divide(summed,lengths,out=np.zeros_like(summed),where=lengths>0)
        light = np.array([.4,.7,-.5],np.float32)
        light /= np.linalg.norm(light)
        shade = .4+.6*np.maximum(0,summed@light)
        colors[groups>=0,:3] *= shade[groups[groups>=0],None]
    return colors
