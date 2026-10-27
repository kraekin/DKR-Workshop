"""Source-compatible F3DDKR batch sizes and lossless legacy-export rebatching.

Local buildModelBatch.cpp limits batches at 24; all 55 Rev1 track models and
390 object models are audited in tests. The DMA field can encode 32, which is
not evidence that a 32-vertex batch is safe for this game's microcode layout.
Keep legacy projects readable; split their draw ranges before ROM compression.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
import numpy as np
from typing import TYPE_CHECKING

from src.core.level_model import BATCH_STRUCT, LevelModel

if TYPE_CHECKING:
    from src.core.rom import RomImage

MAX_BATCH_VERTICES = 24
ENCODED_BATCH_VERTICES = 32
MAX_BATCH_FACES = 16
Vertex = tuple[int, ...]
Triangle = tuple[int, ...]
Batch = tuple[int, ...]


@dataclass(frozen=True)
class BatchArrays:
    vertices: tuple[Vertex, ...]
    triangles: tuple[Triangle, ...]
    batches: tuple[Batch, ...]  # Includes the terminal record.
    remap: dict[int, int]


def _check_split_normals(vertices: tuple[Vertex, ...], groups: list[tuple[list[int], list[Triangle]]]) -> None:
    """miscData=FE assigns one normal per row (object_models.c:model_init_normals).

    Duplicating a shared row splits its face-normal accumulator. Coincident
    unrelated rows must not be welded or assigned a different smoothing group.
    Refuse a legacy export if the normalized accumulators would differ.
    """
    totals: dict[int, np.ndarray] = {}
    sums: list[dict[int, np.ndarray]] = []
    for rows, faces in groups:
        local: dict[int, np.ndarray] = {}
        for face in faces:
            ids = [rows[i] for i in face[1:4]]
            points = np.asarray([vertices[i][:3] for i in ids], np.float64)
            normal = np.cross(points[1]-points[0], points[2]-points[0])
            length = float(np.linalg.norm(normal))
            if length:
                normal /= length
            for i in ids:
                local[i] = local.get(i, np.zeros(3)) + normal
                totals[i] = totals.get(i, np.zeros(3)) + normal
        sums.append(local)
    def unit(value: np.ndarray) -> np.ndarray:
        length = float(np.linalg.norm(value))
        return value/length if length else value
    for local in sums:
        if any(not np.allclose(unit(value), unit(totals[i]), rtol=0, atol=1e-7) for i, value in local.items()):
            raise ValueError('Cannot safely split a legacy lit batch: shared vertex normals would change. '
                             'Re-import the mesh with the current 24-vertex batches before exporting.')


def split_batches(vertices: tuple[Vertex, ...], triangles: tuple[Triangle, ...],
                  batches: tuple[Batch, ...]) -> BatchArrays | None:
    """Retain face order, all corner data/material flags and vertex references.

    Identity is the original vertex row, not just XYZ, so colors and distinct
    lighting/reference rows cannot merge. Every retained row receives a map.
    """
    pairs = tuple(zip(batches, batches[1:]))
    if all(0 < e[2]-b[2] <= MAX_BATCH_VERTICES and 0 < e[3]-b[3] <= MAX_BATCH_FACES for b, e in pairs):
        return None
    out_vertices: list[Vertex] = []
    out_faces: list[Triangle] = []
    out_batches: list[Batch] = []
    remap: dict[int, int] = {}
    for batch, end in pairs:
        nv, nf = end[2]-batch[2], end[3]-batch[3]
        if not 1 <= nv <= ENCODED_BATCH_VERTICES or not 1 <= nf <= MAX_BATCH_FACES:
            raise ValueError('Legacy batch exceeds encoded F3DDKR bounds')
        if batch[1] not in (0, nv):
            raise ValueError('Cannot rebatch a mixed-matrix vertex range')
        groups: list[tuple[list[int], list[Triangle]]] = []
        if nv <= MAX_BATCH_VERTICES:
            groups.append((list(range(batch[2], end[2])), list(triangles[batch[3]:end[3]])))
        else:
            rows: list[int] = []
            faces: list[Triangle] = []
            local: dict[int, int] = {}
            for face in triangles[batch[3]:end[3]]:
                ids = tuple(batch[2]+i for i in face[1:4])
                if any(i < batch[2] or i >= end[2] for i in ids):
                    raise ValueError('Legacy face leaves its loaded vertex range')
                if len(local)+len(set(ids)-local.keys()) > MAX_BATCH_VERTICES:
                    groups.append((rows, faces))
                    rows, faces, local = [], [], {}
                indices: list[int] = []
                for i in ids:
                    if i not in local:
                        local[i] = len(rows)
                        rows.append(i)
                    indices.append(local[i])
                faces.append((face[0], *indices, *face[4:]))
            groups.append((rows, faces))
            if batch[4] == 254:
                _check_split_normals(vertices, groups)
            used = {i for rows, _ in groups for i in rows}
            for i in range(batch[2], end[2]):
                if i in used:
                    continue
                spare = next((rows for rows, _ in groups if len(rows) < MAX_BATCH_VERTICES), None)
                if spare is None:
                    raise ValueError('Cannot retain an unused legacy reference vertex in safe batches')
                spare.append(i)
        for rows, faces in groups:
            start = len(out_vertices)
            out_batches.append((batch[0], 0 if batch[1] == 0 else len(rows), start, len(out_faces), *batch[4:]))
            for i in rows:
                remap.setdefault(i, len(out_vertices))
                out_vertices.append(vertices[i])
            out_faces.extend(faces)
    terminal = list(batches[-1])
    terminal[2:4] = len(out_vertices), len(out_faces)
    out_batches.append(tuple(terminal))
    return BatchArrays(tuple(out_vertices), tuple(out_faces), tuple(out_batches), remap)


def rebatch_track(raw: bytes, *, segmented: bool) -> bytes:
    """Export-only normalization; preserves geometry edits and collision face IDs."""
    from src.core.track_import import _assemble as assemble_single, validate_import_runtime
    from src.core.track_segments import _Segment, _assemble, validate_segmented_runtime
    import numpy as np

    model = LevelModel.from_bytes(raw)
    segptr = struct.unpack_from('>I', raw, 4)[0]
    segments: list[_Segment] = []
    changed = False
    for s in model.segments:
        vp, tp, _, bp, _, fp = struct.unpack_from('>6I', raw, segptr+s.index*0x44)
        vertices = tuple(struct.iter_unpack('>hhhBBBB', raw[vp:vp+s.vertex_count*10]))
        triangles = tuple(struct.iter_unpack('>BBBBhhhhhh', raw[tp:tp+s.triangle_count*16]))
        batches = tuple(BATCH_STRUCT.iter_unpack(raw[bp:bp+(len(s.batches)+1)*12]))
        result = split_batches(vertices, triangles, batches)
        if result is not None:
            vertices, triangles, batches = result.vertices, result.triangles, result.batches
            changed = True
        # Splitting may add opaque ranges. Determine their boundary by the
        # original face offset, not texture flags from an unrelated source.
        opaque_end = s.batches[s.opaque_batch_count].faces_offset if s.opaque_batch_count < len(s.batches) else s.triangle_count
        opaque = sum(b[3] < opaque_end for b in batches[:-1])
        facets = np.frombuffer(raw, '>u2', s.triangle_count*4, fp).reshape(-1, 4).copy()
        bounds = tuple(map(int, (*s.bounds.minimum, *s.bounds.maximum)))
        segments.append(_Segment(vertices, triangles, batches[:-1], opaque, bounds, facets))
    if not changed:
        return raw
    if segmented:
        nodes = tuple((n.left_node, n.right_node, n.split_type, n.segment_index, n.split_value) for n in model.bsp_nodes)
        bounds = tuple(map(int, (*model.stored_bounds.minimum, *model.stored_bounds.maximum)))
        output = _assemble(raw, model.textures, segments, nodes, bounds)
        validate_segmented_runtime(LevelModel.from_bytes(output))
    else:
        if len(segments) != 1:
            raise ValueError('Single-segment rebatch received multiple segments')
        s = segments[0]
        output = assemble_single(raw, model.textures, s.vertices, s.triangles, s.batches, s.opaque, s.bounds, s.facets)
        validate_import_runtime(LevelModel.from_bytes(output))
    return output


def rebatch_static_model(source: RomImage, index: int, original: bytes, raw: bytes) -> bytes:
    """Retain static attachment/sphere identities when exporting an old rebuild."""
    from src.core.object_models import ObjectModel
    from src.core.object_rebuild import align, eligible, validate_rebuild
    from src.core.model_editing import structures

    model = ObjectModel.from_bytes(raw, index)
    seg = model.mesh.segments[0]
    vp, tp = struct.unpack_from('>2I', raw, 4)
    bp = struct.unpack_from('>I', raw, 0x38)[0]
    vertices = tuple(struct.iter_unpack('>hhhBBBB', raw[vp:vp+seg.vertex_count*10]))
    triangles = tuple(struct.iter_unpack('>BBBBhhhhhh', raw[tp:tp+seg.triangle_count*16]))
    batches = tuple(BATCH_STRUCT.iter_unpack(raw[bp:bp+(len(seg.batches)+1)*12]))
    result = split_batches(vertices, triangles, batches)
    if result is None:
        return raw
    eligible(source, index, original)
    if len(raw) == len(original):
        raise ValueError('Oversized fixed-topology object batch requires an explicit static rebuild')
    attaches, spheres = structures(raw)
    out = bytearray(raw[:len(original)])
    out.extend(bytes(align(len(out))-len(out)))
    def append(payload: bytes) -> int:
        start = len(out)
        out.extend(payload)
        out.extend(bytes(align(len(out))-len(out)))
        return start
    vp = append(b''.join(struct.pack('>hhhBBBB', *v) for v in result.vertices))
    tp = append(b''.join(struct.pack('>BBBBhhhhhh', *f) for f in result.triangles))
    bp = append(b''.join(BATCH_STRUCT.pack(*b) for b in result.batches))
    struct.pack_into('>2I', out, 4, vp, tp)
    struct.pack_into('>3h', out, 0x24, len(result.vertices), len(result.triangles), len(result.batches)-1)
    struct.pack_into('>I', out, 0x38, bp)
    if attaches:
        pointer = append(struct.pack('>'+str(len(attaches))+'h', *(result.remap[i] for i in attaches)))
        struct.pack_into('>I', out, 0x14, pointer)
    if spheres:
        pointer = append(b''.join(struct.pack('>hh', result.remap[i], scale) for i, scale in spheres))
        struct.pack_into('>I', out, 0x1C, pointer)
    struct.pack_into('>I', out, 0x2C, len(out))
    output = bytes(out)
    validate_rebuild(source, index, original, output)
    return output
