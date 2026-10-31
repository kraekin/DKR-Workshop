"""Visual assignment drafts, scoped commits and preview lifetime."""
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.core.editing import EditSession
from src.core.materials import (MaterialEdit, batch_for_face, edit_materials,
                                slot_uses, texture_assignment_error, pick_track_face)
from src.core.rom import AssetType, LUT_START, LUT_END, RomImage, parse_asset_lut
from src.ui.main_window import MainWindow
from src.ui.material_picker import DATA


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def rom():
    return RomImage.from_file(Path('Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64'))


@pytest.fixture
def window(app, rom):
    w = MainWindow()
    assert w.load_rom(rom.source_path, show_errors=False)
    w.level_panel.select_level(5)
    w.object_inspector.tabs.setCurrentWidget(w.object_inspector.geometry_tabs)
    w.object_inspector.geometry_tabs.setCurrentWidget(w.object_inspector.materials)
    yield w
    w.object_inspector.materials.cancel_preview()
    w.edit_session = None
    w.viewport._timer.stop()
    w.deleteLater()
    app.processEvents()


def alternate(dialog):
    current = dialog.model.textures[dialog.slot]
    for i in range(dialog.choices.count()):
        item = dialog.choices.item(i)
        if item.flags() & Qt.ItemFlag.ItemIsEnabled and item.data(DATA+1) != current.texture_id:
            return item
    raise AssertionError('Expected a compatible alternate texture')


def test_geometry_material_selection_highlights_whole_batch(window):
    panel = window.object_inspector.materials
    assert window.object_inspector.tools.indexOf(panel) == -1
    assert window.viewport.material_active and not window.viewport.geometry_active
    panel.batches.setCurrentItem(panel.batches.topLevelItem(0))
    assert panel.key == (0, 0)
    panel.pick_face(0, 0)
    segment = window.current_model.segments[0]
    first, end = (*segment.batches, segment.terminal_batch)[:2]
    assert window.viewport.material_faces == tuple((0, i) for i in range(first.faces_offset, end.faces_offset))
    assert str(window.current_model.textures[first.texture_index].texture_id) in panel.texture_info.text()
    panel.isolate.setChecked(True)
    assert window.viewport.material_isolation == panel.key
    window.object_inspector.geometry_tabs.setCurrentWidget(window.object_inspector.geometry_panel)
    assert window.viewport.material_isolation is None and window.viewport.geometry_active
    window._show_face_material(0, 0)
    assert window.object_inspector.geometry_tabs.currentWidget() is panel
    assert window.viewport.material_active and not window.viewport.geometry_active


def test_batch_preview_cancel_and_noop_leave_history_and_camera_unchanged(window):
    panel = window.object_inspector.materials
    before = window.current_model.raw_data
    position, target = window.viewport.camera.position.copy(), window.viewport.camera.target.copy()
    panel.change_material.click()
    picker = panel._picker
    assert picker is not None and not picker.apply.isEnabled()
    picker.choices.setCurrentItem(alternate(picker))
    assert picker.apply.isEnabled() and window.viewport.model.raw_data != before
    assert window.current_model.raw_data == before
    assert not window.edit_session.dirty and not window.edit_session.can_undo
    assert 'Driving surface:' in picker.details.text()
    picker.reject()
    assert panel._picker is None and window.viewport.model.raw_data == before
    assert not window.edit_session.dirty
    np.testing.assert_array_equal(position, window.viewport.camera.position)
    np.testing.assert_array_equal(target, window.viewport.camera.target)


def test_batch_apply_is_one_scoped_edit_with_project_and_rom_roundtrip(window, tmp_path):
    panel = window.object_inspector.materials
    before = window.current_model
    panel.change_material.click()
    picker = panel._picker
    chosen = alternate(picker)
    value = chosen.data(DATA)
    picker.choices.setCurrentItem(chosen)
    assert '3 faces' in picker.scope.text()
    picker.apply.click()
    assert panel._picker is None
    after = window.edit_session.track_model(5)
    assert after.segments[0].batches[0].texture_index == value
    assert after.textures == before.textures
    for segment in before.segments:
        for i, batch in enumerate(segment.batches):
            if (segment.index, i) != panel.key:
                assert after.segments[segment.index].batches[i] == batch
    window._undo()
    assert window.current_model.raw_data == before.raw_data and not window.edit_session.dirty
    window._redo()
    assert window.current_model.raw_data == after.raw_data
    loaded = EditSession.load_project(window.save_project_to(tmp_path/'materials.dkrproj'))
    assert loaded.track_model(5).raw_data == after.raw_data
    data = loaded.build_rom()
    output = RomImage(data, 'z64', parse_asset_lut(data, LUT_START, LUT_END))
    assert output.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True) == after.raw_data
    assert output.section(AssetType.TEXTURES_3D) == window.edit_session.rom.section(AssetType.TEXTURES_3D)


