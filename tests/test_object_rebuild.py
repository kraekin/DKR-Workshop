"""Static topology compiler, source command fields, references and v15 isolation."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import pytest

from src.core.compression import audit_inplace_rare
from src.core.editing import EditSession, compress_asset
from src.core.model_editing import edit_mesh, plan_models, structures
from src.core.object_models import ObjectLibrary, ObjectModel
from src.core.object_rebuild import (MAX_BATCH_FACES, MAX_BATCH_VERTICES, MAX_MODEL_BYTES,
    MAX_TRIANGLES, compile_static, eligible, rebuild_obj, runtime_usage, validate_rebuild)
from src.core.rom import AssetType, RomImage, parse_asset_lut, LUT_START, LUT_END

ROOT = Path(__file__).resolve().parents[1]
M = AssetType.OBJECT_MODELS
TRIANGLE = 'v 0 0 0\nv .16 0 0\nv 0 .16 0\nf 1 2 3\n'
QUAD = 'v 0 0 0\nv .16 0 0\nv .16 .16 0\nv 0 .16 0\nf 1 2 3 4\n'


def compact_fixture(text: str) -> str:
    """Convert explicitly raw-unit test input; production import never guesses units."""
    lines = []
    for line in text.splitlines():
        words = line.split()
        if words and words[0] == 'v':
            words[1:4] = [f'{float(v)/100:.12g}' for v in words[1:4]]
            line = ' '.join(words)
        lines.append(line)
    return '\n'.join(lines)+'\n'


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:
        pytest.skip('Original local Rev1 ROM absent')
    return RomImage.from_file(paths[0])


def test_user_extruded_sign_compiles_without_modifying_inputs(rom: RomImage) -> None:
    original = Path(r'D:\RomHacking\n64\model_256.obj')
    edited = Path(r'D:\RomHacking\n64\model_256edit.obj')
    if not original.exists() or not edited.exists():
        pytest.skip('User sign reproduction absent')
    hashes = [hashlib.sha1(p.read_bytes()).digest() for p in (original, edited)]
    result = compile_static(rom, 256, compact_fixture(edited.read_text()))
    raw = rom.read_asset(M, 256, decompress=True)
    model = validate_rebuild(rom, 256, raw, result.raw)
    assert result.input_vertices == 42 and model.mesh.triangle_count == 34
    assert result.inferred_faces == 34 and model.animated_count == 0
    assert model.mesh.segments[0].vertices[:, 0].max() == 4
    assert [hashlib.sha1(p.read_bytes()).digest() for p in (original, edited)] == hashes


def test_all_static_stock_templates(rom: RomImage) -> None:
    library = ObjectLibrary(rom)
    passed, refused, static = [], [], []
    for i in range(390):
        if library.clip_count(i):
            continue
        static.append(i)
        model = library.model(i)
        try:
            eligible(rom, i, model.raw_data)
            result = compile_static(rom, i, rebuild_obj(model.raw_data, rom))
            validate_rebuild(rom, i, model.raw_data, result.raw)
            assert result.raw[:4] == model.raw_data[:4]  # texture table retained
            audit_inplace_rare(compress_asset(result.raw), workspace=len(result.raw)+0x80, slack=0x80)
            passed.append(i)
        except ValueError as error:
            assert any(s in str(error) for s in ('transform matrices', 'no triangle faces', 'no appearance triangles')), (i, str(error))
            refused.append(i)
    assert len(static) == 207 and len(passed) >= 190
    assert 256 in passed and len(passed)+len(refused) == 207
    print(f'Static source coverage: {len(passed)} rebuilt, {len(refused)} explicitly refused, {len(static)} checked.')


def _extruded_decal_obj(rom: RomImage, *, explicit: bool) -> str:
    """Source-derived cap extrusion; no dependency on the user's external file."""
    seg = ObjectLibrary(rom).model(256).mesh.segments[0]
    cap = seg.batches[-1].faces_offset
    original_ids = seg.indices[cap]
    added = seg.vertices[original_ids].copy()
    added[:, 0] += 2
    vertices = np.concatenate((seg.vertices, added))
    rows = ['v '+' '.join(map(str, p)) for p in vertices]
    batch_of = {j: i for i, (b, end) in enumerate(zip(seg.batches,
        (*seg.batches[1:], seg.terminal_batch))) for j in range(b.faces_offset, end.faces_offset)}
    new_ids = tuple(range(len(seg.vertices), len(vertices)))
    for j, face in enumerate(seg.indices):
        if explicit:
            rows.append(f'usemtl batch_{batch_of[j]}')
        rows.append('f '+' '.join(str(int(v)+1) for v in (new_ids if j == cap else face)))
    if explicit:
        rows.append(f'usemtl batch_{len(seg.batches)-1}')
    for i in range(3):
        following = (i+1) % 3
        rows.append('f '+' '.join(str(int(v)+1) for v in
            (original_ids[i], original_ids[following], new_ids[following], new_ids[i])))
    return compact_fixture('\n'.join(rows))


