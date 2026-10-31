"""Atomic existing-object groups, verified transforms, surfaces and orthographic math."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest

from src.core.editing import EditSession, EditError
from src.core.placement import (TerrainSurface, patch_entry, translated_entries, aligned_entries,
                                rotated_entries, scaled_entries, shared_parameter_entries,
                                rotation_axes, can_scale)
from src.core.rom import RomImage, AssetType, parse_asset_lut, LUT_START, LUT_END
from src.core.level_model import load_level_model
from src.renderer.camera import Camera, ScalarDrag, TranslationDrag, project_point, screen_ray, translation_length


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


def objects(session: EditSession, behavior: int, count: int = 1) -> tuple:
    result = tuple(obj for map_id in (5, 73) for obj in session.current_map(map_id).objects if obj.definition.behavior_id == behavior)
    assert len(result) >= count
    return result[:count]


def test_multimap_preview_commit_cancel_and_project_bytes(rom: RomImage, tmp_path: Path) -> None:
    session = EditSession(rom)
    selected = (session.object((5, 0)), session.object((73, 0)))
    before = {obj.key: obj.raw_data for obj in selected}
    session.begin_group(tuple(before), "Move selection")
    for dx in range(1, 25):
        session.preview_group(translated_entries(selected, (dx, 5, -7)))
    assert not session.can_undo and session.moving_key == selected[0].key
    assert session.finish_group() and session.undo_label == "Move selection"
    after = {obj.key: session.object(obj.key).raw_data for obj in selected}
    for obj in selected:
        assert after[obj.key][:2] == before[obj.key][:2] and after[obj.key][8:] == before[obj.key][8:]
    session.undo()
    assert not session.dirty and all(session.object(key).raw_data == value for key, value in before.items())
    session.redo()
    project = session.save_project(tmp_path / "group.dkrproj", 5)
    loaded = EditSession.load_project(project)
    assert all(loaded.object(key).raw_data == value for key, value in after.items())
    # In-memory ROM verification only; no gameplay/sample ROM is published.
    data = loaded.build_rom()
    rebuilt = RomImage(data, "z64", parse_asset_lut(data, LUT_START, LUT_END))
    for section in range(50):
        if section not in (20, 21):
            assert rebuilt.section(section) == rom.section(section)
    session.begin_group(tuple(before), "Cancelled")
    session.preview_group(translated_entries(tuple(session.object(key) for key in before), (99, 0, 0)))
    assert not session.finish_group(cancel=True) and not session.dirty
    assert all(session.object(key).raw_data == value for key, value in after.items())


def test_group_failures_noops_and_redo_are_atomic(rom: RomImage) -> None:
    session = EditSession(rom)
    selected = objects(session, 13, 2)
    entries = translated_entries(selected, (10, 0, 0))
    bad = bytearray(entries[selected[1].key]); bad[0] ^= 1
    entries[selected[1].key] = bytes(bad)
    with pytest.raises(EditError): session.apply_entries(entries, "Invalid")
    assert not session.dirty and not session.can_undo and not session.group_active
    session.apply_entries(translated_entries(selected, (10, 0, 0)), "Move")
    session.undo()
    assert session.can_redo
    assert not session.apply_entries({obj.key: obj.raw_data for obj in selected}, "No-op")
    assert session.can_redo
    session.begin_group(tuple(obj.key for obj in selected), "Preview")
    with pytest.raises(EditError): session.set_position(selected[0].key, (1, 2, 3))
    with pytest.raises(EditError): session.project_document()
    with pytest.raises(EditError): session.undo()
    with pytest.raises(EditError): session.preview_group({selected[0].key: selected[0].raw_data})
    session.finish_group(cancel=True)
    assert session.can_redo and not session.dirty


def test_common_translation_limit_preserves_spacing_and_alignment(rom: RomImage) -> None:
    s = EditSession(rom)
    first, second = objects(s, 13, 2)
    moved = (replace(first, position=(32760, -32760, 0)), replace(second, position=(32766, -32766, 100)))
    entries = translated_entries(moved, (500, -500, 2))
    import struct
    a, b = (struct.unpack_from(">3h", entries[obj.key], 2) for obj in moved)
    assert b == (32767, -32768, 102)
    assert tuple(y - x for x, y in zip(a, b)) == (6, -6, 100)
    entries = aligned_entries((first, second), 0)
    assert struct.unpack_from(">h", entries[second.key], 2)[0] == first.position[0]


def test_verified_rotation_scale_and_field_isolation(rom: RomImage) -> None:
    s = EditSession(rom)
    scenery = objects(s, 2)
    checkpoints = objects(s, 13, 2)
    controller = objects(s, 49)
    balloon = objects(s, 17)
    assert rotation_axes(controller) == (0, 1, 2)
    assert rotation_axes(scenery + checkpoints[:1]) == (1,)
    assert not rotation_axes(balloon) and not can_scale(checkpoints)
    assert can_scale(scenery + balloon)
    old = controller[0]
    s.apply_entries(rotated_entries(controller, 0, 90), "Pitch")
    assert (s.object(old.key).value("x_rotation") - old.value("x_rotation")) % 256 == 64
    assert s.object(old.key).position == old.position
    assert s.object(old.key).raw_data[:8] == old.raw_data[:8]
    s.undo()
    s.apply_entries(rotated_entries(checkpoints, 1, 90), "Yaw")
    assert (s.object(checkpoints[0].key).value("angleY") - checkpoints[0].value("angleY")) % 256 == 16
    s.undo()
    old = balloon[0]
    s.apply_entries(scaled_entries(balloon, .5), "Scale")
    assert s.object(old.key).value("scale") == round(max(old.value("scale"), 10) * .5)
    for i, (a, b) in enumerate(zip(old.raw_data, s.object(old.key).raw_data)):
        assert a == b or i == 10
    with pytest.raises(ValueError): scaled_entries(checkpoints, 2)
    with pytest.raises(ValueError): rotated_entries(balloon, 1, 10)
    with pytest.raises(ValueError): scaled_entries(balloon, 100)


def test_shared_fields_reject_mixed_schemas_before_any_write(rom: RomImage) -> None:
    s = EditSession(rom)
    points = objects(s, 13, 2)
    s.apply_entries(shared_parameter_entries(points, "unk19", 4), "HUD cues")
    assert all(s.object(obj.key).value("unk19") == 4 for obj in points)
    s.undo()
    assert not s.dirty
    with pytest.raises(ValueError): shared_parameter_entries(points + objects(s, 17), "unk19", 4)
    with pytest.raises(ValueError): patch_entry(points[0], parameters={"unkB": 128})
    assert not s.dirty


def test_surface_nearest_hit_drop_offset_and_misses() -> None:
    triangles = np.array([[[0, y, 0], [10, y, 0], [0, y, 10]] for y in (0, 5)], np.float64)
    surface = TerrainSurface(triangles)
    assert surface.surface_y((2, 4, 2), drop=True) == 0
    assert surface.surface_y((2, 10, 2), drop=True) == 5
    assert surface.surface_y((2, 4, 2), drop=False, offset=3) == 8
    assert surface.surface_y((2, -1, 2), drop=True) is None
    assert surface.surface_y((20, 10, 20), drop=False) is None
    assert surface.raycast(np.array([2, 10, 2]), np.array([1, 0, 0])) is None
    with pytest.raises(ValueError): surface.raycast(np.zeros(3), np.zeros(3))
    with pytest.raises(ValueError): surface.raycast(np.zeros(3), np.array([np.nan, 0, 1]))


def test_real_track_surface_is_immutable_and_hits(rom: RomImage) -> None:
    model = load_level_model(rom, 5)
    surface = TerrainSurface.from_model(model)
    assert not surface.triangles.flags.writeable and len(surface.triangles) > 1000
    for triangle in surface.triangles:
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        if abs(normal[1]) > 1:
            p = triangle.mean(0)
            assert surface.raycast(np.array([p[0], model.bounds.maximum[1] + 1, p[2]]), np.array([0, -1, 0])) is not None
            break


@pytest.mark.parametrize("name", ["Top", "Front", "Right"])
def test_orthographic_projection_parallel_rays_handles_and_speed(name: str) -> None:
    camera = Camera(speed=123)
    camera.fit_bounds(np.full(3, -100), np.full(3, 100), 800 / 600)
    camera.set_view(name)
    camera.fit_bounds(np.full(3, -100), np.full(3, 100), 800 / 600)
    assert camera.speed == 123 and np.isfinite(camera.view_matrix()).all()
    matrix = camera.projection_matrix(800 / 600) @ camera.view_matrix()
    _, a = screen_ray(200, 300, 800, 600, matrix)
    _, b = screen_ray(600, 300, 800, 600, matrix)
    assert np.allclose(a, b)
    center = project_point(np.zeros(3), matrix, 800, 600)
    length = translation_length(camera, np.zeros(3), 600)
    endpoint = project_point(camera.right * length, matrix, 800, 600)
    assert np.isclose(np.linalg.norm(np.array(endpoint) - center), 90, atol=.001)
    drag = TranslationDrag.begin(np.zeros(3), None, *center, camera.forward, matrix, 800, 600)
    assert drag is not None
    old = camera.ortho_height
    camera.zoom(1)
    assert camera.ortho_height < old and camera.speed == 123


def test_rotation_and_scale_pointer_math() -> None:
    camera = Camera()
    camera.fit_bounds(np.full(3, -100), np.full(3, 100), 800 / 600)
    camera.set_view("Top")
    matrix = camera.projection_matrix(800 / 600) @ camera.view_matrix()
    first = project_point(np.array([50, 0, 0]), matrix, 800, 600)
    last = project_point(np.array([0, 0, -50]), matrix, 800, 600)
    drag = ScalarDrag.begin("Rotate", 1, np.zeros(3), *first, matrix, 800, 600)
    assert np.isclose(drag.value_at(*last), 90, atol=.001)
    assert drag.value_at(*last, snap=True) == 90
    scale = ScalarDrag.begin("Scale", None, np.zeros(3), 400, 300, matrix, 800, 600)
    assert scale.value_at(520, 300) == 2
