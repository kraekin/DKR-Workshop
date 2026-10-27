"""Saved environment defaults and deterministic preview math from local sources.

tracks.c, textures_sprites.c, object_functions.c:texscroll and waves.c are
authoritative. All results are transient; model/header bytes are never changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import struct

import numpy as np
from numpy.typing import NDArray

from src.core.level_header import LevelHeader
from src.core.level_model import LevelModel, TriangleBatchInfo, _readonly
from src.core.objects import LevelObject
from src.core.textures import Texture

FloatArray = NDArray[np.float32]
ScrollRates = dict[int, tuple[tuple[int, int], ...]]
WAVE_FLAGS = 0x2000 | 0x1000000


def fog_defaults(header: LevelHeader) -> tuple[float, float, tuple[float, float, float], bool]:
    f = header.fog
    enabled = any((f.near, f.far, *f.color))
    near, far = sorted((f.near, f.far))
    far = min(far, 1023)
    near = min(near, far-5)
    return float(near), float(far), tuple(v/255 for v in f.color), enabled


def fog_factor(distance: float, near: float, far: float) -> float:
    """gSPFogPosition and the game's CAMERA_NEAR=10/CAMERA_FAR=15000."""
    ndc = 15010/14990 - 300000/(14990*max(distance, .001))
    return float(np.clip((500*(ndc+1)-near)/(far-near), 0., 1.))


def texture_frame(texture: Texture, batch: TriangleBatchInfo, seconds: float) -> int:
    """track_tex_anim's discrete 60Hz updates, including ping-pong/reverse.

    Random-trigger bit23 batches retain the stored frame until game state starts
    them; the editor does not fabricate a random trigger. No flags are saved.
    """
    count = len(texture.frames)
    advance = texture.frames[0].header.frame_advance
    if (not batch.flags & 0x10000 or count <= 1 or not advance or
            batch.flags & 0x800000 and not batch.flags & 0x2000000):
        return texture.frame_index(batch.texture_offset)
    frames, start = _frame_cycle(count, advance, batch.texture_offset, batch.misc_data, batch.flags)
    tick = max(0, int(seconds*60))
    if tick >= len(frames):
        tick = start+(tick-start) % (len(frames)-start)
    return frames[tick]


@lru_cache(maxsize=2048)
def _frame_cycle(count: int, advance: int, offset: int, misc: int, flags: int) -> tuple[tuple[int, ...], int]:
    counter = offset << 6
    if flags & 0x80000000:
        counter |= misc & 63
    limit = count*256
    seen: dict[tuple[int, int], int] = {}
    frames: list[int] = []
    while (counter, flags & 0x6000000) not in seen:
        seen[counter, flags & 0x6000000] = len(frames)
        frames.append(min(counter >> 8, count-1) if counter < limit else 0)
        if flags & 0x800000 and not flags & 0x2000000:
            continue  # Waiting for a runtime random trigger.
        counter += -advance if flags & 0x4000000 else advance
        if flags & 0x800000:
            if counter >= limit:
                counter = 2*limit-counter-1
                flags |= 0x4000000
            if counter < 0:
                counter = 0
                flags &= ~0x6000000
        elif flags & 0x2000000:
            # tex_animate_texture reflects at -1 / limit, preserving endpoints.
            while counter < 0 or counter >= limit:
                if counter < 0:
                    counter = -counter
                    flags &= ~0x4000000
                if counter >= limit:
                    counter = 2*limit-counter-1
                    flags |= 0x4000000
        else:
            counter %= limit
        # Track stores only texOffset's high bits unless bit31 retains miscData.
        counter = ((counter >> 6) & 255) << 6 | (counter & 63 if flags & 0x80000000 else 0)
    # material_set takes texOffset<<14, selecting counter's high 8 bits.
    return tuple(frames), seen[counter, flags & 0x6000000]


@lru_cache(maxsize=32)
def _wave_grid(tiles: int, seed_size: int) -> NDArray[np.int32]:
    seed = int.from_bytes(b'WAVF', 'big')
    grid = np.empty((tiles, tiles, 2), np.int32)
    for row in grid.reshape(-1, 2):
        for component in (0, 1):
            signed = seed if seed < 0x80000000 else seed-0x100000000
            temp = (signed << 32) | (signed >> 1)
            temp ^= (signed & 0xFFFFF) << 12
            seed = (temp ^ ((temp >> 20) & 0xFFF)) & 0xFFFFFFFF
            row[component] = seed % seed_size
    return _readonly(grid)


def scroll_rates(objects: tuple[LevelObject, ...], slots: int) -> ScrollRates:
    result: ScrollRates = {}
    if not slots:
        return result
    for obj in objects:
        if obj.definition.behavior_id != 29:
            continue
        slot = min(max(int(obj.value('textureIndex', 0)), 0), slots-1)
        result[slot] = (*result.get(slot, ()), (int(obj.value('unkA', 0)), int(obj.value('unkB', 0))))
    return result


