"""Bounded static ObjectModel compiler. Local structs.h/f3ddkr.h/objects.c.

The original serialized bytes remain a protected prefix. New arrays are appended
once, with canonical pointers; repeated rebuilding does not grow a prefix chain.
Animation table30 and texture IDs are never changed by this compiler.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import struct

import numpy as np

from src.core.level_model import BATCH_STRUCT
from src.core.object_models import ObjectModel, ObjectLibrary
from src.core.obj_units import GAME_UNITS_PER_OBJ_UNIT, OBJ_UNITS_PER_GAME_UNIT
from src.core.rom import AssetType, RomImage
from src.core.track_import import ObjMesh, parse_obj
from src.core.textures import Texture, load_model_textures
from src.core.render_batches import MAX_BATCH_VERTICES, MAX_BATCH_FACES, ENCODED_BATCH_VERTICES

# Editor bounds, NOT a claim that this much unused RAM exists in every scene.
MAX_VERTICES = 4096
MAX_TRIANGLES = 2048
MAX_BATCHES = 512
MAX_MODEL_BYTES = 256*1024
HIDDEN, NO_COLLISION, TRANSLUCENT, ENVMAP = 0x100, 0x200, 4, 0x8000


def align(value: int) -> int:
    return (value+15) & -16


def eligible(source: RomImage, index: int, raw: bytes) -> None:
    if type(index) is not int or not 0 <= index < source.count(AssetType.OBJECT_MODELS):
        raise ValueError('Object model ID outside the original table')
    if ObjectLibrary(source).clip_count(index):
        raise ValueError('Topology rebuilding supports static models only; this model has animation clips')
    model = ObjectModel.from_bytes(raw, index)
    seg = model.mesh.segments[0]
    for b, end in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
        if b.vertex_override not in (0, end.vertices_offset-b.vertices_offset):
            raise ValueError('This model splits a batch between transform matrices; retargeting is not implemented')


def runtime_usage(raw: bytes) -> tuple[int, int, int, int]:
    """Shared allocation, shaded-instance allocation, normal scratch, collision upper bound.

    object_models.c:model_instance_init/model_init_normals/model_init_collision.
    Normal smoothing count <= lit vertex count; allocator slot overhead separate.
    """
    model = ObjectModel.from_bytes(raw)
    seg = model.mesh.segments[0]
    lit = model.normal_vertex_count
    collision = sum(e.faces_offset-b.faces_offset for b, e in zip(seg.batches,
        (*seg.batches[1:], seg.terminal_batch)) if not b.flags & NO_COLLISION)
    shared = len(raw)+0x80+lit*6
    instance = 0x24+(model.mesh.vertex_count*10 if lit else 0)
    scratch = model.mesh.triangle_count*12+model.mesh.vertex_count*2+lit*12 if lit else 0
    return shared, instance, scratch, collision*72


def report_changes(before: bytes, after: bytes) -> tuple[str, ...]:
    a, b = ObjectModel.from_bytes(before), ObjectModel.from_bytes(after)
    old, new = runtime_usage(before), runtime_usage(after)
    return (f'Static rebuild: {a.mesh.vertex_count} → {b.mesh.vertex_count} vertices; '
        f'{a.mesh.triangle_count} → {b.mesh.triangle_count} triangles; '
        f'{len(a.mesh.segments[0].batches)} → {len(b.mesh.segments[0].batches)} batches.',
        f'Shared model + normals: {old[0]:,} → {new[0]:,} B ({new[0]-old[0]:+,}).',
        f'Per shaded instance: {old[1]:,} → {new[1]:,} B; basic instances remain 36 B.',
        f'Normal-generation scratch upper bound: {new[2]:,} B; optional collision facets/planes: {new[3]:,} B.',
        'Scene-wide residency, allocator slots, frame commands, compiled vertex uses and behavior need gameplay review.',
        'Static IDs/clip ranges, texture assets and opaque original bytes retained; load-time normals/collision regenerate.')


def validate_rebuild(source: RomImage, index: int, original: bytes, raw: bytes) -> ObjectModel:
    from src.core.model_editing import structures
    eligible(source, index, original)
    if not len(original) < len(raw) <= MAX_MODEL_BYTES or len(raw) % 16:
        raise ValueError('Rebuilt model must have a bounded, aligned appended layout')
    model = ObjectModel.from_bytes(raw, index)
    if not 1 <= model.mesh.vertex_count <= MAX_VERTICES or not 1 <= model.mesh.triangle_count <= MAX_TRIANGLES:
        raise ValueError('Rebuilt model exceeds editor vertex/triangle bounds')
    if not 1 <= len(model.mesh.segments[0].batches) <= MAX_BATCHES:
        raise ValueError('Rebuilt model batch count is outside editor bounds')
    if model.animated_count or struct.unpack_from('>I', raw, 0x4C)[0]:
        raise ValueError('Rebuilt static models must have no vertex-animation mapping')
    allowed = bytearray(len(original))
    for start, count in ((4, 8), (0x14, 4), (0x1C, 4), (0x24, 6), (0x2C, 4),
                         (0x38, 8), (0x4A, 6)):
        allowed[start:start+count] = b'\1'*count
    if any(a != b and not allowed[i] for i, (a, b) in enumerate(zip(original, raw[:len(original)]))):
        raise ValueError('Rebuild changed protected original header/texture/opaque data')
    attaches, spheres = structures(raw)
    _, old_spheres = structures(original)
    if any(p[1] < 0 and p[1] != old[1] for p, old in zip(spheres, old_spheres)):
        raise ValueError('Negative collision radius scale is not supported')
    pointer = align(len(original))
    for field, width in ((4, model.mesh.vertex_count*10), (8, model.mesh.triangle_count*16),
                         (0x38, (len(model.mesh.segments[0].batches)+1)*12),
                         (0x14, len(attaches)*2), (0x1C, len(spheres)*4)):
        actual = struct.unpack_from('>I', raw, field)[0]
        if width:
            if actual != pointer:
                raise ValueError('Rebuilt model arrays are not in canonical appended order')
            pointer = align(pointer+width)
        elif actual != struct.unpack_from('>I', original, field)[0]:
            raise ValueError('Empty reference pointer changed')
    if pointer != len(raw) or struct.unpack_from('>I', raw, 0x2C)[0] != len(raw):
        raise ValueError('Rebuilt model size/tail is not canonical')
    # Alignment between arrays is deterministic; no unchecked opaque trailer.
    ranges = [(len(original), align(len(original)))]
    for field, width in ((4, model.mesh.vertex_count*10), (8, model.mesh.triangle_count*16),
                         (0x38, (len(model.mesh.segments[0].batches)+1)*12),
                         (0x14, len(attaches)*2), (0x1C, len(spheres)*4)):
        if width:
            start = struct.unpack_from('>I', raw, field)[0]
            ranges.append((start+width, align(start+width)))
    if any(any(raw[a:b]) for a, b in ranges):
        raise ValueError('Rebuilt model padding must be zero')
    distance = struct.unpack_from('>f', raw, 0x3C)[0]
    if not math.isfinite(distance) or not 0 <= distance <= 100000:
        raise ValueError('Invalid rebuilt collision broad-phase distance')
    old = ObjectModel.from_bytes(original)
    old_seg, seg = old.mesh.segments[0], model.mesh.segments[0]
    if old.uses_normals != model.uses_normals:
        raise ValueError('Rebuilt model must retain its lit/unlit instance allocation kind')
    signatures = {(b.texture_index, b.misc_data, b.texture_offset, b.flags, b.vertex_override == 0) for b in old_seg.batches}
    triangle_flags: dict[tuple[int, ...], set[int]] = {}
    for b, end in zip(old_seg.batches, (*old_seg.batches[1:], old_seg.terminal_batch)):
        signature = (b.texture_index, b.misc_data, b.texture_offset, b.flags, b.vertex_override == 0)
        triangle_flags.setdefault(signature, set()).update(map(int, old_seg.triangle_flags[b.faces_offset:end.faces_offset]))
    transparent_seen = False
    for b, end in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
        nv, nf = end.vertices_offset-b.vertices_offset, end.faces_offset-b.faces_offset
        if not 1 <= nv <= ENCODED_BATCH_VERTICES or not 1 <= nf <= MAX_BATCH_FACES:
            raise ValueError('Batch exceeds F3DDKR 32-vertex / 16-triangle command fields')
        anchor = ((b.texture_index, b.texture_offset, b.flags, b.vertex_override) == (255, 0, HIDDEN|NO_COLLISION, 0)
                  and b.misc_data in (254, 255))
        if not anchor and (b.texture_index, b.misc_data, b.texture_offset, b.flags, b.vertex_override == 0) not in signatures:
            raise ValueError('Rebuilt batch must retain an existing material/lighting signature')
        if not anchor:
            signature = (b.texture_index, b.misc_data, b.texture_offset, b.flags, b.vertex_override == 0)
            if any(int(v) not in triangle_flags[signature] for v in seg.triangle_flags[b.faces_offset:end.faces_offset]):
                raise ValueError('Rebuilt triangle flags must retain verified source material values')
        if b.vertex_override not in (0, nv):
            raise ValueError('Mixed matrix vertex regions are protected')
        faces = seg.indices[b.faces_offset:end.faces_offset]
        points = seg.vertices[faces].astype(np.float64)
        area = np.linalg.norm(np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0]), axis=1)
        if anchor:
            if nv != 1 or nf != 1 or not np.all(faces == b.vertices_offset):
                raise ValueError('Malformed retained reference anchor')
        elif np.any(area == 0):
            raise ValueError('Rebuilt mesh contains a collapsed triangle')
        if not b.flags & HIDDEN:
            if transparent_seen and not b.flags & TRANSLUCENT:
                raise ValueError('Opaque batches must precede translucent batches')
            transparent_seen |= bool(b.flags & TRANSLUCENT)
    sentinel = seg.terminal_batch
    if (sentinel.texture_index, sentinel.vertex_override, sentinel.misc_data, sentinel.texture_offset, sentinel.flags) != (255, 0, 255, 0, 0):
        raise ValueError('Invalid rebuilt batch sentinel')
    return model


@dataclass(frozen=True)
class RebuiltModel:
    raw: bytes
    input_vertices: int
    triangles: int
    inferred_faces: int
    anchors: int
    warnings: tuple[str, ...]


def _parse(text: str) -> tuple[ObjMesh, tuple[bool, ...]]:
    lines: list[str] = []
    colors: list[bool] = []
    for line in text.splitlines():
        words = line.split('#', 1)[0].split()
        if words and words[0] == 'v':
            colors.append(len(words) in (7, 8))
        if words and words[0] == 'f':
            # A stock (v,v,v) anchor is not a polygon. Its position is retained
            # through the attachment/collision reference pass below if needed.
            indices = [p.split('/')[0] for p in words[1:]]
            if len(set(indices)) < 3:
                continue
        lines.append(line)
    try:
        return parse_obj('\n'.join(lines), max_faces=MAX_TRIANGLES), tuple(colors)
    except ValueError as error:
        raise ValueError(str(error).replace('small-track', 'object')) from error


def rebuild_obj(raw: bytes, source: RomImage) -> str:
    """Compact XYZ/UV/material OBJ; batch_N retains source render signatures."""
    model = ObjectModel.from_bytes(raw)
    textures: dict[int, Texture] = {}
    load_model_textures(source, model.mesh, textures)
    lines = ['# DKR static rebuild OBJ: Y up; preserve reference vertex row order.',
             f'# 1 OBJ unit = {GAME_UNITS_PER_OBJ_UNIT:g} model units; Blender import/export Scale 1.',
             '# batch_N names select an existing render signature; PNG edits use the Texture Browser.']
    seg = model.mesh.segments[0]
    for p, rgba in zip(seg.vertices, seg.colors):
        lines.append('v '+' '.join(f'{float(v)*OBJ_UNITS_PER_GAME_UNIT:.9g}' for v in p)
                     +' '+' '.join(f'{int(c)/255:.9g}' for c in rgba))
    cursor = 1
    for i, b in enumerate(seg.batches):
        end = (*seg.batches[1:], seg.terminal_batch)[i]
        lines.append(f'usemtl batch_{i}')
        h = textures[model.mesh.textures[b.texture_index].texture_id].frames[0].header if b.texture_index != 255 else None
        for j in range(b.faces_offset, end.faces_offset):
            indices = seg.indices[j]
            if len(set(map(int, indices))) < 3:
                continue
            for u, v in seg.uvs[j]:
                lines.append(f'vt {float(u)/(32*(h.width if h else 1)):.9g} {1-float(v)/(32*(h.height if h else 1)):.9g}')
            lines.append('f '+' '.join(f'{int(vi)+1}/{cursor+k}' for k, vi in enumerate(indices)))
            cursor += 3
    return '\n'.join(lines)+'\n'


def compile_static(source: RomImage, index: int, text: str, *, appearance: bytes | None = None) -> RebuiltModel:
    """Restore compact OBJ positions, then rebuild in native model coordinates."""
    from src.core.model_editing import structures
    original = source.read_asset(AssetType.OBJECT_MODELS, index, decompress=True)
    eligible(source, index, original)
    base = ObjectModel.from_bytes(appearance or original, index)
    reference_model = base
    original_rows = False
    mesh, has_colors = _parse(text)
    if len(mesh.vertices) > MAX_VERTICES:
        raise ValueError(f'OBJ exceeds the {MAX_VERTICES}-vertex editor limit')
    positions = np.rint(np.asarray(mesh.vertices, np.float64)*GAME_UNITS_PER_OBJ_UNIT)
    if not np.isfinite(positions).all() or np.any(positions < -32768) or np.any(positions > 32767):
        raise ValueError('Object coordinates exceed signed16 storage')
    if appearance is not None and all(face.material == '(default)' for face in mesh.faces):
        # A legacy file exported before a rebuild still uses the original row
        # identities. Reimporting it into an already rebuilt draft/project must
        # not inherit materials from unrelated, reordered compiled rows.
        stock = ObjectModel.from_bytes(original, index)
        def matching_rows(model: ObjectModel) -> int:
            vertices = model.mesh.segments[0].vertices
            count = min(len(vertices), len(positions))
            return int(np.all(vertices[:count] == positions[:count], axis=1).sum())
        if matching_rows(stock) > matching_rows(base):
            base = stock
            original_rows = True
    seg = base.mesh.segments[0]
    points = seg.vertices[seg.indices].astype(np.float64)
    normals = np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    valid = np.flatnonzero(lengths > 0)
    if not len(valid):
        raise ValueError('Source model has no appearance triangles')
    normals = np.divide(normals, lengths[:, None], out=np.zeros_like(normals), where=lengths[:, None] > 0)
    face_batch = np.zeros(base.mesh.triangle_count, dtype=np.int32)
    for i, b in enumerate(seg.batches):
        end = (*seg.batches[1:], seg.terminal_batch)[i]
        face_batch[b.faces_offset:end.faces_offset] = i
    textures: dict[int, Texture] = {}
    load_model_textures(source, base.mesh, textures)
    centers, extent = points.mean(axis=1), max(float(np.ptp(seg.vertices, axis=0).max()), 1.)
    nearest: dict[int, int] = {}
    def ancestor(i: int) -> int:
        if i < base.mesh.vertex_count:
            return i
        if i not in nearest:
            distances = np.square(seg.vertices-positions[i]).sum(axis=1)
            nearest[i] = int(len(distances)-1-np.argmin(distances[::-1]))
        return nearest[i]
    records: list[tuple[int, tuple[tuple[int, ...], ...], tuple[int, ...], int, tuple[int, ...]]] = []
    inferred = 0
    has_source_rows = len(positions) >= base.mesh.vertex_count
    for face in mesh.faces:
        ids = tuple(c.vertex for c in face.corners)
        p = positions[list(ids)]
        normal = np.cross(p[1]-p[0], p[2]-p[0])
        length = float(np.linalg.norm(normal))
        if length == 0:
            raise ValueError('Integer coordinate rounding collapsed an imported triangle')
        normal /= length
        explicit = re.fullmatch(r'batch_(\d+)(?:\.\d+)?', face.material)
        candidates = valid
        selected = None
        if explicit:
            selected = int(explicit[1])
            if not 0 <= selected < len(seg.batches):
                raise ValueError(f'Unknown existing batch material {face.material}')
            candidates = valid[face_batch[valid] == selected]
        elif face.material != '(default)':
            raise ValueError(f'Unknown material {face.material!r}; use exported batch_N names')
        if not len(candidates):
            raise ValueError('Selected material has no source appearance triangle')
        # An extrusion wall shares source row identities with its cap, but its
        # surface points in a different direction. Identity-overlap alone makes
        # it inherit a coplanar decal (and degenerate/transparent UVs) instead
        # of the object's side material. Retain exact existing faces and explicit
        # batch_N assignments; infer new faces from aligned source surfaces first.
        if selected is None and not (has_source_rows and any(
                set(ids) == set(map(int, seg.indices[j])) for j in candidates)):
            aligned = candidates[(normals[candidates]@normal) >= .5]
            visible = aligned[np.array([not seg.batches[int(face_batch[j])].flags & HIDDEN
                                        for j in aligned], dtype=bool)]
            if len(visible):
                candidates = visible
        ancestors = {ancestor(i) for i in ids}
        overlap = np.array([len(ancestors & set(map(int, seg.indices[j]))) for j in candidates])
        score = (3-overlap)*4+2*(1-normals[candidates]@normal)+np.linalg.norm(centers[candidates]-p.mean(axis=0), axis=1)/extent
        template = int(candidates[int(np.argmin(score))])
        batch_id = int(face_batch[template])
        b = seg.batches[batch_id]
        source_ids = list(map(int, seg.indices[template]))
        # Never infer a hidden collision/reference material for visible geometry.
        if b.flags & HIDDEN and selected is None and set(ids) != set(source_ids):
            visible = valid[np.array([not seg.batches[int(face_batch[j])].flags & HIDDEN for j in valid])]
            if not len(visible):
                raise ValueError('No visible source material to inherit')
            template = int(visible[np.argmin(np.linalg.norm(centers[visible]-p.mean(axis=0), axis=1))])
            batch_id, b = int(face_batch[template]), seg.batches[int(face_batch[template])]
        source_ids = list(map(int, seg.indices[template]))
        tri = points[template]
        basis = np.column_stack((tri[1]-tri[0], tri[2]-tri[0]))
        ab = np.linalg.lstsq(basis, (p-tri[0]).T, rcond=None)[0].T
        weights = np.column_stack((1-ab.sum(axis=1), ab))
        h = textures[base.mesh.textures[b.texture_index].texture_id].frames[0].header if b.texture_index != 255 else None
        rgba: list[tuple[int, ...]] = []
        uv: list[int] = []
        for corner, vi, weight in zip(face.corners, ids, weights):
            if has_colors[vi]:
                color = np.rint(np.array(mesh.colors[vi])*255).astype(int)
            elif vi < base.mesh.vertex_count:
                color = seg.colors[vi].astype(int)
            else:
                color = np.clip(np.rint(weight@seg.colors[source_ids]), 0, 255).astype(int)
            rgba.append(tuple(map(int, (*positions[vi], *color))))
            if corner.uv is not None:
                u, v = mesh.uvs[corner.uv]
                pair = (u*32*(h.width if h else 1), (1-v)*32*(h.height if h else 1))
            elif vi in source_ids:
                pair = seg.uvs[template][source_ids.index(vi)]
            else:
                pair = weight@seg.uvs[template]
            q = np.rint(pair).astype(np.int64)
            if np.any(q < -32768) or np.any(q > 32767):
                raise ValueError('Inherited/imported UV exceeds signed s10.5 storage')
            uv.extend(map(int, q))
        inferred += int(not explicit or any(c.uv is None for c in face.corners))
        records.append((batch_id, tuple(rgba), tuple(uv), int(seg.triangle_flags[template]), ids))
    records.sort(key=lambda r: (bool(seg.batches[r[0]].flags & TRANSLUCENT), r[0]))
    vertices: list[tuple[int, ...]] = []
    faces: list[tuple[int, ...]] = []
    batches: list[tuple[int, ...]] = []
    local: dict[tuple[int, ...], int] = {}
    remap: dict[int, int] = {}
    active, start_faces, start_vertices = -1, 0, 0
    def finish() -> None:
        if active < 0:
            return
        b = seg.batches[active]
        batches.append((b.texture_index, 0 if b.vertex_override == 0 else len(vertices)-start_vertices,
            start_vertices, start_faces, b.misc_data, b.texture_offset, b.flags))
    for batch_id, verts, uv, flags, input_ids in records:
        additional = len({v for v in verts if v not in local})
        if batch_id != active or len(local)+additional > MAX_BATCH_VERTICES or len(faces)-start_faces >= MAX_BATCH_FACES:
            finish()
            active, start_faces, start_vertices, local = batch_id, len(faces), len(vertices), {}
        indices: list[int] = []
        for vi, vertex in zip(input_ids, verts):
            if vertex not in local:
                local[vertex] = len(vertices)-start_vertices
                vertices.append(vertex)
            indices.append(local[vertex])
            remap.setdefault(vi, start_vertices+local[vertex])
        faces.append((flags, *indices, *uv))
    finish()
    attaches, spheres = structures(appearance or original)
    if original_rows and (attaches or spheres):
        # Existing reference slots belong to the current compiled layout. Map
        # their positions back to original OBJ rows before the normal input-row
        # retargeting pass; never reinterpret compiled row numbers as old rows.
        stock_vertices = base.mesh.segments[0].vertices
        current_vertices = reference_model.mesh.segments[0].vertices
        reference_rows: dict[int, int] = {}
        for vi in dict.fromkeys((*attaches, *(v for v, _ in spheres))):
            matches = np.flatnonzero(np.all(stock_vertices == current_vertices[vi], axis=1))
            if not len(matches):
                raise ValueError('This original-row OBJ cannot retain a current attachment/collision vertex; export the current model OBJ first')
            reference_rows[vi] = int(matches[0])
        attaches = tuple(reference_rows[i] for i in attaches)
        spheres = tuple((reference_rows[i], scale) for i, scale in spheres)
    anchors = 0
    for vi in dict.fromkeys((*attaches, *(v for v, _ in spheres))):
        if not 0 <= vi < len(positions):
            raise ValueError('Keep original reference vertex rows when rebuilding an attached/collision model')
        if vi not in remap:
            start = len(vertices)
            remap[vi] = start
            vertices.append((*map(int, positions[vi]), 255, 255, 255, 255))
            batches.append((255, 0, start, len(faces), 255, 0, HIDDEN|NO_COLLISION))
            faces.append((0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            anchors += 1
    # Some stock static models have lit reference vertices but baked visible
    # geometry. Keep a non-null normal allocation for their shaded instances.
    if base.uses_normals and not any(b[4] != 255 or b[6] & ENVMAP for b in batches):
        start = len(vertices)
        vertices.append((*map(int, positions[0]), 255, 255, 255, 255))
        batches.append((255, 0, start, len(faces), 254, 0, HIDDEN|NO_COLLISION))
        faces.append((0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        anchors += 1
    if len(vertices) > MAX_VERTICES or len(faces) > MAX_TRIANGLES or len(batches) > MAX_BATCHES:
        raise ValueError('Stored geometry including reference anchors exceeds editor bounds')
    out = bytearray(original)
    out.extend(bytes(align(len(out))-len(out)))
    def append(data: bytes) -> int:
        start = len(out)
        out.extend(data)
        out.extend(bytes(align(len(out))-len(out)))
        return start
    vp = append(b''.join(struct.pack('>3h4B', *v) for v in vertices))
    fp = append(b''.join(struct.pack('>4B6h', *f) for f in faces))
    sentinel = (255, 0, len(vertices), len(faces), 255, 0, 0)
    bp = append(b''.join(BATCH_STRUCT.pack(*b) for b in (*batches, sentinel)))
    struct.pack_into('>2I', out, 4, vp, fp)
    struct.pack_into('>3h', out, 0x24, len(vertices), len(faces), len(batches))
    struct.pack_into('>I', out, 0x38, bp)
    if attaches:
        struct.pack_into('>I', out, 0x14, append(struct.pack('>'+str(len(attaches))+'h', *(remap[i] for i in attaches))))
    if spheres:
        struct.pack_into('>I', out, 0x1C, append(b''.join(struct.pack('>hh', remap[i], scale) for i, scale in spheres)))
    struct.pack_into('>hI', out, 0x4A, 0, 0)
    # Preserve an explicitly larger existing broad-phase distance; expand it
    # to enclose the new local geometry before the game applies its scale.
    extent_radius = float(np.linalg.norm(positions, axis=1).max())
    previous_distance = struct.unpack_from('>f', appearance or original, 0x3C)[0]
    struct.pack_into('>f', out, 0x3C, max(previous_distance, math.ceil(extent_radius)))
    struct.pack_into('>I', out, 0x2C, len(out))
    raw = bytes(out)
    validate_rebuild(source, index, original, raw)
    warnings = ('No animation clips; original unused vertex-group mapping is disabled.',)
    if inferred:
        warnings += (f'{inferred} faces inherit source material/UV appearance. Review new surfaces in preview; export batch_N/UVs for explicit control.',)
    if attaches or spheres:
        warnings += ('Reference indices follow original OBJ vertex row identities. Keep those rows ordered; compiled vertex accesses are not retargeted.',)
    return RebuiltModel(raw, len(mesh.vertices), len(faces), inferred, anchors, warnings)
