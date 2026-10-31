"""Source-backed structural feasibility; experiments never write ROM files."""
from __future__ import annotations

from dataclasses import replace
import copy
import json
from pathlib import Path
import struct

import pytest

from src.core.editing import EditSession, EditError, n64_checksums
from src.core.objects import ObjectMap, load_object_database, load_object_map
from src.core.rom import RomImage, AssetType, LUT_START, LUT_END, parse_asset_lut
from src.core.structure import (MAP_WORKSPACE, OBJECT_POOL, OBJECT_BYTES, StructuralDraft,
    StructureError, PRODUCTION_STRUCTURAL_TYPES, audit_session, raw_map, rebuild_map,
    template_reasons, simple_instance_bytes, workspace_usage, known_incoming)


@pytest.fixture(scope='module')
def rom() -> RomImage:
    paths = list(Path(__file__).resolve().parents[1].glob('*.z64'))
    if not paths:
        pytest.skip('Local original Rev1 ROM absent')
    return RomImage.from_file(paths[0])


@pytest.fixture
def session(rom: RomImage) -> EditSession:
    return EditSession(rom)


def candidate(draft: StructuralDraft) -> str:
    return next(e.identity for e in draft.entries if not template_reasons(draft.templates[e.template]))


def reload_rom(raw: bytes) -> RomImage:
    return RomImage(raw, 'z64', parse_asset_lut(raw, LUT_START, LUT_END))


def test_workspace_formula_exact_boundaries_and_bad_sizes() -> None:
    tight = workspace_usage(0x2FE0, 3584)
    assert tight.required == MAP_WORKSPACE and tight.remaining == 0 and not tight.errors
    assert tight.compressed_start == 0x2FE0-3584+32
    assert workspace_usage(0x2FE8, 3584).errors
    assert workspace_usage(100, 133).errors
    assert not workspace_usage(100, 132).errors
    assert not workspace_usage(0, 0).errors
    assert workspace_usage(16, 0).errors
    for sizes in ((-1, 0), (0, -1), (True, 0), (1., 1)):
        with pytest.raises(StructureError): workspace_usage(*sizes)


def test_all_138_maps_noedit_identity_and_actual_loader_bounds(session: EditSession) -> None:
    for map_id in range(session.rom.count(AssetType.LEVEL_OBJECT_MAPS)):
        model = session.current_map(map_id)
        assert rebuild_map(model, tuple(o.raw_data for o in model.objects), session.database) == raw_map(model)
        size = session.rom.index_table(AssetType.LEVEL_OBJECT_MAPS).span(map_id).size
        assert not workspace_usage(len(raw_map(model)), size).errors
    assert raw_map(session.current_map(81)) == raw_map(session.current_map(99)) == b''


def test_rebuild_preserves_reserved_header_alias_flags_and_entry_bytes(session: EditSession) -> None:
    source = session.current_map(0)
    reserved = bytes(range(12))
    entries = [o.raw_data for o in source.objects]
    assert any(entry[1] & 128 for entry in entries)
    entries[0] = bytes((entries[0][0], entries[0][1] | 64))+entries[0][2:]
    data = source.header[:4]+reserved+b''.join(entries)+source.padding
    model = ObjectMap.from_bytes(data, session.database)
    reordered = tuple((*entries[1:], entries[0], entries[0]))
    raw = rebuild_map(model, reordered, session.database)
    parsed = ObjectMap.from_bytes(raw, session.database)
    assert raw[4:16] == reserved
    assert tuple(o.raw_data for o in parsed.objects) == reordered
    assert parsed.objects[-1].size_bit6
    assert parsed.payload_size == sum(map(len, reordered))
    assert len(raw) % 8 == 0 and len(parsed.padding) < 8
    assert rebuild_map(model, reordered, session.database) == raw
    with pytest.raises(ValueError): rebuild_map(model, (b'\0'*9,), session.database)


