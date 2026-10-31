"""Source-format object art, encoding, protected writes and shared persistence."""
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
from src.core.global_objects import edit_definition, plan_global_objects
from src.core.model_editing import (animation_document, animation_owner, asset_uses,
    clip_offsets, edit_mesh, encode_clip, import_animation, import_mesh_obj,
    linked_vertices, mesh_obj, plan_models, structures, validate_clip, validate_mesh, _normal_keys)
from src.core.object_models import AnimationClip, ObjectLibrary, ObjectModel
from src.core.rom import AssetType, RomImage, parse_asset_lut, LUT_START, LUT_END

ROOT = Path(__file__).resolve().parents[1]
M, A = AssetType.OBJECT_MODELS, AssetType.OBJECT_ANIMATIONS


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(ROOT.glob('*.z64'))
    if not paths:
        pytest.skip('Original local Rev1 ROM absent')
    return RomImage.from_file(paths[0])


@pytest.fixture(scope='module')
def library(rom: RomImage) -> ObjectLibrary:
    return ObjectLibrary(rom)


def shifted_mesh(raw: bytes, distance: int = 1) -> bytes:
    text = mesh_obj(raw)
    lines = []
    for line in text.splitlines():
        if line.startswith('v '):
            words = line.split()
            words[1] = str(float(words[1])+distance/100)
            line = ' '.join(words)
        lines.append(line)
    return import_mesh_obj(raw, '\n'.join(lines))


def shifted_clip(raw: bytes, model: ObjectModel, distance: int = 1) -> bytes:
    doc = animation_document(raw, model)
    values = np.array(doc['offsets'])
    values[:, :, 1] += distance
    doc['offsets'] = values.tolist()
    return import_animation(raw, model, doc)


def test_every_stock_mesh_and_clip_lossless(library: ObjectLibrary) -> None:
    counts = 0
    for i in range(390):
        model = library.model(i)
        assert validate_mesh(model.raw_data, model.raw_data).raw_data == model.raw_data
        assert import_mesh_obj(model.raw_data, mesh_obj(model.raw_data)) == model.raw_data
        for j in range(library.clip_count(i)):
            clip = library.clip(i, j)
            assert import_animation(clip.raw_data, model, animation_document(clip.raw_data, model)) == clip.raw_data
            assert animation_owner(library.source, clip.animation_id) == i
            counts += 1
    assert counts == 470


@pytest.mark.parametrize('model_id', [0, 1, 16, 50, 100, 150, 200, 240, 260, 300, 350, 389])
def test_mesh_replacement_retains_topology_mapping_and_opaque_bytes(library: ObjectLibrary, model_id: int) -> None:
    model = library.model(model_id)
    after = shifted_mesh(model.raw_data)
    parsed = validate_mesh(model.raw_data, after)
    np.testing.assert_array_equal(parsed.mesh.segments[0].vertices,
        model.mesh.segments[0].vertices+np.array([1, 0, 0]))
    np.testing.assert_array_equal(parsed.mesh.indices, model.mesh.indices)
    np.testing.assert_array_equal(parsed.animated_indices, model.animated_indices)
    assert after[:0x58] == model.raw_data[:0x58]


@pytest.mark.parametrize('offset', [0, 4, 8, 0xC, 0x10, 0x14, 0x18, 0x1A, 0x1C, 0x20, 0x22,
    0x24, 0x26, 0x28, 0x2A, 0x2C, 0x30, 0x32, 0x34, 0x38, 0x40, 0x44, 0x48, 0x4A, 0x4C, 0x50, 0x52, 0x54])
def test_protected_header_bytes(library: ObjectLibrary, offset: int) -> None:
    original = library.model(240).raw_data
    raw = bytearray(original)
    raw[offset] ^= 1
    with pytest.raises(ValueError):
        validate_mesh(original, bytes(raw))


def test_linked_vertex_edit_and_normal_partition(library: ObjectLibrary) -> None:
    model = library.model(240)
    index = next(i for i in range(model.mesh.vertex_count) if len(linked_vertices(model, i)) > 1)
    group = linked_vertices(model, index)
    before = model.mesh.segments[0].vertices
    point = before[index].astype(np.int32)+[1, 0, 0]
    raw = edit_mesh(model.raw_data, 'vertex', index, point.tolist())
    after = validate_mesh(model.raw_data, raw).mesh.segments[0].vertices
    np.testing.assert_array_equal(after[list(group)], np.tile(point, (len(group), 1)))
    np.testing.assert_array_equal(after[[i for i in range(len(before)) if i not in group]],
        before[[i for i in range(len(before)) if i not in group]])


