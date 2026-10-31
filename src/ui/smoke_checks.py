"""Explicit native GUI/GL regression checks for the --smoke-test command.

Imported only when requested; normal application startup does not load checks.
"""
from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow

if TYPE_CHECKING:
    from src.renderer.viewport import Viewport


def smoke_test(app: QApplication, window: MainWindow, screenshot: Path) -> int:
    """Exercise the real GL window and, when supplied, its loaded catalog."""
    import numpy as np
    from OpenGL import GL
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QFocusEvent, QImage, QMouseEvent, QWheelEvent
    from PySide6.QtTest import QTest

    viewport = window.viewport
    window.object_inspector.mouse_move.setChecked(False)
    window.toolbar.objects.setChecked(False)
    window.toolbar.sprites.setChecked(False)
    window.animation_toolbar.models.setChecked(False)
    try:
        window.activateWindow()
        viewport.setFocus()
        deadline = time.perf_counter() + 12.0
        while viewport.frame_count < 10 and viewport.render_error is None:
            QTest.qWait(50)
            if time.perf_counter() > deadline:
                raise RuntimeError("Timed out waiting for a rendered OpenGL frame")
        if viewport.render_error:
            raise RuntimeError(viewport.render_error)
        if window.catalog is not None:
            catalog = window.catalog
            tree = window.level_panel.tree
            assert tree.topLevelItemCount() == len(catalog.levels)
            chosen = next((level for level in catalog.levels if level.name == "Ancient Lake"), catalog.levels[0])
            window.level_panel.search.setText(chosen.name)
            QTest.qWait(60)
            visible = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                       if not tree.topLevelItem(i).isHidden()]
            assert visible and any(item.text(0) == chosen.name for item in visible)
            window.level_panel.select_level(chosen.index)
            assert window.selected_level == chosen
            details = window.object_inspector.tree
            values = {details.topLevelItem(i).text(0): details.topLevelItem(i).text(1)
                      for i in range(details.topLevelItemCount())}
            assert values["Geometry ID"] == str(chosen.header.geometry_id)
            assert values["Collectables map"] == str(chosen.header.object_map_id)
            window.level_panel.search.setText("no-match-catalog-smoke-check")
            assert all(tree.topLevelItem(i).isHidden() for i in range(tree.topLevelItemCount()))
            window.level_panel.search.clear()
            assert not window.load_rom(Path("artifacts/nonexistent-rom-for-smoke.z64"), show_errors=False)
            assert window.catalog is catalog and window.selected_level == chosen
            print(f"CATALOG PASS | {len(catalog.levels)} levels | filter, selection, metadata, failed-load preservation")
        camera_speed_smoke_test(window)
        camera_pan_smoke_test(viewport)
        track_model = window.current_model
        reference_overlays = viewport.preview_sky, viewport.preview_water, viewport.show_special_art
        viewport.preview_sky = viewport.preview_water = viewport.show_special_art = False
        # Keep the reference-grid camera/axis regression independent of track
        # placement: many tracks are thousands of units away from the origin.
        if track_model is not None:
            viewport.set_model(None)
            QTest.qWait(100)
        viewport.reset_camera()
        QTest.qWait(80)
        original = viewport.camera.position.copy()
        QTest.keyPress(viewport, Qt.Key.Key_W)
        QTest.qWait(250)
        QTest.keyRelease(viewport, Qt.Key.Key_W)
        assert float(np.linalg.norm(viewport.camera.position - original)) > 0.5, "W did not move camera"
        viewport.reset_camera()
        for key in (Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D, Qt.Key.Key_Q, Qt.Key.Key_E):
            before = viewport.camera.position.copy()
            QTest.keyPress(viewport, key)
            QTest.qWait(70)
            QTest.keyRelease(viewport, key)
            assert not np.allclose(before, viewport.camera.position), f"Movement key {key} failed"
        viewport.reset_camera()
        QTest.keyPress(viewport, Qt.Key.Key_Shift)
        QTest.keyPress(viewport, Qt.Key.Key_W)
        QTest.qWait(250)
        QTest.keyRelease(viewport, Qt.Key.Key_W)
        QTest.keyRelease(viewport, Qt.Key.Key_Shift)
        assert float(np.linalg.norm(viewport.camera.position - original)) > 10.0, "Shift boost failed"
        QTest.keyClick(viewport, Qt.Key.Key_F)
        np.testing.assert_allclose(viewport.camera.position, original)
        QTest.mousePress(viewport, Qt.MouseButton.RightButton, pos=viewport.rect().center())
        yaw = viewport.camera.yaw
        center = viewport.rect().center()
        local = QPointF(center + QPoint(40, -15))
        mouse_event = QMouseEvent(
            QEvent.Type.MouseMove, local, QPointF(viewport.mapToGlobal(local.toPoint())),
            Qt.MouseButton.NoButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(viewport, mouse_event)
        assert viewport.camera.yaw != yaw, "Right mouse look failed"
        QTest.mouseRelease(viewport, Qt.MouseButton.RightButton, pos=center)
        assert not viewport._looking and viewport.mouseGrabber() is None, "Mouse capture was not released"
        QTest.mousePress(viewport, Qt.MouseButton.RightButton, Qt.KeyboardModifier.AltModifier, pos=center)
        distance = float(np.linalg.norm(viewport.camera.position - viewport.camera.target))
        QApplication.sendEvent(viewport, mouse_event)
        assert np.isclose(np.linalg.norm(viewport.camera.position - viewport.camera.target), distance), "Orbit radius changed"
        QTest.keyClick(viewport, Qt.Key.Key_Escape)
        assert not viewport._looking, "Escape did not release input"
        fov = viewport.camera.fov
        QApplication.sendEvent(viewport, QWheelEvent(
            QPointF(center), QPointF(viewport.mapToGlobal(center)), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
        ))
        assert viewport.camera.fov < fov, "Wheel zoom failed"
        QTest.keyPress(viewport, Qt.Key.Key_W)
        QApplication.sendEvent(viewport, QFocusEvent(QEvent.Type.FocusOut))
        assert not viewport._keys, "Focus loss did not clear keys"
        viewport.setFocus()
        viewport.reset_camera()
        # The adaptive grid is automatic/off in Perspective. Axes now live in
        # a child orientation widget rather than world-origin GL lines.
        window.toolbar.grid.setChecked(True)
        viewport.set_grid_visible(True)
        window.toolbar.axes.setChecked(True)
        QTest.qWait(100)
        frame = viewport.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
        assert not frame.isNull(), "Framebuffer is empty"
        pixels = np.frombuffer(frame.constBits(), dtype=np.uint8).reshape(frame.height(), frame.bytesPerLine())
        rgb = pixels[:, :frame.width() * 4].reshape(frame.height(), frame.width(), 4)[:, :, :3]
        assert np.unique(rgb.reshape(-1, 3), axis=0).shape[0] > 4, "Working grid was not drawn"
        assert viewport.orientation.isVisible(), "Corner axes are hidden"
        frame = viewport.orientation.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(frame.constBits(), dtype=np.uint8).reshape(frame.height(), frame.bytesPerLine())
        rgb = pixels[:, :frame.width()*4].reshape(frame.height(), frame.width(), 4)[:, :, :3]
        # MSAA can mix every pixel of a one-pixel line with the background.
        # Test color dominance, independent of its subpixel coverage/brightness.
        signed_rgb = rgb.astype(np.int16)
        for channel, label in enumerate(("Red X", "Green Y", "Blue Z")):
            others = [index for index in range(3) if index != channel]
            dominant = signed_rgb[:, :, channel] > np.max(signed_rgb[:, :, others], axis=2) + 30
            assert np.count_nonzero(dominant) > 5, f"{label} axis is missing"
        window.toolbar.grid.setChecked(False)
        window.toolbar.axes.setChecked(False)
        QTest.qWait(80)
        assert not viewport.show_grid and not viewport.show_axes
        blank = viewport.grabFramebuffer()
        assert blank.pixelColor(blank.width() // 2, blank.height() // 2).red() < 20
        window.toolbar.grid.setChecked(True)
        window.toolbar.axes.setChecked(True)
        QTest.qWait(100)
        viewport.makeCurrent()
        assert GL.glGetError() == GL.GL_NO_ERROR, "GL error after input and toggles"
        viewport.doneCurrent()
        assert not viewport.render_error
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        viewport.preview_sky, viewport.preview_water, viewport.show_special_art = reference_overlays
        if track_model is not None:
            viewport.set_model(track_model, window.current_textures)
            if window.selected_level is not None:
                viewport.set_catalog_caption(window.selected_level.name, track_model.model_id)
            window.toolbar.grid.setChecked(False)
            window.toolbar.axes.setChecked(False)
            QTest.qWait(180)
            assert viewport._mesh is not None and viewport._mesh.visible_triangle_count > 0

            def frame_pixels() -> np.ndarray:
                frame = viewport.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
                rows = np.frombuffer(frame.constBits(), dtype=np.uint8).reshape(frame.height(), frame.bytesPerLine())
                return rows[:, :frame.width() * 4].reshape(frame.height(), frame.width(), 4).copy()

            baseline = frame_pixels()
            if window.current_textures:
                assert window.toolbar.textures.isEnabled()
                assert viewport._mesh.texture_handles, "No track textures were uploaded"
                window.toolbar.textures.setChecked(False)
                QTest.qWait(80)
                untextured = frame_pixels()
                assert np.count_nonzero(untextured != baseline) > 1000, "Texture toggle did not change the image"
                window.toolbar.textures.setChecked(True)
                QTest.qWait(80)
                assert np.count_nonzero(frame_pixels() != baseline) == 0, "Texture toggle did not restore the image"
            background = np.array([11, 16, 22], dtype=np.int16)
            coverage = np.max(np.abs(baseline[:, :, :3].astype(np.int16) - background), axis=2) > 20
            assert np.count_nonzero(coverage) > 1000, "Track did not produce visible solid geometry"
            full_calls = viewport._mesh.draw_call_count
            window.toolbar.wireframe.setChecked(True)
            QTest.qWait(80)
            assert np.count_nonzero(frame_pixels() != baseline) > 100, "Wireframe did not change the image"
            window.toolbar.wireframe.setChecked(False)
            window.toolbar.vertex_colors.setChecked(False)
            QTest.qWait(80)
            assert np.count_nonzero(frame_pixels() != baseline) > 100, "Vertex-color toggle did not change the image"
            window.toolbar.vertex_colors.setChecked(True)
            window.toolbar.bounds.setChecked(True)
            QTest.qWait(80)
            assert np.count_nonzero(frame_pixels() != baseline) > 100, "Segment bounds did not appear"
            window.toolbar.segments.setCurrentIndex(1)
            window.toolbar.isolate.setChecked(True)
            QTest.qWait(100)
            assert viewport.isolate_segment and viewport.selected_segment == 0
            assert viewport._mesh.draw_call_count < full_calls or len(track_model.segments) == 1
            expected_target = np.mean([track_model.segments[0].geometry_bounds.minimum,
                                       track_model.segments[0].geometry_bounds.maximum], axis=0)
            np.testing.assert_allclose(viewport.camera.target, expected_target)
            assert window.grab().save(str(screenshot.with_name(screenshot.stem + "-segment.png")))
            exported = window.export_current(screenshot.with_suffix(".obj"))
            assert exported.segment_count == len(track_model.segments)
            assert exported.triangle_count == track_model.triangle_count
            if window.current_textures:
                assert exported.material_path is not None and exported.material_path.is_file()
                assert exported.texture_paths and all(path.is_file() for path in exported.texture_paths)
                print(f"TEXTURE PASS | {len(window.current_textures)} texture IDs | toggle, UV seams, MTL, {len(exported.texture_paths)} PNGs")
            window.toolbar.isolate.setChecked(False)
            window.toolbar.segments.setCurrentIndex(0)
            window.toolbar.bounds.setChecked(False)
            window.toolbar.culling.setChecked(False)
            QTest.qWait(80)
            assert not viewport.cull_backfaces
            window.toolbar.culling.setChecked(True)
            if window.catalog is not None and len(window.catalog.levels) > 1:
                current_level = window.selected_level
                window.level_panel.select_level(0 if current_level.index != 0 else 1)
                QTest.qWait(100)
                assert viewport._mesh is not None and not viewport.render_error
                window.level_panel.select_level(current_level.index)
            QTest.qWait(120)
            viewport.makeCurrent()
            assert GL.glGetError() == GL.GL_NO_ERROR
            viewport.doneCurrent()
            assert not viewport.render_error
            print(f"GEOMETRY PASS | {len(track_model.segments)} segments | {track_model.vertex_count} vertices | "
                  f"{track_model.triangle_count} triangles | colors, wireframe, bounds, isolation, culling, reload, OBJ")
            if window.current_objects:
                inspector = window.object_inspector
                assert inspector.object_list.topLevelItemCount() == len(window.current_objects)
                plain = frame_pixels()
                window.toolbar.objects.setChecked(True)
                QTest.qWait(100)
                assert np.count_nonzero(frame_pixels() != plain) > 50, "Object gizmos did not render"
                window.toolbar.objects.setChecked(False)
                window.toolbar.racelines.setChecked(True)
                QTest.qWait(100)
                if viewport.paths:
                    assert np.count_nonzero(frame_pixels() != plain) > 50, "Racelines did not render"
                window.toolbar.vehicle.setCurrentIndex(1)
                window.toolbar.lane.setCurrentIndex(5)
                QTest.qWait(60)
                assert all(path.checkpoint_set in (-1, window.selected_level.header.checkpoint_sets[0]) for path in viewport.paths)
                window.toolbar.lane.setCurrentIndex(0)
                window.toolbar.vehicle.setCurrentIndex(0)
                window.toolbar.objects.setChecked(True)
                inspector.tabs.setCurrentIndex(1)
                inspector.category.setCurrentIndex(inspector.category.findData("Checkpoints"))
                candidates = [i for i,obj in enumerate(window.current_objects) if obj.category == "Checkpoints"]
                if not candidates:
                    inspector.category.setCurrentIndex(0)
                    candidates = list(range(len(window.current_objects)))
                selected = candidates[0]
                inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(selected))
                QTest.qWait(30)
                assert viewport.selected_object == selected
                item = inspector.object_list.topLevelItem(selected)
                inspector.object_list.scrollToItem(item)
                QTest.mouseClick(inspector.object_list.viewport(),Qt.MouseButton.LeftButton,
                                 pos=inspector.object_list.visualItemRect(item).center())
                QTest.qWait(30)
                QTest.mouseDClick(inspector.object_list.viewport(),Qt.MouseButton.LeftButton,
                                 pos=inspector.object_list.visualItemRect(item).center())
                QTest.qWait(80)
                np.testing.assert_allclose(viewport.camera.target,window.current_objects[selected].position)
                point = viewport.rect().center()
                hit = viewport.pick_object(point.x(),point.y())
                assert hit >= 0, "Ray did not intersect the focused marker"
                QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,pos=point)
                QTest.qWait(50)
                assert viewport.selected_object == hit
                assert inspector.object_list.currentItem().data(0,Qt.ItemDataRole.UserRole) == hit
                values = {inspector.properties.topLevelItem(i).text(0):inspector.properties.topLevelItem(i).text(1)
                          for i in range(inspector.properties.topLevelItemCount())}
                assert values["Object ID (9-bit)"] == str(window.current_objects[hit].object_id)
                assert values["Internal name"] == window.current_objects[hit].definition.name
                assert window.grab().save(str(screenshot.with_name(screenshot.stem+"-selected-object.png")))
                inspector.object_search.setText("no-match-object-smoke")
                assert not viewport.visible_objects
                inspector.object_search.clear()
                inspector.category.setCurrentIndex(0)
                viewport.select_object(-1)
                viewport.reset_camera()
                QTest.qWait(80)
                assert not viewport.render_error
                print(f"OBJECT PASS | {len(window.current_objects)} objects | {len(viewport.paths)} routes/edges | filters, picking, inspector, focus, vehicle/lane controls")
            if window.current_sprites:
                window.toolbar.objects.setChecked(False)
                window.toolbar.racelines.setChecked(False)
                viewport.reset_camera()
                QTest.qWait(80)
                plain = frame_pixels()
                window.toolbar.sprites.setChecked(True)
                QTest.qWait(100)
                assert viewport._sprite_mesh is not None
                assert viewport._sprite_mesh.instance_count == len(window.current_sprites)
                assert np.count_nonzero(frame_pixels() != plain) > 50, "Sprite artwork did not render"
                # Gizmo filters must not hide the physical artwork.
                window.object_inspector.category.setCurrentIndex(window.object_inspector.category.findData("Checkpoints"))
                QTest.qWait(60)
                assert np.count_nonzero(frame_pixels() != plain) > 50
                window.object_inspector.category.setCurrentIndex(0)
                window.toolbar.sprites.setChecked(False)
                QTest.qWait(80)
                assert np.array_equal(frame_pixels(), plain), "Sprite toggle did not restore the track"
                window.toolbar.sprites.setChecked(True)
                QTest.qWait(80)
                assert not viewport.render_error
                print(f"SPRITE PASS | {len(window.current_sprites)} instances | multi-tile billboards, toggle, independent gizmo filter")
            if window.edit_session is not None:
                checkpoint_names_smoke_test(window, screenshot)
                editing_smoke_test(window, screenshot)
                mouse_move_smoke_test(window, screenshot)
        assert viewport.grabFramebuffer().save(str(screenshot)), "Could not save screenshot"
        if window.catalog is not None:
            assert window.grab().save(str(screenshot.with_name(screenshot.stem + "-window.png")))
        count = viewport.frame_count
        start = time.perf_counter()
        # QTest.qWait polls event delivery and can under-report rendering FPS.
        # Measure with the same event loop used by the normal application.
        from PySide6.QtCore import QEventLoop, QTimer
        benchmark_loop = QEventLoop()
        QTimer.singleShot(1100,benchmark_loop.quit)
        benchmark_loop.exec()
        fps = (viewport.frame_count - count) / (time.perf_counter() - start)
        print(f"SMOKE PASS | {viewport.gl_description} | {fps:.1f} FPS | {viewport.frame_count} frames | {viewport.framebuffer_samples}x MSAA")
        print(f"Camera keys, boost, mouse look, orbit, zoom, reset, focus release, grid/axes: PASS\nScreenshot: {screenshot.resolve()}")
        return 0
    except Exception:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(screenshot.with_name(screenshot.stem + "-failure.png")))
        logging.exception("Viewer smoke test failed")
        return 1
    finally:
        # This smoke window owns only temporary test edits, already exported on success.
        window.edit_session = None
        window.close()
        app.processEvents()