def test_stock_audit_reports_necessary_bounds_without_claiming_headroom(session: EditSession) -> None:
    signature = session._signature()
    report = audit_session(session)
    assert len(report.maps) == 138 and not report.errors and not any(m.errors for m in report.maps)
    assert report.maximum_loaded_entries == 301 and 'Windmill Plains' in report.maximum_entry_context
    assert report.maximum_pool_baseline == 48032 and 'Central Area' in report.pool_context
    tight = min((m for m in report.maps if m.usage.stored), key=lambda m: m.usage.remaining)
    assert (tight.map_id, tight.usage.decoded, tight.usage.stored, tight.usage.remaining) == (91, 10440, 3584, 1816)
    assert sum(m.template_count for m in report.maps) == 206
    assert len(report.references) == 4 and all('Snowball Valley' in issue for issue in report.references)
    assert not PRODUCTION_STRUCTURAL_TYPES
    text = report.to_text()
    assert 'No proven peak' in text and 'in-place inflate' in text
    assert 'not a proven reserve' in text
    assert 'not an allowed number' in text and '70 object models' in text
    assert signature == session._signature() and not session.dirty and not session.can_undo


def test_audited_template_allocation_and_emitters_stay_blocked(session: EditSession) -> None:
    assert OBJECT_BYTES == 128 and OBJECT_POOL == 88064
    model = session.current_map(0)
    bush = next(o for o in model.objects if o.definition.name == 'BlueBerryBush')
    assert simple_instance_bytes(bush) == 208 and not template_reasons(bush)
    tree = next(o for o in model.objects if o.definition.name == 'Beachtree')
    assert tree.definition.raw_data[0x57] == 1
    assert simple_instance_bytes(tree) is None and template_reasons(tree)


def test_append_remove_reorder_and_exact_history(session: EditSession) -> None:
    draft = StructuralDraft(session, 5)
    original = draft.serialize()
    before = draft.entries
    source = candidate(draft)
    new_id = draft.append(source, (-32768, 32767, 123))
    appended = draft.serialize()
    parsed = ObjectMap.from_bytes(appended, session.database, map_id=5)
    assert parsed.objects[-1].position == (-32768, 32767, 123)
    assert parsed.objects[-1].raw_data[:2] == draft.templates[source].raw_data[:2]
    assert parsed.objects[-1].raw_data[8:] == draft.templates[source].raw_data[8:]
    order = [e.identity for e in draft.entries]
    a, b = order.index(source), order.index(new_id)
    order[a], order[b] = order[b], order[a]
    draft.reorder(tuple(order)); moved = draft.serialize()
    assert draft.entries[a].identity == new_id
    exported = reload_rom(draft.experimental_rom_bytes())
    assert raw_map(load_object_map(exported, 5, session.database)) == moved
    draft.remove(source); removed = draft.serialize()
    assert len(draft.entries) == len(before)
    exported = reload_rom(draft.experimental_rom_bytes())
    assert raw_map(load_object_map(exported, 5, session.database)) == removed
    draft.undo(); assert draft.serialize() == moved
    draft.undo(); assert draft.serialize() == appended
    draft.undo(); assert draft.serialize() == original and draft.entries == before
    draft.redo(); draft.redo(); draft.redo(); assert draft.serialize() == removed
    assert not session.dirty and not session.can_undo and session.build_rom() == session.rom.data


def test_stable_identity_is_not_reused_after_undo_branch(session: EditSession) -> None:
    draft = StructuralDraft(session, 5); source = candidate(draft)
    first = draft.append(source); draft.undo()
    second = draft.append(source)
    assert first != second and not draft.can_redo
    assert draft.templates[source].index == session.object(draft.templates[source].key).index


