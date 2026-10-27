"""Existing lanes/connections, with explicit source identities and diagnostics."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
                               QCheckBox, QComboBox, QSpinBox, QGridLayout, QPushButton, QGroupBox)
from src.core.objects import LevelObject
from src.core.routes import LATERAL, HEIGHT, BEHAVIOR, route_diagnostics, route_label


class RoutePanel(QWidget):
    selected = Signal(object, bool)
    parameter_changed = Signal(object, str, object)
    connection_changed = Signal(object, int, int)
    preview_changed = Signal()
    pick_requested = Signal(int)
    build_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.obj: LevelObject | None = None
        self._context: object = None
        self._loading = False
        layout = QVBoxLayout(self)
        self.summary = QLabel("Select a checkpoint or AI node.", self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.course_builder=QPushButton('Course builder…',self)
        self.course_builder.setObjectName('openCourseBuilder')
        self.course_builder.clicked.connect(self.build_requested)
        layout.addWidget(self.course_builder)
        self.list = QTreeWidget(self)
        self.list.setHeaderLabels(["Existing routes", "Map / entry"])
        self.list.setColumnWidth(0, 230)
        self.list.itemClicked.connect(lambda item, _: self.selected.emit(item.data(0, Qt.ItemDataRole.UserRole), False))
        self.list.itemDoubleClicked.connect(lambda item, _: self.selected.emit(item.data(0, Qt.ItemDataRole.UserRole), True))
        layout.addWidget(self.list, 2)
        self.lanes = QGroupBox("Checkpoint lane controls", self)
        grid = QGridLayout(self.lanes)
        self.drag = QCheckBox("Drag lane points in viewport", self)
        self.drag.toggled.connect(self.preview_changed)
        grid.addWidget(self.drag, 0, 0, 1, 4)
        self.lane = QComboBox(self)
        self.lane.setAccessibleName("Route lane")
        for i in range(4):
            self.lane.addItem(f"Lane {i}", i)
        self.lane.currentIndexChanged.connect(self.preview_changed)
        grid.addWidget(self.lane, 1, 0, 1, 4)
        for column, title in enumerate(("Lane", "Lateral", "Height", "Behavior")):
            grid.addWidget(QLabel(title, self), 2, column)
        self.values: list[tuple[QSpinBox, ...]] = []
        for lane in range(4):
            grid.addWidget(QLabel(str(lane), self), 3 + lane, 0)
            spins = []
            for column, field in enumerate((LATERAL[lane], HEIGHT[lane], BEHAVIOR[lane]), 1):
                spin = QSpinBox(self)
                spin.setRange(-128, 127)
                spin.setAccessibleName(f"Lane {lane} {('lateral', 'height', 'behavior')[column - 1]}")
                spin.setToolTip(f"Stored signed8 field {field}; behavior is a selector, not flags.")
                spin.editingFinished.connect(lambda f=field, s=spin: self._parameter(f, s.value()))
                grid.addWidget(spin, 3 + lane, column)
                spins.append(spin)
            self.values.append(tuple(spins))
        layout.addWidget(self.lanes)
        self.links = QGroupBox("AI directed connections", self)
        link_layout = QGridLayout(self.links)
        self.targets: list[QComboBox] = []
        for slot in range(4):
            link_layout.addWidget(QLabel(f"Slot {slot}", self), slot, 0)
            combo = QComboBox(self)
            combo.setAccessibleName(f"AI connection slot {slot}")
            combo.activated.connect(lambda _, s=slot, c=combo: self.connection_changed.emit(self.obj.key, s, c.currentData()) if self.obj and not self._loading else None)
            self.targets.append(combo)
            link_layout.addWidget(combo, slot, 1)
            pick = QPushButton("Pick…", self)
            pick.clicked.connect(lambda _, s=slot: self.pick_requested.emit(s))
            link_layout.addWidget(pick, slot, 2)
        layout.addWidget(self.links)
        self.diagnostics = QTreeWidget(self)
        self.diagnostics.setHeaderLabels(["Graph diagnostics"])
        self.diagnostics.itemDoubleClicked.connect(self._diagnostic_selected)
        layout.addWidget(self.diagnostics, 1)
        self.message = QLabel("Lane drag edits lateral/height only; Ctrl snaps. AI links are directed; reciprocal slots are separate edits. IDs and counts are never renumbered.", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def _parameter(self, field: str, value: int) -> None:
        if not self._loading and self.obj and self.obj.value(field) != value:
            self.parameter_changed.emit(self.obj.key, field, value)

    def _diagnostic_selected(self, item: QTreeWidgetItem, column: int) -> None:
        keys = item.data(0, Qt.ItemDataRole.UserRole)
        if keys:
            self.selected.emit(keys[0], True)

    def show_context(self, objects: tuple[LevelObject, ...], obj: LevelObject | None,
                     sets: tuple[int, int, int], enabled: bool) -> None:
        self._loading = True
        self.course_builder.setEnabled(enabled)
        self.obj = obj
        key = tuple((o.key, o.position, o.parameters) for o in objects if o.definition.behavior_id in (13, 16)), sets
        if self._context != key:
            self._context = key
            scroll = self.list.verticalScrollBar().value()
            self.list.clear()
            for other in objects:
                if other.definition.behavior_id not in (13, 16):
                    continue
                item = QTreeWidgetItem([route_label(other, sets), f"{other.map_id} / {other.index}"])
                item.setData(0, Qt.ItemDataRole.UserRole, other.key)
                self.list.addTopLevelItem(item)
            self.list.verticalScrollBar().setValue(scroll)
            self.diagnostics.clear()
            for issue in route_diagnostics(objects, sets):
                item = QTreeWidgetItem([issue.message])
                item.setToolTip(0, issue.message + "\n" + issue.code + " · Existing warnings are reported, never repaired automatically.")
                item.setData(0, Qt.ItemDataRole.UserRole, issue.keys)
                self.diagnostics.addTopLevelItem(item)
            if not self.diagnostics.topLevelItemCount():
                self.diagnostics.addTopLevelItem(QTreeWidgetItem(["No duplicate indexes/IDs or dangling references found."]))
        is_checkpoint = obj is not None and obj.definition.behavior_id == 13
        is_ai = obj is not None and obj.definition.behavior_id == 16
        self.lanes.setVisible(is_checkpoint)
        self.links.setVisible(is_ai)
        self.lanes.setEnabled(enabled)
        self.links.setEnabled(enabled)
        self.summary.setText(f"{route_label(obj, sets)}\nMap {obj.map_id} / entry {obj.index}" if obj else "Select a checkpoint or AI node. Double-click a route or diagnostic to focus it.")
        if is_checkpoint:
            for i, spins in enumerate(self.values):
                for spin, field in zip(spins, (LATERAL[i], HEIGHT[i], BEHAVIOR[i])):
                    if not spin.hasFocus():
                        spin.setValue(obj.value(field))
        if is_ai:
            counts: dict[int, int] = {}
            for other in objects:
                if other.definition.behavior_id == 16:
                    node_id = other.value("nodeID")
                    counts[node_id] = counts.get(node_id, 0) + 1
            for slot, combo in enumerate(self.targets):
                combo.clear()
                combo.addItem("255 · No connection", 255)
                for node_id in sorted(n for n, count in counts.items() if 0 <= n < 128 and count == 1 and n != obj.value("nodeID")):
                    combo.addItem(f"AI {node_id}", node_id)
                current = obj.value("adjacent")[slot]
                if combo.findData(current) < 0:
                    combo.addItem(f"{current} · current (see diagnostics)", current)
                combo.setCurrentIndex(combo.findData(current))
        self._loading = False
