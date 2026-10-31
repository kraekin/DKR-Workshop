"""Display names remain independent of binary field keys and project data."""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.core.editing import EditSession
from src.core.objects import ENTRY_LAYOUTS, ObjectMap
from src.core.parameter_labels import PARAMETER_LABELS, parameter_info, parameter_label
from src.core.research import research_fields
from src.core.rom import AssetType, LUT_END, LUT_START, RomImage, parse_asset_lut
from src.ui.cinematic_panel import FIELDS
from src.ui.deferred_edits import flush_edits
from src.ui.object_inspector import EDIT_ROLE, ObjectInspector


@pytest.fixture(scope='module')
def rom():
    return RomImage.from_file(Path('Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64'))


def test_metadata_only_names_existing_fields_and_keeps_unknowns_unclassified():
    for behavior, labels in PARAMETER_LABELS.items():
        schema = {row[0] for row in ENTRY_LAYOUTS[behavior][1]}
        assert labels.keys() <= schema
    assert parameter_label(49, 'unk15', 21) == 'Release actor ID'
    assert parameter_label(13, 'unk15', 21) == 'AI lane 2 behavior'
    assert parameter_label(49, 'unk23', 35) == 'Unknown (0x23)'
    assert parameter_label(49, 'unk31', 49) == 'Unknown (0x31)'
    assert parameter_info(49, 'unk23') is None
    assert parameter_label(17, 'padB', 11) == 'Padding (0x0B)'
    assert parameter_info(3, 'unkD').label == 'Height scale'
    assert parameter_info(29, 'unkA').label == 'U scroll speed'
    assert len({key for key, _, _ in FIELDS}) == len(FIELDS)
    for key, label, hint in FIELDS:
        assert label == parameter_info(49, key).label
        assert hint == parameter_info(49, key).description


def test_renamed_animation_field_keeps_offset_history_project_and_rom(rom, tmp_path):
    session = EditSession(rom)
    obj = next(o for o in session.current_map(5).objects if o.definition.behavior_id == 49)
    value = 7 if obj.value('unk15') != 7 else 8
    assert session.set_parameter(obj.key, 'unk15', value)
    changed = session.object(obj.key)
    assert [i for i, (a, b) in enumerate(zip(obj.raw_data, changed.raw_data)) if a != b] == [0x15]
    assert next(f for f in research_fields(changed) if f.key == 'unk15').label == 'Release actor ID'
    session.undo()
    assert session.object(obj.key).raw_data == obj.raw_data
    session.redo()
    loaded = EditSession.load_project(session.save_project(tmp_path/'labels.dkrproj', 5))
    assert loaded.object(obj.key).raw_data == changed.raw_data
    data = loaded.build_rom()
    exported = RomImage(data, 'z64', parse_asset_lut(data, LUT_START, LUT_END))
    decoded = ObjectMap.from_bytes(exported.read_asset(AssetType.LEVEL_OBJECT_MAPS, obj.map_id, decompress=True),
                                   session.database, map_id=obj.map_id)
    assert decoded.objects[obj.index].raw_data == changed.raw_data
    assert exported.read_asset(AssetType.LEVEL_OBJECT_MAPS, 73) == rom.read_asset(AssetType.LEVEL_OBJECT_MAPS, 73)


def test_inspector_shows_friendly_name_but_emits_canonical_field(rom):
    app = QApplication.instance() or QApplication([])
    session = EditSession(rom)
    obj = next(o for o in session.current_map(5).objects if o.definition.behavior_id == 49)
    inspector = ObjectInspector()
    inspector.set_editing_enabled(True)
    inspector.set_objects((obj,))
    inspector.select_object(0)
    group = next(inspector.properties.topLevelItem(i) for i in range(inspector.properties.topLevelItemCount())
                 if inspector.properties.topLevelItem(i).text(0) == 'Parameters')
    rows = {group.child(i).data(1, EDIT_ROLE)[1]: group.child(i) for i in range(group.childCount())}
    assert rows['unk15'].text(0) == '0x15 Release actor ID'
    assert 'Original field: unk15' in rows['unk15'].toolTip(0)
    assert rows['unk23'].text(0) == '0x23 Unknown (0x23)'
    seen = []
    inspector.edit_requested.connect(lambda *args: seen.append(args))
    rows['unk15'].setText(1, '7')
    flush_edits(inspector)
    assert seen == [(obj.key, 'parameter', 'unk15', 7)]
    assert session.object(obj.key).raw_data == obj.raw_data
    inspector.deleteLater()
    app.processEvents()