def test_baked_rgba_uv_and_lit_protection(library: ObjectLibrary) -> None:
    baked = library.model(254)
    raw = edit_mesh(baked.raw_data, 'color', 0, [13, 24, 35, 46])
    assert list(ObjectModel.from_bytes(raw).mesh.segments[0].colors[0]) == [13, 24, 35, 46]
    raw = edit_mesh(raw, 'uv', 0, [-32768, 32767, -7, 11, 32, 64])
    assert ObjectModel.from_bytes(raw).mesh.segments[0].uvs[0].reshape(-1).tolist() == [-32768, 32767, -7, 11, 32, 64]
    lit = library.model(240)
    with pytest.raises(ValueError, match='protected'):
        edit_mesh(lit.raw_data, 'color', 0, [1, 2, 3, 4])


@pytest.mark.parametrize('kind,values', [('vertex', [32768, 0, 0]), ('vertex', [0.5, 0, 0]),
    ('vertex', [True, False, False]), ('color', [-1, 0, 0, 0]), ('uv', [0]*5), ('distance', float('nan')),
    ('distance', -1), ('distance', float('inf')), ('vertex', [[1, 2, 3]])])
def test_invalid_numeric_input(library: ObjectLibrary, kind: str, values: object) -> None:
    with pytest.raises(ValueError):
        edit_mesh(library.model(240).raw_data, kind, 0, values)


def test_attachments_and_collision_spheres(library: ObjectLibrary) -> None:
    ids = []
    for i in range(390):
        raw = library.model(i).raw_data
        attaches, spheres = structures(raw)
        if attaches:
            after = edit_mesh(raw, 'attachment', 0, [(attaches[0]+1) % library.model(i).mesh.vertex_count])
            assert structures(after)[0][0] != attaches[0]
        if spheres:
            after = edit_mesh(raw, 'sphere', 0, [spheres[0][0], spheres[0][1]+1])
            assert structures(after)[1][0][1] == spheres[0][1]+1
        if attaches or spheres:
            ids.append(i)
    assert ids
    raw = library.model(ids[0]).raw_data
    after = edit_mesh(raw, 'distance', 0, 700.5)
    assert struct.unpack_from('>f', after, 0x3C)[0] == 700.5


def test_animation_signed_deltas_endpoint_and_fraction(library: ObjectLibrary) -> None:
    model = library.model(240)
    clip = library.clip(240, 0)
    raw = shifted_clip(clip.raw_data, model)
    after = validate_clip(clip.raw_data, raw, model)
    expected = clip.positions.astype(np.int32)+[0, 1, 0]
    np.testing.assert_array_equal(after.positions, expected.astype(np.int16))
    for frame16 in (0, 1, 8, 16, (clip.frame_count-1)*16-1):
        moving = model.animated_indices >= 0
        np.testing.assert_array_equal(after.pose(model, frame16)[moving], clip.pose(model, frame16)[moving]+[0, 1, 0])
    values = clip_offsets(after, model)
    values[-1, 0, 0] += 1
    endpoint = AnimationClip.from_bytes(encode_clip(raw, model, values), model)
    assert endpoint.positions[-1, 0, 0] == after.positions[-1, 0, 0]+1


@pytest.mark.parametrize('field,value', [('format', 'other'), ('version', 2), ('groups', 99),
    ('frames', 1), ('mapping_sha1', 'bad'), ('offsets', []), ('offsets', None)])
def test_invalid_clip_exchange(library: ObjectLibrary, field: str, value: object) -> None:
    model, clip = library.model(240), library.clip(240, 0)
    doc = animation_document(clip.raw_data, model)
    assert doc['mapping_sha1'] == hashlib.sha1(model.animated_indices.astype('>i2').tobytes()).hexdigest()
    doc[field] = value
    with pytest.raises(ValueError):
        import_animation(clip.raw_data, model, doc)


def test_delta_overflow_and_frame_headers(library: ObjectLibrary) -> None:
    model, clip = library.model(240), library.clip(240, 0)
    offsets = clip_offsets(clip, model)
    offsets[1, 0, 0] = offsets[0, 0, 0]+128
    with pytest.raises(ValueError, match='signed8'):
        encode_clip(clip.raw_data, model, offsets)
    n = model.animated_count
    for offset in (4, 6, 10, 15, 16+6*n, 16+6*n+6, 16+6*n+11):
        raw = bytearray(clip.raw_data)
        raw[offset] ^= 1
        with pytest.raises(ValueError, match='protected'):
            validate_clip(clip.raw_data, bytes(raw), model)


@pytest.mark.parametrize('text', ['v nan 1 2', 'v inf 1 2', 'v 40000 1 2', 'v 1 2',
    'f 1 2 3 4', 'cstype bezier', '# empty', 'v 0 0 0\nf 1 1 1', 'f 0 1 2'])
def test_invalid_obj(library: ObjectLibrary, text: str) -> None:
    with pytest.raises(ValueError):
        import_mesh_obj(library.model(240).raw_data, text)