@pytest.mark.parametrize('explicit', [False, True])
def test_extrusion_walls_inherit_side_material_unless_explicit(rom: RomImage, explicit: bool) -> None:
    result = compile_static(rom, 256, _extruded_decal_obj(rom, explicit=explicit))
    seg = ObjectModel.from_bytes(result.raw).mesh.segments[0]
    walls = caps = 0
    for b, end in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
        for j in range(b.faces_offset, end.faces_offset):
            p = seg.vertices[seg.indices[j]]
            if np.all(p[:, 0] == 4):
                caps += 1
                assert b.flags & 0x800 and b.texture_index == 0
            elif p[:, 0].max() == 4 and np.ptp(p[:, 0]):
                walls += 1
                assert bool(b.flags & 0x800) == explicit
                assert b.texture_index == (0 if explicit else 2)
                if not explicit:
                    uv = seg.uvs[j].astype(np.float64)
                    edge, other = uv[1]-uv[0], uv[2]-uv[0]
                    assert abs(edge[0]*other[1]-edge[1]*other[0]) > 0
    assert caps == 1 and walls == 6


def test_legacy_reimport_uses_original_rows_after_decal_wall_rebuild(rom: RomImage) -> None:
    text = _extruded_decal_obj(rom, explicit=False)
    expected = compile_static(rom, 256, text).raw
    # Reproduce an earlier draft whose new walls all used the decal signature.
    previous = compile_static(rom, 256, _extruded_decal_obj(rom, explicit=True)).raw
    assert previous != expected
    assert compile_static(rom, 256, text, appearance=previous).raw == expected
    assert compile_static(rom, 256, text, appearance=expected).raw == expected


def test_legacy_reimport_retargets_current_attachment_to_original_rows(rom: RomImage) -> None:
    model = ObjectLibrary(rom).model(83)
    text = rebuild_obj(model.raw_data, rom)
    compiled = compile_static(rom, 83, text).raw
    legacy = '\n'.join(line for line in text.splitlines() if not line.startswith('usemtl'))
    result = compile_static(rom, 83, legacy, appearance=compiled).raw
    old, _ = structures(model.raw_data)
    current, _ = structures(compiled)
    after, _ = structures(result)
    assert old and current != old  # reproduction requires reordered stored rows
    expected = model.mesh.segments[0].vertices[list(old)]
    np.testing.assert_array_equal(ObjectModel.from_bytes(result).mesh.segments[0].vertices[list(after)], expected)
    moved = edit_mesh(compiled, 'vertex', current[0], np.array([1000, 1000, 1000]))
    with pytest.raises(ValueError, match='cannot retain a current attachment/collision vertex'):
        compile_static(rom, 83, legacy, appearance=moved)


def test_positive_growth_refusal_leaves_session_untouched(rom: RomImage) -> None:
    s = EditSession(rom)
    original_end = rom.sections[-1].end
    # Simulate a ROM with no usable trailing padding; asset contents stay exact.
    s.rom = replace(rom, data=rom.data[:original_end]+b'\x01'+rom.data[original_end+1:])
    text = 'vt 0 0\nvt 1 0\nvt 0 1\n'
    for i in range(100):
        x = i*13
        text += f'v {x} 0 0\nv {x+7} 0 0\nv {x} 11 0\nf {i*3+1}/1 {i*3+2}/2 {i*3+3}/3\n'
    raw = compile_static(rom, 256, compact_fixture(text)).raw
    signature, cursor = s._signature(), s._cursor
    with pytest.raises(ValueError, match='padding'):
        plan_models(s, {(M, 256): raw})
    assert (s._signature(), s._cursor) == (signature, cursor)


