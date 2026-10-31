"""Shared ObjectHeader protections, dependencies, history, v13 and ROM isolation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from dataclasses import replace

import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.global_objects import (FIELDS, ObjectResources, edit_definition,
    validate_definition, definition_uses, plan_global_objects)
from src.core.objects import load_object_database
from src.core.rom import AssetType, RomImage, LUT_START, LUT_END, parse_asset_lut


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob('*.z64')))


@pytest.fixture(scope='module')
def resources(rom: RomImage) -> ObjectResources:
    return ObjectResources(rom)


def test_all_304_original_headers_are_lossless(rom, resources):
    database = load_object_database(rom)
    assert len(database.definitions) == 304
    for definition in database.definitions:
        raw = definition.raw_data
        parsed = validate_definition(raw, raw, resources)
        assert parsed.model_ids == definition.model_ids
        assert parsed.scale == definition.scale and parsed.raw_data == raw


@pytest.mark.parametrize('field', [f for f in FIELDS if f.key != 'directional'], ids=lambda f: f.key)
def test_scalar_writes_touch_only_verified_bytes(rom, resources, field):
    original = rom.read_asset(AssetType.OBJECTS, 48)
    choices = {'scale': 4.5, 'draw_distance': 5000, 'ambient': .75, 'diffuse': 1.25,
               'shadow_scale': 4.0, 'water_scale': 1.5,
               'shadow_bottom': -90, 'shadow_top': 40,
               'shadow_outer': 2000, 'shadow_inner': 1500}
    value = choices.get(field.key, 22)
    result = edit_definition(original, field.key, value)
    validate_definition(original, result, resources)
    size = struct.calcsize('>'+field.format)
    assert result[:field.offset] == original[:field.offset]
    assert result[field.offset+size:] == original[field.offset+size:]
    assert field.read(result) == pytest.approx(value)


@pytest.mark.parametrize('key,value', [('scale', 0), ('scale', 65), ('scale', float('nan')),
    ('scale', float('inf')), ('draw_distance', -1), ('ambient', 1.1), ('diffuse', 2),
    ('light_red', 256), ('directional', 2), ('draw_distance', 2.5), ('scale', True)])
def test_invalid_values_are_refused(rom, key, value):
    with pytest.raises(ValueError):
        edit_definition(rom.read_asset(AssetType.OBJECTS, 48), key, value)


def test_every_protected_byte_and_array_size_is_guarded(rom, resources):
    original = rom.read_asset(AssetType.OBJECTS, 48)
    permitted = {i for field in FIELDS for i in range(field.offset, field.offset+struct.calcsize('>'+field.format))}
    pointer = struct.unpack_from('>I', original, 0x10)[0]
    permitted.update(range(pointer, pointer+4*original[0x55]))
    for i in set(range(len(original))) - permitted:
        raw = bytearray(original)
        raw[i] ^= 1
        with pytest.raises(ValueError):
            validate_definition(original, bytes(raw), resources)
    with pytest.raises(ValueError):
        validate_definition(original, original+b'\0', resources)
    with pytest.raises(ValueError, match='bottom'):
        validate_definition(original, edit_definition(original, 'shadow_bottom', 200), resources)
    with pytest.raises(ValueError):
        edit_definition(original, 'behavior', 1)
    raw = bytearray(original)
    struct.pack_into('>f', raw, 0xC, float('nan'))
    with pytest.raises(ValueError):
        validate_definition(original, bytes(raw), resources)


def test_artwork_ids_and_runtime_capacities(rom, resources):
    raw = rom.read_asset(AssetType.OBJECTS, 48)
    assert validate_definition(raw, edit_definition(raw, 'model_0', 107), resources).model_ids == (107,)
    with pytest.raises(ValueError, match='Sprite ID'):
        validate_definition(raw, edit_definition(raw, 'model_0', 193), resources)
    with pytest.raises(ValueError):
        edit_definition(raw, 'model_1', 107)
    resources.compatible(0, 241, 242)  # two existing static lit models
    with pytest.raises(ValueError, match='lighting layout'):
        resources.compatible(0, 241, 254)
    with pytest.raises(ValueError):
        resources.signature(0, 390)
    with pytest.raises(ValueError):
        resources.signature(3, 0)
    # A billboard cannot enable the point-light path that dereferences 3D shading.
    with pytest.raises(ValueError, match='shaded 3D'):
        validate_definition(raw, edit_definition(raw, 'directional', 1), resources)


def test_known_dependencies_cover_aliases_maps_actors_attachments_and_skies(rom):
    s = EditSession(rom)
    uses = definition_uses(s)
    assert uses[48].aliases == (78,) and uses[48].instances == 14
    assert {0, 5} <= {int(level.split(':')[0]) for level in uses[48].levels}
    for level in s._catalog.levels:
        sky = s.level_header(level.index).skybox_id
        if sky in uses:
            assert f'{level.index}: {level.name}' in uses[sky].levels
    for child, use in uses.items():
        for parent in use.parents:
            assert set(uses[parent].levels) <= set(use.levels)
        for map_id in use.maps:
            assert 0 <= map_id < rom.count(AssetType.LEVEL_OBJECT_MAPS)


def test_plan_cancel_apply_history_and_cached_object_definitions(rom):
    s = EditSession(rom)
    original_map = s.current_map(5)
    key = next(obj.key for obj in original_map.objects if obj.definition.header_id == 48)
    original = s.current_asset(AssetType.OBJECTS, 48)
    changed = edit_definition(edit_definition(original, 'scale', 4), 'model_0', 107)
    signature, history = s._signature(), len(s._history)
    plan = plan_global_objects(s, {48: changed})
    assert s._signature() == signature and len(s._history) == history and not s.dirty
    assert plan.report.growth_bytes == 0
    assert s.apply_global_objects(plan)
    assert s.object(key).definition.scale == 4 and s.object(key).definition.model_ids == (107,)
    assert s.current_map(5).objects[key[1]].raw_data == original_map.objects[key[1]].raw_data
    assert len(s._history) == history+1
    s.undo()
    assert s.object(key).definition.scale == 3 and not s.dirty
    s.redo()
    assert s.object(key).definition.model_ids == (107,)
    assert s.export_report().assets[0].section == 34
    restore = plan_global_objects(s, {48: original})
    assert not restore.report.assets
    s.apply_global_objects(restore)
    assert not s.dirty


def test_preview_refusal_and_stale_plan_are_atomic(rom):
    s = EditSession(rom)
    original = s.current_asset(AssetType.OBJECTS, 48)
    valid = edit_definition(original, 'scale', 5)
    invalid = bytearray(s.current_asset(AssetType.OBJECTS, 49))
    invalid[0x54] = 1
    signature = s._signature()
    with pytest.raises(ValueError):
        plan_global_objects(s, {48: valid, 49: bytes(invalid)})
    assert s._signature() == signature and not s.can_undo
    plan = plan_global_objects(s, {48: valid})
    obj = s.current_map(5).objects[0]
    s.set_position(obj.key, (obj.position[0]+1, *obj.position[1:]))
    signature = s._signature()
    with pytest.raises(ValueError, match='stale'):
        s.apply_global_objects(plan)
    assert s._signature() == signature and s.current_asset(AssetType.OBJECTS, 48) == original


def test_v13_names_structures_notes_and_globals_coexist(rom, tmp_path):
    s = EditSession(rom)
    tree = next(t for t in s.object_catalog if t.object_id == 78)
    key = s.add_object(5, tree, (-1800, 80, -7000))
    s.set_course_names(5, {'english': 'My Course'})
    raw = edit_definition(s.current_asset(AssetType.OBJECTS, 48), 'scale', 4)
    s.apply_global_objects(plan_global_objects(s, {48: raw}))
    path = s.save_project(tmp_path/'global.dkrproj', 5)
    document = json.loads(path.read_text())
    assert document['version'] == 13 and document['course_names'] and document['structural_maps']
    reopened = EditSession.load_project(path)
    assert reopened.object(key).definition.scale == 4
    assert reopened.object(key).object_id == 78 and reopened.course_names(5).english == 'My Course'
    assert reopened.current_asset(AssetType.OBJECTS, 48) == raw and not reopened.dirty


@pytest.mark.parametrize('version', range(1, 13))
def test_older_versions_cannot_enable_global_writer(rom, tmp_path, version):
    s = EditSession(rom)
    raw = edit_definition(s.current_asset(AssetType.OBJECTS, 48), 'scale', 4)
    s.apply_global_objects(plan_global_objects(s, {48: raw}))
    document = s.project_document()
    document['version'] = version
    path = tmp_path/'legacy.dkrproj'
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        EditSession.load_project(path)


def test_project_cannot_tamper_with_protected_header_bytes(rom, tmp_path):
    s = EditSession(rom)
    raw = edit_definition(s.current_asset(AssetType.OBJECTS, 48), 'scale', 4)
    s.apply_global_objects(plan_global_objects(s, {48: raw}))
    document = s.project_document()
    document['asset_edits'][0]['bytes'].append({'offset': 0x55, 'value': 2})
    path = tmp_path/'tampered.dkrproj'
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        EditSession.load_project(path)


def test_in_memory_rom_changes_only_selected_definition_and_retains_tables(rom):
    s = EditSession(rom)
    before = s.current_asset(AssetType.OBJECTS, 48)
    after = edit_definition(edit_definition(before, 'scale', 4), 'model_0', 107)
    s.apply_global_objects(plan_global_objects(s, {48: after}))
    data = s.build_rom()
    exported = RomImage(data, 'z64', parse_asset_lut(data, LUT_START, LUT_END))
    assert len(data) == len(rom.data)
    assert exported.read_asset(AssetType.OBJECTS, 48) == after
    for section in range(len(rom.sections)):
        if section != 34:
            a, b = exported.sections[section], rom.sections[section]
            assert exported.data[a.start:a.end] == rom.data[b.start:b.end]
    for i in range(rom.count(AssetType.OBJECTS)):
        if i != 48:
            assert exported.read_asset(AssetType.OBJECTS, i) == rom.read_asset(AssetType.OBJECTS, i)
    assert load_object_database(exported).resolve(78).model_ids == (107,)
    assert hashlib.sha1(rom.data).hexdigest() == '6d96743d46f8c0cd0edb0ec5600b003c89b93755'


def test_global_special_texture_custom_artwork_and_track_project_roundtrip(rom, tmp_path):
    from src.core.track_import import ImportOptions, parse_obj, default_materials
    from src.core.track_segments import compile_segmented_obj
    from src.core.track_artwork import MaterialImage, ObjMaterial, TextureOptions, stage_artwork
    from src.core.special_art import SpecialLibrary
    s = EditSession(rom)
    mesh = parse_obj('usemtl Road\nv -2000 24 -7000\nv -2000 24 -6600\nv -1600 24 -6600\n'
        'vt 0 0\nvt 0 1\nvt 1 1\nf 1/1 2/2 3/3\n')
    image = MaterialImage(ObjMaterial('Road'), np.full((8, 8, 4), 255, np.uint8), TextureOptions(8, 8), 0)
    model = s.track_model(5)
    appearance, mapping, added, refs = stage_artwork(model.raw_data, s.material_references,
        default_materials(mesh, model), {'Road': image}, {})
    result = compile_segmented_obj(mesh, s.original_asset(AssetType.LEVEL_MODELS, 5), refs, mapping, ImportOptions(scale=1.0), appearance=appearance)
    s.import_track(5, result.raw, textures=added)
    s.set_course_names(5, {'english': 'Custom Course'})
    index = rom.count(AssetType.TEXTURES_3D)
    raw = edit_definition(s.current_asset(AssetType.OBJECTS, 132), 'model_0', 0x8000 | index)
    s.apply_global_objects(plan_global_objects(s, {132: raw}))
    # The special portrait renderer and image dependency browser must decode
    # the same namespace bit as load_texture in the game.
    obj = replace(s.current_map(5).objects[0], definition=s.database.definitions[132])
    art = SpecialLibrary(s.asset_source).instances((obj,), None, portrait=0)
    assert len(art) == 1 and art[0].texture.header.width == 8
    assert any('CharacterFlag' in name for name in s.image_uses.direct[(AssetType.TEXTURES_3D, index)])
    path = s.save_project(tmp_path/'custom-globals.dkrproj')
    reopened = EditSession.load_project(path)
    assert reopened.project_document()['version'] == 13 and len(reopened.custom_textures) == 1
    assert reopened.database.definitions[132].model_ids[0] == 0x8000 | index
    assert reopened.track_model(5).raw_data == s.track_model(5).raw_data
    assert reopened.course_names(5).english == 'Custom Course'


def test_zero_shadow_scale_disables_existing_zipper_preview(rom):
    from src.core.special_art import shadow_spec
    s = EditSession(rom)
    d = next(d for d in s.database.definitions if d.behavior_id == 82)
    assert shadow_spec(s.asset_source, d) is not None
    raw = edit_definition(d.raw_data, 'shadow_scale', 0)
    s.apply_global_objects(plan_global_objects(s, {d.header_id: raw}))
    assert shadow_spec(s.asset_source, s.database.definitions[d.header_id]) is None
