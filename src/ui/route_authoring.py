"""Visual paired-alternate placement and staged lane finishing."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QLabel, QComboBox, QTreeWidget, QTreeWidgetItem, QPushButton, QCheckBox, QSpinBox, QTextEdit)

from src.core.course import CoursePlan, level_objects, plan_objects
from src.core.editing import EditSession
from src.core.objects import build_race_paths
from src.core.placement import TerrainSurface
from src.core.route_authoring import AlternatePoint, LaneOptions, build_route_plan
from src.core.textures import load_model_textures
from src.ui.course_builder import CourseViewport, PointDelegate

ROLE = int(Qt.ItemDataRole.UserRole)


class RouteAuthoringDialog(QDialog):
    def __init__(self, session: EditSession, level: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session, self.level = session, level
        self.header = session.level_header(level)
        self.original = level_objects(session, level)
        self.plan: CoursePlan | None = None
        self._loading = False
        self._closing = False
        self._drag_row = -1
        self._history: list[tuple[tuple[object, ...], ...]] = []
        self._cursor = 0
        self._drafts: dict[int, tuple[tuple[object, ...], ...]] = {}
        self._active_group: int | None = None
        model = session.track_model(self.header.geometry_id)
        self.terrain = TerrainSurface.from_model(model)
        self.setWindowTitle("Route finishing — alternates and AI lanes")
        self.resize(1350, 850)
        layout = QVBoxLayout(self)
        note = QLabel("Create alternates paired to main checkpoint indexes, then place them on the other road. The preview shows the branch entering and rejoining the main route and all four AI lanes. Apply checks and commits the entire draft as one undo step.", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        split = QSplitter(self)
        layout.addWidget(split, 1)
        left = QWidget(split)
        form = QVBoxLayout(left)
        self.group = QComboBox(left)
        for value in sorted({int(o.value("vehicleType")) for o in self.original if o.definition.behavior_id == 13}):
            self.group.addItem(f"Checkpoint set {value}", value)
        form.addWidget(self.group)
        self.first, self.last = QComboBox(left), QComboBox(left)
        row = QHBoxLayout()
        form.addLayout(row)
        row.addWidget(QLabel("Branch from / through", left))
        row.addWidget(self.first)
        row.addWidget(self.last)
        self.add = QPushButton("Create paired branch", left)
        self.add.clicked.connect(self.add_branch)
        form.addWidget(self.add)
        self.rows = QTreeWidget(left)
        self.rows.setHeaderLabels(("Main CP", "X", "Y", "Z"))
        self.rows.setRootIsDecorated(False)
        self.rows.setItemDelegate(PointDelegate(self.rows))
        self.rows.itemChanged.connect(self._edited)
        self.rows.currentItemChanged.connect(self._selected)
        form.addWidget(self.rows, 1)
        row = QHBoxLayout()
        form.addLayout(row)
        self.remove = QPushButton("Remove alternate", left)
        self.remove.clicked.connect(self.remove_row)
        row.addWidget(self.remove)
        self.undo = QPushButton("Undo branch edit", left)
        self.redo = QPushButton("Redo", left)
        self.undo.clicked.connect(lambda: self._travel(-1))
        self.redo.clicked.connect(lambda: self._travel(1))
        row.addWidget(self.undo)
        row.addWidget(self.redo)
        self.pick = QCheckBox("Click road to place selected alternate", left)
        self.pick.toggled.connect(self._picker)
        form.addWidget(self.pick)
        self.align = QCheckBox("Align alternate headings to branch direction", left)
        form.addWidget(self.align)
        self.lanes = QCheckBox("Generate four evenly spaced AI lanes", left)
        form.addWidget(self.lanes)
        row = QHBoxLayout()
        form.addLayout(row)
        self.width = QSpinBox(left)
        self.width.setRange(0, 2000)
        self.width.setValue(160)
        row.addWidget(QLabel("Lane half-width", left))
        row.addWidget(self.width)
        self.height = QSpinBox(left)
        self.height.setRange(-1000, 1000)
        self.height.setValue(32)
        row.addWidget(QLabel("Height above road", left))
        row.addWidget(self.height)
        self.follow = QCheckBox("Fit lane heights to nearby road", left)
        self.reset = QCheckBox("Reset lane behavior selectors to neutral", left)
        form.addWidget(self.follow)
        form.addWidget(self.reset)
        self.report = QTextEdit(left)
        self.report.setReadOnly(True)
        form.addWidget(self.report, 1)
        right = QWidget(split)
        preview = QVBoxLayout(right)
        self.view = QComboBox(right)
        self.view.addItems(("Perspective", "Top", "Front", "Right"))
        preview.addWidget(self.view)
        self.viewport = CourseViewport(right)
        self.viewport.set_model(model, load_model_textures(session.asset_source, model))
        self.viewport.set_catalog_caption('Route finishing', model.model_id)
        self.viewport.set_mouse_move_enabled(True)
        self.viewport.show_racelines = True
        self.viewport.surface_picked.connect(self._place)
        self.viewport.object_selected.connect(self._object_selected)
        self.viewport.object_drag_started.connect(self._begin_drag)
        self.viewport.object_drag_preview.connect(self._drag)
        self.viewport.object_drag_finished.connect(self._end_drag)
        self.view.currentTextChanged.connect(self.viewport.set_view)
        preview.addWidget(self.viewport, 3)
        self.issues = QTreeWidget(right)
        self.issues.setHeaderLabels(("Route readiness — double-click to focus",))
        self.issues.itemDoubleClicked.connect(self._focus_issue)
        preview.addWidget(self.issues, 1)
        split.setSizes((450, 850))
        row = QHBoxLayout()
        layout.addLayout(row)
        self.apply = QPushButton("Apply current checkpoint set", self)
        self.apply.clicked.connect(self.apply_plan)
        row.addWidget(self.apply)
        close = QPushButton("Cancel", self)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh_preview)
        self.group.currentIndexChanged.connect(self._load_set)
        for control in (self.align, self.lanes, self.follow, self.reset):
            control.toggled.connect(self._invalidate)
        for control in (self.width, self.height):
            control.valueChanged.connect(self._invalidate)
        self.finished.connect(self._cleanup)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self._load_set()

    def _load_set(self) -> None:
        if self._active_group is not None:
            self._drafts[self._active_group] = self._state()
        self._loading = True
        self.rows.clear()
        self.first.clear()
        self.last.clear()
        group = self.group.currentData()
        self._active_group = group
        main = sorted((o for o in self.original if o.definition.behavior_id == 13 and o.value("vehicleType") == group
                       and not o.value("isAltCheckpoint")), key=lambda o: o.value("index"))
        for obj in main:
            self.first.addItem(str(obj.value("index")), int(obj.value("index")))
            self.last.addItem(str(obj.value("index")), int(obj.value("index")))
        for obj in self.original:
            if obj.definition.behavior_id == 13 and obj.value("vehicleType") == group and obj.value("isAltCheckpoint"):
                self._row(AlternatePoint(int(obj.value("index")), obj.position, obj.key))
        if group in self._drafts:
            self.rows.clear()
            for values in self._drafts[group]:
                self._row(AlternatePoint(int(values[0]), tuple(int(x) for x in values[1:4]), values[4]))
        self._loading = False
        self._history = [self._state()]
        self._cursor = 0
        self._invalidate()

    def _row(self, point: AlternatePoint) -> None:
        item = QTreeWidgetItem((str(point.index), *(str(v) for v in point.position)))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, ROLE, point.key)
        self.rows.addTopLevelItem(item)

    def _state(self) -> tuple[tuple[object, ...], ...]:
        return tuple((*[self.rows.topLevelItem(i).text(c) for c in range(4)], self.rows.topLevelItem(i).data(0, ROLE)) for i in range(self.rows.topLevelItemCount()))

    def _edited(self, *_: object) -> None:
        if not self._loading:
            state = self._state()
            if state != self._history[self._cursor]:
                self._history[self._cursor + 1:] = [state]
                self._cursor += 1
            self._invalidate()

    def _travel(self, direction: int) -> None:
        target = self._cursor + direction
        if not 0 <= target < len(self._history):
            return
        self._cursor = target
        self._loading = True
        self.rows.clear()
        for value in self._history[target]:
            item = QTreeWidgetItem(tuple(str(v) for v in value[:4]))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(0, ROLE, value[4])
            self.rows.addTopLevelItem(item)
        self._loading = False
        self._invalidate()

    def add_branch(self) -> None:
        if self.first.currentData() is None:
            return
        low, high = self.first.currentData(), self.last.currentData()
        if low > high:
            self.report.setPlainText("Choose a forward index range. For a branch across CP0, create the end and start ranges separately.")
            return
        existing = {int(self.rows.topLevelItem(i).text(0)) for i in range(self.rows.topLevelItemCount())}
        self._loading = True
        for obj in sorted(self.original, key=lambda o: int(o.value("index", 0))):
            if obj.definition.behavior_id == 13 and obj.value("vehicleType") == self.group.currentData() and not obj.value("isAltCheckpoint") and low <= obj.value("index") <= high and obj.value("index") not in existing:
                self._row(AlternatePoint(int(obj.value("index")), obj.position))
        self._loading = False
        self._edited()
        self.rows.setCurrentItem(self.rows.topLevelItem(self.rows.topLevelItemCount() - 1))

    def remove_row(self) -> None:
        row = self.rows.indexOfTopLevelItem(self.rows.currentItem())
        if row >= 0:
            self.rows.takeTopLevelItem(row)
            self._edited()

    def _invalidate(self, *_: object) -> None:
        if self._closing:
            return
        self.plan = None
        self.apply.setEnabled(False)
        self.undo.setEnabled(self._cursor > 0)
        self.redo.setEnabled(self._cursor + 1 < len(self._history))
        self.timer.start(120)

    def refresh_preview(self) -> None:
        self.timer.stop()
        try:
            points = tuple(AlternatePoint(int(v[0]), tuple(int(x) for x in v[1:4]), v[4]) for v in self._state())
            lanes = LaneOptions(self.width.value(), self.follow.isChecked(), self.height.value(), self.reset.isChecked()) if self.lanes.isChecked() else None
            self.plan = build_route_plan(self.session, self.level, self.group.currentData(), self.header.object_map_id,
                                         points, lanes, align_alternates=self.align.isChecked())
            self.display = tuple(o for o in plan_objects(self.session, self.plan) if o.definition.behavior_id == 13 and o.value("vehicleType") == self.group.currentData())
            self.viewport.set_objects(self.display, build_race_paths(self.display, self.header.checkpoint_sets))
            self.viewport.set_labels(tuple((f"{'Alt' if o.value('isAltCheckpoint') else 'CP'} {o.value('index')}", o.position, "#b563bd" if o.value("isAltCheckpoint") else "#287b86") for o in self.display))
            self._selected()
            self.issues.clear()
            for issue in self.plan.issues:
                item = QTreeWidgetItem((issue.message,))
                item.setData(0, ROLE, issue.keys)
                self.issues.addTopLevelItem(item)
            self.report.setPlainText("\n".join(self.plan.changes) + "\nClick an alternate to select it; drag its handles or enable road placement. Main checkpoints remain protected here.")
            self.apply.setEnabled(self.plan.before != self.plan.after)
        except (ValueError, TypeError, OverflowError) as error:
            self.plan = None
            self.report.setPlainText(str(error))

    def _picker(self) -> None:
        self.viewport.finish_object_drag(cancel=True)
        self.viewport.surface_picker = self.terrain if self.pick.isChecked() else None

    def _selected(self, *_: object) -> None:
        item = self.rows.currentItem()
        if item is not None and hasattr(self, "display"):
            index = next((i for i, o in enumerate(self.display) if o.value("isAltCheckpoint") and o.value("index") == int(item.text(0))), -1)
            self.viewport.select_object(index)

    def _object_selected(self, index: int) -> None:
        if 0 <= index < len(self.display):
            obj = self.display[index]
            if obj.value("isAltCheckpoint"):
                for i in range(self.rows.topLevelItemCount()):
                    if int(self.rows.topLevelItem(i).text(0)) == obj.value("index"):
                        self.rows.setCurrentItem(self.rows.topLevelItem(i))

    def _place(self, position: tuple[float, float, float]) -> None:
        item = self.rows.currentItem()
        if item is None:
            return
        values = tuple(round(v) for v in position)
        values = values[0], values[1] + self.height.value(), values[2]
        self._loading = True
        for c, value in enumerate(values, 1):
            item.setText(c, str(value))
        self._loading = False
        self._edited()

    def _begin_drag(self, index: int) -> None:
        self._object_selected(index)
        self._drag_row = self.rows.indexOfTopLevelItem(self.rows.currentItem()) if 0 <= index < len(self.display) and self.display[index].value("isAltCheckpoint") else -1
        if self._drag_row < 0:
            self.viewport.finish_object_drag(cancel=True)
        self._drag_start = self._state()

    def _drag(self, position: tuple[int, int, int]) -> None:
        if self._drag_row < 0:
            return
        self._loading = True
        for c, value in enumerate(position, 1):
            self.rows.topLevelItem(self._drag_row).setText(c, str(value))
        self._loading = False
        self._invalidate()

    def _end_drag(self, cancelled: bool) -> None:
        if self._drag_row < 0:
            return
        self._drag_row = -1
        if cancelled:
            self._loading = True
            for i, values in enumerate(self._drag_start):
                for c in range(4):
                    self.rows.topLevelItem(i).setText(c, str(values[c]))
            self._loading = False
        self._edited()

    def _focus_issue(self, item: QTreeWidgetItem, *_: object) -> None:
        keys = item.data(0, ROLE) or ()
        obj = next((o for o in self.display if o.key in keys), None)
        if obj is not None:
            import numpy as np
            position = np.array(obj.position, float)
            self.viewport.camera.fit_bounds(position - 300, position + 300, self.viewport.width() / max(self.viewport.height(), 1))
            self.viewport.update()

    def apply_plan(self) -> None:
        self.refresh_preview()
        if self.plan is not None:
            try:
                self.session.apply_course_plan(self.plan)
                self.accept()
            except ValueError as error:
                self.report.append(str(error))

    def _cleanup(self, *_: object) -> None:
        self._closing = True
        self.timer.stop()
        self.viewport._release_input()
        self.viewport._timer.stop()
        self.viewport.cleanup()