def test_mixed_version15_project_keeps_older_features(rom: RomImage, tmp_path: Path) -> None:
    from src.core.object_structure import ObjectTemplate
    from src.core.global_objects import edit_definition, plan_global_objects
    from src.core.track_import import ImportOptions, parse_obj, default_materials
    from src.core.track_segments import compile_segmented_obj
    from src.core.track_artwork import MaterialImage, ObjMaterial, TextureOptions, stage_artwork
    s = EditSession(rom)
    mesh = parse_obj('usemtl Road\nv -2000 24 -7000\nv -2000 24 -6600\nv -1600 24 -6600\n'
        'vt 0 0\nvt 0 1\nvt 1 1\nf 1/1 2/2 3/3\n')
    image = MaterialImage(ObjMaterial('Road'), np.full((8, 8, 4), 255, np.uint8), TextureOptions(8, 8), 0)
    track = s.track_model(5)
    appearance, mapping, added, refs = stage_artwork(track.raw_data, s.material_references,
        default_materials(mesh, track), {'Road': image}, {})
    result = compile_segmented_obj(mesh, s.original_asset(AssetType.LEVEL_MODELS, 5), refs, mapping, ImportOptions(scale=1.0), appearance=appearance)
    s.import_track(5, result.raw, textures=added)
    key = s.add_object(5, ObjectTemplate(78), (-1000, 100, -7000))
    s.set_course_names(5, {'english': 'Static Course'})
    header = edit_definition(s.current_asset(AssetType.OBJECTS, 48), 'scale', 4.)
    s.apply_global_objects(plan_global_objects(s, {48: header}))
    s.apply_models(plan_models(s, {(M, 256): compile_static(rom, 256, QUAD).raw}))
    path = s.save_project(tmp_path/'coexist.dkrproj')
    loaded = EditSession.load_project(path)
    assert loaded.project_document()['version'] == 15
    assert loaded._signature() == s._signature()
    assert loaded.object(key).definition.scale == 4
    assert loaded.track_model(5).raw_data == s.track_model(5).raw_data
    assert loaded.export_report().can_export


def test_quad_triangulation_and_canonical_repeated_rebuild(rom: RomImage) -> None:
    result = compile_static(rom, 256, QUAD)
    model = ObjectModel.from_bytes(result.raw)
    assert model.mesh.triangle_count == 2 and model.mesh.vertex_count == 4
    repeated = compile_static(rom, 256, rebuild_obj(result.raw, rom), appearance=result.raw)
    assert repeated.raw == result.raw
    assert runtime_usage(result.raw)[0] == len(result.raw)+0x80


@pytest.mark.parametrize('model_id', [0, 16, 240])
def test_animation_or_matrix_splits_are_explicitly_refused(rom: RomImage, model_id: int) -> None:
    # Pick an animated model independently of hardcoded assumptions for 0/16.
    library = ObjectLibrary(rom)
    if not library.clip_count(model_id):
        model_id = next(i for i in range(390) if library.clip_count(i))
    with pytest.raises(ValueError, match='animation clips'):
        compile_static(rom, model_id, TRIANGLE)


@pytest.mark.parametrize('text', [
    '', 'v nan 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3',
    'v inf 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3',
    'v 40000 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3',
    'v 0 0 0\nv 0.001 0 0\nv 0 0.001 0\nf 1 2 3',
    TRIANGLE.replace('f 1 2 3', 'f 0 2 3'),
    TRIANGLE.replace('f 1 2 3', 'f 1 2 9'),
    'usemtl unknown\n'+TRIANGLE,
    'usemtl batch_999\n'+TRIANGLE,
    'cstype bspline\n'+TRIANGLE,
    'v 0 0 0\nv 2 0 0\nv 0 2 1\nv 1 1 0\nf 1 2 3 4',
    'v 0 0 0\nv 2 0 0\nv 1 1 0\nv 2 2 0\nv 0 2 0\nf 1 2 3 4 5',
])
def test_malformed_obj_is_refused(rom: RomImage, text: str) -> None:
    with pytest.raises(ValueError):
        compile_static(rom, 256, text)


