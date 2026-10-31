"""Read-only catalog artwork using the existing object/model/texture parsers.

ObjectHeader kinds/IDs: local structs.h:ObjectHeader, objects.c:spawn_object.
These are reference previews, not behavior initialization or a new asset writer.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

import numpy as np
from PIL import Image

from src.core.editing import EditSession
from src.core.level_model import Bounds
from src.core.object_models import ObjectLibrary, ObjectModel
from src.core.object_structure import ObjectTemplate
from src.core.objects import LevelObject, ObjectMap
from src.core.rom import AssetType, RomImage
from src.core.textures import Pixels, load_sprite, load_texture


def template_object(session: EditSession, template: ObjectTemplate) -> LevelObject:
    raw = template.raw(session)
    return ObjectMap.from_bytes(struct.pack('>I12x', len(raw))+raw,
                                session.database).objects[0]


@dataclass(frozen=True)
class CatalogArtwork:
    label: str
    note: str
    model: ObjectModel | None = None
    pixels: Pixels | None = None


class CatalogLibrary:
    """Dialog-owned resource cache; always reads the current project source."""

    def __init__(self, source: RomImage) -> None:
        self.source = source
        self.models = ObjectLibrary(source)
        self.images: dict[tuple[int, int], Pixels] = {}

    def artwork(self, obj: LevelObject) -> CatalogArtwork:
        definition = obj.definition
        if not definition.model_ids:
            return CatalogArtwork('Logic object', 'No standalone artwork is referenced. Use its marker in the course.')
        variant = int(obj.value('modelIndex', obj.value('balloonType', 0)))
        if definition.behavior_id == 109:
            variant = int(bool(obj.value('drumstick', 0)))
        if not 0 <= variant < len(definition.model_ids):
            variant = 0
        index = definition.model_ids[variant]
        kind = definition.model_type
        note = 'Reference artwork for the selected template. Game state can choose other variants or hide helpers.'
        if kind == 0:
            return CatalogArtwork(f'3D model {index} · variant {variant}', note, self.models.model(index))
        key = kind, index
        if kind in (1, 2):
            sprite = load_sprite(self.source, index)
            frame_index = next((i for i in range(sprite.frame_count)
                                if sprite.frame_offsets[i+1] > sprite.frame_offsets[i]), 0)
            if key not in self.images:
                frames = [load_texture(self.source, tid, asset_type=AssetType.TEXTURES_2D).frames[0]
                          for tid in sprite.texture_ids(frame_index)]
                if not frames:
                    return CatalogArtwork(f'Sprite {index}', 'This sprite has an empty first frame.')
                positions = [struct.unpack_from('>bb', frame.header.raw, 3) for frame in frames]
                left, top = min(x for x, _ in positions), min(y for _, y in positions)
                width = max(x+frame.header.width for (x, _), frame in zip(positions, frames))-left
                height = max(y+frame.header.height for (_, y), frame in zip(positions, frames))-top
                canvas = Image.new('RGBA', (width, height))
                for frame, (x, y) in zip(frames, positions):
                    canvas.alpha_composite(frame.to_image(), (x-left, y-top))
                self.images[key] = np.array(canvas, dtype=np.uint8)
            return CatalogArtwork(f'Sprite {index} · frame {frame_index}', note, pixels=self.images[key])
        if kind == 4:
            if key not in self.images:
                self.images[key] = load_texture(self.source, index & 0x7FFF,
                    asset_type=AssetType.TEXTURES_3D if index & 0x8000 else AssetType.TEXTURES_2D).frames[0].pixels
            return CatalogArtwork(f'Texture {index & 0x7FFF}',
                'Referenced texture only; procedural geometry and game-state substitutions are not simulated.',
                pixels=self.images[key])
        return CatalogArtwork('Runtime artwork', 'This object has no supported standalone artwork preview.')

    def thumbnail(self, artwork: CatalogArtwork, size: int = 96) -> Pixels | None:
        if not 16 <= size <= 256:
            raise ValueError('Catalog thumbnail size must be 16..256')
        if artwork.model is None:
            if artwork.pixels is None:
                return None
            image = Image.fromarray(artwork.pixels)
            image.thumbnail((size-8, size-8), Image.Resampling.NEAREST)
            canvas = Image.new('RGBA', (size, size))
            canvas.alpha_composite(image, ((size-image.width)//2, (size-image.height)//2))
            return np.array(canvas, dtype=np.uint8)
        return model_thumbnail(artwork.model, self.models, size)


def artwork_bounds(model: ObjectModel) -> Bounds:
    """Frame visible triangles; loose attachment rows must not dwarf the artwork."""
    seg = model.mesh.segments[0]
    used: list[int] = []
    for batch, end in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
        if not batch.hidden:
            for face in seg.indices[batch.faces_offset:end.faces_offset]:
                if len(set(map(int, face))) == 3:
                    used.extend(map(int, face))
    return Bounds.from_vertices(seg.vertices[sorted(set(used))]) if used else model.mesh.bounds


def model_thumbnail(model: ObjectModel, library: ObjectLibrary, size: int) -> Pixels:
    """Small orthographic textured thumbnail, with depth and cutout alpha.

    Pure NumPy/Pillow: no GL contexts or per-card widgets. The selected preview
    uses the normal renderer. Thumbnails omit game lighting and behavior motion.
    """
    seg = model.mesh.segments[0]
    yaw, pitch = math.radians(-130), math.radians(-25)
    forward = np.array((math.cos(yaw)*math.cos(pitch), math.sin(pitch), math.sin(yaw)*math.cos(pitch)))
    right = np.array((-math.sin(yaw), 0, math.cos(yaw)))
    up = np.cross(right, forward)
    xyz = seg.vertices @ np.stack((right, -up, forward)).T
    bounds = artwork_bounds(model)
    # Project the visible AABB corners, keeping one stable view for every card.
    corners = np.array([(x, y, z) for x in (bounds.minimum[0], bounds.maximum[0])
        for y in (bounds.minimum[1], bounds.maximum[1]) for z in (bounds.minimum[2], bounds.maximum[2])])
    projected = corners @ np.stack((right, -up, forward)).T
    lower, upper = projected.min(axis=0), projected.max(axis=0)
    scale = (size-12)/max(float(np.max(upper[:2]-lower[:2])), 1.)
    xyz[:, :2] = (xyz[:, :2]-(lower[:2]+upper[:2])*.5)*scale+size*.5
    output = np.zeros((size, size, 4), np.float64)
    depth = np.full((size, size), np.inf)
    batches = (*seg.batches, seg.terminal_batch)
    faces: list[tuple[float, int, int]] = []
    for b, (batch, end) in enumerate(zip(batches, batches[1:])):
        if batch.flags & 0x100:
            continue
        faces.extend((float(xyz[seg.indices[f], 2].mean()), b, f)
                     for f in range(batch.faces_offset, end.faces_offset))
    for _, b, f in sorted(faces, reverse=True):
        batch = seg.batches[b]
        ids = seg.indices[f]
        p = xyz[ids]
        low = np.maximum(np.floor(p[:, :2].min(axis=0)).astype(int), 0)
        high = np.minimum(np.ceil(p[:, :2].max(axis=0)).astype(int), size-1)
        if np.any(high < low):
            continue
        a, c = p[1, :2]-p[0, :2], p[2, :2]-p[0, :2]
        determinant = a[0]*c[1]-a[1]*c[0]
        if abs(determinant) < 1e-8:
            continue
        y, x = np.mgrid[low[1]:high[1]+1, low[0]:high[0]+1]
        dx, dy = x+.5-p[0, 0], y+.5-p[0, 1]
        u, v = (dx*c[1]-dy*c[0])/determinant, (a[0]*dy-a[1]*dx)/determinant
        weights = np.stack((1-u-v, u, v), axis=-1)
        z = weights @ p[:, 2]
        region = np.s_[low[1]:high[1]+1, low[0]:high[0]+1]
        mask = (weights.min(axis=-1) >= -1e-6) & (z <= depth[region]+1e-6)
        color = weights @ (seg.render_colors[ids].astype(np.float64)/255)
        if batch.texture_index != 255:
            texture = library.textures[model.mesh.textures[batch.texture_index].texture_id]
            frame = texture.frames[texture.frame_index(batch.texture_offset)]
            uv = weights @ (seg.uvs[f].astype(np.float64)/32)
            tx, ty = np.floor(uv[..., 0]).astype(int), np.floor(uv[..., 1]).astype(int)
            tx = np.clip(tx, 0, frame.header.width-1) if frame.header.clamp_u else tx % frame.header.width
            ty = np.clip(ty, 0, frame.header.height-1) if frame.header.clamp_v else ty % frame.header.height
            color *= frame.pixels[ty, tx]/255
        color = np.clip(color, 0, 1)
        mask &= color[..., 3] >= .1
        target = output[region]
        alpha = color[..., 3:4]
        out_alpha = alpha+target[..., 3:4]*(1-alpha)
        rgb = (color[..., :3]*alpha+target[..., :3]*target[..., 3:4]*(1-alpha))/np.maximum(out_alpha, 1e-12)
        composed = np.concatenate((rgb, out_alpha), axis=-1)
        target[mask] = composed[mask]
        depth[region][mask & (color[..., 3] >= .99)] = z[mask & (color[..., 3] >= .99)]
    return np.rint(output*255).astype(np.uint8)