def test_shared_texture_and_surface_apply_together_without_changing_batch_assignments(window):
    panel = window.object_inspector.materials
    before = window.current_model
    panel.isolate.setChecked(True)
    panel.shared.click()
    picker = panel._picker
    assert picker.shared
    assert window.viewport.material_isolation is None
    uses = slot_uses(before, panel.slot)
    assert len(uses) > 1 and str(len(uses)) in picker.scope.text()
    assert len(window.viewport.material_faces) == sum(n for _, _, n in uses)
    picker.choices.setCurrentItem(alternate(picker))
    picker.surface.setCurrentIndex(picker.surface.findData(2))
    draft = picker.draft
    assert draft is not None and not window.edit_session.dirty
    assert draft.textures[panel.slot].surface_type == 2
    assert draft.textures[panel.slot].texture_id != before.textures[panel.slot].texture_id
    picker.apply.click()
    assert panel.isolate.isChecked() and window.viewport.material_isolation == panel.key
    after = window.edit_session.track_model(5)
    assert after.raw_data == draft.raw_data
    for old, new in zip(before.segments, after.segments):
        assert old.batches == new.batches
    window._undo()
    assert not window.edit_session.dirty and window.current_model.raw_data == before.raw_data


@pytest.mark.parametrize('action', ('level', 'tab', 'save', 'undo', 'refresh'))
def test_preview_cancels_on_context_and_history_boundaries(window, tmp_path, action):
    panel = window.object_inspector.materials
    before = window.current_model.raw_data
    panel.change_material.click()
    picker = panel._picker
    picker.choices.setCurrentItem(alternate(picker))
    assert window.viewport.model.raw_data != before
    if action == 'level':
        window.level_panel.select_level(6)
    elif action == 'tab':
        window.object_inspector.geometry_tabs.setCurrentWidget(window.object_inspector.geometry_panel)
    elif action == 'save':
        path = window.save_project_to(tmp_path/'no-preview.dkrproj')
        assert EditSession.load_project(path).track_model(5).raw_data == before
        assert panel._picker is picker and picker.apply.isEnabled()
        assert window.viewport.model.raw_data != before
        panel.cancel_preview()
    elif action == 'undo':
        window._undo()
    else:
        window._refresh_graphics()
    assert panel._picker is None
    assert not window.edit_session.dirty
    assert window.edit_session.track_model(5).raw_data == before
    assert window.viewport.model.raw_data == window.current_model.raw_data


def test_picker_filters_disabled_choices_and_preserves_unrelated_refresh(window):
    panel = window.object_inspector.materials
    panel.shared.click()
    picker = panel._picker
    bad = next(picker.choices.item(i) for i in range(picker.choices.count()) if picker.choices.item(i).data(DATA+2))
    assert bad.isHidden()
    picker.compatible.setChecked(False)
    assert not bad.isHidden() and not bad.flags() & Qt.ItemFlag.ItemIsEnabled
    assert 'render' in bad.toolTip()
    chosen = alternate(picker)
    picker.choices.setCurrentItem(chosen)
    raw = picker.draft.raw_data
    window._update_material_panel()
    assert panel._picker is picker and picker.draft.raw_data == raw
    picker.search.setText(str(chosen.data(DATA+1)))
    assert not chosen.isHidden()
    assert any(picker.choices.item(i).isHidden() for i in range(picker.choices.count()))


def test_compatibility_filter_agrees_with_protected_writer(rom):
    session = EditSession(rom)
    model, refs = session.track_model(5), session.material_references
    key = (0, 0)
    for texture_id in (0, 55, 213, 272, 294):
        slot = model.segments[0].batches[0].texture_index
        uses = tuple((s, b) for s, b, _ in slot_uses(model, slot))
        reason = texture_assignment_error(model, refs, texture_id, uses)
        if reason:
            with pytest.raises(ValueError, match='opaque/translucent'):
                edit_materials(model.raw_data, (MaterialEdit('texture', (slot,), texture_id),), refs)
        else:
            assert edit_materials(model.raw_data, (MaterialEdit('texture', (slot,), texture_id),), refs)
    segment = model.segments[0]
    vertices = segment.vertices[segment.indices[0]].astype(np.float64)
    normal = np.cross(vertices[1]-vertices[0], vertices[2]-vertices[0])
    normal /= np.linalg.norm(normal)
    hit = pick_track_face(model, vertices.mean(axis=0)+normal*10, -normal, batch=key)
    assert hit is not None and (hit[0], batch_for_face(model, *hit)) == key
