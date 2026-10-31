"""New objects start on visible ground ahead of the camera, never its stale target."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from src.core.placement import TerrainSurface
from src.core.rom import RomImage
from src.renderer.camera import Camera, ground_placement, project_point
from src.ui.main_window import MainWindow


def plane(y: float = 0., extent: float = 2000.) -> np.ndarray:
    return np.array([[[-extent, y, -extent], [extent, y, -extent], [extent, y, extent]],
                     [[-extent, y, -extent], [extent, y, extent], [-extent, y, extent]]], np.float64)


def camera(pitch: float = -30.) -> Camera:
    return Camera(position=np.array((0., 100., 200.), np.float32),
                  target=np.array((12000., -20000., 17000.), np.float32), yaw=-90., pitch=pitch)


def test_centre_hit_ignores_stale_navigation_target_and_keeps_camera() -> None:
    cam = camera()
    before = cam.position.copy(), cam.target.copy(), cam.yaw, cam.pitch, cam.speed
    assert ground_placement(cam, TerrainSurface(plane()), 800, 600) == (0, 1, 27)
    np.testing.assert_array_equal(cam.position, before[0])
    np.testing.assert_array_equal(cam.target, before[1])
    assert (cam.yaw, cam.pitch, cam.speed) == before[2:]


def test_horizon_miss_uses_visible_ground_below_the_centre() -> None:
    cam = camera(0.)
    point = ground_placement(cam, TerrainSurface(plane()), 800, 600)
    assert point is not None and point[1] == 1 and point[2] < cam.position[2]
    pixel = project_point(np.asarray(point), cam.projection_matrix(800/600)@cam.view_matrix(), 800, 600)
    assert pixel is not None and abs(pixel[0]-400) < 1e-3 and 300 < pixel[1] < 600


@pytest.mark.parametrize('view', ('Top', 'Front', 'Right'))
def test_orthographic_ground_at_view_centre_depth(view: str) -> None:
    if view == 'Top':
        cam = Camera(position=np.array((0., 300., 0.), np.float32), target=np.zeros(3, np.float32),
                     yaw=-90., pitch=-90., view=view, ortho_height=400.)
    else:
        cam = Camera(position=np.array((0., 100., 500.) if view == 'Front' else (500., 100., 0.), np.float32),
                     target=np.array((0., 100., 0.), np.float32), yaw=-90. if view == 'Front' else 180.,
                     pitch=0., view=view, ortho_height=400.)
    # A roof beyond this view must not become the default placement height.
    terrain = TerrainSurface(np.concatenate((plane(), plane(800.))))
    assert ground_placement(cam, terrain, 800, 600) == (0, 1, 0)


def test_slope_rounding_resamples_integer_xz_above_the_ground() -> None:
    triangles = plane(extent=10.)
    triangles[..., 1] = triangles[..., 0]*.6+triangles[..., 2]*.2+.3
    surface = TerrainSurface(triangles)
    point = surface.grounded_position(np.array((.51, 10., .49)), np.array((0., -1., 0.)))
    assert point == (1, 2, 0)
    assert point[1] > point[0]*.6+point[2]*.2+.3


def test_selected_layer_does_not_jump_to_a_roof() -> None:
    surface = TerrainSurface(np.concatenate((plane(), plane(20.))))
    assert surface.grounded_position(np.array((0., 10., 10.)), np.array((0., -1., -1.))) == (0, 1, 0)


def test_walls_do_not_count_as_ground_or_allow_placement_through_them() -> None:
    wall = np.array([[[-2000, -1000, 100], [2000, -1000, 100], [2000, 1000, 100]],
                     [[-2000, -1000, 100], [2000, 1000, 100], [-2000, 1000, 100]]], np.float64)
    surface = TerrainSurface(np.concatenate((plane(), wall)))
    assert surface.grounded_position(np.array((0., 100., 200.)), np.array((0., -.5, -1.))) is None
    assert ground_placement(camera(0.), surface, 800, 600) is None


def test_no_ground_sky_invalid_rays_and_unrepresentable_positions() -> None:
    empty = TerrainSurface(np.empty((0, 3, 3)))
    assert ground_placement(camera(), empty, 800, 600) is None
    assert ground_placement(camera(85.), TerrainSurface(plane()), 800, 600) is None
    clipped = Camera(position=np.array((0., 200., 0.), np.float32), yaw=-90., pitch=-90., far=100.)
    assert ground_placement(clipped, TerrainSurface(plane()), 800, 600) is None
    too_low = Camera(position=np.array((0., .5, 0.), np.float32), yaw=-90., pitch=-90.)
    assert ground_placement(too_low, TerrainSurface(plane()), 800, 600) is None
    with pytest.raises(ValueError):
        ground_placement(camera(), empty, 0, 600)
    with pytest.raises(ValueError):
        empty.grounded_position(np.array((np.nan, 0, 0)), np.array((0., -1., 0.)))
    assert TerrainSurface(plane(extent=50000.)).grounded_position(
        np.array((32767.6, 100., 0.)), np.array((0., -1., 0.))) is None
    assert TerrainSurface(plane(32767.)).grounded_position(
        np.array((0., 32768., 0.)), np.array((0., -1., 0.))) is None


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    paths = list(Path(__file__).resolve().parents[1].glob('*.z64'))
    if not paths:
        pytest.skip('Local original Rev1 ROM absent')
    widget = MainWindow()
    assert widget.load_rom(paths[0], show_errors=False)
    widget.level_panel.select_level(5)
    yield widget
    widget.edit_session = None
    widget.viewport._timer.stop()
    widget.viewport.cleanup()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('accept', (False, True))
def test_add_dialog_default_selection_override_cancel_and_one_undo(window, monkeypatch, accept: bool) -> None:
    session = window.edit_session
    original = next(o for o in window.current_objects if o.definition.behavior_id == 2)
    index = window.current_objects.index(original)
    window._select_group((index,), index)
    window.viewport.camera = camera()
    cam = window.viewport.camera
    before = session._signature(), cam.position.copy(), cam.target.copy(), session._cursor
    monkeypatch.setattr(window, '_terrain', lambda: TerrainSurface(plane()))
    template = next(t for t in session.object_catalog if session.database.resolve(t.object_id).name == 'RubberTree')
    captured = []
    class Palette:
        DialogCode = QDialog.DialogCode
        def __init__(self, edit_session, level, position, parent):
            assert edit_session is session and level == 5
            captured.append(position)
            self.map = SimpleNamespace(currentData=lambda: session.level_header(5).object_map_id)
        def exec(self):
            return self.DialogCode.Accepted if accept else self.DialogCode.Rejected
        def template(self):
            return template
        def position(self):
            return (10, 25, 30)  # Explicit XYZ edits in the catalog must still win.
        def deleteLater(self):
            pass
    monkeypatch.setattr('src.ui.main_window.ObjectPalette', Palette)
    window._add_object()
    assert captured == [(0, 1, 27)] and captured[0] != original.position
    np.testing.assert_array_equal(cam.position, before[1])
    np.testing.assert_array_equal(cam.target, before[2])
    if accept:
        added = session.object(session.last_key)
        assert added.position == (10, 25, 30) and added.raw_data[8:] == template.raw(session)[8:]
        assert session._cursor == before[3]+1
        session.undo()
    assert session._signature() == before[0]


def test_no_ground_does_not_open_catalog_or_change_history(window, monkeypatch) -> None:
    session = window.edit_session
    before = session._signature(), session._cursor
    window.viewport.camera = camera(85.)
    monkeypatch.setattr(window, '_terrain', lambda: TerrainSurface(plane()))
    def unexpected(*args):
        raise AssertionError('No catalog should open without ground')
    monkeypatch.setattr('src.ui.main_window.ObjectPalette', unexpected)
    window._add_object()
    assert 'Aim at the track' in window.statusBar().currentMessage()
    assert (session._signature(), session._cursor) == before
