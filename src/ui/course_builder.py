"""Independent live course draft; cleanup, routes and starts commit together."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QModelIndex, QTimer
from PySide6.QtGui import QIntValidator, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QCheckBox, QPushButton, QTreeWidget, QTreeWidgetItem, QSpinBox,
    QDoubleSpinBox, QTabWidget, QSplitter, QPlainTextEdit, QDialogButtonBox, QHeaderView,
    QStyledItemDelegate, QStyleOptionViewItem, QLineEdit, QScrollArea)

from src.core.editing import EditSession
from src.core.course import (CoursePoint, CourseOptions, GridOptions, CoursePlan,
    level_objects, route_points, build_course_plan, preview_course_plan, plan_objects,
    route_heading, forward, yaw_byte, grid_placement, grid_before_checkpoint, surface_snap)
from src.core.objects import LevelObject, RacePath, build_race_paths, catmull_rom
from src.core.placement import TerrainSurface
from src.core.textures import load_model_textures
from src.renderer.camera import project_point
from src.renderer.viewport import Viewport

ROLE = Qt.ItemDataRole.UserRole
ObjectKey = tuple[int, int]
ValueWidget = QCheckBox | QComboBox | QSpinBox | QDoubleSpinBox


class PointDelegate(QStyledItemDelegate):
    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget | None:
        if index.column() == 0:
            return None
        editor = QLineEdit(parent)
        editor.setValidator(QIntValidator(-32768, 32767, editor))
        return editor


class CourseViewport(Viewport):
    """Numbered Qt overlays belong only to the independent builder viewport."""
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.course_labels: list[QLabel] = []
        self.label_points: tuple[tuple[str, tuple[int, int, int], str], ...] = ()

    def set_labels(self, values: tuple[tuple[str, tuple[int, int, int], str], ...]) -> None:
        self.label_points = values
        while len(self.course_labels) < len(values):
            label = QLabel(self)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.course_labels.append(label)
        for i, label in enumerate(self.course_labels):
            label.hide()
            if i < len(values):
                text, _, color = values[i]
                label.setText(text)
                label.setStyleSheet(f'color: white; background: {color}; border: 1px solid white; border-radius: 4px; padding: 2px 4px;')
                label.adjustSize()

    def paintGL(self) -> None:
        super().paintGL()
        matrix = self.camera.projection_matrix(self.width()/max(self.height(), 1)) @ self.camera.view_matrix()
        for label, (_, position, _) in zip(self.course_labels, self.label_points):
            pixel = project_point(np.asarray(position, np.float32), matrix, self.width(), self.height())
            visible = pixel is not None and 0 <= pixel[0] <= self.width() and 0 <= pixel[1] <= self.height()
            label.setVisible(visible)
            if visible:
                label.move(round(pixel[0])-label.width()//2, round(pixel[1])-label.height()-10)


@dataclass(frozen=True)
class DraftState:
    routes: tuple[tuple[int, tuple[CoursePoint, ...]], ...]
    group: int
    removed: tuple[ObjectKey, ...]
    values: tuple[tuple[str, Any], ...]
    grid_placed: bool


class CourseBuilder(QDialog):
    def __init__(self, session: EditSession, level: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('courseBuilderDialog')
        self.setWindowTitle('Course Builder — fresh courses, checkpoints and starts')
        self.resize(1400, 960)
        self.session, self.level = session, level
        self.plan: CoursePlan | None = None
        self._live_plan: CoursePlan | None = None
        self._loading = True
        self.original_objects = level_objects(session, level)
        self.header = session.level_header(level)
        self.model = session.track_model(self.header.geometry_id)
        self.terrain = TerrainSurface.from_model(self.model)
        self.preview_objects = self.original_objects
        self.removed: set[ObjectKey] = set()
        self._routes: dict[int, tuple[CoursePoint, ...]] = {}
        self._roles: list[tuple[str, Any]] = []
        self._selected_role: tuple[str, Any] | None = None
        self._drag_state: DraftState | None = None
        self._drag_role: tuple[str, Any] | None = None
        self._drag_position: tuple[int, int, int] | None = None
        self._grid_placed = False
        self._history: list[DraftState] = []
        self._cursor = 0
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_live)
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.timeout.connect(self._record_history)
        layout = QVBoxLayout(self)
        intro = QLabel('Clear inherited objects if needed, draw the checkpoint loop, then place and aim the eight-racer grid. '
            'Everything stays in this draft until Apply; the whole course is one project undo step.', self)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.fresh = QPushButton('Start fresh — clear all objects', self)
        self.fresh.setObjectName('freshCourse')
        self.fresh.clicked.connect(self._fresh)
        self.race_only = QPushButton('Replace race setup — keep other objects', self)
        self.race_only.clicked.connect(self._race_only)
        row.addWidget(self.fresh)
        row.addWidget(self.race_only)
        row.addStretch(1)
        self.undo_button = QPushButton('Undo draft', self)
        self.redo_button = QPushButton('Redo draft', self)
        self.undo_button.clicked.connect(self._undo)
        self.redo_button.clicked.connect(self._redo)
        row.addWidget(self.undo_button)
        row.addWidget(self.redo_button)
        for keys, callback in (('Ctrl+Z', self._undo), ('Ctrl+Y', self._redo), ('Ctrl+Shift+Z', self._redo)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
        split = QSplitter(self)
        layout.addWidget(split, 1)
        controls = QWidget(split)
        controls.setMaximumWidth(440)
        left = QVBoxLayout(controls)
        left.setContentsMargins(0, 0, 6, 0)
        self.pages = QTabWidget(controls)
        left.addWidget(self.pages, 1)
        route = QWidget(self.pages)
        form = QVBoxLayout(route)
        self.pages.addTab(route, 'Checkpoints')
        self.edit_route = QCheckBox('Apply checkpoint sequence', route)
        self.edit_route.setChecked(True)
        form.addWidget(self.edit_route)
        self.group = QComboBox(route)
        self.group.setAccessibleName('Course checkpoint set')
        groups = sorted(set(self.header.checkpoint_sets) | {int(o.value('vehicleType')) for o in self.original_objects if o.definition.behavior_id == 13})
        for group in groups:
            users = '/'.join(name for name, g in zip(('Car', 'Hovercraft', 'Plane'), self.header.checkpoint_sets) if g == group) or 'unmapped'
            self.group.addItem(f'Set {group} · {users}', group)
            self._routes[group] = route_points(self.original_objects, group)
        self.group.setCurrentIndex(self.group.findData(self.header.checkpoint_sets[0]))
        self._group = int(self.group.currentData())
        form.addWidget(self.group)
        self.all_vehicles = QCheckBox('Copy this route to every level vehicle set', route)
        self.all_vehicles.setToolTip('Replaces the other mapped sets with copies of this route and neutral AI lanes; level header mappings are retained.')
        form.addWidget(self.all_vehicles)
        self.points = QTreeWidget(route)
        self.points.setObjectName('coursePoints')
        self.points.setHeaderLabels(('Checkpoint', 'X', 'Y', 'Z'))
        self.points.setRootIsDecorated(False)
        self.points.setItemDelegate(PointDelegate(self.points))
        self.points.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        form.addWidget(self.points, 1)
        row = QHBoxLayout()
        form.addLayout(row)
        for title, callback in (('Up', lambda: self._move(-1)), ('Down', lambda: self._move(1)),
                                ('Remove', self._remove), ('Make CP0', self._make_cp0)):
            button = QPushButton(title, route)
            button.clicked.connect(callback)
            row.addWidget(button)
        row = QHBoxLayout()
        form.addLayout(row)
        self.midpoint = QPushButton('Insert midpoint', route)
        self.midpoint.clicked.connect(self._midpoint)
        self.reverse = QPushButton('Reverse (keep CP0)', route)
        self.reverse.clicked.connect(self._reverse)
        row.addWidget(self.midpoint)
        row.addWidget(self.reverse)
        row = QHBoxLayout()
        form.addLayout(row)
        self.reload = QPushButton('Reload this set', route)
        self.reload.clicked.connect(self._reload_route)
        self.clear = QPushButton('Clear route rows', route)
        self.clear.clicked.connect(self._clear)
        row.addWidget(self.reload)
        row.addWidget(self.clear)
        self.snap_points = QCheckBox('Snap moved points to nearby road', route)
        self.snap_points.setChecked(True)
        form.addWidget(self.snap_points)
        self.align = QCheckBox('Align headings to route direction', route)
        form.addWidget(self.align)
        self.height = self._spin(-1000, 1000, 32, route)
        row = QHBoxLayout()
        form.addLayout(row)
        row.addWidget(QLabel('Point height above road', route))
        row.addWidget(self.height)
        details = self._details(form, 'Advanced checkpoint settings')
        self.map = QComboBox(details)
        self.map.setAccessibleName('Course new-entry map')
        for m in dict.fromkeys(i for i in (self.header.object_map_id, self.header.secondary_object_map_id) if i >= 0):
            self.map.addItem(f'New entries → map {m}', m)
        details.layout().addWidget(self.map)
        self.reset_lanes = QCheckBox('Reset retained AI lanes / behaviors', details)
        details.layout().addWidget(self.reset_lanes)
        self.scale = self._spin(5, 255, 64, details)
        self.lane_width = self._spin(0, 2000, 160, details)
        for title, widget in (('New/reset scale', self.scale), ('AI lane half-width', self.lane_width)):
            line = QHBoxLayout()
            line.addWidget(QLabel(title, details))
            line.addWidget(widget)
            details.layout().addLayout(line)
        self.remove_alts = QCheckBox('Remove selected set’s alternates', details)
        self.drop = QCheckBox('Drop all checkpoint origins below their stored Y', details)
        details.layout().addWidget(self.remove_alts)
        details.layout().addWidget(self.drop)
        grid_page = QWidget(self.pages)
        grid_form = QVBoxLayout(grid_page)
        self.pages.addTab(grid_page, 'Start grid')
        self.edit_grid = QCheckBox('Apply eight-racer start grid', grid_page)
        grid_form.addWidget(self.edit_grid)
        self.place_grid = QPushButton('Place grid on road, then aim it', grid_page)
        self.place_grid.clicked.connect(lambda: self.pick.setCurrentIndex(3))
        grid_form.addWidget(self.place_grid)
        row = QHBoxLayout()
        grid_form.addLayout(row)
        self.focus_grid = QPushButton('Focus grid', grid_page)
        self.focus_grid.clicked.connect(self._focus_grid)
        self.aim_grid = QPushButton('Aim grid toward road point', grid_page)
        self.aim_grid.clicked.connect(lambda: self.pick.setCurrentIndex(4 if self._grid_placed else 3))
        row.addWidget(self.focus_grid)
        row.addWidget(self.aim_grid)
        self.grid_status = QLabel(grid_page)
        self.grid_status.setWordWrap(True)
        grid_form.addWidget(self.grid_status)
        g = QGridLayout()
        grid_form.addLayout(g)
        self.anchor: list[QSpinBox] = []
        for row, axis in enumerate('XYZ'):
            spin = self._spin(-32768, 32767, 0, grid_page)
            spin.setAccessibleName('Course grid anchor '+axis)
            g.addWidget(QLabel('Front row center '+axis, grid_page), row, 0)
            g.addWidget(spin, row, 1)
            self.anchor.append(spin)
        self.yaw = QDoubleSpinBox(grid_page)
        self.yaw.setRange(-360, 360)
        self.yaw.setDecimals(3)
        self.yaw.setSingleStep(5.625)
        self.yaw.setSuffix('°')
        g.addWidget(QLabel('Driving heading', grid_page), 3, 0)
        g.addWidget(self.yaw, 3, 1)
        self.columns = self._spin(1, 8, 2, grid_page)
        self.spacing_x = self._spin(1, 4000, 120, grid_page)
        self.spacing_z = self._spin(1, 4000, 140, grid_page)
        for row, (title, widget) in enumerate((('Columns', self.columns), ('Column spacing', self.spacing_x), ('Row spacing', self.spacing_z)), 4):
            g.addWidget(QLabel(title, grid_page), row, 0)
            g.addWidget(widget, row, 1)
        self.grid_drop = QCheckBox('Snap each racer to nearby road', grid_page)
        self.grid_drop.setChecked(True)
        grid_form.addWidget(self.grid_drop)
        self.grid_height = self._spin(-1000, 1000, 8, grid_page)
        row = QHBoxLayout()
        grid_form.addLayout(row)
        row.addWidget(QLabel('Start height above road', grid_page))
        row.addWidget(self.grid_height)
        self.clearance = self._spin(1, 4000, 200, grid_page)
        row = QHBoxLayout()
        grid_form.addLayout(row)
        row.addWidget(QLabel('Minimum distance before CP0', grid_page))
        row.addWidget(self.clearance)
        self.before_cp0 = QPushButton('Fit whole grid on approach before CP0', grid_page)
        self.before_cp0.clicked.connect(self._grid_before)
        grid_form.addWidget(self.before_cp0)
        self.flip_grid = QPushButton('Rotate grid 180°', grid_page)
        self.flip_grid.clicked.connect(lambda: self.yaw.setValue((self.yaw.value()+180) % 360))
        grid_form.addWidget(self.flip_grid)
        details = self._details(grid_form, 'Advanced entrance / vehicle settings')
        self.entrance = self._spin(0, 255, 0, details)
        line = QHBoxLayout()
        line.addWidget(QLabel('Entrance ID (0 = Ancient Lake race)', details))
        line.addWidget(self.entrance)
        details.layout().addLayout(line)
        self.stagger = QDoubleSpinBox(details)
        self.stagger.setRange(0, 1)
        self.stagger.setSingleStep(.1)
        self.stagger.setDecimals(2)
        line = QHBoxLayout()
        line.addWidget(QLabel('Odd-column stagger', details))
        line.addWidget(self.stagger)
        details.layout().addLayout(line)
        self.vehicle = QComboBox(details)
        self.vehicle.addItem('Keep existing / level choice', None)
        for title, value in (('Use level vehicle', -1), ('Car', 0), ('Hovercraft', 1), ('Plane', 2)):
            self.vehicle.addItem(title, value)
        details.layout().addWidget(self.vehicle)
        self.load_grid = QPushButton('Load this entrance’s current anchor / heading', details)
        self.load_grid.clicked.connect(self._load_grid)
        details.layout().addWidget(self.load_grid)
        grid_form.addStretch(1)
        cleanup_page = QWidget(self.pages)
        cleanup = QVBoxLayout(cleanup_page)
        self.pages.addTab(cleanup_page, 'Cleanup')
        note = QLabel('Choose categories to remove from both loaded object maps. Geometry, textures, collision and level settings stay in place.', cleanup_page)
        note.setWordWrap(True)
        cleanup.addWidget(note)
        self.cleanup_list = QTreeWidget(cleanup_page)
        self.cleanup_list.setHeaderLabels(('Placed object category', 'Count'))
        self.cleanup_list.setRootIsDecorated(False)
        cleanup.addWidget(self.cleanup_list, 1)
        self.clear_categories = QPushButton('Stage removal of checked categories', cleanup_page)
        self.clear_categories.clicked.connect(self._clear_categories)
        cleanup.addWidget(self.clear_categories)
        self.cleanup_summary = QLabel(cleanup_page)
        self.cleanup_summary.setWordWrap(True)
        cleanup.addWidget(self.cleanup_summary)
        maps = {o.map_id for o in self.original_objects}
        uses = [f'{l.index}: {l.name}' for l in session._catalog.levels if l.index != level and maps & {session.level_header(l.index).object_map_id, session.level_header(l.index).secondary_object_map_id}]
        shared = QLabel('Shared maps also affect: '+', '.join(uses) if uses else 'These object maps are not used by other catalog levels.', cleanup_page)
        shared.setWordWrap(True)
        cleanup.addWidget(shared)
        # Expanded advanced controls must scroll, not force a taller window.
        pages = [(self.pages.widget(i), self.pages.tabText(i)) for i in range(self.pages.count())]
        for _ in pages:
            self.pages.removeTab(0)
        for page, title in pages:
            scroll = QScrollArea(self.pages)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addTab(scroll, title)
        self.pick = QComboBox(controls)
        self.pick.setAccessibleName('Course viewport click mode')
        self.pick.addItems(('Select / drag draft markers', 'Click road: append checkpoint',
                            'Click road: move selected point', 'Click road: grid anchor', 'Click road: aim grid'))
        self.pick.currentIndexChanged.connect(self._pick_mode)
        left.addWidget(self.pick)
        self.build = QPushButton('Review changes / ROM budget', controls)
        self.build.setObjectName('buildCoursePreview')
        self.build.clicked.connect(self.build_preview)
        left.addWidget(self.build)
        self.message = QLabel(controls)
        self.message.setWordWrap(True)
        left.addWidget(self.message)
        right = QWidget(split)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        right_layout.addLayout(row)
        row.addWidget(QLabel('View', right))
        self.view = QComboBox(right)
        self.view.addItems(('Perspective', 'Top', 'Front', 'Right'))
        row.addWidget(self.view)
        self.place_points = QPushButton('Place checkpoints', right)
        self.place_points.clicked.connect(lambda: self.pick.setCurrentIndex(1))
        self.select_points = QPushButton('Select / drag', right)
        self.select_points.clicked.connect(lambda: self.pick.setCurrentIndex(0))
        row.addWidget(self.place_points)
        row.addWidget(self.select_points)
        row.addStretch(1)
        self.viewport = CourseViewport(right)
        self.viewport.setMinimumSize(420, 280)
        self.viewport.set_model(self.model, load_model_textures(session.asset_source, self.model))
        self.viewport.set_catalog_caption('Course draft', self.header.geometry_id)
        self.viewport.show_racelines = True
        self.viewport.set_mouse_move_enabled(True)
        self.viewport.surface_picked.connect(self._surface_picked)
        self.viewport.object_selected.connect(self._object_selected)
        self.viewport.object_drag_started.connect(self._begin_drag)
        self.viewport.object_drag_preview.connect(self._preview_drag)
        self.viewport.object_drag_finished.connect(self._finish_drag)
        self.view.currentTextChanged.connect(self.viewport.set_view)
        right_layout.addWidget(self.viewport, 3)
        reports = QTabWidget(right)
        right_layout.addWidget(reports, 1)
        self.summary = QPlainTextEdit(right)
        self.summary.setReadOnly(True)
        reports.addTab(self.summary, 'Changes')
        self.issues = QTreeWidget(right)
        self.issues.setHeaderLabels(('Readiness / diagnostics',))
        self.issues.setWordWrap(True)
        self.issues.itemDoubleClicked.connect(self._focus_issue)
        reports.addTab(self.issues, 'Readiness')
        self.budget = QPlainTextEdit(right)
        self.budget.setReadOnly(True)
        reports.addTab(self.budget, 'ROM budget')
        split.setSizes([420, 950])
        help_text = QLabel('CP0 is orange; numbered starts are green (red when invalid). Arrows show driving direction. '
            'Select / drag moves a checkpoint or the whole grid; Esc cancels a drag. RMB/WASD camera · F fit · Ctrl+Z draft undo.', self)
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)
        self.apply = QPushButton('Apply course', self)
        self.apply.setObjectName('applyCourse')
        self.apply.clicked.connect(self._apply)
        buttons.addButton(self.apply, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)
        # Enter commits a field; it must never trigger fresh/clear/apply buttons.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self._widgets: dict[str, ValueWidget] = {name: getattr(self, name) for name in (
            'edit_route', 'all_vehicles', 'align', 'reset_lanes', 'scale', 'lane_width',
            'remove_alts', 'drop', 'height', 'map', 'edit_grid', 'entrance', 'yaw',
            'columns', 'spacing_x', 'spacing_z', 'stagger', 'vehicle', 'grid_drop',
            'grid_height', 'clearance', 'snap_points')}
        self._widgets.update({f'anchor_{i}': spin for i, spin in enumerate(self.anchor)})
        for name, widget in self._widgets.items():
            signal = widget.toggled if isinstance(widget, QCheckBox) else widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged
            signal.connect(lambda *_, n=name: self._field_changed(n))
        self.points.itemChanged.connect(self.invalidate)
        self.points.currentItemChanged.connect(self._point_selected)
        self.points.itemDoubleClicked.connect(lambda item, column: self._focus_point() if column == 0 else None)
        self.group.currentIndexChanged.connect(self._switch_set)
        self.finished.connect(self._cleanup)
        self._show_rows(self._routes[self._group])
        self._load_grid()
        self._loading = False
        self._history = [self._state()]
        self._refresh_live()
        self._update_history_buttons()
        if not self.map.count():
            self.build.setEnabled(False)
            self.pick.setEnabled(False)
            self.apply.setEnabled(False)
            self.message.setText('Choose a level with an existing object map to build a course.')

    @staticmethod
    def _spin(low: int, high: int, value: int, parent: QWidget) -> QSpinBox:
        spin = QSpinBox(parent)
        spin.setRange(low, high)
        spin.setValue(value)
        return spin

    @staticmethod
    def _details(layout: QVBoxLayout, title: str) -> QWidget:
        button = QPushButton(title+' ▸')
        button.setCheckable(True)
        layout.addWidget(button)
        content = QWidget()
        QVBoxLayout(content).setContentsMargins(6, 0, 0, 0)
        content.hide()
        button.toggled.connect(content.setVisible)
        layout.addWidget(content)
        return content

    def _draft(self) -> tuple[CoursePoint, ...]:
        points = []
        for row in range(self.points.topLevelItemCount()):
            item = self.points.topLevelItem(row)
            position = tuple(int(item.text(i)) for i in (1, 2, 3))
            if any(not -32768 <= v <= 32767 for v in position):
                raise ValueError('Point coordinates must fit signed16')
            points.append(CoursePoint(position, item.data(0, ROLE)))
        return tuple(points)

    def _row(self, point: CoursePoint) -> QTreeWidgetItem:
        item = QTreeWidgetItem(['', *map(str, point.position)])
        item.setData(0, ROLE, point.key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _show_rows(self, points: tuple[CoursePoint, ...], selected: int = 0) -> None:
        loading, self._loading = self._loading, True
        self.points.clear()
        for i, point in enumerate(points):
            item = self._row(point)
            item.setText(0, 'CP0' if i == 0 else str(i))
            self.points.addTopLevelItem(item)
        if points:
            self.points.setCurrentItem(self.points.topLevelItem(min(max(selected, 0), len(points)-1)))
        self._loading = loading

    def _switch_set(self) -> None:
        if self._loading:
            return
        self._flush_history()
        self._routes[self._group] = self._draft()
        common = self._routes[self._group]
        self._group = int(self.group.currentData())
        if self.all_vehicles.isChecked():
            self._routes[self._group] = tuple(CoursePoint(p.position) for p in common)
        self._show_rows(self._routes.get(self._group, ()))
        self._selected_role = None
        self.invalidate(record=False)

    def _reload_route(self) -> None:
        self._flush_history()
        points = route_points(tuple(o for o in self.original_objects if o.key not in self.removed), self._group)
        self._show_rows(points)
        self.invalidate()

    def _state(self) -> DraftState:
        self._routes[self._group] = self._draft()
        values = tuple((name, w.isChecked() if isinstance(w, QCheckBox) else w.currentIndex() if isinstance(w, QComboBox) else w.value()) for name, w in self._widgets.items())
        return DraftState(tuple(sorted(self._routes.items())), self._group, tuple(sorted(self.removed)), values, self._grid_placed)

    def _restore(self, state: DraftState) -> None:
        self._loading = True
        self._routes = dict(state.routes)
        self._group = state.group
        self.group.setCurrentIndex(self.group.findData(state.group))
        self.removed = set(state.removed)
        self._grid_placed = state.grid_placed
        for name, value in state.values:
            widget = self._widgets[name]
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(value)
            else:
                widget.setValue(value)
        self._show_rows(self._routes[self._group])
        self._selected_role = None
        self._loading = False
        self.invalidate(record=False)

    def _record_history(self) -> None:
        if self._loading or self._drag_state is not None or not self._history:
            return
        try:
            state = self._state()
            if state != self._history[self._cursor]:
                self._history[self._cursor+1:] = [state]
                self._cursor += 1
        except ValueError:
            pass
        self._update_history_buttons()

    def _flush_history(self) -> None:
        self._history_timer.stop()
        self._record_history()

    def _update_history_buttons(self) -> None:
        self.undo_button.setEnabled(self._cursor > 0)
        self.redo_button.setEnabled(self._cursor+1 < len(self._history))

    def _undo(self) -> None:
        if self._drag_state is not None:
            self.viewport.finish_object_drag(cancel=True)
            return
        self.viewport.finish_object_drag(cancel=True)
        self._flush_history()
        if self._cursor:
            self._cursor -= 1
            self._restore(self._history[self._cursor])
        self._update_history_buttons()

    def _redo(self) -> None:
        if self._drag_state is not None:
            self.viewport.finish_object_drag(cancel=True)
            return
        self.viewport.finish_object_drag(cancel=True)
        self._flush_history()
        if self._cursor+1 < len(self._history):
            self._cursor += 1
            self._restore(self._history[self._cursor])
        self._update_history_buttons()

    def _field_changed(self, name: str) -> None:
        if self._loading:
            return
        if name.startswith('anchor_') or name in ('yaw', 'columns', 'spacing_x', 'spacing_z', 'stagger',
                'vehicle', 'entrance', 'grid_drop', 'grid_height'):
            self._loading = True
            if name.startswith('anchor_'):
                self._grid_placed = True
            elif name == 'entrance':
                self._grid_placed = False
            self.edit_grid.setChecked(True)
            self._loading = False
        self.invalidate()

    def invalidate(self, *_: object, record: bool = True) -> None:
        if self._loading:
            return
        self.plan = None
        self.apply.setEnabled(False)
        self.budget.setPlainText('Live draft changed. Review changes / ROM budget or Apply runs the exact export checks.')
        self._refresh_timer.start(35)
        if record and self._drag_state is None:
            self._history_timer.start(180)

    def _options(self) -> CourseOptions:
        return CourseOptions(self._group, int(self.map.currentData()), self.align.isChecked(), self.reset_lanes.isChecked(),
            self.scale.value(), self.lane_width.value(), self.remove_alts.isChecked(), self.drop.isChecked(), self.height.value(),
            tuple(sorted(self.removed)), tuple(dict.fromkeys(self.header.checkpoint_sets)) if self.all_vehicles.isChecked() else ())

    def _grid_options(self, *, force: bool = False) -> GridOptions | None:
        if not force and not self.edit_grid.isChecked():
            return None
        return GridOptions(tuple(s.value() for s in self.anchor), self.yaw.value(), self.entrance.value(), self.columns.value(),
            self.spacing_x.value(), self.spacing_z.value(), self.stagger.value(), self.grid_drop.isChecked(), self.grid_height.value(), self.vehicle.currentData())

    def _route_requested(self, points: tuple[CoursePoint, ...]) -> bool:
        return self.edit_route.isChecked() and (points != route_points(self.original_objects, self._group)
            or any(w.isChecked() for w in (self.align, self.reset_lanes, self.remove_alts, self.drop, self.all_vehicles)))

    def _template(self, behavior: int) -> LevelObject:
        obj = next((o for o in self.original_objects if o.definition.behavior_id == behavior), None)
        if obj is not None:
            return obj
        template = next(t for t in self.session.object_catalog if self.session.database.resolve(t.object_id).behavior_id == behavior and t.map_id is not None)
        return self.session.original_map(template.map_id).objects[template.entry_index]

    @staticmethod
    def _marker(template: LevelObject, index: int, position: tuple[int, int, int], parameters: dict[str, int]) -> LevelObject:
        return replace(template, index=index, position=position,
            parameters=tuple(replace(p, value=parameters.get(p.name, p.value)) for p in template.parameters))

    def _refresh_live(self) -> None:
        self._refresh_timer.stop()
        if self._loading or not self.map.count():
            return
        self._live_plan = None
        self.apply.setEnabled(False)
        try:
            points = self._draft()
            self._routes[self._group] = points
            options, grid = self._options(), self._grid_options()
            self._loading = True
            for i in range(self.points.topLevelItemCount()):
                self.points.topLevelItem(i).setText(0, 'CP0' if i == 0 else str(i))
            self._loading = False
            errors: list[str] = []
            placement = None
            if grid is not None:
                if self._grid_placed:
                    placement = grid_placement(grid, self.terrain)
                    errors.extend(message for _, message in placement.errors)
                else:
                    errors.append('Place the starting grid on the road, then aim it toward CP0.')
            route_requested = self._route_requested(points)
            route_valid = not route_requested or 4 <= len(points) <= 60
            if not route_valid:
                errors.append('Draw at least four checkpoints for the closed route (maximum 60 including alternates).')
            try:
                plan = build_course_plan(self.session, self.level, points, options,
                    grid if placement is not None and not placement.errors else None,
                    edit_route=route_requested and route_valid, validate=False)
                objects = plan_objects(self.session, plan)
            except ValueError as error:
                errors.append(str(error))
                plan = None
                objects = tuple(o for o in self.original_objects if o.key not in self.removed)
            # Route markers remain useful even with fewer than four points or a
            # rejected final plan. Their synthetic identities never leave the UI.
            if self.edit_route.isChecked():
                planned_main = {int(o.value('index')): o for o in objects if o.definition.behavior_id == 13 and o.value('vehicleType') == self._group and not o.value('isAltCheckpoint')}
                objects = tuple(o for o in objects if not (o.definition.behavior_id == 13 and o.value('vehicleType') == self._group and not o.value('isAltCheckpoint')))
                template = self._template(13)
                retained = {o.key: o for o in self.original_objects}
                markers = []
                for i, point in enumerate(points):
                    yaw = retained[point.key].value('angleY') if point.key in retained else 0
                    if len(points) >= 3 and (self.align.isChecked() or point.key is None):
                        try:
                            yaw = route_heading(points, i)
                        except ValueError:
                            pass
                    position = planned_main[i].position if plan is not None and route_requested and route_valid and i in planned_main else point.position
                    markers.append(self._marker(template, -1-i, position, {'angleY': yaw, 'index': i, 'vehicleType': self._group, 'isAltCheckpoint': 0}))
                objects += tuple(markers)
            invalid = {i for i, _ in placement.errors} if placement is not None else set()
            if grid is not None:
                objects = tuple(o for o in objects if not (o.definition.behavior_id == 11 and o.value('entranceID') == grid.entrance))
                if placement is not None:
                    template = self._template(11)
                    objects += tuple(self._marker(template, -1000-i, p, {'angleY': yaw_byte(grid.yaw), 'racerIndex': i, 'entranceID': grid.entrance}) for i, p in enumerate(placement.positions))
            self.preview_objects = objects
            self._roles = []
            labels = []
            display = []
            for obj in objects:
                # Other mapped sets can share every position with this route.
                # Keep them in the plan, but don't let their markers steal hits.
                if obj.definition.behavior_id == 13 and obj.value('vehicleType') != self._group:
                    continue
                if obj.definition.behavior_id == 11 and obj.value('entranceID') != self.entrance.value():
                    continue
                if obj.definition.behavior_id == 13 and obj.value('vehicleType') == self._group and not obj.value('isAltCheckpoint'):
                    index = int(obj.value('index'))
                    self._roles.append(('route', index))
                    labels.append(('CP0' if index == 0 else str(index), obj.position, '#b66b00' if index == 0 else '#146b92'))
                elif obj.definition.behavior_id == 11 and obj.value('entranceID') == self.entrance.value():
                    index = int(obj.value('racerIndex'))
                    self._roles.append(('grid', index))
                    labels.append((f'{index+1}'+(' !' if index in invalid else ''), obj.position, '#b52525' if index in invalid else '#197447'))
                else:
                    self._roles.append(('other', obj.key))
                # In this authoring view all arrows describe driving direction.
                if obj.definition.behavior_id == 13:
                    obj = self._marker(obj, obj.index, obj.position, {'angleY': (int(obj.value('angleY'))+32) % 64})
                display.append(obj)
            paths = tuple(p for p in build_race_paths(objects, self.header.checkpoint_sets, lane=4) if p.checkpoint_set == self._group)
            if self.edit_route.isChecked() and len(points) > 1:
                values = np.asarray([p.position for p in points], np.float32)
                curve = catmull_rom(values, closed=True) if len(points) >= 4 else values
                paths += (RacePath('Draft driving route', 'checkpoint', self._group, False, curve, (), True),)
                if len(points) >= 3:
                    try:
                        direction = forward(int(markers[0].value('angleY')))
                        side = np.array([direction[2], 0, -direction[0]])*max(self.lane_width.value(), 100)
                        center = np.asarray(markers[0].position)
                        gate = np.array([center-side, center-side+[0, 160, 0], center+side+[0, 160, 0], center+side], np.float32)
                        paths += (RacePath('CP0 crossing gate', 'checkpoint', self._group, False, gate, (), False),)
                    except ValueError:
                        pass
            self.viewport.set_objects(tuple(display), paths)
            self.viewport.set_labels(tuple(labels))
            self._restore_selection()
            self.issues.clear()
            for error in dict.fromkeys(errors):
                self.issues.addTopLevelItem(QTreeWidgetItem(['Error · '+error]))
            if plan is not None:
                self._issue_objects = plan_objects(self.session, plan)
                for issue in plan.issues:
                    item = QTreeWidgetItem(['Warning · '+issue.message])
                    item.setData(0, ROLE, issue.keys)
                    self.issues.addTopLevelItem(item)
                self.summary.setPlainText('\n'.join(plan.changes) or 'No course changes staged.')
            if not self.issues.topLevelItemCount():
                self.issues.addTopLevelItem(QTreeWidgetItem(['Course checks passed. Review the start grid and route before applying.']))
            if plan is not None and not errors:
                self._live_plan = plan
                self.apply.setEnabled(plan.before != plan.after)
            self._cleanup_counts()
            self.grid_status.setText(('Grid not placed yet. Click the road, then click ahead in the driving direction.' if not self._grid_placed else
                f'Entrance {self.entrance.value()} · heading {yaw_byte(self.yaw.value())*5.625:g}° · drag any numbered start to move the whole grid.')
                + (f'\n{len(invalid)} invalid position(s), marked red.' if invalid else ''))
            self.message.setText(errors[0] if errors else f'Live draft · {len(points)} checkpoint rows · {len(self.removed)} inherited objects cleared. Apply checks the ROM budget.')
        except (ValueError, OverflowError) as error:
            self.message.setText(f'Draft: {error}')
        finally:
            self._loading = False

    def _cleanup_counts(self) -> None:
        checked = {self.cleanup_list.topLevelItem(i).text(0) for i in range(self.cleanup_list.topLevelItemCount()) if self.cleanup_list.topLevelItem(i).checkState(0) == Qt.CheckState.Checked}
        counts: dict[str, int] = {}
        for obj in self.original_objects:
            counts.setdefault(obj.category, 0)
            if obj.key not in self.removed:
                counts[obj.category] += 1
        self.cleanup_list.clear()
        for category, count in sorted(counts.items()):
            item = QTreeWidgetItem([category, str(count)])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if category in checked else Qt.CheckState.Unchecked)
            self.cleanup_list.addTopLevelItem(item)
        self.cleanup_summary.setText(f'{len(self.removed)} placed objects staged for removal. Draft Undo restores them; Cancel leaves the project untouched.')

    def _stage_cleanup(self, keys: set[ObjectKey], *, fresh: bool = False) -> None:
        self.viewport.finish_object_drag(cancel=True)
        self._flush_history()
        self._routes[self._group] = self._draft()
        self._loading = True
        self.removed.update(keys)
        for group, points in self._routes.items():
            self._routes[group] = () if fresh else tuple(p for p in points if p.key not in keys)
        self._show_rows(self._routes[self._group])
        if any(o.key in keys and o.definition.behavior_id == 11 for o in self.original_objects) or fresh:
            self.edit_grid.setChecked(True)
            self._grid_placed = False
        if any(o.key in keys and o.definition.behavior_id == 13 for o in self.original_objects) or fresh:
            self.edit_route.setChecked(True)
            self.align.setChecked(True)
            self.reset_lanes.setChecked(True)
            self.remove_alts.setChecked(True)
            self.all_vehicles.setChecked(True)
        self._selected_role = None
        self._loading = False
        self.view.setCurrentText('Top')
        self.pages.setCurrentIndex(0)
        self.pick.setCurrentIndex(1)
        self.invalidate()
        self._flush_history()
        self._refresh_live()

    def _fresh(self) -> None:
        self._stage_cleanup({o.key for o in self.original_objects}, fresh=True)

    def _race_only(self) -> None:
        self._stage_cleanup({o.key for o in self.original_objects if o.definition.behavior_id in (11, 13, 16)}, fresh=True)

    def _clear_categories(self) -> None:
        categories = {self.cleanup_list.topLevelItem(i).text(0) for i in range(self.cleanup_list.topLevelItemCount()) if self.cleanup_list.topLevelItem(i).checkState(0) == Qt.CheckState.Checked}
        self._stage_cleanup({o.key for o in self.original_objects if o.category in categories})

    def _move(self, delta: int) -> None:
        self._flush_history()
        row = self.points.indexOfTopLevelItem(self.points.currentItem())
        if row >= 0 and 0 <= row+delta < self.points.topLevelItemCount():
            item = self.points.takeTopLevelItem(row)
            self.points.insertTopLevelItem(row+delta, item)
            self.points.setCurrentItem(item)
            self.invalidate()

    def _remove(self) -> None:
        self._flush_history()
        row = self.points.indexOfTopLevelItem(self.points.currentItem())
        if row >= 0:
            self.points.takeTopLevelItem(row)
            self.invalidate()

    def _clear(self) -> None:
        self._flush_history()
        self.points.clear()
        self.invalidate()

    def _midpoint(self) -> None:
        self._flush_history()
        points = self._draft()
        row = self.points.indexOfTopLevelItem(self.points.currentItem())
        if row >= 0 and len(points) >= 2:
            position = tuple(int(round(v)) for v in (np.asarray(points[row].position)+points[(row+1) % len(points)].position)/2)
            item = self._row(CoursePoint(position))
            self.points.insertTopLevelItem(row+1, item)
            self.points.setCurrentItem(item)
            self.invalidate()

    def _reverse(self) -> None:
        self._flush_history()
        points = self._draft()
        self._show_rows((*points[:1], *reversed(points[1:])))
        self.align.setChecked(True)
        self.invalidate()

    def _make_cp0(self) -> None:
        self._flush_history()
        points = self._draft()
        row = self.points.indexOfTopLevelItem(self.points.currentItem())
        if row > 0:
            self._show_rows(points[row:]+points[:row])
            self.invalidate()

    def _pick_mode(self) -> None:
        mode = self.pick.currentIndex()
        self.viewport.finish_object_drag(cancel=True)
        self.viewport.surface_picker = self.terrain if mode > 0 else None
        if mode in (3, 4):
            self.pages.setCurrentIndex(1)
            self.message.setText('Click the road at the front-row center.' if mode == 3 else 'Click ahead in the direction the racers should drive.')
        elif mode in (1, 2):
            self.pages.setCurrentIndex(0)

    def _surface_picked(self, position: tuple[float, float, float]) -> None:
        self._flush_history()
        try:
            point = tuple(int(round(v)) for v in position)
            if any(not -32768 <= v <= 32767 for v in point):
                raise ValueError('Picked point exceeds signed16')
            mode = self.pick.currentIndex()
            if mode in (3, 4):
                self._loading = True
                if mode == 3:
                    for spin, value in zip(self.anchor, point):
                        spin.setValue(value)
                    self._grid_placed = True
                    self.edit_grid.setChecked(True)
                else:
                    delta = np.asarray(point)-np.array([s.value() for s in self.anchor])
                    if np.linalg.norm(delta[[0, 2]]) < 1:
                        raise ValueError('Aim at a different road position ahead of the grid.')
                    self.yaw.setValue(yaw_byte(math.degrees(math.atan2(-delta[0], -delta[2])))*5.625)
                self._loading = False
                self.pick.setCurrentIndex(4 if mode == 3 else 0)
            else:
                point = point[0], point[1]+self.height.value(), point[2]
                if not -32768 <= point[1] <= 32767:
                    raise ValueError('Point height exceeds signed16')
                if mode == 1:
                    if self.points.topLevelItemCount() >= 60:
                        raise ValueError('At most 60 checkpoints including alternates')
                    item = self._row(CoursePoint(point))
                    self.points.addTopLevelItem(item)
                    self.points.setCurrentItem(item)
                elif mode == 2 and self.points.currentItem() is not None:
                    self._loading = True
                    for i, value in enumerate(point, 1):
                        self.points.currentItem().setText(i, str(value))
                    self._loading = False
            self.invalidate()
            self._flush_history()
            self._refresh_live()
            if mode == 3:
                self.message.setText('Grid placed. Click ahead on the road to set its driving direction.')
        except ValueError as error:
            self.message.setText(str(error))
        finally:
            self._loading = False

    def _grid_before(self) -> None:
        self._flush_history()
        try:
            grid = self._grid_options(force=True)
            assert grid is not None
            result = grid_before_checkpoint(self._draft(), grid, self.terrain, self.clearance.value())
            self._loading = True
            for spin, value in zip(self.anchor, result.anchor):
                spin.setValue(value)
            self.yaw.setValue(result.yaw)
            self.edit_grid.setChecked(True)
            self._grid_placed = True
            self._loading = False
            self.invalidate()
            self._flush_history()
            self._refresh_live()
        except ValueError as error:
            self.message.setText(str(error))

    def _focus_grid(self) -> None:
        grid = self._grid_options(force=True)
        if grid is None or not self._grid_placed:
            self.message.setText('Place the grid on the road first.')
            return
        try:
            positions = np.asarray(grid_placement(grid, self.terrain).positions, np.float32)
            self.viewport.camera.fit_bounds(positions.min(axis=0)-120, positions.max(axis=0)+120,
                self.viewport.width()/max(self.viewport.height(), 1))
            self.viewport.update()
        except ValueError as error:
            self.message.setText(str(error))

    def _load_grid(self) -> None:
        loading = self._loading
        starts = sorted((o for o in self.original_objects if o.key not in self.removed and o.definition.behavior_id == 11 and o.value('entranceID') == self.entrance.value()), key=lambda o: o.value('racerIndex'))
        front = [o for o in starts if o.value('racerIndex') < self.columns.value()]
        if front:
            self._loading = True
            for spin, value in zip(self.anchor, np.mean([o.position for o in front], axis=0)):
                spin.setValue(round(value))
            self.yaw.setValue((int(starts[0].value('angleY')) % 64)*5.625)
            self._grid_placed = True
            self._loading = loading
        if not loading:
            self.invalidate()

    def _point_selected(self, *_: object) -> None:
        if self._loading:
            return
        row = self.points.indexOfTopLevelItem(self.points.currentItem())
        self._selected_role = ('route', row) if row >= 0 else None
        self._restore_selection()

    def _restore_selection(self) -> None:
        index = self._roles.index(self._selected_role) if self._selected_role in self._roles else -1
        self.viewport.set_mouse_move_enabled(index >= 0 and self._roles[index][0] != 'other')
        self.viewport.select_object(index)

    def _object_selected(self, index: int) -> None:
        if not 0 <= index < len(self._roles):
            self._selected_role = None
            return
        role = self._roles[index]
        self._selected_role = role
        self.viewport.set_mouse_move_enabled(role[0] != 'other')
        if role[0] == 'route' and 0 <= role[1] < self.points.topLevelItemCount():
            self._loading = True
            self.points.setCurrentItem(self.points.topLevelItem(role[1]))
            self._loading = False

    def _begin_drag(self, index: int) -> None:
        self._flush_history()
        if not 0 <= index < len(self._roles) or self._roles[index][0] == 'other':
            self.viewport.finish_object_drag(cancel=True)
            return
        self._drag_state = self._state()
        self._drag_role = self._roles[index]
        self._drag_position = self.viewport.objects[index].position
        if self._drag_role[0] == 'grid':
            self._loading = True
            self.edit_grid.setChecked(True)
            self._grid_placed = True
            self._loading = False

    def _preview_drag(self, position: tuple[int, int, int]) -> None:
        if self._drag_state is None or self._drag_role is None:
            return
        assert self._drag_position is not None
        self._loading = True
        try:
            point = tuple(int(round(v)) for v in position)
            if self._drag_role[0] == 'grid':
                values = dict(self._drag_state.values)
                delta = np.asarray(point)-self._drag_position
                anchor = tuple(int(values[f'anchor_{i}']+delta[i]) for i in range(3))
                if any(not -32768 <= v <= 32767 for v in anchor):
                    raise ValueError('Grid anchor exceeds signed16')
                for spin, value in zip(self.anchor, anchor):
                    spin.setValue(value)
            else:
                if self.snap_points.isChecked() and getattr(self.viewport._drag, 'axis', None) != 1:
                    height = surface_snap(self.terrain, point, reference=self._drag_position, offset=self.height.value())
                    point = point[0], height, point[2]
                item = self.points.topLevelItem(self._drag_role[1])
                for i, value in enumerate(point, 1):
                    item.setText(i, str(value))
            self._loading = False
            self.invalidate(record=False)
            self._refresh_live()
        except ValueError as error:
            self.message.setText(str(error))
        finally:
            self._loading = False

    def _finish_drag(self, cancelled: bool) -> None:
        state, self._drag_state = self._drag_state, None
        if state is None:
            return
        if cancelled:
            self._restore(state)
        else:
            self._record_history()
            self.invalidate(record=False)
        self._drag_role = self._drag_position = None

    def build_preview(self) -> None:
        self.viewport.finish_object_drag()
        self._flush_history()
        self._refresh_live()
        self.plan = None
        if self._live_plan is None:
            return
        try:
            report = preview_course_plan(self.session, self._live_plan)
            self.plan = self._live_plan
            self.budget.setPlainText(report.to_text())
            self.message.setText('Review ready. Apply saves this course as one project undo step.')
        except (ValueError, OSError) as error:
            self.apply.setEnabled(False)
            self.message.setText(f'Course review rejected: {error}')

    def _focus(self, position: tuple[int, int, int]) -> None:
        p = np.asarray(position, np.float32)
        self.viewport.camera.fit_bounds(p-180, p+180, self.viewport.width()/max(self.viewport.height(), 1))
        self.viewport.update()

    def _focus_point(self) -> None:
        row = self.points.indexOfTopLevelItem(self.points.currentItem())
        if row >= 0:
            self._focus(self._draft()[row].position)

    def _focus_issue(self, item: QTreeWidgetItem, *_: object) -> None:
        keys = item.data(0, ROLE) or ()
        obj = next((o for o in (*getattr(self, '_issue_objects', ()), *self.preview_objects) if o.key in keys), None)
        if obj is not None:
            self._focus(obj.position)

    def _apply(self) -> None:
        self.build_preview()
        if self.plan is None:
            return
        try:
            self.session.apply_course_plan(self.plan)
            self.accept()
        except ValueError as error:
            self.message.setText(f'Apply rejected: {error}')
            self.apply.setEnabled(False)

    def _cleanup(self, *_: object) -> None:
        self.viewport._release_input()
        self._refresh_timer.stop()
        self._history_timer.stop()
        self.viewport._timer.stop()
        self.viewport.cleanup()