def scroll_delta(rates: tuple[tuple[int, int], ...], tick: int) -> FloatArray:
    """Each controller retains its own two fractional bits; sum after shifting."""
    return np.floor(np.asarray(rates, np.float64)*max(0, tick)/4).sum(axis=0).astype(np.float32)


def flashy_sky(header: LevelHeader, texture: Texture, camera: FloatArray, yaw: float, seconds: float) -> FloatArray:
    """tracks.c:trackbg_render_flashy plane/UVs; color cycling is omitted."""
    raw = header.raw_data
    if raw is None:
        return np.empty((0, 9), np.float32)
    h = texture.frames[0].header
    s, c = math.sin(math.radians(yaw+90)), math.cos(math.radians(yaw+90))
    xz = np.array(((-c-s, -c+s), (c-s, -c-s), (c+s, c-s), (-c+s, c+s), (0, 0),
                   (-c-2*s, s-2*c), (c-2*s, -2*c-s), (c+2*s, 2*c-s), (2*s-c, 2*c+s)), np.float32)*1280
    u, v = h.width*16*max(raw[0xA0], 1), h.height*16*max(raw[0xA1], 1)
    speeds = struct.unpack_from('>2b', raw, 0xA2)
    ticks = max(0, int(seconds*60))
    shifts = np.array((int(camera[0]*320/u)+(speeds[0]*ticks >> 4),
                       int(camera[2]*320/v)+(speeds[1]*ticks >> 4)))
    shifts &= (h.width*32-1, h.height*32-1)
    a, b = u*c, v*s
    uv = np.array(((-a-b, b-a), (a-b, -a-b), (a+b, a-b), (b-a, a+b), (0, 0),
                   (-a-2*b, b-2*a), (a-2*b, -2*a-b), (a+2*b, 2*a-b), (2*b-a, 2*a+b)))+shifts
    uv /= (h.width*32, h.height*32)
    xyz = np.column_stack((xz[:, 0]+camera[0], np.full(9, camera[1]+192), xz[:, 1]+camera[2]))
    colors = np.ones((9, 4), np.float32); colors[5:, 3] = 0
    indices = np.array(((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4),
                        (5, 6, 1), (1, 0, 5), (3, 2, 7), (7, 8, 3)))
    return np.ascontiguousarray(np.column_stack((xyz, colors, uv))[indices].reshape(-1, 9), np.float32)


