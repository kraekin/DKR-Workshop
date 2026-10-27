"""Lossless existing LevelModel material edits; no XYZ/topology/collision writes.

Sources: structs.h:565/574/601/618/693/737, enums.h:152,
tracks.c:1885/2831, textures_sprites.c:1450, hasm/collision.c:128.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import struct
import numpy as np

from src.core.level_model import LevelModel, SEGMENT_SIZE
from src.core.rom import RomImage, AssetType
from src.core.textures import TextureHeader, TextureFormat

SURFACES: tuple[str, ...] = ("Default / road", "Grass", "Sand", "Zip pad", "Stone", "Egg spawn",
                            "Egg 01", "Egg 02", "Egg 03", "Egg 04", "Frozen water", "Calm water",
                            "Taj pad", "Snow", "Wavy water", "Water (unknown F)", "Unknown 10",
                            "Invisible wall", "Unknown 12 (vehicle-dependent)")
# Do not expose wave/animation/envmap/light flags whose other data is not rebuilt.
BATCH_FLAGS: tuple[tuple[int, str], ...] = ((0x10, "Cutout"), (0x100, "Hidden"),
    (0x200, "No collision"), (0x800, "Decal"), (0x4000, "No shadow"), (0x08000000, "Vertex alpha"))
EDITABLE_BATCH_FLAGS = sum(mask for mask, _ in BATCH_FLAGS)


@dataclass(frozen=True)
class TextureReference:
    texture_id: int
    header: TextureHeader

    @property
    def translucent(self) -> bool:
        # material_init ORs these flags into the loaded TextureHeader.
        h = self.header
        return bool(h.flags & 4) or (h.format in (TextureFormat.RGBA16, TextureFormat.RGBA32, TextureFormat.CI4)
                                    and h.render_mode in (0, 2)) or h.format in (TextureFormat.IA4, TextureFormat.IA8, TextureFormat.IA16)

    @property
    def label(self) -> str:
        h = self.header
        return f"{self.texture_id} · {h.width}×{h.height} {h.format.name} · {'translucent' if self.translucent else 'opaque'}"


def texture_references(rom: RomImage) -> tuple[TextureReference, ...]:
    return tuple(TextureReference(i, TextureHeader.from_bytes(rom.read_asset(AssetType.TEXTURES_3D, i)))
                 for i in range(rom.count(AssetType.TEXTURES_3D)))


def _index(value: int, count: int, name: str) -> int:
    if type(value) is not int or not 0 <= value < count:
        raise ValueError(f"{name} must be in 0..{count - 1}")
    return value


def batch_for_face(model: LevelModel, segment: int, face: int) -> int:
    s = model.segments[_index(segment, len(model.segments), "Segment")]
    _index(face, s.triangle_count, "Triangle")
    for i, batch in enumerate(s.batches):
        end = (s.batches + (s.terminal_batch,))[i + 1].faces_offset
        if batch.faces_offset <= face < end:
            return i
    raise ValueError("Triangle is outside the batch ranges")


def slot_uses(model: LevelModel, slot: int) -> tuple[tuple[int, int, int], ...]:
    return tuple((s.index, i, (s.batches + (s.terminal_batch,))[i + 1].faces_offset - b.faces_offset)
                 for s in model.segments for i, b in enumerate(s.batches) if b.texture_index == slot)


def _offsets(model: LevelModel, segment: int) -> tuple[int, int, int]:
    _index(segment, len(model.segments), "Segment")
    start = struct.unpack_from(">I", model.raw_data, 4)[0] + segment * SEGMENT_SIZE
    vertices, faces, _, batches = struct.unpack_from(">4I", model.raw_data, start)
    return vertices, faces, batches


def editable_mask(model: LevelModel) -> np.ndarray:
    mask = np.zeros(len(model.raw_data), np.uint8)
    textures = struct.unpack_from(">I", model.raw_data)[0]
    mask[textures:textures + 8 * len(model.textures)] = 255
    for s in model.segments:
        vertices, faces, batches = _offsets(model, s.index)
        for i in range(s.vertex_count):
            mask[vertices + 10 * i + 6:vertices + 10 * i + 10] = 255
        for i in range(s.triangle_count):
            mask[faces + 16 * i] = 0x40
            mask[faces + 16 * i + 4:faces + 16 * i + 16] = 255
        for i in range(len(s.batches)):
            mask[batches + 12 * i] = 255
            mask[batches + 12 * i + 7] = 255
            mask[batches + 12 * i + 8:batches + 12 * i + 12] = np.frombuffer(struct.pack(">I", EDITABLE_BATCH_FLAGS), np.uint8)
    return mask


def _opaque(model: LevelModel, segment: int, batch: int, refs: Sequence[TextureReference]) -> bool:
    b = model.segments[segment].batches[batch]
    translucent = False if b.texture_index == 255 else refs[_index(model.textures[b.texture_index].texture_id, len(refs), "Texture ID")].translucent
    return (not translucent and not b.flags & 0x2000) or bool(b.flags & 0x800)


def texture_assignment_error(model: LevelModel, refs: Sequence[TextureReference], texture_id: int,
                             batches: Sequence[tuple[int, int]]) -> str | None:
    """Explain render-pass incompatibility without rebuilding a model per thumbnail.

    Final assignments still run through edit_materials/validate_material_edit.
    The same tracks.c opaque/decal rule used above applies to each affected batch.
    """
    ref = refs[_index(texture_id, len(refs), "Texture ID")]
    for segment, batch in batches:
        b = model.segments[segment].batches[batch]
        candidate = (not ref.translucent and not b.flags & 0x2000) or bool(b.flags & 0x800)
        if _opaque(model, segment, batch, refs) != candidate:
            return (f'Segment {segment}, batch {batch}: this texture changes the opaque/translucent '
                    'rendering pass. Choose a compatible material; batch ordering is protected.')
    return None


def validate_material_edit(original: bytes, updated: bytes, refs: Sequence[TextureReference]) -> LevelModel:
    if len(original) != len(updated):
        raise ValueError("Material edits must retain the complete inflated model length")
    base = LevelModel.from_bytes(original)
    delta = np.bitwise_xor(np.frombuffer(original, np.uint8), np.frombuffer(updated, np.uint8))
    if np.any(delta & ~editable_mask(base)):
        raise ValueError("Edit changes protected geometry, counts, offsets, collision, bounds, metadata or flag bits")
    new = LevelModel.from_bytes(updated)
    for old, info in zip(base.textures, new.textures):
        if info.surface_type != old.surface_type and not 0 <= info.surface_type < len(SURFACES):
            raise ValueError("New surface assignments must use verified codes 0..18")
        ref = refs[_index(info.texture_id, len(refs), "Texture ID")]
        if info.texture_id != old.texture_id:
            if (info.width, info.height, info.format) != (ref.header.width, ref.header.height, ref.header.raw[2]):
                raise ValueError("Replacement texture metadata does not match its ROM header")
        elif (info.width, info.height, info.format) != (old.width, old.height, old.format):
            raise ValueError("Texture dimensions/format are derived from a reference; they cannot be changed independently")
    for s in base.segments:
        for i, old in enumerate(s.batches):
            if new.segments[s.index].batches[i].texture_index == 255 and old.texture_index != 255:
                raise ValueError("Cannot create untextured batches: the game's height-query path reads the texture slot without a 255 guard. Existing untextured batches are preserved.")
            if _opaque(base, s.index, i, refs) != _opaque(new, s.index, i, refs):
                raise ValueError(f"Segment {s.index}, batch {i}: replacement changes the opaque/translucent pass. Choose a compatible texture/slot; batch ordering is protected.")
    return new


@dataclass(frozen=True)
class MaterialEdit:
    kind: str
    location: tuple[int, ...]
    value: int | tuple[int, ...]


def edit_materials(raw: bytes, edits: Sequence[MaterialEdit], refs: Sequence[TextureReference],
                   *, original: bytes | None = None) -> bytes:
    """One atomic operation, patched into original byte spans without reserialization."""
    model = LevelModel.from_bytes(raw)
    out = bytearray(raw)
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for edit in edits:
        identity = edit.kind, edit.location
        if identity in seen:
            raise ValueError("Duplicate material field in one operation")
        seen.add(identity)
        if edit.kind in ("texture", "surface"):
            if len(edit.location) != 1:
                raise ValueError("Texture edit needs one existing slot")
            slot = _index(edit.location[0], len(model.textures), "Texture slot")
            offset = struct.unpack_from(">I", raw)[0] + 8 * slot
            if edit.kind == "texture":
                ref = refs[_index(edit.value, len(refs), "Texture ID")]
                if ref.texture_id == model.textures[slot].texture_id:
                    continue  # Do not normalize legacy metadata on a no-op.
                base_info = LevelModel.from_bytes(original).textures[slot] if original is not None else model.textures[slot]
                metadata = ((base_info.width, base_info.height, base_info.format) if ref.texture_id == base_info.texture_id
                            else (ref.header.width, ref.header.height, ref.header.raw[2]))
                struct.pack_into(">IBBB", out, offset, ref.texture_id, *metadata)
            else:
                struct.pack_into(">b", out, offset + 7, _index(edit.value, len(SURFACES), "Surface"))
            continue
        if len(edit.location) != 2:
            raise ValueError("Material edit needs a segment and existing row")
        segment = _index(edit.location[0], len(model.segments), "Segment")
        s = model.segments[segment]
        vertices, faces, batches = _offsets(model, segment)
        row = edit.location[1]
        try:
            if edit.kind == "color":
                offset = vertices + 10 * _index(row, s.vertex_count, "Vertex") + 6
                if not isinstance(edit.value, tuple) or len(edit.value) != 4 or any(type(v) is not int for v in edit.value):
                    raise ValueError("RGBA requires four byte integers")
                struct.pack_into(">4B", out, offset, *edit.value)
            elif edit.kind == "uv":
                offset = faces + 16 * _index(row, s.triangle_count, "Triangle") + 4
                if not isinstance(edit.value, tuple) or len(edit.value) != 6 or any(type(v) is not int for v in edit.value):
                    raise ValueError("UV requires six signed16 raw integers (32 units per texel)")
                struct.pack_into(">6h", out, offset, *edit.value)
            elif edit.kind == "backface":
                offset = faces + 16 * _index(row, s.triangle_count, "Triangle")
                if type(edit.value) is not int or edit.value not in (0, 1):
                    raise ValueError("Backface drawing must be 0 or 1")
                out[offset] = (out[offset] & ~0x40) | (0x40 if edit.value else 0)
            elif edit.kind in ("batch_texture", "frame", "flags"):
                offset = batches + 12 * _index(row, len(s.batches), "Batch")
                if edit.kind == "batch_texture":
                    value = 255 if edit.value == 255 and type(edit.value) is int else _index(edit.value, min(255, len(model.textures)), "Texture slot")
                    out[offset] = value
                elif edit.kind == "frame":
                    out[offset + 7] = _index(edit.value, 256, "Raw texture frame offset")
                else:
                    if type(edit.value) is not int or not 0 <= edit.value <= 0xFFFFFFFF:
                        raise ValueError("Flags must be an unsigned32 integer")
                    struct.pack_into(">I", out, offset + 8, edit.value)
            else:
                raise ValueError("Unsupported material operation")
        except struct.error as error:
            raise ValueError(str(error)) from error
    result = bytes(out)
    validate_material_edit(original if original is not None else raw, result, refs)
    return result


def material_changes(base: LevelModel, new: LevelModel) -> tuple[str, ...]:
    rows: list[str] = []
    for i, (a, b) in enumerate(zip(base.textures, new.textures)):
        if a != b:
            rows.append(f"Texture slot {i}: ID {a.texture_id} → {b.texture_id}; surface {a.surface_type} → {b.surface_type} ({len(slot_uses(new, i))} batch uses)")
    for a, b in zip(base.segments, new.segments):
        for i, (x, y) in enumerate(zip(a.batches, b.batches)):
            if x != y:
                rows.append(f"Segment {a.index} batch {i}: slot {x.texture_index} → {y.texture_index}; frame offset {x.texture_offset} → {y.texture_offset}; flags 0x{x.flags:08X} → 0x{y.flags:08X}")
        for i in np.flatnonzero(np.any(a.uvs != b.uvs, axis=(1, 2))):
            rows.append(f"Segment {a.index} triangle {i} UV: {a.uvs[i].tolist()} → {b.uvs[i].tolist()}")
        for i in np.flatnonzero(a.triangle_flags != b.triangle_flags):
            rows.append(f"Segment {a.index} triangle {i} flags: 0x{a.triangle_flags[i]:02X} → 0x{b.triangle_flags[i]:02X}")
        for i in np.flatnonzero(np.any(a.colors != b.colors, axis=1)):
            rows.append(f"Segment {a.index} vertex {i} RGBA: {a.colors[i].tolist()} → {b.colors[i].tolist()}")
    return tuple(rows)


def pick_track_face(model: LevelModel, origin: np.ndarray, direction: np.ndarray,
                    *, segment: int = -1, cull_backfaces: bool = False,
                    batch: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """Closest triangle from visible batches, respecting optional backface culling."""
    if not np.all(np.isfinite(origin)) or not np.all(np.isfinite(direction)) or np.linalg.norm(direction) < 1e-10:
        return None
    best: tuple[float, int, int] | None = None
    for s in model.segments:
        if segment >= 0 and segment != s.index:
            continue
        points = np.asarray(s.vertices[s.indices], np.float64)
        e1, e2 = points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]
        p = np.cross(direction, e2)
        det = np.einsum("ij,ij->i", e1, p)
        inv = np.divide(1., det, out=np.zeros_like(det), where=np.abs(det) > 1e-9)
        t = origin - points[:, 0]
        u = np.einsum("ij,ij->i", t, p) * inv
        q = np.cross(t, e1)
        v = q @ direction * inv
        distance = np.einsum("ij,ij->i", e2, q) * inv
        valid = (np.abs(det) > 1e-9) & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7) & (distance >= 0)
        if cull_backfaces:
            valid &= (det > 1e-9) | ((s.triangle_flags & 0x40) != 0)
        for i, b in enumerate(s.batches):
            if b.hidden or (batch is not None and batch != (s.index, i)):
                valid[b.faces_offset:(s.batches + (s.terminal_batch,))[i + 1].faces_offset] = False
        hits = np.flatnonzero(valid)
        if len(hits):
            face = int(hits[np.argmin(distance[hits])])
            candidate = float(distance[face]), s.index, face
            if best is None or candidate < best:
                best = candidate
    return best[1:] if best else None
