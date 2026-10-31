"""Editor axial scenery and camera-facing pickups: stable planes and alpha picking."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from src.core.textures import SpriteInstance, SpriteTile, TextureFrame, TextureHeader
from src.renderer.camera import Camera, billboard_axes, normalized, ray_sprite_distance
from src.renderer.track_mesh import SpriteMesh, SpriteDrawRange


def tree() -> SpriteInstance:
    raw = bytearray(32)
    raw[:3] = bytes((8, 8, 0))
    raw[18] = 1
    header = TextureHeader.from_bytes(bytes(raw))
    pixels = np.full((8, 8, 4), 255, np.uint8)
    pixels[2:4, 2:4, 3] = 0
    tile = SpriteTile(0, TextureFrame(header, pixels), -4., 4., 8., 0.)
    return SpriteInstance(0, 0, (20., 3., -7.), 4., (tile,), upright=True)


@pytest.mark.parametrize('yaw,pitch', [(-110., -27.), (-110., -8.), (30., 40.), (170., -80.)])
def test_scenery_card_does_not_tilt_into_wall_when_view_rotates(yaw: float, pitch: float) -> None:
    camera = Camera(position=np.array([-3575., 804.4, -2529.7], np.float32), yaw=yaw, pitch=pitch)
    center = np.array([-4026., 303., -3409.], np.float32)
    right, up = billboard_axes(camera.view_matrix(), camera.position, center, upright=True)
    # Doorway cliff behind this original tree: canopy remains above its base,
    # rather than shifting back into the cliff as the camera tilts downward.
    np.testing.assert_array_equal(up, [0., 1., 0.])
    np.testing.assert_array_equal(center+up*348, [-4026., 651., -3409.])
    assert np.isclose(np.linalg.norm(right), 1.) and right[1] == 0
    assert np.dot(np.cross(right, up), camera.position-center) > 0
    expected, _ = billboard_axes(Camera().view_matrix(), camera.position, center, upright=True)
    np.testing.assert_array_equal(right, expected)


@pytest.mark.parametrize('view', ['Perspective', 'Top', 'Front', 'Right'])
def test_regular_billboards_and_orthographic_fallback_retain_screen_basis(view: str) -> None:
    camera = Camera()
    camera.set_view(view)
    matrix = camera.view_matrix()
    right, up = billboard_axes(matrix, camera.position, np.zeros(3), upright=False)
    np.testing.assert_array_equal(right, matrix[0, :3])
    np.testing.assert_array_equal(up, matrix[1, :3])


@pytest.mark.parametrize('pitch', [-90., -50., 0., 80.])
def test_eye_above_anchor_has_a_finite_upright_fallback(pitch: float) -> None:
    camera = Camera(position=np.array([0., 100., 0.]), pitch=pitch)
    right, up = billboard_axes(camera.view_matrix(), camera.position, np.zeros(3), upright=True)
    assert np.isfinite(right).all() and np.isclose(np.linalg.norm(right), 1.)
    assert np.dot(right, up) == 0


@pytest.mark.parametrize('upright', [True, False])
def test_picking_matches_rendered_card_and_transparent_pixels(upright: bool) -> None:
    sprite = tree()
    camera = Camera(position=np.array([0., 40., 100.], np.float32), yaw=-70., pitch=-45.)
    view = camera.view_matrix()
    center = np.asarray(sprite.position)
    right, up = billboard_axes(view, camera.position, center, upright=upright)
    for x, y, visible in ((2., 2., True), (-1.1, 4.9, False), (5., 2., False)):
        point = center+sprite.scale*(x*right+y*up)
        direction = normalized(point-camera.position)
        origin = camera.position+direction*.1
        hit = ray_sprite_distance(origin, direction, sprite, view,
                                  camera_position=camera.position, upright_sceneries=upright)
        if visible:
            assert hit is not None and np.isclose(hit, np.linalg.norm(point-origin), atol=.001)
        else:
            assert hit is None
    assert sprite.upright and not replace(sprite, upright=False).upright


def test_translucent_upright_tiles_sort_by_their_displayed_centers() -> None:
    mesh = SpriteMesh.__new__(SpriteMesh)
    mesh.instances = ()
    mesh.ranges = [SpriteDrawRange(0,0,6,True,np.zeros(3,np.float32),upright=True)]
    mesh.vertices = np.zeros((6,7),np.float32)
    mesh.vertices[:,4] = 100.
    mesh.draw = lambda *args, **kwargs: None
    camera = Camera(position=np.array([0.,200.,500.],np.float32),pitch=-30.)
    view = camera.view_matrix()
    upright = mesh.transparent_draws(np.eye(4),view,camera.position,seconds=0.,hidden=frozenset())
    np.testing.assert_array_equal(upright[0].center,[0.,100.,0.])
    assert view[2,:3]@upright[0].center != view[2,:3]@mesh.ranges[0].center
    flat = mesh.transparent_draws(np.eye(4),view,camera.position,seconds=0.,hidden=frozenset(),upright_sceneries=False)
    np.testing.assert_array_equal(flat[0].center,mesh.ranges[0].center)
