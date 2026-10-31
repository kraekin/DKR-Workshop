"""Paired branch provenance, protected bytes, bounded lanes and draft lifecycle."""
from __future__ import annotations

from pathlib import Path
import pytest

from src.core.editing import EditSession
from src.core.rom import RomImage, AssetType
from src.core.course import level_objects, plan_objects
from src.core.route_authoring import AlternatePoint, LaneOptions, build_route_plan
from src.core.routes import LATERAL, HEIGHT, BEHAVIOR


@pytest.fixture(scope="module")
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob("*.z64")))


def main_points(session: EditSession) -> list:
    return sorted((o for o in level_objects(session, 5) if o.definition.behavior_id == 13
                   and o.value("vehicleType") == 0 and not o.value("isAltCheckpoint")), key=lambda o: o.value("index"))


def test_alternate_clones_paired_source_and_round_trips_project(rom: RomImage, tmp_path: Path) -> None:
    s = EditSession(rom)
    main = main_points(s)[1]
    position = (main.position[0] + 50, main.position[1] + 8, main.position[2])
    point = AlternatePoint(int(main.value("index")), position)
    plan = build_route_plan(s, 5, 0, s.level_header(5).object_map_id, (point,), align_alternates=False)
    assert not s.dirty
    alternate = next(o for o in plan_objects(s, plan) if o.definition.behavior_id == 13 and o.value("isAltCheckpoint"))
    assert alternate.position == position and alternate.raw_data[:2] == main.raw_data[:2]
    assert alternate.raw_data[8:23] == main.raw_data[8:23]
    assert alternate.raw_data[24:] == main.raw_data[24:]
    assert s.apply_course_plan(plan)
    s.save_project(tmp_path / "route.dkrproj")
    loaded = EditSession.load_project(tmp_path / "route.dkrproj")
    assert loaded.object(alternate.key).raw_data == alternate.raw_data
    s.undo()
    assert all(s._map_state(state.map_id) == state for state in plan.before)
    s.redo()
    assert s.object(alternate.key).position == position


def test_lane_generation_preserves_behavior_height_and_nonroute_bytes(rom: RomImage) -> None:
    s = EditSession(rom)
    original = level_objects(s, 5)
    alt = tuple(AlternatePoint(int(o.value("index")), o.position, o.key) for o in original
                if o.definition.behavior_id == 13 and o.value("vehicleType") == 0 and o.value("isAltCheckpoint"))
    plan = build_route_plan(s, 5, 0, s.level_header(5).object_map_id, alt, LaneOptions(60), align_alternates=False)
    after = {o.key: o for o in plan_objects(s, plan)}
    for obj in original:
        updated = after[obj.key]
        if obj.definition.behavior_id == 13 and obj.value("vehicleType") == 0:
            assert [updated.value(f) for f in LATERAL] == sorted(updated.value(f) for f in LATERAL)
            assert [updated.value(f) for f in HEIGHT + BEHAVIOR] == [obj.value(f) for f in HEIGHT + BEHAVIOR]
            assert updated.raw_data[:11] == obj.raw_data[:11]
            assert updated.raw_data[15:] == obj.raw_data[15:]
        else:
            assert updated.raw_data == obj.raw_data
    assert s.apply_course_plan(plan)
    s.undo()
    assert not s.dirty


@pytest.mark.parametrize("kind", ["duplicate", "orphan", "range", "provenance"])
def test_invalid_branch_or_lane_plan_is_atomic(rom: RomImage, kind: str) -> None:
    s = EditSession(rom)
    obj = main_points(s)[0]
    point = AlternatePoint(int(obj.value("index")), obj.position)
    points, lanes = (point,), None
    if kind == "duplicate": points = (point, point)
    if kind == "orphan": points = (AlternatePoint(254, obj.position),)
    if kind == "range": lanes = LaneOptions(10000)
    if kind == "provenance": points = (AlternatePoint(point.index, obj.position, obj.key),)
    with pytest.raises(ValueError):
        build_route_plan(s, 5, 0, s.level_header(5).object_map_id, points, lanes)
    assert not s.dirty and not s.can_undo


def test_route_dialog_branch_history_and_cancel(rom: RomImage) -> None:
    from PySide6.QtWidgets import QApplication
    from src.ui.route_authoring import RouteAuthoringDialog
    app = QApplication.instance() or QApplication([])
    s = EditSession(rom)
    dialog = RouteAuthoringDialog(s, 5)
    dialog.refresh_preview()
    assert dialog.plan is not None, dialog.report.toPlainText()
    count = dialog.rows.topLevelItemCount()
    dialog.add_branch()
    assert dialog.rows.topLevelItemCount() == count + 1
    dialog._travel(-1)
    assert dialog.rows.topLevelItemCount() == count
    dialog._travel(1)
    dialog.refresh_preview()
    assert dialog.plan is not None and dialog.apply.isEnabled(), dialog.report.toPlainText()
    dialog.reject()
    assert not s.dirty
    dialog.deleteLater()
    app.processEvents()