@pytest.mark.parametrize('version', (1, 2, 3, 4, 5, 6))
def test_old_project_import_migrates_edits_and_notes_to_stable_identities(session: EditSession, tmp_path: Path, version: int) -> None:
    original = StructuralDraft(session, 5)
    source = candidate(original); obj = original.templates[source]
    session.set_parameter(obj.key, 'radius', 70)
    if version >= 3:
        session.set_note(obj.key, 'radius', 'Research stays on this entry', 'Untested')
    document = session.project_document(5); document['version'] = version
    if version < 3: document.pop('research')
    path = tmp_path/f'legacy{version}.dkrproj'; path.write_text(json.dumps(document))
    migrated_session = EditSession.load_project(path)
    migrated = StructuralDraft(migrated_session, 5)
    assert migrated.source_ids == original.source_ids
    assert migrated.templates[source].value('radius') == 70
    new = migrated.append(source, (100, 200, 300))
    reopened = StructuralDraft.from_document(migrated_session, migrated.document())
    assert reopened.serialize() == migrated.serialize() and reopened.entries == migrated.entries
    assert reopened.entries[-1].identity == new
    if version >= 3:
        assert reopened.notes[source, 'radius'].text == 'Research stays on this entry'
        migrated.remove(source); migrated.undo()
        assert migrated.notes[source, 'radius'].text == 'Research stays on this entry'
    assert not migrated_session.dirty and migrated_session.project_document()['version'] == 6


def test_experimental_export_reloads_and_preserves_other_maps_sections_and_checksum(session: EditSession) -> None:
    session.set_level_field(5, 'laps', 2)
    draft = StructuralDraft(session, 5)
    source = candidate(draft)
    draft.append(source, (100, 200, 300))
    snapshot = session.project_document()
    output = draft.experimental_rom_bytes(); rebuilt = reload_rom(output)
    assert len(output) == len(session.rom.data)
    assert struct.unpack_from('>2I', output, 16) == n64_checksums(output)
    db = load_object_database(rebuilt)
    assert raw_map(load_object_map(rebuilt, 5, db)) == draft.serialize()
    base_overlay = reload_rom(session.build_rom())
    for map_id in range(138):
        if map_id != 5:
            assert rebuilt.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id) == base_overlay.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id)
    for index in range(50):
        if index not in (20, 21):
            a, b = rebuilt.sections[index], base_overlay.sections[index]
            assert rebuilt.data[a.start:a.end] == base_overlay.data[b.start:b.end]
    assert session.project_document() == snapshot
    draft.undo(); assert draft.experimental_rom_bytes() == session.build_rom()


def test_known_references_graphs_unknowns_and_emitters_cannot_be_structurally_changed(session: EditSession) -> None:
    draft = StructuralDraft(session, 5)
    for behavior in (13, 16, 49):
        match = next(((m, obj) for m in range(138) for obj in session.current_map(m).objects if obj.definition.behavior_id == behavior), None)
        assert match is not None
        map_id, obj = match
        other = StructuralDraft(session, map_id); identity = other.source_ids[obj.index]
        before = other.entries
        with pytest.raises(StructureError, match='Protected'): other.remove(identity)
        with pytest.raises(StructureError, match='Protected'): other.append(identity)
        assert other.entries == before and not other.can_undo
    target, objects = next((obj, session.current_map(m).objects) for m in range(138)
        for obj in session.current_map(m).objects if obj.definition.behavior_id == 16 and known_incoming(session.current_map(m).objects, obj))
    assert known_incoming(objects, target)
    with pytest.raises(StructureError): draft.reorder(tuple(reversed(draft.source_ids)))
    other = StructuralDraft(session, 0)
    emitter = next(e.identity for e in other.entries if other.templates[e.template].definition.name == 'Beachtree')
    with pytest.raises(StructureError): other.append(emitter)


