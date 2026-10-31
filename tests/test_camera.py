"""Camera geometry invariants; no QApplication or GL context is initialized."""

import numpy as np

from src.renderer.camera import Camera


def scene_camera(aspect: float = 1.0) -> Camera:
    camera = Camera()
    camera.fit_bounds(np.array([-20, 0, -20], dtype=np.float32),
                      np.array([20, 10, 20], dtype=np.float32), aspect)
    return camera


def test_view_places_eye_at_origin_and_target_in_front() -> None:
    camera = scene_camera()
    eye = camera.view_matrix() @ np.append(camera.position, 1.0)
    np.testing.assert_allclose(eye, [0, 0, 0, 1], atol=1e-5)
    target = camera.view_matrix() @ np.append(camera.target, 1.0)
    np.testing.assert_allclose(target[:2], [0, 0], atol=1e-5)
    assert target[2] < 0


def test_diagonal_speed_and_time_step_are_consistent() -> None:
    straight, diagonal, stepped = scene_camera(), scene_camera(), scene_camera()
    start = straight.position.copy()
    straight.move(1, 0, 0, 1.0, False)
    diagonal.move(1, 1, 1, 1.0, False)
    for _ in range(60):
        stepped.move(1, 0, 0, 1.0 / 60.0, False)
    assert np.isclose(np.linalg.norm(straight.position - start), np.linalg.norm(diagonal.position - start))
    np.testing.assert_allclose(straight.position, stepped.position, atol=1e-4)


def test_fit_keeps_all_corners_in_frustum_in_portrait_and_landscape() -> None:
    for aspect in (0.3, 1.0, 2.5):
        camera = scene_camera(aspect)
        transform = camera.projection_matrix(aspect) @ camera.view_matrix()
        for x in (-20, 20):
            for y in (0, 10):
                for z in (-20, 20):
                    clip = transform @ np.array([x, y, z, 1], dtype=np.float32)
                    assert clip[3] > 0
                    assert np.all(np.abs(clip[:3] / clip[3]) < 1.0)


def test_orbit_preserves_target_radius_and_zoom_has_limits() -> None:
    camera = scene_camera()
    target = camera.target.copy()
    distance = np.linalg.norm(camera.position - target)
    camera.look(300, -100, orbit=True)
    np.testing.assert_array_equal(camera.target, target)
    assert np.isclose(np.linalg.norm(camera.position - target), distance)
    camera.look(0, 100000)
    assert camera.pitch == -89
    camera.zoom(1000)
    assert camera.fov == 20
    camera.zoom(-1000)
    assert camera.fov == 100


def test_fitting_object_or_scene_preserves_movement_speed() -> None:
    camera = Camera(speed=2375.0)
    for radius in (10000.0, 30.0, 1.0, 10000.0):
        center = np.array([2000, 100, -7000], dtype=np.float32)
        camera.fit_bounds(center-radius, center+radius, 1.5)
        assert camera.speed == 2375.0
        start = camera.position.copy()
        camera.move(1, 0, 0, 0.25, False)
        assert np.isclose(np.linalg.norm(camera.position-start), 2375.0 * 0.25)


def test_cinematic_camera_basis_includes_roll():
    from src.core.cinematics import CinematicPose, camera_view
    pose = CinematicPose((100, 50, 200), (.3, .4, .8), 1, 0, 0, 0, 'Test')
    view = camera_view(pose)
    camera = Camera(view_override=view)
    np.testing.assert_array_equal(camera.forward, -view[2, :3])
    np.testing.assert_array_equal(camera.right, view[0, :3])
    camera.view_override = None
    assert not np.allclose(camera.right, view[0, :3])
