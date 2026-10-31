"""Confirmed audit regressions; owned Qt widgets and in-memory ROM sessions."""
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSpinBox

from src.core.editing import EditSession
from src.core.rom import AssetType, RomImage
from src.ui.deferred_edits import defer_edit, flush_edits
from src.ui.main_window import MainWindow
from src.ui.object_inspector import EDIT_ROLE


@pytest.fixture(scope='module')
def rom():
    return RomImage.from_file(Path('Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64'))


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, rom):
    window = MainWindow()
    assert window.load_rom(rom.source_path, show_errors=False)
    yield window
    window.edit_session = None
    window.viewport._timer.stop()
    window.viewport.cleanup()
    window.deleteLater()
    app.processEvents()


def test_flush_delivers_only_editor_callbacks_and_preserves_reentrant_edits(app):
    from PySide6.QtCore import QObject
    owner = QObject()
    seen = []
    QTimer.singleShot(0, lambda: seen.append('unrelated'))
    def first():
        seen.append('first')
        defer_edit(owner, lambda: seen.append('second'))
        flush_edits(owner)
    defer_edit(owner, first)
    flush_edits(owner)
    assert seen == ['first', 'second']
    app.processEvents()
    assert seen == ['first', 'second', 'unrelated']


def test_deferred_setting_never_steals_import_or_pointer_target(window, monkeypatch):
    import src.ui.main_window as main
    window.level_panel.select_level(8)
    settings = window.object_inspector.level_settings
    rows = [settings.tree.topLevelItem(i).child(j)
            for i in range(settings.tree.topLevelItemCount())
            for j in range(settings.tree.topLevelItem(i).childCount())]
    row = next(row for row in rows if row.data(1, EDIT_ROLE) == ('level', 'skybox_id'))
    row.setText(1, '211')
    window.level_panel.select_level(5)
    assert window.edit_session.level_header(8).skybox_id == 211
    assert window.selected_level.index == window.current_model.model_id == 5
    # Completion originating from a background level also stays in the background.
    defer_edit(settings, lambda: window._apply_level_setting(8, 'skybox_id', 203))
    window.viewport.prepare_pointer_selection.emit()
    assert window.selected_level.index == window.current_model.model_id == 5
    targets = []
    class Dialog:
        def __init__(self, session, index, *args, **kwargs):
            targets.append(index)
        def exec(self): return 0
        def deleteLater(self): pass
    monkeypatch.setattr(main, 'TrackImportDialog', Dialog)
    window._show_track_import()
    assert targets == [5]


def test_committing_cells_preserves_armed_viewport_picker(window, monkeypatch):
    window.viewport.begin_grid_placement()
    assert window.viewport.grid_pick
    # Native focus loss cancels viewport modes; reproduce it without showing
    # a GPU window in the headless suite.
    monkeypatch.setattr(QApplication, 'focusWidget', lambda: window.viewport)
    monkeypatch.setattr(window.viewport, 'clearFocus', window.viewport._release_input)
    window._commit_editor()
    assert window.viewport.grid_pick
    assert not window.edit_session.dirty


def test_model_summary_replaces_rows(window):
    panel = window.object_inspector
    count = panel.tree.topLevelItemCount()
    for _ in range(3):
        panel.show_model(window.current_model)
    assert panel.tree.topLevelItemCount() == count
    panel.show_model(window.current_model, selected_segment=0)
    assert panel.tree.topLevelItemCount() == count + 6
    panel.show_model(window.current_model)
    assert panel.tree.topLevelItemCount() == count


def test_unrelated_refresh_keeps_minimap_and_png_drafts(window):
    from src.ui.image_browser import ImageBrowser
    window.level_panel.select_level(5)
    mini = window.object_inspector.minimap
    key = next(k for k, c in mini.controls.items() if isinstance(c, QSpinBox) and c.value() < c.maximum())
    control = mini.controls[key]
    draft = control.value() + 1
    control.setValue(draft)
    window._update_material_panel()
    assert control.value() == draft
    browser = ImageBrowser(window.art_source, window.edit_session, window.object_database, window)
    window.image_browser = browser
    browser.draft = browser.pixels.copy()
    browser.quantized = browser.pixels.copy()
    browser.apply.setEnabled(True)
    browser.discard.setEnabled(True)
    browser.view.setCurrentIndex(2)
    expected = browser.draft
    window._refresh_track_model(5)
    assert browser.draft is expected and browser.apply.isEnabled()
    assert browser.view.currentIndex() == 2 and control.value() == draft