def test_capacity_failure_is_atomic_and_shared_context_is_checked(session: EditSession) -> None:
    draft = StructuralDraft(session, 5); source = candidate(draft)
    accepted = 0
    while True:
        before = draft.entries; counter = draft._serial; cursor = draft._cursor
        try:
            draft.append(source)
            accepted += 1
        except StructureError as error:
            assert 'reference' in str(error) or 'bound' in str(error) or 'workspace' in str(error)
            assert draft.entries == before and draft._serial == counter and draft._cursor == cursor
            break
        assert accepted < 512
    assert accepted > 0 and not session.dirty
    # Both roles count, including when a level references the same map twice.
    other = StructuralDraft(session, 5)
    class Header:
        object_map_id = secondary_object_map_id = 5
    class Level:
        index = 5
    session._catalog = replace(session._catalog, levels=(Level(),))
    session.level_header = lambda _: Header()
    while len(other.entries) <= 256:
        before = other.entries
        try: other.append(candidate(other))
        except StructureError as error:
            assert 'Level 5' in str(error) and ('reference' in str(error) or 'bound' in str(error))
            assert other.entries == before
            break
    else: pytest.fail('Combined shared map bounds were not enforced')


@pytest.mark.parametrize('mutation', ('duplicate', 'template', 'source', 'counter', 'position', 'remove_graph', 'graph_position', 'graph_reorder'))
def test_research_document_cannot_bypass_protected_graphs_or_identities(session: EditSession, mutation: str) -> None:
    draft = StructuralDraft(session, 5); draft.append(candidate(draft))
    document = copy.deepcopy(draft.document())
    protected = [i for i, e in enumerate(draft.entries) if template_reasons(draft.templates[e.template])]
    if mutation == 'duplicate': document['entries'].append(document['entries'][0])
    elif mutation == 'template': document['entries'][-1]['template'] = []
    elif mutation == 'source': document['source_signature'] = '0'*64
    elif mutation == 'counter': document['next_serial'] = 1
    elif mutation == 'position': document['entries'][-1]['position'] = [32768, 0, 0]
    elif mutation == 'remove_graph': document['entries'].pop(protected[0])
    elif mutation == 'graph_position': document['entries'][protected[0]]['position'][0] += 1
    elif mutation == 'graph_reorder':
        a, b = protected[:2]; document['entries'][a], document['entries'][b] = document['entries'][b], document['entries'][a]
    with pytest.raises(ValueError): StructuralDraft.from_document(session, document)


def test_production_projects_refuse_structural_maps_and_changed_source_exports(session: EditSession, tmp_path: Path) -> None:
    draft = StructuralDraft(session, 5); draft.append(candidate(draft))
    with pytest.raises(EditError, match='(?i)structural'): session._install(5, draft.serialize())
    assert not session.dirty
    path = tmp_path/'draft.dkrproj'; path.write_text(json.dumps(draft.document()))
    with pytest.raises(EditError): EditSession.load_project(path)
    document = session.project_document(); document['structural_edits'] = []
    path.write_text(json.dumps(document))
    with pytest.raises(EditError, match='(?i)structural'): EditSession.load_project(path)
    session.set_level_field(5, 'laps', 2)
    with pytest.raises(StructureError, match='Source project changed'): draft.experimental_rom_bytes()
    assert session.can_undo


def test_vacant_slots_and_invalid_operation_inputs_stay_unchanged(session: EditSession) -> None:
    draft = StructuralDraft(session, 81)
    assert draft.serialize() == b'' and draft.experimental_rom_bytes() == session.rom.data
    with pytest.raises(StructureError): rebuild_map(draft.model, (session.current_map(5).objects[0].raw_data,), session.database)
    other = StructuralDraft(session, 5); source = candidate(other)
    for point in ((0, 0, 32768), (True, 0, 0), (1, 2), [1, 2, 3]):
        with pytest.raises(StructureError): other.append(source, point)
    with pytest.raises(StructureError): other.reorder((source,)*len(other.entries))
    with pytest.raises(StructureError): other.remove('missing')
    assert not other.can_undo and not session.dirty