def test_obj_face_sorting_and_omitted_anchor_records(library: ObjectLibrary) -> None:
    raw = library.model(240).raw_data
    lines = mesh_obj(raw).splitlines()
    vertices = [line for line in lines if not line.startswith('f ')]
    faces = []
    for line in reversed(lines):
        if line.startswith('f '):
            _, a, b, c = line.split()
            if len({a, b, c}) == 3:
                faces.append(f'f {b} {c} {a}')
    assert len(faces) < library.model(240).mesh.triangle_count
    assert import_mesh_obj(raw, '\n'.join([*vertices, *faces])) == raw
    with pytest.raises(ValueError, match='connectivity'):
        import_mesh_obj(raw, '\n'.join([*vertices, *faces[1:]]))
    reversed_face = faces[0].split()
    reversed_face[1], reversed_face[2] = reversed_face[2], reversed_face[1]
    with pytest.raises(ValueError, match='connectivity'):
        import_mesh_obj(raw, '\n'.join([*vertices, ' '.join(reversed_face), *faces[1:]]))


def test_environment_normal_sharing_matches_mixed_source_search(library: ObjectLibrary) -> None:
    model = library.model(240)
    segment = model.mesh.segments[0]
    prototype = segment.batches[0]
    batches = tuple(replace(prototype, vertices_offset=i, misc_data=kind, flags=flags)
        for i, (kind, flags) in enumerate(((1, 0x8000), (254, 0x8000), (255, 0x8000), (1, 0))))
    segment = replace(segment, vertices=np.zeros((4, 3), np.float32), batches=batches,
        terminal_batch=replace(prototype, vertices_offset=4))
    model = replace(model, mesh=replace(model.mesh, segments=(segment,), flat_vertices=np.zeros((4, 7), np.float32)))
    assert _normal_keys(model) == (0, 1, 0, 0)


def test_signed8_wrap_boundary_roundtrip(library: ObjectLibrary) -> None:
    model = library.model(240)
    n = model.animated_count
    first = np.full((n, 3), 32767, dtype='>i2')
    raw = struct.pack('>I', 3)+bytes(12)+first.tobytes()+bytes(12)+np.full((n, 3), 127, np.int8).tobytes()+bytes(12)+np.full((n, 3), -128, np.int8).tobytes()
    clip = AnimationClip.from_bytes(raw, model)
    assert encode_clip(raw, model, clip_offsets(clip, model)) == raw


def test_staged_atomic_history_and_caches(rom: RomImage) -> None:
    session = EditSession(rom)
    model = ObjectLibrary(rom).model(240)
    aid = ObjectLibrary(rom).animation_ids[240]
    original = session.current_asset(A, aid)
    before = session._signature(), session._cursor
    resource = session.object_resources
    drafts = {(M, 240): shifted_mesh(model.raw_data), (A, aid): shifted_clip(original, model)}
    plan = plan_models(session, drafts)
    assert len(plan.after) == 2 and plan.report.can_export
    assert (session._signature(), session._cursor) == before
    session.apply_models(plan)
    assert session._cursor == before[1]+1
    assert session.object_resources is not resource
    library = ObjectLibrary(session.asset_source)
    np.testing.assert_array_equal(library.model(240).mesh.segments[0].vertices,
        model.mesh.segments[0].vertices+[1, 0, 0])
    assert library.clip(240, 0).raw_data == drafts[A, aid]
    session.undo()
    assert session._signature() == before[0]
    session.redo()
    assert all(session.current_asset(*k) == raw for k, raw in drafts.items())
    with pytest.raises(ValueError, match='stale'):
        session.apply_models(plan)
    restored = plan_models(session, {(M, 240): model.raw_data, (A, aid): original})
    assert not any(d.section in (29, 32) for d in restored.report.assets)
    session.apply_models(restored)
    assert session._signature() == before[0] and not session.export_report().assets