def test_cinematic_same_node_and_track_refresh_keeps_draft(app, rom):
    from src.core.cinematics import build_tracks, CinematicTimeline
    from src.core.course import level_objects
    from src.ui.cinematic_panel import CinematicPanel
    session = EditSession(rom)
    timelines = tuple(CinematicTimeline(track, {}) for track in build_tracks(level_objects(session, 0), session.database, 1))
    panel = CinematicPanel()
    panel.set_tracks(timelines, True)
    assert panel.node is not None
    key = panel.node.key
    draft = panel.value.value() + 1
    panel.value.setValue(draft)
    panel.select_node(key)
    assert panel.value.value() == draft
    panel.set_tracks(timelines, True)
    assert panel.value.value() == draft
    panel.clear_drafts()
    panel.select_node(key)
    assert panel.value.value() != draft


@pytest.mark.parametrize('revert', [False, True])
def test_cannot_restore_deleted_stock_checkpoint_set(rom, revert):
    from src.core.course import level_objects
    session = EditSession(rom)
    header = session.level_header(5)
    route = tuple(o for o in level_objects(session, 5) if o.definition.behavior_id == 13 and o.value('vehicleType') == 0)
    clone = session.duplicate_objects((route[0].key,))[0]
    session.set_parameter(clone, 'vehicleType', 1)
    session.set_level_field(5, 'checkpoint_sets', (1, 1, 1))
    session.delete_objects(tuple(o.key for o in route))
    before = session._signature(), session._cursor
    with pytest.raises(ValueError, match='Checkpoint set'):
        if revert:
            session.revert_level(5)
        else:
            session.set_level_field(5, 'checkpoint_sets', header.checkpoint_sets)
    assert (session._signature(), session._cursor) == before
    session.undo()  # Restore the removed route; header restoration now succeeds.
    assert session.revert_level(5)


def test_catalog_header_tracks_history(rom):
    session = EditSession(rom)
    original = session.level_header(5).laps
    session.set_level_field(5, 'laps', original - 1)
    assert session._catalog.levels[5].header.laps == original - 1
    session.undo()
    assert session._catalog.levels[5].header.laps == original
    session.redo()
    assert session._catalog.levels[5].header.laps == original - 1


def custom_track(session, color=180):
    from src.core.track_artwork import TextureOptions, build_texture, texture_pool_refs, material_appearance
    from src.core.track_import import parse_obj, ImportOptions
    from src.core.track_segments import compile_segmented_obj as compile_obj
    raw = build_texture(np.full((8, 8, 4), color, np.uint8), TextureOptions(8, 8))
    first = session.rom.count(AssetType.TEXTURES_3D) + len(session.custom_textures)
    refs = session.material_references + texture_pool_refs(first, (raw,))
    base = session.track_model(5).raw_data
    appearance, mapping = material_appearance(base, refs, {'Road': (first, 0)})
    mesh = parse_obj('usemtl Road\nv -20 1 -70\nv -20 1 -66\nv -16 1 -66\nf 1 2 3\n')
    compiled = compile_obj(mesh, session.original_asset(AssetType.LEVEL_MODELS, 5), refs, mapping,
                           ImportOptions(), appearance=appearance)
    return compiled.raw, raw


def test_stock_restore_prunes_unused_artwork_and_undo_restores_edited_pixels(rom, tmp_path):
    session = EditSession(rom)
    track, texture = custom_track(session)
    session.import_track(5, track, textures=(texture,))
    index = rom.count(AssetType.TEXTURES_3D)
    pixels = session.image_texture(AssetType.TEXTURES_3D, index).frames[0].pixels.copy()
    pixels[0, 0] = (255, 0, 0, 255)
    session.import_image(AssetType.TEXTURES_3D, index, 0, pixels)
    edited = session.current_asset(AssetType.TEXTURES_3D, index)
    signature = session._signature()
    session.restore_stock_track(5)
    assert session.custom_textures == () and not session.dirty
    assert session.build_rom() == rom.data
    session.undo()
    assert session._signature() == signature
    assert session.current_asset(AssetType.TEXTURES_3D, index) == edited
    session.redo()
    assert not session.custom_textures and not session.dirty
    path = tmp_path/'restored.dkrproj'
    session.save_project(path)
    loaded = EditSession.load_project(path, base_path=rom.source_path)
    assert not loaded.custom_textures and loaded.build_rom() == rom.data