def checkpoint_names_smoke_test(window: MainWindow, screenshot: Path) -> None:
    """Named checkpoint fields retain original edit keys and exact byte writes."""
    from unittest.mock import patch
    import json
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QComboBox, QLineEdit, QTreeWidgetItem
    from src.core.editing import EditSession
    from src.core.objects import load_object_map
    from src.core.rom import RomImage, LUT_START, LUT_END, parse_asset_lut
    from src.ui.object_inspector import EDIT_ROLE
    from src.core.parameter_labels import CHECKPOINT_PARAMETERS

    prior = window.edit_session
    assert prior is not None
    session = EditSession(prior.rom, prior.database)
    inspector = window.object_inspector
    selected = next((i for i,o in enumerate(window.current_objects) if o.key == (5,48)),
                    next(i for i,o in enumerate(window.current_objects) if o.definition.behavior_id == 13))
    key = window.current_objects[selected].key
    original = session.object(key)
    window.edit_session = session
    try:
        window._refresh_edits(key)

        def parameter(name: str) -> QTreeWidgetItem:
            root = next(inspector.properties.topLevelItem(i) for i in range(inspector.properties.topLevelItemCount())
                        if inspector.properties.topLevelItem(i).text(0) == "Parameters")
            return next(root.child(i) for i in range(root.childCount())
                        if root.child(i).data(1,EDIT_ROLE) == ("parameter",name))

        for p in original.parameters:
            row = parameter(p.name)
            assert CHECKPOINT_PARAMETERS[p.name].label in row.text(0)
            assert f"Original field: {p.name}" in row.toolTip(0)
        assert "AI lane 0 lateral" in parameter("unkB").text(0)
        assert "Unused byte" in parameter("unk18").text(0)
        assert "Unused byte" in parameter("unk1B").text(0)

        def combo(name: str) -> QComboBox:
            row = parameter(name)
            inspector.properties.scrollToItem(row)
            inspector.properties.editItem(row,1)
            QTest.qWait(30)
            return next(editor for editor in inspector.properties.findChildren(QComboBox) if editor.isVisible())

        def choose(name: str, value: int) -> None:
            editor = combo(name)
            QTest.mouseClick(editor,Qt.MouseButton.LeftButton,pos=QPoint(editor.width()-10,editor.height()//2))
            # Windows animates the popup through a temporary QRollEffect.
            deadline = time.perf_counter()+2
            while not editor.view().isVisible() and time.perf_counter() < deadline:
                QTest.qWait(30)
            assert editor.view().isVisible(), "Choice popup did not open"
            index = editor.model().index(editor.findData(value),0)
            editor.view().scrollTo(index)
            QTest.mouseMove(editor.view().viewport(),editor.view().visualRect(index).center())
            QTest.qWait(80)
            QTest.mouseClick(editor.view().viewport(),Qt.MouseButton.LeftButton,pos=editor.view().visualRect(index).center())
            QTest.qWait(80)
            assert session.object(key).value(name) == value

        choose("unk19",4)
        assert "4 · Right turn" == parameter("unk19").text(1)
        assert [i for i,(a,b) in enumerate(zip(original.raw_data,session.object(key).raw_data)) if a!=b] == [25]
        window.undo_action.trigger()
        assert session.object(key).raw_data == original.raw_data
        window.redo_action.trigger()
        assert session.object(key).value("unk19") == 4
        choose("unk13",4)
        assert parameter("unk13").text(1) == "4 · AI slowdown"
        editor = combo("unk13")
        editor.lineEdit().setText("-128")
        QTest.keyClick(editor,Qt.Key.Key_Return)
        QTest.qWait(80)
        assert session.object(key).value("unk13") == -128
        assert parameter("unk13").text(1) == "-128"
        editor = combo("unk13")
        editor.lineEdit().setText("128")
        QTest.keyClick(editor,Qt.Key.Key_Return)
        QTest.qWait(80)
        assert session.object(key).value("unk13") == -128, "Signed bounds were lost by choice editing"
        window.undo_action.trigger()
        assert session.object(key).value("unk13") == 4

        # Original named numeric fields still use the normal integer editor.
        row = parameter("unkB")
        inspector.properties.scrollToItem(row)
        inspector.properties.editItem(row,1)
        QTest.qWait(20)
        line = next(e for e in inspector.properties.findChildren(QLineEdit) if e.isVisible())
        line.setText("-43")
        QTest.keyClick(line,Qt.Key.Key_Return)
        QTest.qWait(80)
        assert session.object(key).value("unkB") == -43

        # Saving an active editable choice must commit even an unlisted value.
        editor = combo("unk19")
        editor.lineEdit().setText("0xFF")
        project = screenshot.with_name(screenshot.stem+"-checkpoint.dkrproj")
        with patch("src.ui.main_window.QFileDialog.getSaveFileName",return_value=(str(project),"")):
            window.save_project_action.trigger()
        assert session.object(key).value("unk19") == 255
        assert session.object(key).raw_data[25] == 255
        assert EditSession.load_project(project).object(key).raw_data == session.object(key).raw_data
        document = json.loads(project.read_text())
        assert {item["offset"] for item in document["edits"][0]["bytes"]} == {11,19,25}
        edited_rom = session.build_rom()
        # Inspect this test export explicitly; normal from_bytes/from_file
        # still require the original ROM identity.
        exported = RomImage(edited_rom,"z64",parse_asset_lut(edited_rom,LUT_START,LUT_END))
        parsed = load_object_map(exported,key[0],session.database)
        assert parsed.objects[key[1]].raw_data == session.object(key).raw_data
        window.grab().save(str(screenshot.with_name(screenshot.stem+"-checkpoint-labels.png")))
        print("CHECKPOINT NAMES PASS | all labels/tooltips, dropdown mouse selection, arbitrary/signed input, undo/redo, active-cell project save and ROM bytes")
    finally:
        window._commit_editor()
        window.edit_session = prior
        window._refresh_edits(key)
        window.viewport.reset_camera()


def editing_smoke_test(window: MainWindow, screenshot: Path) -> None:
    """Real Qt delegate/keyboard edits, live GPU preview and project/ROM save actions."""
    from unittest.mock import patch
    import numpy as np
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QTreeWidgetItem, QMessageBox
    from src.core.editing import EditSession, n64_checksums
    import struct

    session = window.edit_session
    assert session is not None
    if session.modified_maps:
        print("EDITOR PROJECT PASS | saved overlay loaded against verified original ROM")
        return
    viewport = window.viewport
    inspector = window.object_inspector
    inspector.tabs.setCurrentIndex(1)
    inspector.category.setCurrentIndex(0)
    inspector.object_search.clear()
    selected = next(i for i,obj in enumerate(window.current_objects) if obj.definition.behavior_id == 2)
    original = window.current_objects[selected]
    inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(selected))
    viewport.focus_object(selected)
    QTest.qWait(80)
    position = viewport.camera.position.copy()
    target = viewport.camera.target.copy()

    def framebuffer() -> np.ndarray:
        frame = viewport.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(frame.constBits(),np.uint8).copy()

    def commit(item: QTreeWidgetItem, text: str) -> None:
        inspector.properties.scrollToItem(item)
        inspector.properties.setCurrentItem(item)
        inspector.properties.editItem(item,1)
        QTest.qWait(20)
        editor = next((field for field in inspector.properties.findChildren(QLineEdit) if field.isVisible()), None)
        assert editor is not None, "Property editor did not open"
        QTest.keyClick(editor,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor,text)
        QTest.keyClick(editor,Qt.Key.Key_Return)
        QTest.qWait(60)

    def root(name: str) -> QTreeWidgetItem:
        return next(inspector.properties.topLevelItem(i) for i in range(inspector.properties.topLevelItemCount())
                    if inspector.properties.topLevelItem(i).text(0) == name)

    plain = framebuffer()
    inspector.move_step.setValue(64)
    QTest.mouseClick(inspector.nudge_buttons[1],Qt.MouseButton.LeftButton)
    QTest.qWait(80)
    assert session.object(original.key).position[0] == original.position[0]+64
    assert np.count_nonzero(framebuffer() != plain) > 20, "Moving sprite did not change the GPU image"
    np.testing.assert_array_equal(viewport.camera.position,position)
    np.testing.assert_array_equal(viewport.camera.target,target)
    inspector.move_keys.setChecked(True)
    viewport.setFocus()
    QTest.keyClick(viewport,Qt.Key.Key_PageUp)
    QTest.qWait(60)
    assert session.object(original.key).position[1] == original.position[1]+64
    QTest.keyClick(viewport,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(60)
    assert session.object(original.key).position[1] == original.position[1]
    window.redo_action.trigger()
    QTest.qWait(60)
    assert session.object(original.key).position[1] == original.position[1]+64
    inspector.move_keys.setChecked(False)
    box = inspector.coordinates[2]
    box.setFocus()
    QTest.keyClick(box,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(box,str(original.position[2]+32))
    QTest.keyClick(box,Qt.Key.Key_Return)
    QTest.qWait(60)
    assert session.object(original.key).position[2] == original.position[2]+32

    parameters = root("Parameters")
    from src.ui.object_inspector import EDIT_ROLE
    radius = next(parameters.child(i) for i in range(parameters.childCount())
                  if parameters.child(i).data(1, EDIT_ROLE) == ('parameter', 'radius'))
    commit(radius,"80")
    assert session.object(original.key).value("radius") == 80
    inspector.raw_edit.setChecked(True)
    raw = root("Raw entry")
    commit(raw.child(1),"0x90")
    assert session.object(original.key).value("radius") == 144
    raw = root("Raw entry")
    byte = raw.child(1)
    byte.setExpanded(True)
    bit = byte.child(0)
    inspector.properties.scrollToItem(bit)
    QTest.qWait(30)
    rectangle = inspector.properties.visualItemRect(bit)
    x = inspector.properties.header().sectionViewportPosition(1)+10
    QTest.mouseClick(inspector.properties.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(x,rectangle.center().y()))
    QTest.qWait(60)
    assert session.object(original.key).value("radius") == 145, "Bit checkbox did not update raw byte"
    raw = root("Raw entry")
    commit(raw.child(1),"0x100")
    assert session.object(original.key).value("radius") == 145
    assert "rejected" in inspector.edit_message.text()
    window._revert_selected()
    assert session.object(original.key) == original and not session.modified_maps
    window.undo_action.trigger()
    assert session.object(original.key).value("radius") == 145

    # Edit an actual unknown/padding field and confirm its bit checkboxes agree.
    checkpoint_index = next(i for i,obj in enumerate(window.current_objects) if obj.definition.behavior_id == 13)
    checkpoint = window.current_objects[checkpoint_index]
    inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(checkpoint_index))
    # Multi-selection synchronizes its primary/property tree on the next event.
    QTest.qWait(60)
    inspector.raw_edit.setChecked(True)
    raw = root("Raw entry")
    commit(raw.child(27-8),"0xA5")
    assert session.object(checkpoint.key).raw_data[27] == 0xA5
    assert session.object(checkpoint.key).value("unk1B") == 0xA5
    window.toolbar.racelines.setChecked(True)
    # Editing keeps category filters, selection and the camera intact.
    inspector.category.setCurrentIndex(inspector.category.findData("Checkpoints"))
    before = viewport.camera.position.copy()
    window._nudge_selected(0,32)
    np.testing.assert_array_equal(viewport.camera.position,before)
    assert inspector.category.currentData() == "Checkpoints"
    assert viewport.selected_object == checkpoint_index
    window.undo_action.trigger()
    inspector.category.setCurrentIndex(0)

    project = screenshot.with_suffix(".dkrproj")
    # Save shortcuts must include text still being edited, before Enter/focus-out.
    pending = root("Raw entry").child(27-8)
    inspector.properties.editItem(pending,1)
    QTest.qWait(30)
    editor = next((field for field in inspector.properties.findChildren(QLineEdit) if field.isVisible()), None)
    assert editor is not None
    editor.setText("0xA7")
    with patch("src.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(project),"")):
        window.save_project_action.trigger()
    assert project.is_file() and not session.dirty
    assert session.object(checkpoint.key).raw_data[27] == 0xA7
    pending = root("Raw entry").child(27-8)
    inspector.properties.editItem(pending,1)
    QTest.qWait(30)
    editor = next((field for field in inspector.properties.findChildren(QLineEdit) if field.isVisible()), None)
    assert editor is not None
    editor.setText("0xA5")
    exported = screenshot.with_name(screenshot.stem+"-edited.z64")
    with patch("src.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(exported),"")):
        window.save_rom_action.trigger()
    data = exported.read_bytes()
    assert n64_checksums(data) == struct.unpack_from(">2I",data,0x10)
    assert session.object(checkpoint.key).raw_data[27] == 0xA5 and session.dirty
    with patch("src.ui.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Cancel):
        assert not window.load_project(project,show_errors=False)
    assert window.edit_session is session and session.object(checkpoint.key).raw_data[27] == 0xA5
    window.save_project_action.trigger()
    assert not session.dirty
    level_id = window.selected_level.index
    window.level_panel.select_level(0 if level_id != 0 else 1)
    QTest.qWait(60)
    window.undo_action.trigger()
    assert session.dirty
    window.redo_action.trigger()
    assert not session.dirty
    window.level_panel.select_level(level_id)
    QTest.qWait(60)
    assert next(o for o in window.current_objects if o.key == original.key) == session.object(original.key)
    saved = EditSession.load_project(project)
    assert saved.object(original.key) == session.object(original.key)
    assert saved.object(checkpoint.key).raw_data[27] == 0xA5
    assert window.load_project(project,show_errors=False)
    assert window.edit_session.object(checkpoint.key).raw_data[27] == 0xA5
    # Reopening the current project with Save must load the newly saved edits,
    # rather than the snapshot read before the unsaved-changes dialog.
    current_x = window.edit_session.object(checkpoint.key).position[0]
    window._apply_edit(checkpoint.key,"position",0,current_x+16)
    with patch("src.ui.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Save) as confirm:
        assert window.load_project(project,show_errors=False)
        assert confirm.call_count == 1
    assert window.edit_session.object(checkpoint.key).position[0] == current_x+16
    window._apply_edit(checkpoint.key,"raw",27,0xA7)
    with patch("src.ui.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.Discard) as confirm:
        assert window.load_project(project,show_errors=False)
        assert confirm.call_count == 1
    assert window.edit_session.object(checkpoint.key).raw_data[27] == 0xA5
    with patch("src.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(exported),"")):
        window.save_rom_action.trigger()
    inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(checkpoint_index))
    QTest.qWait(60)
    viewport.reset_camera()
    raw = root("Raw entry")
    raw.setExpanded(True)
    raw.child(27-8).setExpanded(True)
    from PySide6.QtWidgets import QAbstractItemView
    inspector.properties.scrollToItem(raw.child(27-8).child(7), QAbstractItemView.ScrollHint.PositionAtBottom)
    QTest.qWait(100)
    assert not viewport.render_error
    assert window.grab().save(str(screenshot.with_name(screenshot.stem+"-raw-editor.png")))
    print("EDITOR PASS | XYZ, nudges, live sprite GPU changes, typed/raw/bit edits, bounds, undo/redo, filters, project reload and ROM/checksum export")


def mouse_move_smoke_test(window: MainWindow, screenshot: Path) -> None:
    """Real mouse events: axes, center, sprite picking, cancellation and persistence."""
    import numpy as np
    from PySide6.QtCore import QPoint, QEvent
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtTest import QTest
    from src.renderer.camera import project_point, translation_length
    from src.core.editing import EditSession

    viewport = window.viewport
    inspector = window.object_inspector
    session = window.edit_session
    assert session is not None
    inspector.mouse_move.setChecked(True)
    inspector.category.setCurrentIndex(0)
    window.toolbar.sprites.setChecked(True)
    window.toolbar.objects.setChecked(False)
    window.toolbar.racelines.setChecked(False)
    index = next(i for i,obj in enumerate(window.current_objects)
                 if obj.definition.behavior_id == 2 and obj.value("radius",64) <= 100)
    original = window.current_objects[index]
    inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(index))
    viewport.focus_object(index)
    viewport.setFocus()
    QTest.qWait(100)
    camera_position = viewport.camera.position.copy()
    prior_undo = session.can_undo

    def axis_points(axis: int) -> tuple[QPoint, QPoint]:
        center = np.asarray(session.object(original.key).position,np.float32)
        matrix = viewport.camera.projection_matrix(viewport.width()/viewport.height()) @ viewport.camera.view_matrix()
        length = translation_length(viewport.camera,center,viewport.height())
        first = center.copy();first[axis] += length*.72
        last = first.copy();last[axis] += length*.45
        a = project_point(first,matrix,viewport.width(),viewport.height())
        b = project_point(last,matrix,viewport.width(),viewport.height())
        start,end = QPoint(round(a[0]),round(a[1])),QPoint(round(b[0]),round(b[1]))
        assert viewport.translation_handle_at(start.x(),start.y()) == axis
        return start,end

    def move(start: QPoint, end: QPoint) -> None:
        for fraction in (.3,.6,1.):
            point = start+(end-start)*fraction
            QTest.mouseMove(viewport,point)
            QTest.qWait(25)

    for axis in range(3):
        sprite_mesh = viewport._sprite_mesh
        before_cursor = session._cursor
        start,end = axis_points(axis)
        QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
        assert session.moving_key == original.key
        assert viewport._drag.axis == axis
        move(start,end)
        QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
        QTest.qWait(50)
        changed = session.object(original.key)
        assert changed.position[axis] != original.position[axis]
        assert all(changed.position[i] == original.position[i] for i in range(3) if i != axis)
        assert changed.raw_data[8:] == original.raw_data[8:]
        assert session.moving_key is None and session._cursor == before_cursor+1
        assert viewport._sprite_mesh is sprite_mesh,"Dragging rebuilt sprite GPU resources"
        np.testing.assert_array_equal(viewport.camera.position,camera_position)
        assert tuple(box.value() for box in inspector.coordinates) == changed.position
        window.undo_action.trigger()
        assert session.object(original.key) == original and session.can_undo == prior_undo
        window.redo_action.trigger()
        assert session.object(original.key) == changed
        window.undo_action.trigger()

    for cancel in ("escape","focus","disable"):
        start,end = axis_points(0)
        QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
        move(start,end)
        assert session.object(original.key).position != original.position
        if cancel == "escape":
            QTest.keyClick(viewport,Qt.Key.Key_Escape)
        elif cancel == "focus":
            QApplication.sendEvent(viewport,QFocusEvent(QEvent.Type.FocusOut,Qt.FocusReason.OtherFocusReason))
        else:
            inspector.mouse_move.setChecked(False)
        QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
        QTest.qWait(40)
        assert session.object(original.key) == original and session.moving_key is None
        assert session.can_redo and viewport._drag is None
        inspector.mouse_move.setChecked(True)
        viewport.setFocus()

    start,end = axis_points(0)
    QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,pos=start)
    assert session.object(original.key) == original and session.can_redo
    # Switching levels rolls back the provisional move before loading new maps.
    level_id = window.selected_level.index
    QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
    move(start,end)
    window.level_panel.select_level(0 if level_id != 0 else 1)
    assert session.object(original.key) == original and session.moving_key is None
    QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
    window.level_panel.select_level(level_id)
    inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(index))
    viewport.focus_object(index)
    viewport.setFocus()
    QTest.qWait(70)

    # Find a visible opaque texel away from the object origin and drag the artwork.
    sprite = next(sprite for sprite in window.current_sprites if sprite.object_index == index)
    view = viewport.camera.view_matrix()
    matrix = viewport.camera.projection_matrix(viewport.width()/viewport.height()) @ view
    artwork: QPoint | None = None
    for tile in sprite.tiles:
        header = tile.frame.header
        candidates = np.argwhere(tile.frame.pixels[:,:,3] == 255)
        for py,px in candidates[::max(1,len(candidates)//80)]:
            u = (float(px)+.5-1/32)/(header.width-1-1/32)
            v = (float(py)+.5)/(header.height-1)
            x,y = tile.left+u*(tile.right-tile.left),tile.top-v*(tile.top-tile.bottom)
            world = np.asarray(sprite.position)+view[0,:3]*x*sprite.scale+view[1,:3]*y*sprite.scale
            projected = project_point(world,matrix,viewport.width(),viewport.height())
            if projected is None:continue
            point = QPoint(round(projected[0]),round(projected[1]))
            if viewport.rect().adjusted(40,40,-40,-40).contains(point) and viewport.translation_handle_at(point.x(),point.y()) is None and viewport.pick_object(point.x(),point.y()) == index:
                artwork = point
                break
        if artwork is not None:break
    assert artwork is not None,"No visible sprite pixel available for picking"
    viewport.select_object(-1)
    inspector.category.setCurrentIndex(inspector.category.findData("Checkpoints"))
    QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=artwork)
    assert viewport.selected_object == index and viewport._drag.axis is None
    assert inspector.category.currentIndex() == 0,"Picking a sprite did not reveal its filtered inspector row"
    end = artwork+QPoint(30,-20)
    move(artwork,end)
    QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
    QTest.qWait(60)
    assert session.object(original.key).position != original.position
    window.undo_action.trigger()
    assert session.object(original.key) == original

    # A save shortcut during the gesture commits its current preview exactly once.
    during_drag = screenshot.with_name(screenshot.stem+"-during-drag.dkrproj")
    window.save_project_to(during_drag)
    viewport.setFocus()
    start,end = axis_points(0)
    QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
    move(start,end)
    saved_position = session.object(original.key).position
    QTest.keyClick(viewport,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier)
    assert session.moving_key is None
    QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
    assert EditSession.load_project(during_drag).object(original.key).position == saved_position
    window.undo_action.trigger()
    assert session.object(original.key) == original

    # Ctrl snapping uses the existing movement Step, relative to the starting XYZ.
    inspector.move_step.setValue(16)
    start,end = axis_points(0)
    QTest.mousePress(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier,pos=start)
    move(start,end)
    QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier,pos=end)
    QTest.qWait(60)
    changed = session.object(original.key)
    assert changed.position[0] != original.position[0]
    assert (changed.position[0]-original.position[0])%16 == 0
    assert changed.raw_data[8:] == original.raw_data[8:]
    project = screenshot.with_name(screenshot.stem+"-mouse.dkrproj")
    window.save_project_to(project)
    assert EditSession.load_project(project).object(original.key) == changed
    session.save_rom(screenshot.with_name(screenshot.stem+"-mouse.z64"))
    QTest.qWait(80)
    assert not viewport.render_error
    assert window.grab().save(str(screenshot.with_name(screenshot.stem+"-mouse.png")))
    # Checkpoint motion also updates line buffers without replacing marker VAOs.
    scenery_index = index
    index = next(i for i,obj in enumerate(window.current_objects) if obj.definition.behavior_id == 13)
    original = window.current_objects[index]
    inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(index))
    window.toolbar.objects.setChecked(True)
    window.toolbar.racelines.setChecked(True)
    viewport.focus_object(index)
    viewport.setFocus()
    QTest.qWait(80)
    gizmo_mesh = viewport._gizmos
    old_paths = tuple(path.points.copy() for path in viewport.paths)
    start,end = axis_points(0)
    QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
    move(start,end)
    QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
    QTest.qWait(60)
    assert any(not np.array_equal(a,b.points) for a,b in zip(old_paths,viewport.paths))
    assert viewport._gizmos is gizmo_mesh,"Checkpoint movement rebuilt marker GPU resources"
    window.undo_action.trigger()
    assert session.object(original.key) == original and not session.dirty
    window.toolbar.objects.setChecked(False)
    window.toolbar.racelines.setChecked(False)
    inspector.object_list.setCurrentItem(inspector.object_list.topLevelItem(scenery_index))
    viewport.focus_object(scenery_index)
    print("MOUSE PASS | X/Y/Z, sprite/view-plane dragging, live XYZ, Ctrl snap, Escape/focus/disable rollback, single undo/redo, project/ROM export")


def camera_speed_smoke_test(window: MainWindow) -> None:
    """Exercise the real slider and WASD after scene/object framing changes."""
    from unittest.mock import patch
    import numpy as np
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    viewport = window.viewport
    slider = window.camera_toolbar.speed
    objects_visible = window.toolbar.objects.isChecked()
    normal_speed = viewport.camera.speed
    assert slider.value() == 100
    slider.setFocus()
    QTest.keyClick(slider, Qt.Key.Key_Home)
    assert slider.value() == 1
    assert np.isclose(viewport.camera.speed, normal_speed * .01)
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()//2, slider.height()//2))
    assert 1 < slider.value() < 400, "Mouse input did not change camera slider"
    assert np.isclose(viewport.camera.speed, normal_speed * slider.value()/100)
    QTest.keyClick(slider, Qt.Key.Key_End)
    assert slider.value() == 400
    assert np.isclose(viewport.camera.speed, normal_speed * 4)
    slider.setValue(100)

    def walk() -> float:
        viewport.setFocus()
        before = viewport.camera.position.copy()
        with patch.object(viewport.camera, 'move', wraps=viewport.camera.move) as moved:
            QTest.keyPress(viewport, Qt.Key.Key_W)
            QTest.qWait(240)
            QTest.keyRelease(viewport, Qt.Key.Key_W)
        elapsed = sum(call.args[3] for call in moved.call_args_list if call.args[0] == 1)
        distance = float(np.linalg.norm(viewport.camera.position-before))
        assert elapsed > 0 and distance > 0, "W did not move the camera"
        velocity = distance/elapsed
        assert np.isclose(velocity, viewport.camera.speed, rtol=.005)
        return velocity

    # Normalize by the actual input-loop ticks. QTest's wall-clock wait can
    # deliver different numbers of frames under load or during focus changes.
    before_distance = walk()
    if window.current_objects:
        item = window.object_inspector.object_list.topLevelItem(0)
        window.object_inspector.object_list.setCurrentItem(item)
        assert viewport.camera.speed == normal_speed
        window._focus_object(0)
        assert viewport.camera.speed == normal_speed
        focused_distance = walk()
        viewport.select_object(-1)
        window.object_inspector.select_object(-1)
        assert viewport.camera.speed == normal_speed
        deselected_distance = walk()
        assert np.isclose(focused_distance, before_distance, rtol=.005)
        assert np.isclose(deselected_distance, before_distance, rtol=.005)
    slider.setValue(200)
    viewport.reset_camera()
    fast_distance = walk()
    assert np.isclose(fast_distance/before_distance, 2, rtol=.005)
    if window.current_model is not None:
        window.toolbar.segments.setCurrentIndex(1)
        window.toolbar.isolate.setChecked(True)
        viewport.reset_camera()
        assert viewport.camera.speed == normal_speed * 2
        window.toolbar.isolate.setChecked(False)
        window.toolbar.segments.setCurrentIndex(0)
    if window.catalog is not None:
        original_level = window.selected_level.index
        window.level_panel.select_level((original_level+1) % len(window.catalog.levels))
        assert slider.value() == viewport.camera_speed_percent == 200
        window.level_panel.select_level(original_level)
        assert viewport.camera.speed == normal_speed * 2
    slider.setValue(100)
    viewport.reset_camera()
    viewport.setFocus()
    window.toolbar.objects.setChecked(objects_visible)
    print("CAMERA SPEED PASS | slider mouse/keys, WASD distance, selection/focus/deselection, fit/isolation, level changes")


def camera_pan_smoke_test(viewport: Viewport) -> None:
    """Native event/capture lifecycle in the shared widget, without project edits."""
    import copy
    import numpy as np
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QFocusEvent, QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget
    from src.renderer.camera import project_point

    saved = copy.deepcopy(viewport.camera)
    selected = viewport.selected_objects, viewport.selected_object
    route_slot = viewport.route_pick_slot
    center = viewport.rect().center()

    def press() -> None:
        viewport.setFocus()
        QTest.mousePress(viewport, Qt.MouseButton.MiddleButton, pos=center)
        assert viewport._panning and QWidget.mouseGrabber() is viewport
        assert viewport.cursor().shape() == Qt.CursorShape.ClosedHandCursor

    def move(buttons=Qt.MouseButton.MiddleButton) -> None:
        point = QPointF(center+QPoint(73, -29))
        QApplication.sendEvent(viewport, QMouseEvent(QEvent.Type.MouseMove, point,
            QPointF(viewport.mapToGlobal(point.toPoint())), Qt.MouseButton.NoButton,
            buttons, Qt.KeyboardModifier.NoModifier))

    def released(context: str = 'button release') -> None:
        assert not viewport._panning and not viewport._looking and not viewport._keys, context
        assert QWidget.mouseGrabber() is not viewport
        assert viewport.cursor().shape() != Qt.CursorShape.ClosedHandCursor

    try:
        for view in ('Perspective', 'Top', 'Front', 'Right'):
            viewport.camera = copy.deepcopy(saved)
            viewport.camera.set_view(view)
            point = viewport.camera.target.copy()
            settings = (viewport.camera.yaw, viewport.camera.pitch, viewport.camera.fov, viewport.camera.speed)
            before = project_point(point, viewport.camera.projection_matrix(viewport.width()/viewport.height())@
                                   viewport.camera.view_matrix(), viewport.width(), viewport.height())
            viewport.route_pick_slot = 2
            press()
            move()
            after = project_point(point, viewport.camera.projection_matrix(viewport.width()/viewport.height())@
                                  viewport.camera.view_matrix(), viewport.width(), viewport.height())
            np.testing.assert_allclose(np.asarray(after)-before, (73, -29), atol=.01)
            QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=center)
            QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=center)
            assert viewport._panning and not viewport._looking
            assert selected == (viewport.selected_objects, viewport.selected_object)
            # Movement/edit shortcuts cannot move the selection while panning.
            QTest.keyClick(viewport, Qt.Key.Key_W)
            QTest.keyClick(viewport, Qt.Key.Key_Up)
            assert not viewport._keys
            QTest.mouseRelease(viewport, Qt.MouseButton.MiddleButton, pos=center)
            released()
            assert viewport.route_pick_slot == 2, 'Panning cancelled the active route-pick tool'
            assert settings == (viewport.camera.yaw, viewport.camera.pitch, viewport.camera.fov, viewport.camera.speed)
            QTest.qWait(25)
            assert viewport.render_error is None
        for stop in ('escape', 'focus', 'deactivate', 'hide', 'lost-button', 'ungrab'):
            press()
            if stop == 'escape':
                QTest.keyClick(viewport, Qt.Key.Key_Escape)
            elif stop == 'focus':
                QApplication.sendEvent(viewport, QFocusEvent(QEvent.Type.FocusOut))
            elif stop == 'deactivate':
                QApplication.sendEvent(viewport, QEvent(QEvent.Type.WindowDeactivate))
            elif stop == 'hide':
                viewport.hide()
                viewport.show()
            elif stop == 'lost-button':
                move(Qt.MouseButton.NoButton)
            else:
                viewport.releaseMouse()
                QTest.qWait(40)  # Explicit Qt release need not emit UngrabMouse.
            released(stop)
            QTest.mouseRelease(viewport, Qt.MouseButton.MiddleButton, pos=center)
        print('PAN PASS | all four views, pixel scaling, selection/tools preserved, mixed buttons, '
              'release/Escape/focus/deactivation/hide/lost-button/ungrab', flush=True)
    finally:
        viewport._release_input()
        viewport.camera = saved
        viewport.route_pick_slot = route_slot
        viewport.update()