@pytest.mark.parametrize('offset', [0, 0xC, 0x10, 0x18, 0x1A, 0x20, 0x22, 0x2A, 0x30, 0x32,
    0x34, 0x40, 0x44, 0x48, 0x50, 0x52, 0x54, 0x60, 0x98, 0x120])
def test_protected_original_prefix(rom: RomImage, offset: int) -> None:
    original = rom.read_asset(M, 256, decompress=True)
    raw = bytearray(compile_static(rom, 256, QUAD).raw)
    raw[offset] ^= 1
    with pytest.raises(ValueError):
        validate_rebuild(rom, 256, original, bytes(raw))


def test_canonical_pointers_mapping_padding_and_sentinel(rom: RomImage) -> None:
    original = rom.read_asset(M, 256, decompress=True)
    raw = compile_static(rom, 256, QUAD).raw
    for offset, fmt, value in ((4, 'I', 0x58), (8, 'I', 0x58), (0x38, 'I', 0x58),
        (0x4A, 'h', 1), (0x4C, 'I', 0x58), (0x3C, 'f', float('nan')), (0x2C, 'I', len(raw)-16)):
        bad = bytearray(raw)
        struct.pack_into('>'+fmt, bad, offset, value)
        with pytest.raises(ValueError):
            validate_rebuild(rom, 256, original, bytes(bad))
    bad = bytearray(raw)
    bad[len(original)] = 1
    with pytest.raises(ValueError, match='padding'):
        validate_rebuild(rom, 256, original, bytes(bad))
    assert struct.unpack_from('>hI', raw, 0x4A) == (0, 0)


def test_microcode_batches_and_editor_limits(rom: RomImage) -> None:
    lines = ['vt 0 0', 'vt 1 0', 'vt 0 1']
    for i in range(40):
        x = i*20
        lines.extend((f'v {x} 0 0', f'v {x+10} 0 0', f'v {x} 10 0', f'f {i*3+1}/1 {i*3+2}/2 {i*3+3}/3'))
    raw = compile_static(rom, 256, compact_fixture('\n'.join(lines))).raw
    model = ObjectModel.from_bytes(raw)
    seg = model.mesh.segments[0]
    assert len(seg.batches) > 1
    for b, e in zip(seg.batches, (*seg.batches[1:], seg.terminal_batch)):
        assert 1 <= e.vertices_offset-b.vertices_offset <= MAX_BATCH_VERTICES
        assert 1 <= e.faces_offset-b.faces_offset <= MAX_BATCH_FACES
    with pytest.raises(ValueError):
        compile_static(rom, 256, TRIANGLE+'f 1 2 3\n'*MAX_TRIANGLES)


def test_material_uv_color_and_winding(rom: RomImage) -> None:
    text = ('usemtl batch_2\nv 0 0 0 1 0 0\nv .16 0 0 0 1 0\nv 0 .16 0 0 0 1\n'
        'vt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3')
    raw = compile_static(rom, 256, text).raw
    model = ObjectModel.from_bytes(raw)
    seg = model.mesh.segments[0]
    b = seg.batches[0]
    original_batch = ObjectModel.from_bytes(rom.read_asset(M, 256, decompress=True)).mesh.segments[0].batches[2]
    assert (b.texture_index, b.flags) == (original_batch.texture_index, original_batch.flags)
    np.testing.assert_array_equal(seg.colors, [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]])
    assert np.cross(seg.vertices[1]-seg.vertices[0], seg.vertices[2]-seg.vertices[0])[2] > 0
    assert seg.uvs[0, 0, 0] == 0 and seg.uvs[0, 1, 0] > 0


def test_lit_source_vertex_literals_retained_before_runtime_shading(rom: RomImage) -> None:
    original = ObjectModel.from_bytes(rom.read_asset(M, 260, decompress=True))
    rebuilt = ObjectModel.from_bytes(compile_static(rom, 260, TRIANGLE).raw)
    np.testing.assert_array_equal(rebuilt.mesh.segments[0].colors[:3], original.mesh.segments[0].colors[:3])


def test_rebuilt_triangle_flags_remain_source_verified(rom: RomImage) -> None:
    original = rom.read_asset(M, 256, decompress=True)
    raw = bytearray(compile_static(rom, 256, QUAD).raw)
    fp = struct.unpack_from('>I', raw, 8)[0]
    raw[fp] = 0xFF
    with pytest.raises(ValueError, match='triangle flags'):
        validate_rebuild(rom, 256, original, bytes(raw))


