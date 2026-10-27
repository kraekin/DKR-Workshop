"""Constrained stock track reshaping; structs.h and tracks.c:1985,2832–3222.

XYZ only. Keep the stock segment boxes/BSP/PVS envelope and collision graph.
The game regenerates grids, planes and wave batch indexes at load time. Equal
stock positions are one logical vertex across batches and segment seams.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
import struct

import numpy as np

from src.core.level_model import LevelModel, SEGMENT_SIZE
from src.core.compression import audit_inplace_rare

VertexKey = tuple[int, int]
Position = tuple[int, int, int]
TRACK_HEAP = 0x82A00  # tracks.c:30, generate_track


@dataclass(frozen=True)
class GeometryProfile:
    model: LevelModel
    offsets: tuple[int, ...]
    groups: Mapping[Position, tuple[VertexKey, ...]]
    locked: Mapping[VertexKey, str]
    partitions: tuple[tuple[tuple[int, int], ...], ...]
    facets: tuple[np.ndarray, ...]


def _vertex(model: LevelModel, key: VertexKey) -> Position:
    if (not isinstance(key, tuple) or len(key) != 2 or any(type(i) is not int for i in key)
            or not 0 <= key[0] < len(model.segments)
            or not 0 <= key[1] < model.segments[key[0]].vertex_count):
        raise ValueError('Choose an existing segment and vertex')
    return tuple(int(v) for v in model.segments[key[0]].vertices[key[1]])


@lru_cache(maxsize=64)
def geometry_profile(raw: bytes) -> GeometryProfile:
    model = LevelModel.from_bytes(raw)
    segments = struct.unpack_from('>I', raw, 4)[0]
    groups: dict[Position, list[VertexKey]] = {}
    locked: dict[VertexKey, str] = {}
    offsets: list[int] = []
    facets: list[np.ndarray] = []
    for s in model.segments:
        start = segments+s.index*SEGMENT_SIZE
        offsets.append(struct.unpack_from('>I', raw, start)[0])
        pointer = struct.unpack_from('>I', raw, start+0x14)[0]
        if pointer < 0x4C or pointer+s.triangle_count*8 > model.byte_size:
            raise ValueError(f'Segment {s.index}: invalid serialized 8-byte collision facet span')
        data = np.frombuffer(raw, '>u2', s.triangle_count*4, pointer).reshape(-1, 4).copy()
        data.setflags(write=False)
        facets.append(data)
        active = np.flatnonzero((s.triangle_flags & 0x80) == 0)
        if not np.array_equal(data[active, 0], np.arange(len(active))):
            raise ValueError(f'Segment {s.index}: unsupported collision base-plane mapping')
        if np.any(data[active, 1:] >= len(active)):
            raise ValueError(f'Segment {s.index}: invalid serialized collision neighbor')
        for i, point in enumerate(s.vertices):
            groups.setdefault(tuple(int(v) for v in point), []).append((s.index, i))
        for b, end in zip(s.batches, (*s.batches[1:], s.terminal_batch)):
            if b.flags & 0x2000:
                for i in range(b.vertices_offset, end.vertices_offset):
                    locked[s.index, i] = 'Generated water vertices cannot be edited directly.'
        for face in active:
            for corner, neighbor in enumerate(data[face, 1:]):
                if neighbor == data[face, 0]:
                    continue
                other = int(active[int(neighbor)])
                edge = {tuple(s.vertices[i]) for i in s.indices[face][[corner, (corner+1) % 3]]}
                target = s.vertices[s.indices[other]]
                if not any({tuple(target[j]), tuple(target[(j+1) % 3])} == edge for j in range(3)):
                    # Stock has some non-edge smoothing links. Preserve those
                    # faces until their relation can be rebuilt independently.
                    for i in (*s.indices[face], *s.indices[other]):
                        locked[s.index, int(i)] = 'Unresolved stock collision smoothing link touches this vertex'
    paths: list[list[tuple[int, int]]] = [[] for _ in model.segments]
    if model.bsp_nodes:
        pending = [(0, 0, len(model.segments)-1, ())]
        visited: set[int] = set()
        leaves: set[int] = set()
        while pending:
            index, low, high, path = pending.pop()
            if index in visited:
                raise ValueError('BSP branches share a node')
            visited.add(index)
            node = model.bsp_nodes[index]
            if not low < node.segment_index <= high:
                raise ValueError('BSP segment ranges are inconsistent')
            branch = (*path, (node.split_type, node.split_value))
            for child, a, b in ((node.left_node, low, node.segment_index-1), (node.right_node, node.segment_index, high)):
                if child >= 0:
                    pending.append((child, a, b, branch))
                elif a == b and a not in leaves:
                    leaves.add(a)
                    paths[a] = list(branch)
                else:
                    raise ValueError('BSP leaf does not identify exactly one segment')
        if len(leaves) != len(model.segments) or len(visited) != len(model.bsp_nodes):
            raise ValueError('BSP does not cover all segments')
    # Generated seam guides may reference a neighboring cell's coordinates.
    # Keep their entire welded group fixed until an import rebuilds that seam.
    from src.core.track_segments import collision_helper_faces
    helpers=collision_helper_faces(model)
    protected={tuple(map(int,model.segments[s].vertices[v])) for s,f in helpers for v in model.segments[s].indices[f]}
    for position in protected:
        for key in groups[position]:
            locked[key]='Collision seam guide touches this vertex; reimport the mesh to rebuild segment seams'
    return GeometryProfile(model, tuple(offsets), {k: tuple(v) for k, v in groups.items()}, locked,
                           tuple(tuple(p) for p in paths), tuple(facets))


def copy_geometry(target: bytes, source: bytes) -> bytes:
    """Copy only existing signed16 XYZ fields; counts, colors and derived data stay protected."""
    if len(target) != len(source):
        raise ValueError('Geometry edits retain the complete inflated model length')
    model = LevelModel.from_bytes(target)
    start = struct.unpack_from('>I', target, 4)[0]
    out = bytearray(target)
    for s in model.segments:
        pointer = struct.unpack_from('>I', target, start+s.index*SEGMENT_SIZE)[0]
        for i in range(s.vertex_count):
            p = pointer+10*i
            out[p:p+6] = source[p:p+6]
    return bytes(out)


def geometry_changed(original: bytes, updated: bytes) -> bool:
    return copy_geometry(original, updated) != original


def linked_vertices(profile: GeometryProfile, keys: Sequence[VertexKey]) -> tuple[VertexKey, ...]:
    return tuple(sorted({key for selected in keys for key in profile.groups[_vertex(profile.model, selected)]}))


def selection_center(model: LevelModel, keys: Sequence[VertexKey]) -> Position:
    if not keys:
        raise ValueError('Select track vertices or faces first')
    points = set(_vertex(model, key) for key in keys)
    return tuple(int(round(v)) for v in np.mean(tuple(points), axis=0))


def collision_base_planes(points: np.ndarray) -> np.ndarray:
    """track_init_collision's float32 triangle-plane arithmetic (not serialized)."""
    data = np.asarray(points, np.float32)
    if data.ndim != 3 or data.shape[1:] != (3, 3):
        raise ValueError('Collision planes need three XYZ vertices per triangle')
    x1,y1,z1 = data[:,0].T
    x2,y2,z2 = data[:,1].T
    x3,y3,z3 = data[:,2].T
    normals = np.column_stack((y1*(z2-z3)+y2*(z3-z1)+y3*(z1-z2),
        z1*(x2-x3)+z2*(x3-x1)+z3*(x1-x2), x1*(y2-y3)+x2*(y3-y1)+x3*(y1-y2)))
    magnitude = np.sqrt(normals[:,0]*normals[:,0]+normals[:,1]*normals[:,1]+normals[:,2]*normals[:,2])
    # The source skips division for a zero magnitude, retaining signed zero bits.
    normals = np.divide(normals, magnitude[:,None], out=normals.copy(), where=magnitude[:,None] > 0)
    distance = -(x1*normals[:,0]+y1*normals[:,1]+z1*normals[:,2])
    return np.column_stack((normals,distance)).astype(np.float32)