@dataclass(frozen=True)
class WaveSettings:
    subdivisions: int
    tiles: int
    step0: int
    phase0: int
    height0: float
    step1: int
    phase1: int
    height1: float
    seed_size: int
    power: float
    texture_id: int
    uv_scale: tuple[int, int]
    uv_scroll: tuple[int, int]
    translucent: bool
    double_density: bool
    shade_strength: float

    @classmethod
    def from_header(cls, header: LevelHeader) -> WaveSettings | None:
        raw = header.raw_data
        if raw is None:
            return None  # Never infer absent structured JSON wave fields.
        subdivisions, tiles, step0, phase0, h0, step1, phase1, h1, size, power = struct.unpack_from('>4Bh2B3h', raw, 0x56)
        if not subdivisions or not tiles or size < 2:
            return None
        if subdivisions > 32 or tiles > 64 or size > 4096:
            raise ValueError('Wave preview settings exceed supported source grid bounds')
        texture = struct.unpack_from('>H', raw, 0x68)[0]
        return cls(subdivisions, tiles, step0, phase0, h0/256., step1, phase1, h1/256.,
            size & ~1, power/256., texture, tuple(raw[0x6A:0x6C]),
            struct.unpack_from('>2b', raw, 0x6C), bool(raw[0x70]), bool(raw[0x71]), struct.unpack_from('>h', raw, 0x66)[0]/256.)

    def heights(self, xz: FloatArray, seconds: float, origin: tuple[float, float],
                tile_size: tuple[float, float]) -> FloatArray:
        """Source sine table and seeded phase grid, with continuous grid blending.

        Omit the camera/racer-dependent edge dampening and swell emitters; these
        are explicitly an approximate water preview, not a physics simulation.
        """
        phases = np.arange(self.seed_size, dtype=np.float64)
        table = np.sin((self.phase0*256+phases*((self.step0 << 16)//self.seed_size))*math.tau/65536)*self.height0
        table += np.sin((self.phase1*256+phases*((self.step1 << 16)//self.seed_size))*math.tau/65536)*self.height1
        if self.double_density:
            table *= 2
        phase_grid = _wave_grid(self.tiles, self.seed_size)
        coords = (xz-origin)/np.maximum(tile_size, .001)*self.subdivisions*(2 if self.double_density else 1)
        base = np.floor(coords).astype(np.int32)
        fraction = coords-base
        result = np.zeros(len(xz), np.float64)
        ticks = max(0, int(seconds*60))
        for dx, dz in ((0, 0), (1, 0), (0, 1), (1, 1)):
            indices = phase_grid[(base[:, 1]+dz) % self.tiles, (base[:, 0]+dx) % self.tiles]
            heights = table[(indices[:, 0]+ticks) % self.seed_size]+table[(indices[:, 1]+ticks) % self.seed_size]
            weights = (fraction[:, 0] if dx else 1-fraction[:, 0])*(fraction[:, 1] if dz else 1-fraction[:, 1])
            result += weights*heights*self.power
        return result.astype(np.float32)


@dataclass(frozen=True, eq=False)
class WaterPreview:
    vertices: FloatArray  # expanded XYZ RGBA UV
    faces: tuple[tuple[int, int], ...]  # segment, batch
    settings: WaveSettings
    origin: tuple[float, float]
    tile_size: tuple[float, float]
    texture_id: int
    detail: Texture | None = None
    batch: TriangleBatchInfo | None = None

    def buffer(self, texture: Texture, seconds: float) -> FloatArray:
        result = self.vertices.copy()
        heights = self.settings.heights(result[:, (0, 2)], seconds, self.origin, self.tile_size)
        result[:, 1] += heights
        if self.settings.translucent:
            # waves.c:func_800B92F4's shade/alpha ramps. A fixed mid-intensity
            # sample replaces its camera-dependent noise/fade field.
            intensity = np.clip(128.+heights*self.settings.shade_strength, 0., 255.).astype(np.int32)
            shade = np.where(intensity < 192, 255., (255.-intensity)*4)/255
            result[:, 3:6] = shade[:, None]
            result[:, 6] = np.where(intensity < 64, intensity*4, 255.)/255
        h = texture.frames[0].header
        result[:, 7:9] += np.array(self.settings.uv_scroll)*max(0, int(seconds*60))/(32*np.array((h.width, h.height)))
        return result


def water_preview(model: LevelModel, settings: WaveSettings | None, textures: dict[int, Texture]) -> WaterPreview | None:
    if settings is None:
        return None
    entries: list[tuple[int, int]] = []
    buffers: list[FloatArray] = []
    first_segment = None
    texture_id = -1
    first_batch = None
    wave_segments: set[int] | None = None
    if model.raw_data:
        pointer = struct.unpack_from('>I', model.raw_data, 4)[0]
        wave_segments = {i for i in range(len(model.segments)) if model.raw_data[pointer+i*0x44+0x2B]}
    for segment in model.segments:
        if wave_segments is not None and segment.index not in wave_segments:
            continue
        for bi, (batch, following) in enumerate(zip(segment.batches, (*segment.batches[1:], segment.terminal_batch))):
            if batch.flags & (0x2000 | 0x100) != 0x2000 or batch.texture_index == 255:
                continue
            if first_segment is None:
                first_segment = segment
                texture_id = model.textures[batch.texture_index].texture_id
                first_batch = batch
            entries.append((segment.index, bi))
            extent = np.maximum(np.array(segment.bounds.maximum)-segment.bounds.minimum, 1)
            # Tessellate the stored triangles instead of inventing a full tile
            # outside their footprint. This preserves shoreline holes/materials.
            n = min(settings.subdivisions*(2 if settings.double_density else 1), 12)
            for fi in range(batch.faces_offset, following.faces_offset):
                triangle = segment.vertices[segment.indices[fi]]
                colors = segment.render_colors[segment.indices[fi]].astype(np.float32)/255
                for row in range(n):
                    for col in range(n-row):
                        weights = [np.array((1-(row+col)/n, row/n, col/n)),
                                   np.array((1-(row+col+1)/n, (row+1)/n, col/n)),
                                   np.array((1-(row+col+1)/n, row/n, (col+1)/n))]
                        if row+col < n-1:
                            weights.extend((weights[1], np.array((1-(row+col+2)/n, (row+1)/n, (col+1)/n)), weights[2]))
                        w = np.array(weights)
                        xyz = w@triangle
                        uv = (xyz[:, (0, 2)]-np.array(segment.bounds.minimum)[(0, 2),])/extent[(0, 2),]*settings.uv_scale
                        rgba = w@colors
                        if not settings.translucent:
                            rgba[:, 3] = 1
                        buffers.append(np.column_stack((xyz, rgba, uv)).astype(np.float32))
    if first_segment is None or not buffers:
        return None
    bounds = first_segment.bounds
    origin = bounds.minimum[0], bounds.minimum[2]
    size = max(bounds.maximum[0]-origin[0], 1.), max(bounds.maximum[2]-origin[1], 1.)
    return WaterPreview(_readonly(np.concatenate(buffers)), tuple(entries), settings, origin, size, texture_id, batch=first_batch)
