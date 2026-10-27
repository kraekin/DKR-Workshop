"""Protected existing object meshes/clips. Local objectModel.hpp/object_models.c.

Counts, topology, mapping, batching, frame headers and opaque data are retained.
This writer never allocates a new model, vertex group or animation slot.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import hashlib
import math
from typing import TYPE_CHECKING
import struct

import numpy as np
from numpy.typing import NDArray

from src.core.compression import audit_inplace_rare
from src.core.export_report import AssetDiff, ExportReport, make_export_report
from src.core.global_objects import definition_uses
from src.core.object_models import AnimationClip, ObjectLibrary, ObjectModel
from src.core.obj_units import GAME_UNITS_PER_OBJ_UNIT, OBJ_UNITS_PER_GAME_UNIT
from src.core.rom import AssetTable, AssetType, RomImage

if TYPE_CHECKING:
    from src.core.editing import EditSession

MODEL_ASSETS = frozenset((AssetType.OBJECT_MODELS, AssetType.OBJECT_ANIMATIONS))
AssetKey = tuple[AssetType, int]


def integer(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'Expected an integer in {low}..{high}')
    return value


def array(value: object, shape: tuple[int, ...], low: int, high: int) -> NDArray[np.int32]:
    try:
        result = np.asarray(value)
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid numeric array') from error
    if result.shape != shape or result.dtype.kind not in 'iu' or np.any(result < low) or np.any(result > high):
        raise ValueError(f'Expected integer array {shape} in {low}..{high}')
    return result.astype(np.int32)


def _span(raw: bytes, pointer: int, count: int, width: int) -> tuple[int, int]:
    start = struct.unpack_from('>I', raw, pointer)[0]
    size = struct.unpack_from('>I', raw, 0x2C)[0]
    if count < 0 or count and (start < 0x58 or start+count*width > size):
        raise ValueError('Model attachment/collision array exceeds fileSize')
    return start, count*width


def structures(raw: bytes) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    model = ObjectModel.from_bytes(raw)
    na = struct.unpack_from('>h', raw, 0x18)[0]
    ns = struct.unpack_from('>h', raw, 0x20)[0]
    if ns < 0 or ns % 2:
        raise ValueError('Collision sphere array needs pairs of signed16 words')
    a, aw = _span(raw, 0x14, na, 2)
    s, sw = _span(raw, 0x1C, ns, 2)
    attaches = struct.unpack_from(f'>{na}h', raw, a) if na else ()
    spheres = tuple(struct.iter_unpack('>hh', raw[s:s+sw]))
    if any(not 0 <= i < model.mesh.vertex_count for i in (*attaches, *(p[0] for p in spheres))):
        raise ValueError('Attachment/collision vertex index outside mesh')
    return attaches, spheres


def _normal_keys(model: ObjectModel) -> tuple[object, ...]:
    """Source smoothing equivalence, including environment-map normal groups."""
    segment = model.mesh.segments[0]
    keys: list[object] = [None]*model.mesh.vertex_count
    smooth: dict[tuple[object, ...], int] = {}
    environment: dict[tuple[float, ...], int] = {}
    cursor = 0
    for b, end in zip(segment.batches, (*segment.batches[1:], segment.terminal_batch)):
        for i in range(b.vertices_offset, end.vertices_offset):
            # RENDER_ENVMAP is verified in textures_sprites.h (1 << 15).
            point = tuple(float(v) for v in segment.vertices[i])
            if b.misc_data < 254:
                tag = (b.misc_data, *point)
                group = smooth.get(tag)
                if group is None:
                    group = cursor
                    cursor += 1
                    smooth[tag] = group
            elif b.misc_data == 254:
                group = cursor
                cursor += 1
            elif b.flags & 0x8000:
                # The C search can also join an earlier lit/flat envmap batch.
                group = environment.get(point)
                if group is None:
                    group = cursor
                    cursor += 1
            else:
                continue
            keys[i] = group
            if b.flags & 0x8000:
                environment.setdefault(point, group)
    return tuple(keys)


def linked_vertices(model: ObjectModel, index: int) -> tuple[int, ...]:
    integer(index, 0, model.mesh.vertex_count-1)
    normal = _normal_keys(model)
    selected = {index}
    while True:
        groups = {int(model.animated_indices[i]) for i in selected if model.animated_indices[i] >= 0}
        keys = {normal[i] for i in selected if normal[i] is not None}
        found = {i for i in range(model.mesh.vertex_count)
                 if int(model.animated_indices[i]) in groups or normal[i] is not None and normal[i] in keys}
        if found <= selected:
            return tuple(sorted(selected))
        selected.update(found)


def _editable_spans(raw: bytes) -> tuple[tuple[int, int], ...]:
    model = ObjectModel.from_bytes(raw)
    vp, fp = struct.unpack_from('>II', raw, 4)
    spans: list[tuple[int, int]] = [(0x3C, 4)]
    baked: set[int] = set()
    seg = model.mesh.segments[0]
    for b, end in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
        if b.misc_data == 255 and not b.flags & 0x8000:
            baked.update(range(b.vertices_offset, end.vertices_offset))
    spans.extend((vp+i*10, 10 if i in baked else 6) for i in range(model.mesh.vertex_count))
    spans.extend((fp+i*16+4, 12) for i in range(model.mesh.triangle_count))
    spans.extend((_span(raw, 0x14, struct.unpack_from('>h', raw, 0x18)[0], 2),
                  _span(raw, 0x1C, struct.unpack_from('>h', raw, 0x20)[0], 2)))
    return tuple((s, n) for s, n in spans if n)


def validate_mesh(original: bytes, raw: bytes) -> ObjectModel:
    if len(original) != len(raw):
        raise ValueError('Object model decoded size must stay unchanged')
    before, model = ObjectModel.from_bytes(original), ObjectModel.from_bytes(raw)
    structures(raw)
    # Verify original editable/protected arrays do not overlap any other array.
    nt, nv, nf, nb = struct.unpack_from('>4h', original, 0x22)
    ranges = [(0, 0x58), (struct.unpack_from('>I', original)[0], nt*8),
              (struct.unpack_from('>I', original, 4)[0], nv*10),
              (struct.unpack_from('>I', original, 8)[0], nf*16),
              (struct.unpack_from('>I', original, 0x38)[0], (nb+1)*12),
              _span(original, 0x14, struct.unpack_from('>h', original, 0x18)[0], 2),
              _span(original, 0x1C, struct.unpack_from('>h', original, 0x20)[0], 2)]
    if before.animated_count:
        ranges.append((struct.unpack_from('>I', original, 0x4C)[0], nv*2))
    ranges = sorted((s, s+n) for s, n in ranges if n)
    if any(b > c for (_, b), (c, _) in zip(ranges, ranges[1:])):
        raise ValueError('Overlapping object model arrays are protected')
    allowed = bytearray(len(raw))
    for start, width in _editable_spans(original):
        allowed[start:start+width] = b'\1'*width
    if any(a != b and not allowed[i] for i, (a, b) in enumerate(zip(original, raw))):
        raise ValueError('Topology, counts, mapping, materials, frame bindings and unknown data are protected')
    if original[0x3C:0x40] != raw[0x3C:0x40]:
        distance = struct.unpack_from('>f', raw, 0x3C)[0]
        if not math.isfinite(distance) or not 0 <= distance <= 100000:
            raise ValueError('Collision broad-phase distance must be finite in 0..100000')
    _, old_spheres = structures(original)
    _, spheres = structures(raw)
    if any(a[1] != b[1] and b[1] < 0 for a, b in zip(old_spheres, spheres)):
        raise ValueError('Collision sphere radius scale must be nonnegative')
    # Retain the normal-sharing partition: derived allocations stay the same.
    def partition(m: ObjectModel) -> tuple[int, ...]:
        ids: dict[object, int] = {}
        return tuple(-1 if k is None else ids.setdefault(k, len(ids)) for k in _normal_keys(m))
    if partition(before) != partition(model):
        raise ValueError('Keep coincident smoothing vertices linked; normal-sharing layout changed')
    old_seg, seg = before.mesh.segments[0], model.mesh.segments[0]
    def areas(m: ObjectModel) -> NDArray[np.float64]:
        v = m.mesh.segments[0].vertices[m.mesh.indices].astype(np.float64)
        return np.linalg.norm(np.cross(v[:, 1]-v[:, 0], v[:, 2]-v[:, 0]), axis=1)
    if not np.array_equal(old_seg.vertices, seg.vertices) and np.any((areas(before) > 0) & (areas(model) == 0)):
        raise ValueError('Mesh edit collapses an existing triangle')
    return model


def edit_mesh(raw: bytes, kind: str, index: int, values: object) -> bytes:
    model = ObjectModel.from_bytes(raw)
    result = bytearray(raw)
    if kind in ('vertex', 'color'):
        integer(index, 0, model.mesh.vertex_count-1)
        width = 3 if kind == 'vertex' else 4
        val = array(values, (width,), -32768 if width == 3 else 0, 32767 if width == 3 else 255)
        start = struct.unpack_from('>I', raw, 4)[0]
        targets = linked_vertices(model, index) if kind == 'vertex' else (index,)
        for i in targets:
            struct.pack_into('>3h' if kind == 'vertex' else '>4B', result, start+i*10+(0 if kind == 'vertex' else 6), *val)
    elif kind == 'uv':
        integer(index, 0, model.mesh.triangle_count-1)
        val = array(values, (6,), -32768, 32767)
        struct.pack_into('>6h', result, struct.unpack_from('>I', raw, 8)[0]+16*index+4, *val)
    elif kind in ('attachment', 'sphere'):
        attaches, spheres = structures(raw)
        rows = attaches if kind == 'attachment' else spheres
        integer(index, 0, len(rows)-1)
        val = array(values, (1 if kind == 'attachment' else 2,), 0, 32767)
        integer(int(val[0]), 0, model.mesh.vertex_count-1)
        pointer = 0x14 if kind == 'attachment' else 0x1C
        start = struct.unpack_from('>I', raw, pointer)[0]
        struct.pack_into('>h' if kind == 'attachment' else '>2h', result, start+index*len(val)*2, *val)
    elif kind == 'distance':
        if type(values) not in (int, float) or not math.isfinite(values) or not 0 <= values <= 100000:
            raise ValueError('Collision broad-phase distance must be finite in 0..100000')
        struct.pack_into('>f', result, 0x3C, values)
    else:
        raise ValueError('Unknown model field')
    validate_mesh(raw, bytes(result))
    return bytes(result)


def group_bases(model: ObjectModel) -> NDArray[np.int32]:
    return np.array([model.mesh.segments[0].vertices[np.flatnonzero(model.animated_indices == g)[0]]
                     for g in range(model.animated_count)], dtype=np.int32).reshape(-1, 3)


def clip_offsets(clip: AnimationClip, model: ObjectModel) -> NDArray[np.int32]:
    return (clip.positions.astype(np.int32)-group_bases(model)).astype(np.int16).astype(np.int32)


def encode_clip(original: bytes, model: ObjectModel, offsets: object) -> bytes:
    clip = AnimationClip.from_bytes(original, model)
    values = array(offsets, (clip.frame_count, model.animated_count, 3), -32768, 32767)
    deltas = (values[1:]-values[:-1]).astype(np.int16).astype(np.int32)
    if np.any(deltas < -128) or np.any(deltas > 127):
        bad = np.argwhere((deltas < -128) | (deltas > 127))[0]
        raise ValueError(f'Frame {bad[0]+1}, group {bad[1]}: consecutive offsets need signed8 deltas (-128..127)')
    raw = bytearray(original)
    raw[16:16+6*model.animated_count] = values[0].astype('>i2').tobytes()
    stride = 12+3*model.animated_count
    for i, delta in enumerate(deltas):
        start = 16+6*model.animated_count+12+i*stride
        raw[start:start+3*model.animated_count] = delta.astype(np.int8).tobytes()
    validate_clip(original, bytes(raw), model)
    return bytes(raw)


def validate_clip(original: bytes, raw: bytes, model: ObjectModel) -> AnimationClip:
    before = AnimationClip.from_bytes(original, model)
    clip = AnimationClip.from_bytes(raw, model)
    if len(raw) != len(original) or before.frame_count != clip.frame_count:
        raise ValueError('Clip frame count and decoded size must stay unchanged')
    n, stride = model.animated_count, 12+3*model.animated_count
    if raw[:16] != original[:16]:
        raise ValueError('Animation frame headers/root controls are protected')
    for i in range(before.frame_count-1):
        start = 16+6*n+i*stride
        if raw[start:start+12] != original[start:start+12]:
            raise ValueError('Animation frame headers/root controls are protected')
    end = 16+6*n+(before.frame_count-1)*stride
    if raw[end:] != original[end:]:
        raise ValueError('Animation alignment is protected')
    return clip


def animation_document(raw: bytes, model: ObjectModel) -> dict[str, object]:
    clip = AnimationClip.from_bytes(raw, model)
    return {'format': 'dkr-vertex-animation', 'version': 1, 'groups': model.animated_count,
            'frames': clip.frame_count, 'mapping_sha1': hashlib.sha1(model.animated_indices.astype('>i2').tobytes()).hexdigest(),
            'offsets': clip_offsets(clip, model).tolist()}


def import_animation(original: bytes, model: ObjectModel, document: object) -> bytes:
    expected = animation_document(original, model)
    if not isinstance(document, dict) or any(type(document.get(k)) is not type(expected[k]) or document.get(k) != expected[k]
            for k in ('format', 'version', 'groups', 'frames', 'mapping_sha1')):
        raise ValueError('Animation replacement needs matching mapping, group count and frame count')
    return encode_clip(original, model, document.get('offsets'))


def mesh_obj(raw: bytes) -> str:
    """Export the indexed base mesh in compact OBJ units, retaining row identities."""
    model = ObjectModel.from_bytes(raw)
    lines = ['# DKR fixed-topology object mesh: retain vertex order and connectivity; Y up.',
             f'# 1 OBJ unit = {GAME_UNITS_PER_OBJ_UNIT:g} model units; Blender import/export Scale 1.',
             '# Position-only exchange; colors/UVs/materials/attachments stay in the editor.']
    lines.extend('v '+' '.join(f'{float(v)*OBJ_UNITS_PER_GAME_UNIT:.9g}' for v in p)
                 for p in model.mesh.segments[0].vertices)
    lines.extend('f '+' '.join(str(int(i)+1) for i in face) for face in model.mesh.indices)
    return '\n'.join(lines)+'\n'


def import_mesh_obj(raw: bytes, text: str) -> bytes:
    """Restore compact XYZ to model units before quantization/topology validation."""
    if not isinstance(text, str) or len(text) > 8*1024*1024:
        raise ValueError('Object OBJ exceeds 8 MiB')
    model = ObjectModel.from_bytes(raw)
    vertices: list[list[int]] = []
    faces: list[list[int]] = []
    for line in text.splitlines():
        words = line.split('#', 1)[0].split()
        if not words:
            continue
        if words[0] == 'v':
            if len(words) not in (4, 7, 8):
                raise ValueError('OBJ vertex needs XYZ')
            p = [float(w)*GAME_UNITS_PER_OBJ_UNIT for w in words[1:4]]
            if any(not math.isfinite(v) or not -32768 <= round(v) <= 32767 for v in p):
                raise ValueError('OBJ coordinates exceed signed16')
            vertices.append([round(v) for v in p])
        elif words[0] == 'f':
            if len(words) != 4:
                raise ValueError('Keep triangular faces and original topology')
            row = [int(w.split('/')[0]) for w in words[1:]]
            faces.append([i-1 if i > 0 else len(vertices)+i for i in row])
        elif words[0] not in ('vt', 'vn', 'o', 'g', 's', 'usemtl', 'mtllib'):
            raise ValueError(f'Unsupported OBJ record: {words[0]}')
        if len(vertices) > model.mesh.vertex_count or len(faces) > model.mesh.triangle_count:
            raise ValueError('Object OBJ counts must stay unchanged')
    positions = array(vertices, (model.mesh.vertex_count, 3), -32768, 32767)
    def face_key(face: object) -> tuple[int, int, int]:
        a, b, c = (int(v) for v in face)
        return min((a, b, c), (b, c, a), (c, a, b))
    # Position-only import: external face sorting/cyclic corner rotations do not
    # alter the destination's original batches, UVs, face order or winding.
    expected = Counter(face_key(f) for f in model.mesh.indices)
    actual = Counter(face_key(f) for f in faces)
    # Stock models can carry (v,v,v) anchor faces to retain loose vertices.
    # Blender drops those non-polygons; retain the original binary records.
    missing = expected-actual
    if actual-expected or any(len(set(face)) == 3 for face in missing):
        raise ValueError('Object OBJ connectivity/winding must match; keep vertex order when exporting')
    result = bytearray(raw)
    start = struct.unpack_from('>I', raw, 4)[0]
    for i, p in enumerate(positions):
        struct.pack_into('>3h', result, start+i*10, *p)
    validate_mesh(raw, bytes(result))
    return bytes(result)


def animation_owner(source: RomImage, animation_id: int) -> int:
    integer(animation_id, 0, source.count(AssetType.OBJECT_ANIMATIONS)-1)
    library = ObjectLibrary(source)
    return next(i for i, (a, b) in enumerate(zip(library.animation_ids, library.animation_ids[1:])) if a <= animation_id < b)


def validate_asset(session: EditSession, key: AssetKey, raw: bytes) -> None:
    original = session.original_asset(*key)
    if key[0] == AssetType.OBJECT_MODELS:
        if len(raw) != len(original):
            from src.core.object_rebuild import validate_rebuild
            validate_rebuild(session.rom, key[1], original, raw)
        else:
            validate_mesh(original, raw)
    elif key[0] == AssetType.OBJECT_ANIMATIONS:
        owner = animation_owner(session.rom, key[1])
        model = session.original_object_model(owner)
        validate_clip(original, raw, model)
    else:
        raise ValueError('Not an object-model/animation asset')


def asset_uses(session: EditSession) -> dict[int, tuple[tuple[int, ...], tuple[str, ...]]]:
    uses = definition_uses(session)
    result: dict[int, tuple[tuple[int, ...], tuple[str, ...]]] = {}
    for d in session.database.definitions:
        if d.model_type != 0:
            continue
        for model_id in d.model_ids:
            headers, levels = result.get(model_id, ((), ()))
            result[model_id] = (tuple(sorted({*headers, d.header_id})), tuple(sorted({*levels, *uses[d.header_id].levels})))
    return result


def prepare_sections(session: EditSession, updates: dict[AssetKey, bytes], sections: tuple[bytes, ...],
                     diffs: tuple[AssetDiff, ...]) -> tuple[tuple[bytes, ...], tuple[AssetDiff, ...]]:
    """Rebuild only changed compressed entries; preserve every other entry/table tail."""
    from src.core.editing import compress_asset
    result = list(sections)
    reports = list(diffs)
    uses = asset_uses(session) if updates else {}
    for section in sorted(MODEL_ASSETS):
        ids = {i for s, i in updates if s == section and updates[s, i] != session.original_asset(s, i)}
        if not ids:
            continue
        data, table = session.rom.section(section), session.rom.index_table(section)
        chunks: list[bytes] = []
        offsets = [0]
        for i in range(len(table)):
            span = table.span(i)
            chunk = data[span.start:span.end]
            if i in ids:
                raw = updates[section, i]
                validate_asset(session, (section, i), raw)
                overlay = raw
                if section == AssetType.OBJECT_MODELS:
                    from src.core.render_batches import rebatch_static_model
                    raw = rebatch_static_model(session.rom, i, session.original_asset(section, i), raw)
                packed = compress_asset(raw)
                # Object models/clips allocate their own decoded-size+0x80 block,
                # rather than the fixed 0x3000 object-map workspace.
                audit_inplace_rare(packed, workspace=len(raw)+0x80, slack=0x80)
                owner = i if section == AssetType.OBJECT_MODELS else animation_owner(session.rom, i)
                headers, levels = uses.get(owner, ((), ()))
                base = session.original_asset(section, i)
                rebuilt = section == AssetType.OBJECT_MODELS and len(raw) != len(base)
                from src.core.object_rebuild import report_changes
                details = (report_changes(base, raw) if rebuilt else ('Fixed decoded size, counts and runtime allocation layout retained.',)) + (
                    'Shared model headers: '+(', '.join(map(str, headers)) or 'No header reference; compiled uses may exist'),
                    f'{sum(a != b for a, b in zip(base, raw))+abs(len(raw)-len(base)):,} changed/appended decoded bytes; model {owner}.',
                    'Collision normals/facets regenerate in-game; root/head controls remain unchanged. Gameplay review required.')
                if raw != overlay:
                    details += ('Legacy draw batches split to at most 24 vertices; face order and attachment/collision references retained.',)
                reports.append(AssetDiff(int(section), i, f'{section.name} {i}', len(base), len(raw), len(chunk), len(packed), levels, details))
                chunk = packed
            chunks.append(chunk)
            offsets.append(offsets[-1]+len(chunk))
        chunks.append(data[table.offsets[-1]:])
        table_section = int(section)-1
        table_raw = bytearray(result[table_section])
        struct.pack_into('>'+str(len(offsets))+'I', table_raw, 0, *offsets)
        result[table_section], result[int(section)] = bytes(table_raw), b''.join(chunks)
        AssetTable.parse(result[table_section], len(result[int(section)]))
    return tuple(result), tuple(reports)


@dataclass(frozen=True)
class ModelPlan:
    signature: str
    before: tuple[tuple[AssetKey, bytes], ...]
    after: tuple[tuple[AssetKey, bytes], ...]
    report: ExportReport


def plan_models(session: EditSession, drafts: dict[AssetKey, bytes]) -> ModelPlan:
    session._require_idle()
    for key, raw in drafts.items():
        if (not isinstance(key, tuple) or len(key) != 2 or key[0] not in MODEL_ASSETS
                or type(raw) is not bytes):
            raise ValueError('Invalid object-model draft')
        integer(key[1], 0, session.rom.count(key[0])-1)
        validate_asset(session, key, raw)
    changed = {key: raw for key, raw in drafts.items() if raw != session.current_asset(*key)}
    sections, old = session._prepare_export()
    old_layout_errors = make_export_report(session.rom, sections, old.assets).errors
    final = {key: raw for key, raw in session._assets.items() if key[0] in MODEL_ASSETS}
    final.update(changed)
    sections, diffs = prepare_sections(session, final, sections, tuple(d for d in old.assets if d.section not in MODEL_ASSETS))
    # When the last edit in a section is restored, use the original table/data.
    sections = list(sections)
    for s in MODEL_ASSETS:
        if not any(k[0] == s and v != session.original_asset(*k) for k, v in final.items()):
            sections[int(s)-1], sections[int(s)] = session.rom.section(AssetType(int(s)-1)), session.rom.section(s)
    report = make_export_report(session.rom, tuple(sections), diffs)
    report = report.retain_validation_errors(old, old_layout_errors)
    if not report.can_export:
        raise ValueError('; '.join(report.errors))
    return ModelPlan(session._signature(), tuple((k, session.current_asset(*k)) for k in sorted(changed)),
                     tuple(sorted(changed.items())), report)