def test_stock_restore_keeps_artwork_used_by_another_track(rom):
    session = EditSession(rom)
    track, texture = custom_track(session)
    session.import_track(5, track, textures=(texture,))
    # Both targets have stock metadata in their imported baseline; compile for
    # the second target using the already appended texture rather than new IDs.
    from src.core.track_artwork import material_appearance
    from src.core.track_import import parse_obj, ImportOptions
    from src.core.track_segments import compile_segmented_obj as compile_obj
    base = session.track_model(8).raw_data
    appearance, mapping = material_appearance(base, session.material_references,
                                              {'Road': (rom.count(AssetType.TEXTURES_3D), 0)})
    mesh = parse_obj('usemtl Road\nv -20 1 -70\nv -20 1 -66\nv -16 1 -66\nf 1 2 3\n')
    other = compile_obj(mesh, base, session.material_references, mapping, ImportOptions(), appearance=appearance)
    session.import_track(8, other.raw)
    version = session.track_import_version(8)
    session.restore_stock_track(5)
    assert session.custom_textures == (texture,)
    assert session.export_report().can_export
    from src.core.materials import MaterialEdit
    slot = next(i for i, info in enumerate(session.track_model(8).textures)
                if info.texture_id == rom.count(AssetType.TEXTURES_3D))
    replacement = next(ref.texture_id for ref in session.material_references[:rom.count(AssetType.TEXTURES_3D)]
                       if not ref.translucent)
    session.edit_track_materials(8, (MaterialEdit('texture', (slot,), replacement),))
    # A subsequent restore/cleanup must retain artwork needed by the other
    # import's baseline even after its current material no longer uses it.
    track, extra = custom_track(session, 80)
    session.import_track(5, track, textures=(extra,))
    session.restore_stock_track(5)
    assert session.custom_textures == (texture,)
    assert session.track_import_version(8) == version
    session.restore_stock_track(8)
    assert session.custom_textures == () and not session.dirty


def test_course_builder_only_exposes_handles_on_movable_roles():
    from types import SimpleNamespace
    from src.ui.course_builder import CourseBuilder
    seen = []
    panel = SimpleNamespace(_roles=[('other', 0), ('grid', 0)],
                            viewport=SimpleNamespace(set_mouse_move_enabled=seen.append))
    CourseBuilder._object_selected(panel, 0)
    CourseBuilder._object_selected(panel, 1)
    assert seen == [False, True]


def test_hidden_research_panel_never_erases_saved_experiment(window):
    session = window.edit_session
    session.set_experiment_name('Keep existing project notes')
    window._update_placement()
    window._commit_editor()
    assert session.experiment_name == 'Keep existing project notes'


def test_dependencies_reused_for_positions_but_invalidated_for_actor_targets(rom):
    from src.core.course import level_objects
    session = EditSession(rom)
    before = session.definition_uses
    actor = next(o for o in level_objects(session, 0) if o.definition.behavior_id == 49)
    session.set_position(actor.key, (actor.position[0]+1, *actor.position[1:]))
    assert session.definition_uses is before
    session.set_parameter(actor.key, 'objectIdToSpawn', 0 if actor.value('objectIdToSpawn') != 0 else 1)
    assert session.definition_uses is not before


def test_interleaved_object_poses_reuse_expanded_lighting_buffers(monkeypatch):
    from collections import OrderedDict
    from types import SimpleNamespace
    import src.renderer.object_mesh as module
    mesh = module.ObjectMesh.__new__(module.ObjectMesh)
    positions = np.array(((0, 0, 0), (1, 0, 0), (0, 0, 1)), np.float32)
    indices = np.array(((0, 1, 2),), np.uint32)
    model = SimpleNamespace(mesh=SimpleNamespace(indices=indices))
    mesh.library = SimpleNamespace(model=lambda _: model)
    mesh.meshes = {0: SimpleNamespace(vbo=0, draw=lambda *args, **kwargs: None)}
    mesh.buffers = {0: np.zeros((3, 9), np.float32)}
    mesh.current_poses = {}
    mesh._pose_buffers = OrderedDict()
    calls = []
    def colors(model, pose):
        calls.append(pose.copy())
        return np.ones((3, 4), np.float32)
    monkeypatch.setattr(module, 'preview_colors', colors)
    for name in ('glBindBuffer', 'glBufferSubData'):
        monkeypatch.setattr(module.GL, name, lambda *args: None)
    instance = SimpleNamespace(model_id=0, object_index=0, scale=1, transform=np.eye(4, dtype=np.float32))
    for pose in (positions, positions+1, positions, positions+1):
        mesh._draw_instance(instance, np.eye(4), np.zeros(3), 0, -1, -1,
                            textured=True, wireframe=False, culling=True, transparent=False, pose=pose)
    assert len(calls) == 2