def test_reference_vertices_retarget_and_hidden_anchor(rom: RomImage) -> None:
    library = ObjectLibrary(rom)
    candidates = [i for i in range(390) if not library.clip_count(i) and any(structures(library.model(i).raw_data))]
    assert candidates
    for index in candidates[:4]:
        base = library.model(index)
        try:
            eligible(rom, index, base.raw_data)
        except ValueError:
            continue
        # Keep source reference rows, replace visible faces with a fresh triangle.
        text = '\n'.join('v '+' '.join(map(str, map(int, p))) for p in base.mesh.segments[0].vertices)
        n = base.mesh.vertex_count
        text += f'\nv 0 0 0\nv 16 0 0\nv 0 16 0\nf {n+1} {n+2} {n+3}\n'
        result = compile_static(rom, index, compact_fixture(text))
        model = ObjectModel.from_bytes(result.raw)
        old_a, old_s = structures(base.raw_data)
        new_a, new_s = structures(result.raw)
        assert len(old_a) == len(new_a) and len(old_s) == len(new_s)
        for before, after in zip((*old_a, *(v for v, _ in old_s)), (*new_a, *(v for v, _ in new_s))):
            np.testing.assert_array_equal(base.mesh.segments[0].vertices[before], model.mesh.segments[0].vertices[after])
        assert result.anchors
        return
    pytest.fail('No eligible static reference model found')


def test_atomic_history_subsequent_edits_and_restoration(rom: RomImage) -> None:
    s = EditSession(rom)
    original = s.current_asset(M, 256)
    baseline = s._signature(), s._cursor
    raw = compile_static(rom, 256, QUAD).raw
    plan = plan_models(s, {(M, 256): raw})
    assert (s._signature(), s._cursor) == baseline
    assert any('Shared model + normals' in c for d in plan.report.assets for c in d.changes)
    s.apply_models(plan)
    assert ObjectLibrary(s.asset_source).model(256).mesh.triangle_count == 2
    moved = edit_mesh(s.current_asset(M, 256), 'vertex', 0, [0, 0, 1])
    s.apply_models(plan_models(s, {(M, 256): moved}))
    s.undo(); assert s.current_asset(M, 256) == raw
    s.undo(); assert s._signature() == baseline[0]
    s.redo(); assert s.current_asset(M, 256) == raw
    with pytest.raises(ValueError, match='stale'):
        s.apply_models(plan)
    s.apply_models(plan_models(s, {(M, 256): original}))
    assert not s.dirty and not s.export_report().assets


def test_v15_project_legacy_refusal_tamper_and_mixed_edits(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    raw = compile_static(rom, 256, QUAD).raw
    s.apply_models(plan_models(s, {(M, 256): raw}))
    s.set_course_names(5, {'english': 'Static Course'})
    document = s.project_document(5)
    assert document['version'] == 15 and len(document['object_rebuilds']) == 1
    assert not any(row['section'] == 29 for row in document['asset_edits'])
    path = s.save_project(tmp_path/'rebuilt.dkrproj', 5)
    loaded = EditSession.load_project(path)
    assert loaded._signature() == s._signature() and loaded.current_asset(M, 256) == raw
    for version in range(1, 15):
        bad = dict(document, version=version)
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            EditSession.load_project(path)
    damaged = bytearray(raw); damaged[0x54] ^= 1
    document['object_rebuilds'][0]['data'] = damaged.hex()
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        EditSession.load_project(path)


def test_in_memory_rom_only_selected_model_and_table_change(rom: RomImage) -> None:
    s = EditSession(rom)
    raw = compile_static(rom, 256, QUAD).raw
    s.apply_models(plan_models(s, {(M, 256): raw}))
    data = s.build_rom()
    result = RomImage(data, 'z64', parse_asset_lut(data, LUT_START, LUT_END))
    assert result.read_asset(M, 256, decompress=True) == raw
    for i in range(390):
        if i != 256:
            assert result.read_asset(M, i) == rom.read_asset(M, i)
    for section in AssetType:
        if int(section) not in (28, 29):
            assert result.section(section) == rom.section(section)
    assert hashlib.sha1(rom.data).hexdigest() == '6d96743d46f8c0cd0edb0ec5600b003c89b93755'