def test_retained_alternate_draft_is_exact_noop(rom: RomImage) -> None:
    s = EditSession(rom)
    for level in s._catalog.levels:
        objects = level_objects(s, level.index)
        for group in sorted({int(o.value("vehicleType")) for o in objects if o.definition.behavior_id == 13}):
            points = tuple(AlternatePoint(int(o.value("index")), o.position, o.key) for o in objects
                           if o.definition.behavior_id == 13 and o.value("vehicleType") == group and o.value("isAltCheckpoint"))
            main = [o for o in objects if o.definition.behavior_id == 13 and o.value("vehicleType") == group and not o.value("isAltCheckpoint")]
            if points and len(main) >= 4:
                plan = build_route_plan(s, level.index, group, level.header.object_map_id, points, align_alternates=False)
                assert plan.before == plan.after
                assert not s.apply_course_plan(plan) and not s.dirty
                return
    pytest.fail("Expected a stock course with paired alternates")


@pytest.mark.parametrize("cancel", [False, True])
def test_branch_drag_records_once_or_cancels(rom: RomImage, cancel: bool) -> None:
    from PySide6.QtWidgets import QApplication
    from src.ui.route_authoring import RouteAuthoringDialog
    app = QApplication.instance() or QApplication([])
    s = EditSession(rom)
    dialog = RouteAuthoringDialog(s, 5)
    dialog.add_branch()
    dialog.refresh_preview()
    before, cursor = dialog._state(), dialog._cursor
    index = next(i for i, obj in enumerate(dialog.display) if obj.value("isAltCheckpoint"))
    start = dialog.display[index].position
    dialog._begin_drag(index)
    dialog._drag((start[0] + 40, start[1], start[2]))
    dialog._drag((start[0] + 80, start[1], start[2]))
    dialog._end_drag(cancel)
    if cancel:
        assert dialog._state() == before and dialog._cursor == cursor
    else:
        assert dialog._cursor == cursor + 1
        dialog._travel(-1)
        assert dialog._state() == before
    dialog.reject()
    assert not s.dirty and not dialog.timer.isActive()
    dialog.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("has_floor", [False, True])
def test_road_fitted_lane_heights_and_missing_floor_refusal(rom: RomImage, monkeypatch: pytest.MonkeyPatch, has_floor: bool) -> None:
    import numpy as np
    from src.core.course import CourseOptions, CoursePoint, build_course_plan
    from src.core.placement import TerrainSurface
    from src.core.routes import lane_point
    s = EditSession(rom)
    points = tuple(CoursePoint((x, round(.05 * x) + 32, z))
                   for x, z in ((-1000, -1000), (1000, -1000), (1000, 1000), (-1000, 1000)))
    base = build_course_plan(s, 5, points, CourseOptions(0, s.level_header(5).object_map_id,
        align_headings=True, reset_lanes=True, lane_half_width=80, remove_alternates=True))
    s.apply_course_plan(base)
    extent = 5000 if has_floor else 100
    vertices = np.array(((-extent, -.05 * extent, -extent), (extent, .05 * extent, -extent),
                         (extent, .05 * extent, extent), (-extent, -.05 * extent, extent)), float)
    terrain = TerrainSurface(vertices[np.array(((0, 1, 2), (0, 2, 3)))])
    monkeypatch.setattr('src.core.route_authoring.TerrainSurface.from_model', lambda *_: terrain)
    signature = s._signature()
    if not has_floor:
        with pytest.raises(ValueError, match="surface"):
            build_route_plan(s, 5, 0, s.level_header(5).object_map_id, (), LaneOptions(80, True))
    else:
        plan = build_route_plan(s, 5, 0, s.level_header(5).object_map_id, (), LaneOptions(80, True))
        for obj in plan_objects(s, plan):
            if obj.definition.behavior_id == 13 and obj.value('vehicleType') == 0:
                for lane in range(4):
                    x, y, _ = lane_point(obj, lane)
                    # Nearby-road placement rounds world Y, then the lane's
                    # signed offset at scale 2; allow both quantization steps.
                    assert abs(y - (.05 * x + 32)) <= 1.55
    assert s._signature() == signature