def test_v14_project_and_legacy_permissions(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    raw = session.current_asset(M, 240)
    session.apply_models(plan_models(session, {(M, 240): shifted_mesh(raw)}))
    aid = ObjectLibrary(rom).animation_ids[240]
    session.apply_models(plan_models(session, {(A, aid): shifted_clip(session.current_asset(A, aid), ObjectModel.from_bytes(raw))}))
    session.apply_global_objects(plan_global_objects(session, {48: edit_definition(session.current_asset(AssetType.OBJECTS, 48), 'scale', 4.)}))
    session.set_course_names(5, {'english': 'New Lake'})
    doc = session.project_document(5)
    assert doc['version'] == 14
    project = tmp_path/'models.dkrproj'
    session.save_project(project, 5)
    loaded = EditSession.load_project(project)
    assert loaded._signature() == session._signature()
    assert loaded.current_asset(M, 240) == session.current_asset(M, 240)
    assert loaded.database.definitions[48].scale == 4
    for version in range(1, 14):
        old = dict(doc, version=version)
        old.pop('course_names', None)
        project.write_text(json.dumps(old))
        with pytest.raises(ValueError):
            EditSession.load_project(project)
    doc['asset_edits'][0]['bytes'].append({'offset': 0x54, 'value': 99})
    project.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        EditSession.load_project(project)


def test_export_only_changed_models_and_clips(rom: RomImage) -> None:
    session = EditSession(rom)
    library = ObjectLibrary(rom)
    model, clip = library.model(240), library.clip(240, 0)
    session.apply_models(plan_models(session, {(M, 240): shifted_mesh(model.raw_data),
        (A, clip.animation_id): shifted_clip(clip.raw_data, model)}))
    result = session.build_rom()
    output = RomImage(result, 'z64', parse_asset_lut(result, LUT_START, LUT_END))
    for i in range(390):
        if i != 240:
            assert output.read_asset(M, i) == rom.read_asset(M, i)
    for i in range(470):
        if i != clip.animation_id:
            assert output.read_asset(A, i) == rom.read_asset(A, i)
    for section in AssetType:
        if int(section) not in (28, 29, 31, 32):
            assert output.section(section) == rom.section(section)
    assert output.read_asset(M, 240, decompress=True) == session.current_asset(M, 240)
    assert output.read_asset(A, clip.animation_id, decompress=True) == session.current_asset(A, clip.animation_id)
    assert hashlib.sha1(rom.data).hexdigest() == '6d96743d46f8c0cd0edb0ec5600b003c89b93755'


def test_dependencies_and_inplace_loading(rom: RomImage, library: ObjectLibrary) -> None:
    uses = asset_uses(EditSession(rom))
    assert any('Ancient Lake' in name for name in uses[240][1])
    for i in (0, 240, 260, 389):
        raw = shifted_mesh(library.model(i).raw_data)
        audit = audit_inplace_rare(compress_asset(raw), slack=0x80)
        assert audit.minimum_gap >= 0 and audit.huft_bytes <= 0x2800


def test_invalid_mixed_update_is_atomic(rom: RomImage) -> None:
    session = EditSession(rom)
    signature = session._signature()
    with pytest.raises(ValueError):
        plan_models(session, {(M, 240): shifted_mesh(session.current_asset(M, 240)), (A, 0): b'invalid'})
    assert session._signature() == signature and not session.can_undo
    with pytest.raises(ValueError):
        plan_models(session, {(M, -1): b'invalid'})


def test_v14_coexists_with_custom_artwork_track_and_structural_maps(rom: RomImage, tmp_path: Path) -> None:
    from src.core.track_import import ImportOptions, parse_obj, default_materials
    from src.core.track_segments import compile_segmented_obj
    from src.core.track_artwork import MaterialImage, ObjMaterial, TextureOptions, stage_artwork
    from src.core.object_structure import ObjectTemplate
    session = EditSession(rom)
    mesh = parse_obj('usemtl Road\nv -2000 24 -7000\nv -2000 24 -6600\nv -1600 24 -6600\n'
        'vt 0 0\nvt 0 1\nvt 1 1\nf 1/1 2/2 3/3\n')
    image = MaterialImage(ObjMaterial('Road'), np.full((8, 8, 4), 255, np.uint8), TextureOptions(8, 8), 0)
    track = session.track_model(5)
    appearance, mapping, added, refs = stage_artwork(track.raw_data, session.material_references,
        default_materials(mesh, track), {'Road': image}, {})
    result = compile_segmented_obj(mesh, session.original_asset(AssetType.LEVEL_MODELS, 5), refs, mapping, ImportOptions(scale=1.0), appearance=appearance)
    session.import_track(5, result.raw, textures=added)
    key = session.add_object(5, ObjectTemplate(78), (-1000, 100, -7000))
    session.set_course_names(5, {'english': 'Model Course'})
    session.apply_models(plan_models(session, {(M, 240): shifted_mesh(session.current_asset(M, 240))}))
    path = session.save_project(tmp_path/'all-features.dkrproj', 5)
    loaded = EditSession.load_project(path)
    assert loaded.project_document()['version'] == 14 and len(loaded.custom_textures) == 1
    assert loaded.track_model(5).raw_data == session.track_model(5).raw_data
    assert loaded.object(key).definition.header_id == 48
    assert loaded._signature() == session._signature()
    assert loaded.export_report().can_export


def test_core_imports_remain_headless() -> None:
    import subprocess
    import sys
    subprocess.run([sys.executable, '-c', 'import sys; import src.core.model_editing, src.core.editing; '
        'assert not any(n.startswith(("PySide6", "OpenGL")) for n in sys.modules)'], check=True)
