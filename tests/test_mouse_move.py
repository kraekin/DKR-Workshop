"""Headless drag projection, alpha picking and single-record move transactions."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.core.editing import EditError, EditSession
from src.core.rom import RomImage
from src.core.textures import SpriteInstance, SpriteTile, TextureFrame, TextureHeader
from src.renderer.camera import (Camera, TranslationDrag, project_point, translation_length,
                                 pick_translation_handle, ray_plane_point, ray_sprite_distance)


@pytest.fixture
def session() -> EditSession:
    paths = list(Path(__file__).resolve().parents[1].glob("*.z64"))
    if not paths: pytest.skip("Local USA Rev 1 ROM not present")
    return EditSession(RomImage.from_file(paths[0]))


def camera_at(position: np.ndarray) -> Camera:
    camera = Camera()
    camera.fit_bounds(position-100, position+100, 800/600)
    return camera


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_axis_drag_preserves_other_coordinates_and_pointer_offset(axis: int) -> None:
    position = np.array([13, 27, -45], np.float32)
    camera = camera_at(position)
    matrix = camera.projection_matrix(800/600) @ camera.view_matrix()
    length = translation_length(camera, position, 600)
    press = position.copy(); press[axis] += length*.7
    first = project_point(press, matrix, 800, 600)
    assert pick_translation_handle(*first, position, length, matrix, 800, 600) == axis
    drag = TranslationDrag.begin(position, axis, *first, camera.forward, matrix, 800, 600)
    assert drag is not None and drag.position_at(*first) == tuple(position)
    target = press.copy(); target[axis] += 33
    end = project_point(target, matrix, 800, 600)
    expected = position.astype(int); expected[axis] += 33
    assert drag.position_at(*end) == tuple(expected)
    expected[axis] = int(position[axis])+32
    assert drag.position_at(*end, step=16) == tuple(expected)


def test_view_plane_drag_tracks_screen_motion_and_short_bounds() -> None:
    position = np.array([20, 40, -15], np.float32)
    camera = camera_at(position)
    matrix = camera.projection_matrix(800/600) @ camera.view_matrix()
    drag = TranslationDrag.begin(position, None, 400, 300, camera.forward, matrix, 800, 600)
    delta = camera.right*31+camera.view_matrix()[1, :3]*22
    end = project_point(position+delta, matrix, 800, 600)
    assert drag.position_at(*end) == tuple(np.rint(position+delta).astype(int))
    for start, amount, expected in ((32760, 100, 32767), (-32760, -100, -32768)):
        position = np.array([start, 0, 0], np.float32)
        camera = camera_at(position)
        matrix = camera.projection_matrix(800/600) @ camera.view_matrix()
        first = project_point(position, matrix, 800, 600)
        drag = TranslationDrag.begin(position, 0, *first, camera.forward, matrix, 800, 600)
        end = project_point(position+np.array([amount, 0, 0]), matrix, 800, 600)
        assert drag.position_at(*end)[0] == expected


def test_handle_size_uses_logical_pixels_and_center_hit_wins() -> None:
    position = np.zeros(3, np.float32)
    camera = camera_at(position)
    matrix = camera.projection_matrix(800/600) @ camera.view_matrix()
    length = translation_length(camera, position, 600)
    center = project_point(position, matrix, 800, 600)
    endpoint = project_point(position+camera.right*length, matrix, 800, 600)
    assert np.isclose(np.linalg.norm(np.array(endpoint)-center), 90, atol=.001)
    assert pick_translation_handle(*center, position, length, matrix, 800, 600) == -1
    assert pick_translation_handle(1, 1, position, length, matrix, 800, 600) is None
    assert translation_length(camera, camera.position-camera.forward, 600) is None
    assert translation_length(camera, position, 0) is None
    assert project_point(camera.position-camera.forward, matrix, 800, 600) is None


def test_degenerate_rays_do_not_produce_unstable_positions() -> None:
    zero = np.zeros(3)
    assert ray_plane_point(zero, np.array([1,0,0]), zero, np.array([0,1,0])) is None
    assert ray_plane_point(zero, np.array([0,1,0]), np.array([0,-1,0]), np.array([0,1,0])) is None
    camera = Camera(position=np.array([0,0,10],np.float32), yaw=-90, pitch=0)
    matrix = camera.projection_matrix(800/600) @ camera.view_matrix()
    assert TranslationDrag.begin(zero, 2, 400, 300, camera.forward, matrix, 800, 600) is None
    with pytest.raises(ValueError):
        TranslationDrag.begin(zero, 9, 400, 300, camera.forward, matrix, 800, 600)
    drag = TranslationDrag.begin(zero, None, 400, 300, camera.forward, matrix, 800, 600)
    with pytest.raises(ValueError): drag.position_at(400, 300, step=0)


def test_many_previews_commit_one_undo_and_preserve_parameters(session: EditSession) -> None:
    obj = session.current_map(5).objects[0]
    session.begin_move(obj.key)
    assert session.moving_key == obj.key
    for value in range(10):
        session.preview_move((100+value, 200+value, 300+value))
    assert not session.can_undo
    assert session.object(obj.key).raw_data[8:] == obj.raw_data[8:]
    assert session.object(obj.key).raw_data[:2] == obj.raw_data[:2]
    assert session.finish_move()
    assert session.moving_key is None and session.undo_label == "Drag object"
    assert session.undo() == obj.key and session.object(obj.key) == obj
    assert not session.can_undo
    session.redo()
    assert session.object(obj.key).position == (109,209,309)


def test_cancel_and_noop_preserve_saved_state_and_redo_branch(session: EditSession, tmp_path: Path) -> None:
    obj = session.current_map(5).objects[0]
    session.set_position(obj.key, (1,2,3))
    session.undo()
    session.save_project(tmp_path / "baseline.dkrproj")
    session.begin_move(obj.key)
    session.preview_move((20,30,40))
    assert session.dirty
    assert not session.finish_move(cancel=True)
    assert session.object(obj.key) == obj and session.can_redo and not session.dirty
    session.begin_move(obj.key)
    session.preview_move((20,30,40))
    session.preview_move(obj.position)
    assert not session.finish_move() and session.can_redo and not session.dirty
    session.begin_move(obj.key)
    assert not session.finish_move() and session.can_redo
    session.redo()
    assert session.object(obj.key).position == (1,2,3)
    session.undo()
    session.begin_move(obj.key)
    session.preview_move((9,8,7))
    assert session.finish_move() and not session.can_redo
    session.undo()
    assert session.object(obj.key) == obj


def test_transaction_guards_other_edits_saves_and_bad_positions(session: EditSession, tmp_path: Path) -> None:
    obj = session.current_map(5).objects[0]
    session.begin_move(obj.key)
    with pytest.raises(EditError): session.begin_move(obj.key)
    with pytest.raises(EditError): session.set_position(obj.key, (1,2,3))
    with pytest.raises(EditError): session.undo()
    with pytest.raises(EditError): session.redo()
    with pytest.raises(EditError): session.save_project(tmp_path / "pending.dkrproj")
    with pytest.raises(EditError): session.save_rom(tmp_path / "pending.z64")
    with pytest.raises(EditError): session.preview_move((32768,0,0))
    assert session.object(obj.key) == obj
    session.finish_move(cancel=True)
    with pytest.raises(EditError): session.preview_move((1,2,3))


def sprite(alpha: int = 255, hole: bool = False) -> SpriteInstance:
    raw = bytearray(32); raw[:3] = bytes((8,8,16)); raw[18] = 1
    pixels = np.full((8,8,4),255,np.uint8); pixels[:,:,3] = alpha
    if hole: pixels[2:6,2:6,3] = 0
    tile = SpriteTile(0, TextureFrame(TextureHeader.from_bytes(bytes(raw)),pixels), -4,4,4,-4)
    return SpriteInstance(0,0,(0,0,0),1,(tile,))


def test_sprite_picking_respects_transparent_holes_and_cutoff() -> None:
    camera = Camera(position=np.array([0,0,10],np.float32), yaw=-90, pitch=0)
    ray = np.array([0,0,-1],np.float32)
    view = camera.view_matrix()
    assert ray_sprite_distance(camera.position,ray,sprite(hole=True),view) is None
    assert np.isclose(ray_sprite_distance(np.array([3,0,10]),ray,sprite(hole=True),view),10)
    assert ray_sprite_distance(camera.position,ray,sprite(alpha=24),view) is None
    assert np.isclose(ray_sprite_distance(camera.position,ray,sprite(alpha=26),view),10)
    assert ray_sprite_distance(camera.position,-ray,sprite(),view) is None