def validate_geometry(original: bytes, updated: bytes) -> LevelModel:
    """Verify the geometry component only; material/minimap bytes are validated separately."""
    if len(original) != len(updated):
        raise ValueError('Geometry edits retain model length and topology')
    if not geometry_changed(original, updated):
        return LevelModel.from_bytes(updated)
    profile = geometry_profile(original)
    new = LevelModel.from_bytes(updated)
    if (len(new.segments) != len(profile.model.segments)
            or any(not np.array_equal(a.indices, b.indices) for a, b in zip(profile.model.segments, new.segments))):
        raise ValueError('Geometry edits must preserve all segment and triangle topology')
    changed = {tuple(int(v) for v in a.vertices[i]) for a, b in zip(profile.model.segments,new.segments)
               for i in np.flatnonzero(np.any(a.vertices != b.vertices, axis=1))}
    moved_positions: dict[Position, Position] = {}
    for position in changed:
        group = profile.groups[position]
        targets = {_vertex(new, key) for key in group}
        if len(targets) != 1:
            raise ValueError('Coincident stock vertices must move together, including segment seams')
        target = next(iter(targets))
        if target == position:
            continue
        if target in profile.groups:
            raise ValueError('Moving onto another stock vertex would merge topology')
        if target in moved_positions:
            raise ValueError('Distinct vertices cannot merge during geometry editing')
        moved_positions[target] = position
        for segment, vertex in group:
            reason = profile.locked.get((segment, vertex))
            if reason:
                raise ValueError(reason)
            s = profile.model.segments[segment]
            if any(not a <= value <= b for a, b, value in zip(s.bounds.minimum, s.bounds.maximum, target)):
                raise ValueError(f'Segment {segment}: move must stay inside its segment bounds; use OBJ import to expand the track')
            for axis, split in profile.partitions[segment]:
                old, value = position[axis], target[axis]
                if (old == split and value != split) or (old < split) != (value < split):
                    raise ValueError(f'Segment {segment}: move crosses or detaches a stock BSP boundary')
    for a, b in zip(profile.model.segments, new.segments):
        touched = np.any(a.vertices != b.vertices, axis=1)
        faces = np.any(touched[a.indices], axis=1)
        if not np.any(faces):
            continue
        old = a.vertices[a.indices[faces]].astype(np.float64)
        points = b.vertices[b.indices[faces]].astype(np.float64)
        before = np.cross(old[:, 1]-old[:, 0], old[:, 2]-old[:, 0])
        after = np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0])
        if np.any(np.linalg.norm(before, axis=1) == 0) or np.any(np.einsum('ij,ij->i', before, after) <= 0):
            raise ValueError('Move degenerates or reverses an incident triangle')
        source_before = collision_base_planes(old)[:,:3]
        source_after = collision_base_planes(points)[:,:3]
        if np.any(np.einsum('ij,ij->i', source_before, source_after) <= 0):
            raise ValueError('Move degenerates or reverses a float32 collision plane')
    runtime_track_bytes(new, profile.facets)
    return new


