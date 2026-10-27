"""Lossless stock track reconstruction, before topology/import compilation.

Local sources: structs.h:601–763; tracks.c:1681,1885,2031,2832–3222.
The local buildLevelModel.cpp is raw pass-through and is not a compiler.
Typed records are packed into a fresh buffer; only intervening opaque spans are
copied. IEEE float fields in the header retain their exact stored bit patterns.
No new collision adjacency or visibility is inferred by stock reconstruction.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

import numpy as np

from src.core.compression import decompress_rare
from src.core.export_report import AssetDiff, ExportReport, make_export_report
from src.core.geometry import TRACK_HEAP, collision_base_planes, runtime_track_bytes, verify_geometry_stream
from src.core.level_header import load_level_catalog
from src.core.level_model import LevelModel
from src.core.rom import AssetTable, AssetType, RomImage

# Header minimap floats are serialized as their two u32 IEEE payloads.
HEADER = '>6I4hi2H2I4hI6hi'
SEGMENT = '>7I3h6BhbbI2hIh2BIB3B'
FORMATS: dict[str, str] = {
    'header': HEADER, 'segments': SEGMENT, 'textures': '>IBBBb',
    'vertices': '>hhhBBBB', 'triangles': '>BBBBhhhhhh',
    'batches': '>BbhhBBI', 'facets': '>4H', 'boxes': '>6h', 'bsp': '>hhBBh',
}


class RebuildError(ValueError):
    """A stock rebuild failed a layout, identity or runtime check."""


@dataclass(frozen=True)
class RecordBlock:
    kind: str
    offset: int
    format: str
    rows: tuple[tuple[int, ...], ...]
    segment: int = -1

    @property
    def byte_size(self) -> int:
        return struct.calcsize(self.format)*len(self.rows)


@dataclass(frozen=True)
class OpaqueSpan:
    offset: int
    data: bytes


@dataclass(frozen=True)
class StockDocument:
    model_id: int
    byte_size: int
    source_sha256: str
    records: tuple[RecordBlock, ...]
    opaque: tuple[OpaqueSpan, ...]


@dataclass(frozen=True)
class RuntimeSegment:
    grid_masks: tuple[int, ...]
    planes: np.ndarray
    facets: np.ndarray
    water_batches: tuple[int, ...]
    water_height: int


@dataclass(frozen=True)
class RuntimeTrack:
    segments: tuple[RuntimeSegment, ...]
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class StockRebuild:
    model_id: int
    raw: bytes
    packed: bytes
    sha256: str
    record_bytes: int
    opaque_bytes: int
    record_count: int
    vertices: int
    faces: int
    batches: int
    segments: int
    visibility_rows: int
    planes: int
    runtime_bytes: int
    runtime_sha256: str
    cutscene_bytes: int
    cutscene_sha256: str

    def to_text(self) -> str:
        return (
            f'Model {self.model_id}: PASS — rebuilt bytes match the original\n'
            f'  {self.segments} segments; {self.vertices:,} vertices; {self.faces:,} faces; {self.batches} batches\n'
            f'  {self.record_count:,} records / {self.record_bytes:,} bytes re-encoded; '
            f'{self.opaque_bytes:,} opaque bytes retained\n'
            f'  BSP / {self.visibility_rows} visibility rows and serialized facets retained exactly\n'
            f'  Runtime: {self.planes:,} planes, XZ grids, facet fixups and water indexes match\n'
            f'  Track heap: {self.runtime_bytes:,} / {TRACK_HEAP:,} bytes; '
            f'{TRACK_HEAP-self.runtime_bytes:,} bytes remaining\n'
            f'  Cutscene path: {self.cutscene_bytes:,} bytes; base-plane-only runtime data matches\n'
            f'  Recompressed: {len(self.packed):,} bytes; source-model in-place inflation passed\n'
            f'  Payload SHA-256: {self.sha256}\n'
            f'  Runtime data SHA-256: {self.runtime_sha256}'
        )


def decode_stock_track(raw: bytes, *, model_id: int = 0) -> StockDocument:
    """Decode stock records plus a disjoint complement of unsupported bytes."""
    if len(raw) > TRACK_HEAP:
        raise RebuildError('Inflated model exceeds the fixed track heap')
    model = LevelModel.from_bytes(raw, model_id=model_id)
    blocks: list[RecordBlock] = []

    def block(kind: str, offset: int, count: int, *, segment: int = -1,
              format: str | None = None) -> None:
        fmt = format or FORMATS[kind]
        stride = struct.calcsize(fmt)
        if count < 0 or offset < 0 or offset+count*stride > model.byte_size:
            raise RebuildError(f'{kind}: record span exceeds modelSize')
        if count:
            rows = tuple(struct.iter_unpack(fmt, raw[offset:offset+count*stride]))
            blocks.append(RecordBlock(kind, offset, fmt, rows, segment))

    pointers = struct.unpack_from('>6I', raw)
    block('header', 0, 1)
    block('textures', pointers[0], len(model.textures))
    block('segments', pointers[1], len(model.segments))
    block('boxes', pointers[2], len(model.segments))
    block('bsp', pointers[5], len(model.bsp_nodes))
    width = (len(model.segments)+7)//8
    leaves: set[int] = set()
    seen: set[int] = set()
    pending = [(0, 0, len(model.segments)-1)] if model.bsp_nodes else []
    while pending:
        index, low, high = pending.pop()
        if index in seen:
            raise RebuildError('BSP nodes are shared or cyclic')
        seen.add(index)
        node = model.bsp_nodes[index]
        if not low < node.segment_index <= high:
            raise RebuildError('BSP child ranges do not identify stock segments')
        for child, start, end in ((node.left_node, low, node.segment_index-1),
                                  (node.right_node, node.segment_index, high)):
            if child >= 0:
                pending.append((child, start, end))
            elif start == end and start not in leaves:
                leaves.add(start)
            else:
                raise RebuildError('BSP leaf does not identify one distinct segment')
    if model.bsp_nodes and (len(seen) != len(model.bsp_nodes) or len(leaves) != len(model.segments)):
        raise RebuildError('BSP does not cover all stock segments')
    for s in model.segments:
        start = pointers[1]+s.index*0x44
        vp, tp, _, bp, _, fp = struct.unpack_from('>6I', raw, start)
        visibility = struct.unpack_from('>h', raw, start+0x28)[0]
        if visibility < 0 or pointers[4] < 0x4C:
            raise RebuildError(f'Segment {s.index}: invalid visibility row')
        if s.opaque_batch_count > len(s.batches):
            raise RebuildError(f'Segment {s.index}: invalid opaque batch split')
        block('vertices', vp, s.vertex_count, segment=s.index)
        block('triangles', tp, s.triangle_count, segment=s.index)
        block('batches', bp, len(s.batches)+1, segment=s.index)
        block('facets', fp, s.triangle_count, segment=s.index)
        block('visibility', pointers[4]+visibility, 1, segment=s.index, format=f'>{width}B')
    ordered = tuple(sorted(blocks, key=lambda b: b.offset))
    cursor = 0
    opaque: list[OpaqueSpan] = []
    for b in ordered:
        if b.offset < cursor:
            raise RebuildError(f'{b.kind}: overlapping stock record regions')
        if b.offset > cursor:
            opaque.append(OpaqueSpan(cursor, raw[cursor:b.offset]))
        cursor = b.offset+b.byte_size
    if cursor < len(raw):
        opaque.append(OpaqueSpan(cursor, raw[cursor:]))
    return StockDocument(model_id, len(raw), hashlib.sha256(raw).hexdigest(), ordered, tuple(opaque))


def encode_stock_track(document: StockDocument) -> bytes:
    """Reconstruct every byte into a new buffer; refuse changed stock documents."""
    if not 0x4C <= document.byte_size <= TRACK_HEAP:
        raise RebuildError('Invalid stock document size')
    out = bytearray(document.byte_size)
    occupied = bytearray(document.byte_size)

    def write(offset: int, payload: bytes) -> None:
        end = offset+len(payload)
        if offset < 0 or end > len(out) or any(occupied[offset:end]):
            raise RebuildError('Overlapping or out-of-range rebuilt records')
        out[offset:end] = payload
        occupied[offset:end] = b'\x01'*len(payload)

    for b in document.records:
        expected = FORMATS.get(b.kind)
        if expected is None and (b.kind != 'visibility' or len(b.rows) != 1 or not b.rows[0]
                                 or b.format != f'>{len(b.rows[0])}B'):
            raise RebuildError('Unknown stock record encoding')
        if expected is not None and b.format != expected:
            raise RebuildError('Stock record format was changed')
        try:
            packed = b''.join(struct.pack(b.format, *row) for row in b.rows)
        except (struct.error, TypeError, OverflowError) as error:
            raise RebuildError(f'{b.kind}: invalid record value') from error
        write(b.offset, packed)
    for span in document.opaque:
        write(span.offset, span.data)
    if not all(occupied):
        raise RebuildError('Rebuilt document has uncovered bytes')
    result = bytes(out)
    if hashlib.sha256(result).hexdigest() != document.source_sha256:
        raise RebuildError('Stock reconstruction changed protected bytes; use OBJ import for topology changes')
    return result


def _s16(value: int) -> int:
    return (value+32768) % 65536-32768


def _grid(model: LevelModel, segment: int) -> tuple[int, ...]:
    s = model.segments[segment]
    points = s.vertices[s.indices].astype(np.int32)
    masks = np.zeros(s.triangle_count, np.uint16)
    for axis, shift in ((0, 0), (2, 8)):
        minimum = np.minimum(points[:,:,axis].min(axis=1), 32000) if len(points) else np.zeros(0)
        maximum = np.maximum(points[:,:,axis].max(axis=1), -32000) if len(points) else np.zeros(0)
        low = int(s.bounds.minimum[axis])
        delta = _s16(((int(s.bounds.maximum[axis])-low) >> 3)+1)
        high = _s16(low+delta)
        for bit in range(8):
            masks[(high >= minimum) & (maximum >= low)] |= 1 << (bit+shift)
            low, high = _s16(low+delta), _s16(high+delta)
    masks[(s.triangle_flags & 0x80) != 0] = 0
    return tuple(map(int, masks))


def runtime_track(model: LevelModel, *, cutscene: bool = False) -> RuntimeTrack:
    """Source-model generated grids, collision planes/fixups and water indexes.

    CollisionFacetPlanes initially contains neighbor/base indexes, then runtime
    plane indexes (some with bit15 marking inversion). The runtime uses a neighbor
    value as a facet-row index verbatim; retain even non-geometric stock links.
    """
    raw = model.raw_data
    pointer = struct.unpack_from('>I', raw, 4)[0]
    result: list[RuntimeSegment] = []
    original_facets: list[np.ndarray] = []
    total = model.byte_size
    digest = hashlib.sha256()
    for s in model.segments:
        start = struct.unpack_from('>I', raw, pointer+s.index*0x44+0x14)[0]
        if start < 0x4C or start+s.triangle_count*8 > model.byte_size:
            raise RebuildError(f'Segment {s.index}: collision facets outside modelSize')
        facets = np.frombuffer(raw, '>u2', s.triangle_count*4, start).reshape(-1,4).astype(np.uint16)
        original_facets.append(facets.copy())
        active = np.flatnonzero((s.triangle_flags & 0x80) == 0)
        if not np.array_equal(facets[active,0], np.arange(len(active))):
            raise RebuildError(f'Segment {s.index}: invalid base-plane mapping')
        if np.any(facets[active,1:] >= len(active)):
            raise RebuildError(f'Segment {s.index}: collision neighbor outside base planes')
        base = collision_base_planes(s.vertices[s.indices[active]])
        extra: list[tuple[int,int,int]] = []
        count = len(base)
        for b, following in zip(s.batches, (*s.batches[1:], s.terminal_batch)):
            if cutscene:
                break  # tracks.c:3135 returns after base planes in cutscene race types.
            if b.flags & 0x200:
                continue
            for face in range(b.faces_offset, following.faces_offset):
                if s.triangle_flags[face] & 0x80:
                    continue
                own = int(facets[face,0])
                for edge in range(3):
                    neighbor = int(facets[face,edge+1])
                    if neighbor < len(base):
                        if count >= 0x8000:
                            raise RebuildError('Collision plane index exceeds the runtime signed-index range')
                        if neighbor != own:
                            facets[neighbor,1:][facets[neighbor,1:] == own] = count | 0x8000
                        facets[face,edge+1] = count
                        extra.append((face,edge,neighbor))
                        count += 1
        if extra:
            ids = np.asarray(extra, np.int32)
            first = s.vertices[s.indices[ids[:,0],ids[:,1]]]
            second = s.vertices[s.indices[ids[:,0],(ids[:,1]+1) % 3]]
            normal = base[facets[ids[:,0],0],:3]+base[ids[:,2],:3]
            third = normal*np.float32(10)+first
            planes = np.concatenate((base, collision_base_planes(np.stack((first,second,third),axis=1))))
        else:
            planes = base
        if not np.isfinite(planes).all():
            raise RebuildError('Nonfinite generated collision planes')
        water = tuple(i for i,b in enumerate(s.batches) if b.flags & 0x2000)
        height = -10000
        for i in water:
            b = s.batches[i]
            if b.vertices_offset >= s.vertex_count:
                raise RebuildError('Water batch has no first vertex')
            value = int(s.vertices[b.vertices_offset,1])
            if height == -10000 or height < value:
                height = value
        grid = _grid(model, s.index)
        total = (total+2*s.triangle_count+15) & ~15
        total += len(planes)*16
        total = (total+2*len(water)+15) & ~15
        facets.setflags(write=False)
        planes.setflags(write=False)
        result.append(RuntimeSegment(grid, planes, facets, water, height))
        digest.update(struct.pack('>3Ih', len(grid), len(planes), len(water), height))
        digest.update(np.asarray(grid, '>u2').tobytes())
        digest.update(planes.astype('>f4').tobytes())
        digest.update(facets.astype('>u2').tobytes())
        digest.update(np.asarray(water, '>i2').tobytes())
    if total > TRACK_HEAP:
        raise RebuildError(f'Track runtime needs {total:,} bytes; heap is {TRACK_HEAP:,}')
    if not cutscene and total != runtime_track_bytes(model, tuple(original_facets)):
        raise RebuildError('Runtime allocation checks disagree')
    return RuntimeTrack(tuple(result), total, digest.hexdigest())


def rebuild_stock_track(raw: bytes, *, model_id: int = 0) -> StockRebuild:
    document = decode_stock_track(raw, model_id=model_id)
    rebuilt = encode_stock_track(document)
    before = runtime_track(LevelModel.from_bytes(raw, model_id=model_id))
    model = LevelModel.from_bytes(rebuilt, model_id=model_id)
    after = runtime_track(model)
    if (before.byte_size, before.sha256) != (after.byte_size, after.sha256):
        raise RebuildError('Generated runtime data changed after reconstruction')
    cutscene_before = runtime_track(LevelModel.from_bytes(raw), cutscene=True)
    cutscene_after = runtime_track(model, cutscene=True)
    if (cutscene_before.byte_size, cutscene_before.sha256) != (cutscene_after.byte_size, cutscene_after.sha256):
        raise RebuildError('Cutscene runtime data changed after reconstruction')
    # Reuse the production compressor; import locally to keep its dependency one-way.
    from src.core.editing import compress_asset
    packed = compress_asset(rebuilt)
    if decompress_rare(packed) != rebuilt:
        raise RebuildError('Recompressed stock data did not round-trip')
    verify_geometry_stream(rebuilt, packed)
    return StockRebuild(model_id, rebuilt, packed, document.source_sha256,
        sum(b.byte_size for b in document.records), sum(len(s.data) for s in document.opaque),
        sum(len(b.rows) for b in document.records), model.vertex_count, model.triangle_count,
        sum(len(s.batches) for s in model.segments), len(model.segments),
        sum(b.kind == 'visibility' for b in document.records),
        sum(len(s.planes) for s in after.segments), after.byte_size, after.sha256,
        cutscene_after.byte_size, cutscene_after.sha256)


def stock_rebuild_layout(rom: RomImage, rebuilds: Sequence[StockRebuild]) -> tuple[tuple[bytes, ...], ExportReport]:
    """Recompress only verified stock entries, retain all other assets and tails."""
    ids = [r.model_id for r in rebuilds]
    if not ids or len(set(ids)) != len(ids):
        raise RebuildError('Choose distinct verified stock models')
    for r in rebuilds:
        if type(r.model_id) is not int or not 0 <= r.model_id < rom.count(AssetType.LEVEL_MODELS):
            raise RebuildError('Stock model ID is outside the ROM table')
        original = rom.read_asset(AssetType.LEVEL_MODELS, r.model_id, decompress=True)
        if r.raw != original or hashlib.sha256(original).hexdigest() != r.sha256:
            raise RebuildError('Stock export accepts only unchanged original track data')
        if decompress_rare(r.packed) != original:
            raise RebuildError('Stock export compressed data differs from the original track')
        if len(r.packed) % 16:
            raise RebuildError('Stock export compressed entries must be16-byte aligned')
        verify_geometry_stream(original, r.packed)
    replacements = {r.model_id:r for r in rebuilds}
    sections = [rom.data[s.start:s.end] for s in rom.sections]
    table = rom.index_table(AssetType.LEVEL_MODELS)
    data = rom.section(AssetType.LEVEL_MODELS)
    chunks: list[bytes] = []
    offsets = [0]
    diffs: list[AssetDiff] = []
    catalog = load_level_catalog(rom)
    for index in range(len(table)):
        span = table.span(index)
        old = data[span.start:span.end]
        replacement = replacements.get(index)
        chunk = replacement.packed if replacement else old
        chunks.append(chunk)
        offsets.append(offsets[-1]+len(chunk))
        if replacement:
            uses = tuple(f'{level.index}: {level.name}' for level in catalog.levels if level.header.geometry_id == index)
            diffs.append(AssetDiff(27,index,f'Stock track rebuild {index}',len(replacement.raw),len(replacement.raw),
                len(old),len(chunk),uses,('Record reconstruction matches all original inflated bytes; compression only.',)))
    chunks.append(data[table.offsets[-1]:])
    index_data = bytearray(sections[26])
    struct.pack_into('>'+str(len(offsets))+'I', index_data, 0, *offsets)
    sections[26], sections[27] = bytes(index_data), b''.join(chunks)
    AssetTable.parse(sections[26], len(sections[27]))
    prepared = tuple(sections)
    return prepared, make_export_report(rom, prepared, tuple(diffs))


def build_stock_rebuild_rom(rom: RomImage, rebuilds: Sequence[StockRebuild]) -> tuple[bytes, ExportReport]:
    from src.core.editing import _assemble_rom
    sections, report = stock_rebuild_layout(rom, rebuilds)
    return _assemble_rom(rom, sections, report), report


def export_stock_rebuild_rom(rom: RomImage, rebuilds: Sequence[StockRebuild], destination: Path) -> Path:
    """Explicit user export, sharing original-ROM and atomic-write protections."""
    from src.core.editing import _atomic_write
    output, _ = build_stock_rebuild_rom(rom, rebuilds)
    return _atomic_write(destination, output, rom.source_path)
