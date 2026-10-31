"""All-type experimental structural editing, identity/history and v7 projects."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct

import pytest

from src.core.editing import EditSession, EditError, n64_checksums
from src.core.object_structure import ObjectTemplate, MapState, validate_capacity, validate_state
from src.core.objects import load_object_map
from src.core.research import compare_sessions
from src.core.rom import RomImage, AssetType, LUT_START, LUT_END, parse_asset_lut
from src.core.structure import raw_map, StructureError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def rom() -> RomImage:
    for path in ROOT.glob('*.z64'):
        try: return RomImage.from_file(path)
        except ValueError: pass
    pytest.skip('Original local Rev1 ROM unavailable')


@pytest.fixture
def session(rom: RomImage) -> EditSession:
    return EditSession(rom)


def test_all_304_catalog_types_add_edit_delete_and_undo_without_type_gates(session: EditSession) -> None:
    catalog = session.object_catalog
    assert len(catalog) == 304 and len({t.object_id for t in catalog}) == 304
    assert len({session.database.resolve(t.object_id).header_id for t in catalog}) == 304
    assert sum(t.map_id is not None for t in catalog) == 85
    before = raw_map(session.current_map(5))
    for template in catalog:
        key = session.add_object(5, template, (123, 45, -678))
        obj = session.object(key)
        assert obj.object_id == template.object_id and obj.position == (123, 45, -678)
        assert obj.raw_data[8:] == template.raw(session)[8:]
        session.set_position(key, (124, 46, -679))
        session.delete_objects((key,))
        session.undo()
        assert session.object(key).position == (124, 46, -679)
        session.undo(); session.undo()
        assert raw_map(session.current_map(5)) == before and not session.dirty


def test_zero_schema_defaults_are_explicit_and_serialized_from_verified_layout(session: EditSession) -> None:
    stock = next(t for t in session.object_catalog if session.database.resolve(t.object_id).header_id == 43)
    default = ObjectTemplate(stock.object_id)
    assert default.raw(session)[8:] == bytes(4)
    key = session.add_object(5, default, (0, 0, 0))
    assert session.object(key).value('solid') == 0
    assert 'untested' in default.description
    key2 = session.add_object(5, stock, (10, 0, 0))
    assert session.object(key2).raw_data[8:] == stock.raw(session)[8:]


def test_surviving_ids_notes_properties_and_original_revert_do_not_shift(session: EditSession) -> None:
    survivor = session.object((5, 8))
    session.set_note(survivor.key, 'radius', 'belongs to the second bush')
    session.delete_objects(((5, 0), (5, 4)))
    assert session.object(survivor.key).raw_data == survivor.raw_data
    assert session.note(survivor.key, 'radius').text == 'belongs to the second bush'
    assert session.object((5, 8)).offset < survivor.offset
    session.set_parameter(survivor.key, 'radius', 42)
    session.revert_object(survivor.key)
    assert session.object(survivor.key).raw_data == survivor.raw_data
    with pytest.raises(EditError, match='absent'): session.object((5, 4))
    session.undo(); session.undo(); session.undo()
    assert session.object((5, 4)).definition.name == 'BlueBerryBush'
    assert session.note(survivor.key, 'radius').text == 'belongs to the second bush'


def test_new_ids_never_reused_on_branch_and_new_revert_uses_creation_snapshot(session: EditSession) -> None:
    session.set_parameter((5, 4), 'radius', 55)
    first = session.duplicate_objects(((5, 4),))[0]
    session.undo()
    second = session.duplicate_objects(((5, 4),))[0]
    assert first != second and not session.can_redo
    session.set_parameter(second, 'radius', 60)
    session.revert_object(second)
    assert session.object(second).value('radius') == 55


def test_multi_map_structure_is_one_history_item_and_preserves_group_members(session: EditSession) -> None:
    keys = ((5, 4), (73, 0))
    before = tuple(raw_map(session.current_map(m)) for m in (5, 73))
    created = session.duplicate_objects(keys, (0, 1, 0))
    assert len(created) == 2
    session.undo()
    assert session.last_keys == keys
    assert tuple(raw_map(session.current_map(m)) for m in (5, 73)) == before
    session.redo()
    assert session.last_keys == created
    session.set_note(created[0], 'radius', 'clone note')
    session.delete_objects(created)
    assert session.note(created[0], 'radius').text == ''
    session.undo()
    assert session.note(created[0], 'radius').text == 'clone note'
    session.apply_entries({key: session.object(key).raw_data for key in created}, 'No-op group')


def test_checkpoint_ai_and_cinematic_graphs_are_available_with_diagnostics(session: EditSession) -> None:
    for behavior in (13, 16, 49):
        template = next(t for t in session.object_catalog if session.database.resolve(t.object_id).behavior_id == behavior)
        key = session.add_object(5, template, (0, 0, 0))
        assert 'graph repair' in ' '.join(session.structure_warnings)
        clone = session.duplicate_objects((key,))[0]
        assert session.object(clone).raw_data[8:] == session.object(key).raw_data[8:]
        session.delete_objects((key, clone))
        session.undo()
        assert session.object(key) and session.object(clone)
        session.undo(); session.undo()


def test_structural_project_v7_reopens_assets_notes_and_provenance(session: EditSession, tmp_path: Path) -> None:
    session.set_level_field(5, 'laps', 2)
    created = session.duplicate_objects(((5, 4),))[0]
    session.set_parameter(created, 'radius', 49)
    session.set_note(created, 'radius', 'new entry note')
    session.set_note((5, 8), 'radius', 'surviving entry note')
    session.delete_objects(((5, 0),))
    path = session.save_project(tmp_path/'structural.dkrproj')
    document = json.loads(path.read_text())
    assert document['version'] == 7 and len(document['structural_maps']) == 1
    assert document['structural_maps'][0]['entries'][-1]['template']['entry_index'] == 4
    loaded = EditSession.load_project(path)
    assert not loaded.dirty and not loaded.can_undo
    assert loaded.project_document() == session.project_document()
    assert loaded.object(created).value('radius') == 49
    assert loaded.note(created, 'radius').text == 'new entry note'
    assert loaded.note((5, 8), 'radius').text == 'surviving entry note'
    assert loaded.level_header(5).laps == 2
    loaded.revert_object(created)
    assert loaded.object(created).value('radius') == session.original_map(5).objects[4].value('radius')
    assert loaded.duplicate_objects((created,))[0] != created


@pytest.mark.parametrize('case', ('counter', 'duplicate_id', 'base_hash', 'template_hash',
    'template_id', 'initial_prefix', 'original_identity', 'mixed_legacy', 'duplicate_map', 'note_identity'))
def test_malformed_v7_projects_are_rejected(session: EditSession, tmp_path: Path, case: str) -> None:
    key = session.duplicate_objects(((5, 4),))[0]
    session.set_note(key, 'radius', 'note')
    doc = copy.deepcopy(session.project_document())
    data = doc['structural_maps'][0]
    if case == 'counter': data['next_id'] = key[1]
    elif case == 'duplicate_id': data['entries'][-1]['id'] = 4
    elif case == 'base_hash': data['base_map_sha1'] = '0'*40
    elif case == 'template_hash': data['entries'][-1]['template']['sha1'] = '0'*40
    elif case == 'template_id': data['entries'][-1]['template']['object_id'] = 511
    elif case == 'initial_prefix': data['entries'][-1]['initial'] = [{'offset': 0, 'value': 0}]
    elif case == 'original_identity': data['entries'][4]['template'] = data['entries'][8]['template']
    elif case == 'mixed_legacy':
        obj = session.original_map(5).objects[4]
        doc['edits'] = [{'map_id': 5, 'entry_index': 4, 'object_id': obj.object_id,
            'base_entry_sha1': hashlib.sha1(obj.raw_data).hexdigest(), 'bytes': []}]
    elif case == 'duplicate_map': doc['structural_maps'].append(copy.deepcopy(data))
    elif case == 'note_identity': doc['research']['notes'][0]['entry_index'] = 999999
    path = tmp_path/'bad.dkrproj'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError): EditSession.load_project(path)


def test_export_reloads_all_maps_assets_crc_and_remaining_original_bytes(session: EditSession) -> None:
    session.duplicate_objects(((5, 4),), (0, 0, 128))
    session.delete_objects(((5, 0), (73, 0)))
    output = session.build_rom()
    exported = RomImage(output, 'z64', parse_asset_lut(output, LUT_START, LUT_END))
    assert len(output) == len(session.rom.data)
    assert struct.unpack_from('>2I', output, 16) == n64_checksums(output)
    for map_id in range(138):
        if map_id in (5, 73):
            parsed = load_object_map(exported, map_id, session.database)
            assert raw_map(parsed) == raw_map(session.current_map(map_id))
        else:
            assert exported.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id) == session.rom.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id)
    for index, (a, b) in enumerate(zip(session.rom.sections, exported.sections)):
        if index not in (20, 21):
            assert session.rom.data[a.start:a.end] == output[b.start:b.end]
    report = session.export_report()
    assert not report.errors
    assert any('Deleted original' in change for diff in report.assets for change in diff.changes)


def test_capacity_and_invalid_batch_failure_leave_bytes_history_ids_notes_unchanged(session: EditSession) -> None:
    before = session.project_document()
    with pytest.raises(ValueError): session.duplicate_objects(((5, 4), (73, 0)), (99999, 0, 0))
    assert session.project_document() == before and not session.can_undo
    assert not session._next_identity
    key = session.duplicate_objects(((5, 4),))[0]
    source = session._map_state(5)
    bad = MapState(5, source.raw, source.identities[:-1])
    with pytest.raises(StructureError): validate_state(session, bad)
    before = session.project_document()
    session._next_identity[5] = 1000000
    with pytest.raises(EditError): session.duplicate_objects((key,))
    session._next_identity[5] = before['structural_maps'][0]['next_id']
    assert session.project_document() == before


def test_necessary_header_refusal_is_atomic_and_experimental_warnings_do_not_block(session: EditSession) -> None:
    while True:
        before = session.project_document()
        history = len(session._history)
        try: session.duplicate_objects(((5, 4),), (0, 0, 0))
        except ValueError:
            assert session.project_document() == before and len(session._history) == history
            break
        assert len(session.current_map(5).objects) < 512


def test_comparison_matches_stable_ids_instead_of_shifted_row_order(session: EditSession, rom: RomImage) -> None:
    saved = EditSession(rom)
    session.delete_objects(((5, 0),))
    session.set_parameter((5, 4), 'radius', 58)
    rows = compare_sessions(session, saved)
    assert any('entry 0 ' in row[0] and row[1] == 'Object' and row[3] == 'Absent' for row in rows)
    assert any('entry 4 ' in row[0] and row[1].endswith('radius') and row[3] == '58' for row in rows)
    assert not any('entry 8 ' in row[0] for row in rows)


def test_vacant_map_initialization_and_empty_map_deletion_have_valid_headers(session: EditSession) -> None:
    assert raw_map(session.current_map(81)) == b''
    template = session.object_catalog[0]
    key = session.add_object(81, template, (0, 0, 0))
    assert len(session.current_map(81).header) == 16
    session.delete_objects((key,))
    assert raw_map(session.current_map(81)) == b''
    session.undo(); session.undo()
    assert not session.dirty
