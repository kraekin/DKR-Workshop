"""Preview meshes built by object_functions.c and tracks.c, never saved assets.

Texture IDs come from the loaded ObjectHeaders. Geometry is the source's small
procedural construction, not an embedded extraction. See docs/SPECIAL_ARTWORK.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

import numpy as np
from numpy.typing import NDArray

from src.core.level_model import LevelModel, _readonly
from src.core.objects import LevelObject, ObjectDefinition
from src.core.rom import AssetType, DecompAssets, RomImage, read_json
from src.core.textures import Texture, TextureFrame, load_texture

FloatArray = NDArray[np.float32]
IndexArray = NDArray[np.uint32]
SPECIAL_BEHAVIORS = frozenset((3, 47, 61, 82))
PORTRAIT_NAMES = ('Krunch', 'Bumper', 'Tiptup', 'Conker', 'Timber', 'Banjo',
                  'Drumstick', 'Pipsy', 'T.T.', 'Diddy')

# Both animals use two joined strips, with explicit opposite-winding faces.
_FRONT = np.array(((0, 3, 1), (0, 2, 3), (2, 5, 3), (2, 4, 5)), np.uint32)
_ANIMAL_INDICES = _readonly(np.concatenate((_FRONT, _FRONT[:, (0, 2, 1)])))


def artwork_note(behavior: int) -> str:
    return {
        3: 'Fish preview: deterministic home loop and tail. Random starting phase, depth wandering and multiplayer removal are not simulated.',
        61: 'Butterfly preview: idle wing animation at the stored position. Racer pursuit, attraction targets and flight are runtime-dependent.',
        47: 'Portrait sample: choose a character in the Special artwork toolbar. The game uses the character of this player slot.',
        82: 'Ground zipper: texture projected onto eligible track faces within its header height range. Game distance fading and lighting are not simulated.',
        89: 'Runtime only: boost graphics attach to a live racer and use its vehicle, character, boost strength and generated trail geometry. No standalone placed mesh.',
    }.get(behavior, '')


@dataclass(frozen=True, eq=False)
class SpecialInstance:
    object_index: int
    kind: str
    texture: TextureFrame
    vertices: FloatArray
    indices: IndexArray
    uvs: FloatArray  # normalized per triangle corner, canonical stored rows
    position: tuple[float, float, float]
    scale: tuple[float, float, float] = (1., 1., 1.)
    yaw: float = 0.
    radius: float = 0.
    speed: float = 0.
    variant: int = 0
    alpha: float = 1.

    def pose(self, seconds: float) -> FloatArray:
        """Absolute time makes pause, scrub and rewind independent of frame rate."""
        vertices = self.vertices.copy()
        position = np.array(self.position, np.float32)
        yaw = self.yaw
        ticks = max(seconds, 0.) * 60.
        if self.kind == 'butterfly':
            frame = 120 if self.variant == 2 else int(ticks) & 255
            angle = frame * (256 if self.variant == 2 else 128) * math.tau / 65536
            x = abs(math.floor(math.sin(angle) * 32767) >> 10)
            y = math.floor(math.cos(angle) * 32767) >> 10
            if self.variant != 2:
                y = abs(y)
            vertices[(0, 1), 0] = -x
            vertices[(4, 5), 0] = x
            vertices[(0, 1, 4, 5), 1] = y
        elif self.kind == 'fish':
            # The game randomizes the initial phase; use its non-random init
            # phase 0x4000, keep the stored Y and omit random depth wandering.
            phase = math.pi / 2 + ticks * self.speed * 16 * math.tau / 65536
            x, z = math.sin(phase * 2) * self.radius, math.cos(phase) * self.radius
            s, c = math.sin(self.yaw), math.cos(self.yaw)
            position += (x*c+z*s, 0., z*c-x*s)
            dx, dz = 2*math.cos(phase*2), -math.sin(phase)
            if self.radius and self.speed:
                yaw = math.atan2(-(dx*c+dz*s), -(dz*c-dx*s))
            distance = abs(self.radius) * abs(_arc(phase) - _arc(math.pi/2))
            tail = int(math.sin(distance * 0x600 * math.tau / 65536) * 32767) >> 3
            angle = tail * math.tau / 65536
            vertices[(4, 5), 0] = vertices[(2, 3), 0] + int(math.sin(angle)*32)
            vertices[(4, 5), 2] = vertices[(2, 3), 2] + int(math.cos(angle)*32)
        # Yaw-only column transform from math_util.c:mtxf_from_transform.
        # render_misc_model's scaleY scales local Y before rotation.
        s, c = math.sin(yaw), math.cos(yaw)
        rotation = np.array(((c, 0., s), (0., 1., 0.), (-s, 0., c)), np.float32)
        return np.ascontiguousarray((vertices * self.scale) @ rotation.T + position, np.float32)


# Numerically integrate one unit-radius source figure-eight. This only controls
# tail phase; positions use the source's analytic sine/cosine path above.
_PHASES = np.linspace(0., math.tau, 2049)
_SPEEDS = np.sqrt(4*np.cos(2*_PHASES)**2 + np.sin(_PHASES)**2)
_ARC = np.concatenate(([0.], np.cumsum((_SPEEDS[:-1]+_SPEEDS[1:])*.5*math.tau/2048)))


def _arc(phase: float) -> float:
    cycles, fraction = divmod(phase, math.tau)
    return float(cycles*_ARC[-1] + np.interp(fraction, _PHASES, _ARC))


def _animal(texture: TextureFrame, fish: bool) -> tuple[FloatArray, IndexArray, FloatArray]:
    if fish:
        vertices = np.array([(0, y, z) for z in (-64, 32, 64) for y in (64, -64)], np.float32)
        uv = np.array([(u, v) for u in (4, 1, 0) for v in (0, 4)], np.float32)/4
    else:
        vertices = np.array([(x, 0, z) for x in (-64, 0, 64) for z in (32, -32)], np.float32)
        uv = np.array([(u, v) for u in (0, 1, 0) for v in (0, 1)], np.float32)
    h = texture.header
    # Source multiplies/masks by (dimension-1)<<5, then material_set samples
    # raw stored rows. No PNG convenience flip belongs in rendering.
    uv *= ((h.width-1)/h.width, (h.height-1)/h.height)
    return _readonly(vertices), _ANIMAL_INDICES, _readonly(uv[_ANIMAL_INDICES])


@dataclass(frozen=True)
class ShadowSpec:
    scale: float
    texture_id: int
    bottom: int
    top: int


def shadow_spec(source: RomImage | DecompAssets, definition: ObjectDefinition) -> ShadowSpec | None:
    if definition.raw_data is not None:
        raw = definition.raw_data
        group, texture_id = struct.unpack_from('>2h', raw, 0x32)
        scale = struct.unpack_from('>f', raw, 4)[0]
        bottom, top = struct.unpack_from('>2h', raw, 0x42)
    elif isinstance(source, DecompAssets):
        document = read_json(source.entry_path(AssetType.OBJECTS, definition.header_id))
        group = document.get('shadow-group', 0)
        scale = document.get('shadow-scale', 0.)
        unknown = document.get('unknown', {})
        texture_id, bottom, top = (unknown.get(key, 0) for key in ('unk34', 'unk42', 'unk44'))
    else:
        return None
    if type(group) is not int:
        raise ValueError('Invalid ground zipper shadow group')
    if not group:
        return None
    if type(scale) in (int, float) and scale == 0:
        return None  # Runtime skips zero-scale shadows; global properties can disable an existing projection.
    if (type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0 or
            type(texture_id) is not int or not -32768 <= texture_id <= 65535 or
            type(bottom) is not int or type(top) is not int or not -32768 <= bottom <= top <= 32767):
        raise ValueError('Invalid ground zipper shadow dimensions/reference')
    return ShadowSpec(float(scale), texture_id & 0xFFFF, int(bottom), int(top))


def _clip(polygon: FloatArray, axis: int, edge: float, sign: int) -> FloatArray:
    """Sutherland–Hodgman in XZ, interpolating Y on the original facet."""
    result: list[FloatArray] = []
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        da, db = (float(a[axis])-edge)*sign, (float(b[axis])-edge)*sign
        if da >= 0:
            result.append(a)
        if (da >= 0) != (db >= 0):
            result.append(a + (b-a)*(da/(da-db)))
    return np.asarray(result, np.float32).reshape(-1, 3)


def projected_zipper(model: LevelModel, obj: LevelObject, spec: ShadowSpec,
                     texture: TextureFrame, index: int) -> SpecialInstance | None:
    half = spec.scale * max(int(obj.value('scale', 64)), 10)/64 * 10
    x, y, z = obj.position
    vertices: list[FloatArray] = []
    indices: list[tuple[int, int, int]] = []
    highest = -32768.
    for segment in model.segments:
        bounds = segment.geometry_bounds
        if (bounds.maximum[0] < x-half or bounds.minimum[0] > x+half or
                bounds.maximum[2] < z-half or bounds.minimum[2] > z+half):
            continue
        for batch, following in zip(segment.batches, (*segment.batches[1:], segment.terminal_batch)):
            if batch.flags & (0x100 | 0x800 | 0x2000 | 0x4000):
                continue
            triangles = segment.vertices[segment.indices[batch.faces_offset:following.faces_offset]]
            if not len(triangles):
                continue
            low, high = triangles.min(axis=1), triangles.max(axis=1)
            candidates = triangles[(low[:, 0] <= x+half) & (high[:, 0] >= x-half) &
                (low[:, 2] <= z+half) & (high[:, 2] >= z-half) &
                (low[:, 1] <= y+spec.top) & (high[:, 1] >= y+spec.bottom)]
            for triangle in candidates:
                normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
                if abs(float(normal[1])) < 1e-6:
                    continue
                # tracks.c:func_800304C8 uses the highest center-covering facet
                # to scale/fade the projected image with height.
                edges = np.roll(triangle, -1, axis=0)-triangle
                side = (x-triangle[:, 0])*edges[:, 2] - (z-triangle[:, 2])*edges[:, 0]
                if np.all(side >= 0) or np.all(side <= 0):
                    highest = max(highest, float(triangle[0, 1] -
                        (normal[0]*(x-triangle[0, 0])+normal[2]*(z-triangle[0, 2]))/normal[1]))
                polygon = triangle
                for axis, edge, sign in ((0, x-half, 1), (0, x+half, -1), (2, z-half, 1), (2, z+half, -1)):
                    polygon = _clip(polygon, axis, edge, sign)
                    if len(polygon) < 3:
                        break
                if len(polygon) < 3:
                    continue
                start = len(vertices)
                vertices.extend(polygon)
                indices.extend((start+i, start+i+1, start) for i in range(1, len(polygon)-1))
    if not indices:
        return None
    xyz = np.asarray(vertices, np.float32)
    yaw = int(obj.value('angleY', 0))*math.tau/64  # U8_ANGLE_TO_U16 shifts by TEN
    dx, dz = xyz[:, 0]-x, xyz[:, 2]-z
    scale = texture.header.width*16/half*1.4142
    threshold = abs(spec.bottom*.125)
    height = y-highest
    alpha = 1.
    if threshold > 0:
        if height > threshold:
            alpha = max(0., 1.-int(255*(height-threshold)/(7*threshold))/255)
        if height > 0:
            scale *= 1.+.005*height
    uv = np.column_stack(((dx*math.cos(yaw)-dz*math.sin(yaw))*scale + texture.header.width*16,
                          (dz*math.cos(yaw)+dx*math.sin(yaw))*scale + texture.header.width*16))
    uv /= (32*texture.header.width, 32*texture.header.height)
    xyz[:, 1] += 2.  # near-distance surface offset in shadow_generate
    faces = _readonly(np.asarray(indices, np.uint32))
    return SpecialInstance(index, 'zipper', texture, _readonly(xyz), faces,
                           _readonly(uv[faces].astype(np.float32)), (0., 0., 0.), alpha=alpha)


class SpecialLibrary:
    def __init__(self, source: RomImage | DecompAssets) -> None:
        self.source = source
        self.textures: dict[tuple[AssetType, int], Texture] = {}

    def frame(self, section: AssetType, index: int) -> TextureFrame:
        key = section, index
        if key not in self.textures:
            self.textures[key] = load_texture(self.source, index, asset_type=section)
        return self.textures[key].frames[0]

    def instances(self, objects: tuple[LevelObject, ...], model: LevelModel | None,
                  portrait: int = 9) -> tuple[SpecialInstance, ...]:
        result: list[SpecialInstance] = []
        for index, obj in enumerate(objects):
            d = obj.definition
            behavior = d.behavior_id
            if behavior == 82 and model is not None:
                spec = shadow_spec(self.source, d)
                if spec is not None:
                    section = AssetType.TEXTURES_3D if spec.texture_id & 0x8000 else AssetType.TEXTURES_2D
                    item = projected_zipper(model, obj, spec, self.frame(section, spec.texture_id & 0x7FFF), index)
                    if item is not None:
                        result.append(item)
            elif behavior in (3, 61, 47) and d.model_type == 4 and d.model_ids:
                selected = int(obj.value('unkB' if behavior == 3 else 'unkA', 0))
                if behavior == 47:
                    if portrait < 0:
                        continue
                    selected = portrait
                if not 0 <= selected < len(d.model_ids):
                    selected = 0
                texture_id = d.model_ids[selected]
                section = AssetType.TEXTURES_3D if texture_id & 0x8000 else AssetType.TEXTURES_2D
                texture = self.frame(section, texture_id & 0x7FFF)
                if behavior == 47:
                    vertices = _readonly(np.array(((-256, 256, 0), (256, 256, 0),
                                                  (256, -256, 0), (-256, -256, 0)), np.float32))
                    faces = _readonly(np.array(((0, 1, 3), (1, 2, 3)), np.uint32))
                    uv = np.array(((0, 0), (1, 0), (1, 1), (0, 1)), np.float32)
                    uv *= ((texture.header.width-1)/texture.header.width, (texture.header.height-1)/texture.header.height)
                    scale = d.scale*max(int(obj.value('radius', 64)) & 255, 10)/64
                    result.append(SpecialInstance(index, 'portrait', texture, vertices, faces, _readonly(uv[faces]),
                        obj.position, (scale,)*3, int(obj.value('angleY', 0))*math.tau/64))
                else:
                    vertices, faces, uv = _animal(texture, behavior == 3)
                    scale = int(obj.value('unkC' if behavior == 3 else 'unkB', 100))*.01
                    result.append(SpecialInstance(index, 'fish' if behavior == 3 else 'butterfly', texture,
                        vertices, faces, uv, obj.position, (scale, scale*float(obj.value('unkD', 100))*.01 if behavior == 3 else scale, scale),
                        int(obj.value('unkF', 0))*math.tau/256 if behavior == 3 else 0.,
                        float(obj.value('unk8', 0)) if behavior == 3 else 0., float(obj.value('unkE', 0)), selected))
        return tuple(result)
