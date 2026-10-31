from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.core.rom import RomImage, AssetType
from src.core.level_model import LevelModel
from src.renderer.work_grid import grid_lines, grid_spacing
from src.renderer.viewport import Viewport


@pytest.mark.parametrize('view,normal', [('Perspective', 1), ('Top', 1), ('Front', 2), ('Right', 0)])
def test_work_grid_uses_real_world_multiples_around_off_origin_track(view, normal):
    center = np.array((-2970., 51., -7304.), np.float32)
    lines, spacing = grid_lines(center, 10000, view)
    assert spacing == grid_spacing(10000)
    np.testing.assert_array_equal(lines[:, normal], center[normal])
    for a, b in lines.reshape(-1, 2, 6):
        fixed = next(i for i in range(3) if i != normal and a[i] == b[i])
        assert a[fixed]/spacing == round(float(a[fixed]/spacing))
        assert np.linalg.norm((a[:3]+b[:3])*.5-center) <= spacing*25


def test_grid_visibility_is_automatic_until_explicitly_overridden():
    app = QApplication.instance() or QApplication([])
    viewport = Viewport()
    assert not viewport.show_grid
    viewport.set_view('Top')
    assert viewport.show_grid
    viewport.set_view('Perspective')
    assert not viewport.show_grid
    viewport.set_grid_visible(True)
    viewport.set_view('Perspective')
    assert viewport.show_grid
    viewport.set_grid_automatic(True)
    assert not viewport.show_grid
    viewport._timer.stop()
    viewport.deleteLater()
    app.processEvents()


def test_loaded_work_grid_stays_with_the_course_without_mutating_geometry():
    app = QApplication.instance() or QApplication([])
    rom = RomImage.from_file(Path('Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64'))
    model = LevelModel.from_bytes(rom.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True))
    viewport = Viewport()
    viewport.set_model(model)
    viewport.set_objects((), ())
    assert viewport.grid_origin[2] < -2000
    assert viewport.grid_origin[0] < 0
    assert viewport.model.raw_data == model.raw_data
    viewport._timer.stop()
    viewport.deleteLater()
    app.processEvents()


def test_work_plane_click_does_not_edit_objects_or_geometry_and_escape_cancels():
    app = QApplication.instance() or QApplication([])
    rom = RomImage.from_file(Path('Diddy Kong Racing (USA) (En,Fr) (Rev 1).z64'))
    model = LevelModel.from_bytes(rom.read_asset(AssetType.LEVEL_MODELS, 5, decompress=True))
    viewport = Viewport()
    viewport.resize(800, 600)
    viewport.set_model(model)
    viewport.set_view('Top')
    viewport.camera.target = np.array((-1540., 51., -7607.), np.float32)
    viewport.camera.position = viewport.camera.target-viewport.camera.forward*1000
    viewport.camera.ortho_height = 400
    viewport.selected_object = 0
    viewport.object_move_mode = True
    nudges = []
    viewport.object_nudged.connect(lambda *args: nudges.append(args))
    viewport.begin_grid_placement()
    QTest.keyClick(viewport, Qt.Key.Key_Right)
    assert not nudges
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    assert not viewport.grid_pick and not viewport.grid_follow_selection
    assert viewport.show_grid
    np.testing.assert_allclose(viewport.grid_origin[[0, 2]], [-1540., -7607.], atol=.1)
    assert viewport.model.raw_data == model.raw_data
    point = viewport.grid_origin.copy()
    viewport.begin_grid_placement()
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    assert not viewport.grid_pick
    np.testing.assert_array_equal(viewport.grid_origin, point)
    viewport._timer.stop()
    viewport.deleteLater()
    app.processEvents()
