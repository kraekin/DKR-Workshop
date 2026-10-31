"""One checkpoint/branch/lane/grid draft and one real project transaction."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pytest

from src.core.editing import EditSession
from src.core.rom import RomImage
from src.core.course import plan_objects, level_objects
from src.core.routes import LATERAL, HEIGHT
from src.ui.course_builder import CourseBuilder, CoursePoint


@pytest.fixture(scope='module')
def rom() -> RomImage:
    return RomImage.from_file(next(Path.cwd().glob('*.z64')))


@pytest.fixture
def builder(rom: RomImage):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    dialog = CourseBuilder(EditSession(rom), 5)
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def test_three_tabs_and_one_entry_point(builder: CourseBuilder) -> None:
    assert [builder.pages.tabText(i).replace('&&', '&') for i in range(builder.pages.count())] == ['Checkpoints & branches', 'AI lanes', 'Start grid']
    from src.ui.main_window import MainWindow
    assert not hasattr(MainWindow, '_show_route_authoring')
    assert not (Path(__file__).resolve().parents[1] / 'src/ui/route_authoring.py').exists()


def test_branch_pair_survives_reverse_main_delete_and_draft_history(builder: CourseBuilder) -> None:
    d = builder
    d.branch_first.setCurrentIndex(2)
    d.branch_last.setCurrentIndex(2)
    key = d._draft()[2].key
    d._add_branch()
    d._reverse()
    d._refresh_live()
    assert d._live_plan is not None, d.message.text()
    row = next(i for i, p in enumerate(d._draft()) if p.key == key)
    objects = plan_objects(d.session, d._live_plan)
    alt = next(o for o in objects if o.definition.behavior_id == 13 and o.value('isAltCheckpoint') and o.value('vehicleType') == d._group)
    assert alt.value('index') == row
    d.points.setCurrentItem(d.points.topLevelItem(row))
    d._remove()
    d._refresh_live()
    assert not d.branch_points.topLevelItemCount()
    d._undo()
    d._refresh_live()
    assert d.branch_points.topLevelItemCount() == 1
    assert d._branches[d._group][0].main == key
    assert not d.session.dirty


def test_lane_only_edit_preserves_main_indexes_and_previews_real_lanes(builder: CourseBuilder) -> None:
    d = builder
    before = {o.key: o for o in d.original_objects}
    d.reset_lanes.setChecked(True)
    d.lane_width.setValue(55)
    d.pages.setCurrentIndex(1)
    d._refresh_live()
    assert d._live_plan is not None, d.message.text()
    assert not d._route_requested(d._draft())
    for obj in d.preview_objects:
        if obj.definition.behavior_id == 13 and obj.value('vehicleType') == d._group:
            assert obj.value('index') == before[obj.key].value('index')
            assert [obj.value(f) for f in LATERAL] == sorted(obj.value(f) for f in LATERAL)
    assert any('AI lane' in path.name for path in d.viewport.paths)
    assert not d.session.dirty


def test_new_main_branch_lanes_and_grid_apply_as_one_transaction(builder: CourseBuilder) -> None:
    d = builder
    session = d.session
    original = tuple(session._map_state(m) for m in (5, 73))
    d._fresh()
    d.snap_points.setChecked(False)
    d.grid_drop.setChecked(False)
    d.all_vehicles.setChecked(True)
    d._show_rows(tuple(CoursePoint(p) for p in ((-2000, 100, -7000), (-1000, 100, -7000), (-1000, 100, -5000), (-2000, 100, -5000))))
    d._refresh_live()
    d.branch_first.setCurrentIndex(1)
    d.branch_last.setCurrentIndex(1)
    d._add_branch()
    d.pick.setCurrentIndex(5)
    d._surface_picked((-800., 68., -6800.))
    d.pick.setCurrentIndex(0)
    d.lane_width.setValue(60)
    d._loading = True
    for spin, value in zip(d.anchor, (-2000, 100, -7200)):
        spin.setValue(value)
    d._grid_placed = True
    d.edit_grid.setChecked(True)
    d._loading = False
    d.build_preview()
    assert d.plan is not None, d.message.text()
    assert not session.dirty and session._cursor == 0
    result = plan_objects(session, d.plan)
    for group in set(d.header.checkpoint_sets):
        checkpoints = [o for o in result if o.definition.behavior_id == 13 and o.value('vehicleType') == group]
        assert len(checkpoints) == 5
        alternate = next(o for o in checkpoints if o.value('isAltCheckpoint'))
        assert alternate.value('index') == 1 and alternate.position == (-800, 100, -6800)
    assert len([o for o in result if o.definition.behavior_id == 11]) == 8
    assert session.apply_course_plan(d.plan)
    assert session._cursor == 1
    session.undo()
    assert tuple(session._map_state(m) for m in (5, 73)) == original and not session.dirty
    session.redo()
    assert session.dirty


def test_main_and_branch_changes_share_undo_and_cancellation(builder: CourseBuilder) -> None:
    d = builder
    initial = d._state()
    d._add_branch()
    d.lane_width.setValue(54)
    d.reset_lanes.setChecked(True)
    d._flush_history()
    d._undo()
    assert not d.reset_lanes.isChecked()
    d._undo()
    assert d._state() == initial
    d._redo()
    assert d.branch_points.topLevelItemCount() == 1
    d.reject()
    assert not d.session.dirty


def test_copy_preview_keeps_branch_pairing_when_switching_vehicle_set(builder: CourseBuilder) -> None:
    d = builder
    if d.group.count() < 2:
        pytest.fail('Expected multiple stock checkpoint sets')
    d._add_branch()
    d.lane_values[HEIGHT[0]].setValue(9)
    d._refresh_live()
    d.all_vehicles.setChecked(True)
    d.group.setCurrentIndex(1 if d.group.currentIndex() == 0 else 0)
    d._refresh_live()
    assert d.branch_points.topLevelItemCount() == 1
    assert d._live_plan is not None, d.message.text()
    checkpoints = [o for o in plan_objects(d.session, d._live_plan) if o.definition.behavior_id == 13 and o.value('index') == 0 and not o.value('isAltCheckpoint')]
    assert all(o.value(HEIGHT[0]) == 9 for o in checkpoints)
    assert not d.session.dirty


def test_individual_lane_edits_share_draft_history_and_override_generation(builder: CourseBuilder) -> None:
    d = builder
    d.pages.setCurrentIndex(1)
    d.reset_lanes.setChecked(True)
    d.lane_width.setValue(60)
    d._refresh_live()
    generated = d._state()
    original = d.lane_values[LATERAL[0]].value()
    d.lane_values[LATERAL[0]].setValue(original + 3)
    d.lane_values[HEIGHT[0]].setValue(9)
    d._refresh_live()
    assert d._live_plan is not None, d.message.text()
    target = d._lane_target
    obj = next(o for o in plan_objects(d.session, d._live_plan) if o.key == target[2])
    assert obj.value(LATERAL[0]) == original + 3 and obj.value(HEIGHT[0]) == 9
    assert not d.session.dirty
    d._flush_history()
    d._undo()
    d._undo()
    assert d._state() == generated
    d._redo()
    d._redo()
    d.build_preview()
    assert d.plan is not None, d.message.text()
    assert d.session.apply_course_plan(d.plan)
    d.session.undo()
    assert not d.session.dirty


def test_removing_a_main_point_removes_its_lane_override_and_undo_restores_it(builder: CourseBuilder) -> None:
    d = builder
    d.lane_values[HEIGHT[0]].setValue(9)
    target = d._lane_target
    d._refresh_live()
    row = next(i for i, point in enumerate(d._draft()) if point.key == target[2])
    d.points.setCurrentItem(d.points.topLevelItem(row))
    d._remove()
    d._refresh_live()
    assert target not in d._lane_edits
    d._undo()
    d._refresh_live()
    assert target in d._lane_edits
    assert not d.session.dirty


def test_clicking_current_rows_switches_selection_between_main_and_branch(builder: CourseBuilder) -> None:
    d = builder
    d._add_branch()
    d._refresh_live()
    branch = d.branch_points.currentItem()
    main = d.points.currentItem()
    d.branch_points.itemClicked.emit(branch, 0)
    assert d._selected_role == ('branch', 0)
    d.points.itemClicked.emit(main, 0)
    assert d._selected_role == ('route', d.points.indexOfTopLevelItem(main))
    d.branch_points.itemClicked.emit(branch, 0)
    assert d._selected_role == ('branch', 0)
    assert not d.session.dirty