def move_vertices(original: bytes, current: bytes, keys: Sequence[VertexKey], delta: Position) -> bytes:
    if len(delta) != 3 or any(type(value) is not int for value in delta):
        raise ValueError('Geometry movement requires three integer deltas')
    if not keys or len(set(keys)) != len(keys):
        raise ValueError('Select distinct existing track vertices')
    profile = geometry_profile(original)
    model = LevelModel.from_bytes(current)
    out = bytearray(current)
    for segment, vertex in linked_vertices(profile, keys):
        position = _vertex(model, (segment, vertex))
        target = tuple(a+b for a, b in zip(position, delta))
        if any(not -32768 <= v <= 32767 for v in target):
            raise ValueError('Vertex coordinates must fit signed16')
        struct.pack_into('>3h', out, profile.offsets[segment]+10*vertex, *target)
    result = bytes(out)
    validate_geometry(original, result)
    return result


def runtime_track_bytes(model: LevelModel, facets: tuple[np.ndarray, ...] | None = None) -> int:
    """Port generate_track's aligned allocations and track_init_collision's plane count."""
    data = facets if facets is not None else geometry_profile(model.raw_data).facets
    size = model.byte_size
    for s, raw in zip(model.segments, data):
        size = (size+2*s.triangle_count+15) & ~15
        current = raw.copy()
        planes = int(np.count_nonzero((s.triangle_flags & 0x80) == 0))
        count = planes
        for b, end in zip(s.batches, (*s.batches[1:], s.terminal_batch)):
            if b.flags & 0x200:
                continue
            for face in range(b.faces_offset, end.faces_offset):
                if s.triangle_flags[face] & 0x80:
                    continue
                base = int(current[face, 0])
                for edge in range(3):
                    neighbor = int(current[face, edge+1])
                    if neighbor < planes:
                        if neighbor != base:
                            current[neighbor, 1:][current[neighbor, 1:] == base] = count | 0x8000
                        current[face, edge+1] = count
                        count += 1
        size += count*16
        size = (size+2*sum(bool(b.flags & 0x2000) for b in s.batches)+15) & ~15
    if size > TRACK_HEAP:
        raise ValueError(f'Track runtime data needs {size:,} bytes; heap is {TRACK_HEAP:,}')
    return size


def verify_geometry_stream(raw: bytes, packed: bytes) -> None:
    """The track loader stages compressed data at the aligned end of its fixed heap."""
    stream = packed
    start = (TRACK_HEAP-len(stream)) & ~15
    slack = start-(len(raw)-len(stream))
    if start < len(raw) or slack < 0:
        raise ValueError('Track compressed staging overlaps its inflated data')
    audit_inplace_rare(stream, workspace=TRACK_HEAP, slack=slack)


def geometry_changes(before: LevelModel, after: LevelModel) -> tuple[str, ...]:
    return tuple(f'Segment {a.index} vertex {i} XYZ: {tuple(map(int, a.vertices[i]))} → {tuple(map(int, b.vertices[i]))}'
                 for a, b in zip(before.segments, after.segments)
                 for i in np.flatnonzero(np.any(a.vertices != b.vertices, axis=1)))
