"""Screen-space panning and checkpoint travel arrows, without Qt/GL contexts."""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.core.course import forward
from src.core.objects import LevelObject, ObjectDefinition, ObjectParameter
from src.renderer.camera import Camera, project_point
from src.renderer.gizmos import _marker


@pytest.mark.parametrize('view', ['Perspective', 'Top', 'Front', 'Right'])
@pytest.mark.parametrize('size', [(800, 600), (600, 800), (1600, 1200)])
def test_pan_grabs_scene_in_logical_pixels_and_preserves_camera_settings(view: str, size: tuple[int, int]) -> None:
    width, height = size
    camera = Camera(speed=2875.)
    camera.fit_bounds(np.array([-500, -100, -1000]), np.array([1200, 400, 600]), width/height)
    camera.set_view(view)
    if view == 'Perspective':
        camera.look(35, -70)
        camera.zoom(4)
    point = camera.target.copy()
    matrix = camera.projection_matrix(width/height)@camera.view_matrix()
    before = np.asarray(project_point(point, matrix, width, height))
    position, target = camera.position.copy(), camera.target.copy()
    settings = camera.yaw, camera.pitch, camera.fov, camera.speed, camera.ortho_height, camera.near, camera.far
    camera.pan(93.5, -47.25, height)
    matrix = camera.projection_matrix(width/height)@camera.view_matrix()
    after = np.asarray(project_point(point, matrix, width, height))
    np.testing.assert_allclose(after-before, (93.5, -47.25), atol=.001)
    np.testing.assert_allclose(camera.target-camera.position, target-position, atol=.001)
    assert settings == (camera.yaw, camera.pitch, camera.fov, camera.speed, camera.ortho_height, camera.near, camera.far)
    camera.pan(-93.5, 47.25, height)
    np.testing.assert_allclose(camera.position, position, atol=.001)
    np.testing.assert_allclose(camera.target, target, atol=.001)


def test_pan_is_independent_of_movement_speed_and_drag_subdivision() -> None:
    a, b = Camera(speed=1), Camera(speed=99999)
    for camera in (a, b):
        camera.fit_bounds(np.full(3, -500.), np.full(3, 500.))
    a.pan(100, 50, 600)
    for _ in range(10):
        b.pan(10, 5, 600)
    np.testing.assert_allclose(a.position, b.position, atol=.002)
    np.testing.assert_allclose(a.target, b.target, atol=.002)


@pytest.mark.parametrize('delta', [(1, 2, 0), (1, 2, -1), (float('nan'), 2, 600), (1, float('inf'), 600)])
def test_invalid_pan_input_is_inert(delta: tuple[float, float, float]) -> None:
    camera = Camera()
    before = camera.position.copy(), camera.target.copy()
    with pytest.raises(ValueError):
        camera.pan(*delta)
    np.testing.assert_array_equal(camera.position, before[0])
    np.testing.assert_array_equal(camera.target, before[1])


@pytest.mark.parametrize('behavior', [11, 13, 93])
@pytest.mark.parametrize('yaw', [0, 8, 16, 32, 48, 63])
def test_checkpoint_start_arrows_show_travel_and_other_arrows_keep_orientation(behavior: int, yaw: int) -> None:
    definition = ObjectDefinition(0, 'Synthetic heading', behavior, 1.)
    obj = LevelObject(0, 0, 16, 0, definition, (100, 200, -300), 28, False,
                      (ObjectParameter('angleY', 10, 'B', yaw),), b'unchanged')
    before = obj.raw_data, obj.parameters
    radius = 37.
    vertices = _marker(obj, radius)
    tip = (vertices[-5, :3]-np.asarray(obj.position))/(2.5*radius)
    expected = forward(yaw) if behavior in (11, 13) else (math.sin(obj.yaw), 0, math.cos(obj.yaw))
    np.testing.assert_allclose(tip, expected, atol=1e-6)
    assert before == (obj.raw_data, obj.parameters)
