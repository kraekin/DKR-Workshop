"""Tools for selected existing entries; no creation or duplication."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QCheckBox, QPushButton,
                               QSpinBox, QDoubleSpinBox, QComboBox, QHBoxLayout)
from src.core.objects import LevelObject
from src.core.placement import rotation_axes, can_scale


class PlacementPanel(QWidget):
    operation = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QLabel("Select objects with Ctrl-click, or Ctrl/Shift in the Objects list.", self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.group_properties = QCheckBox("Apply properties to selection", self)
        self.group_properties.setToolTip("Off: properties edit only the primary object. On: one atomic edit to a field shared by every selected type. Raw bytes/bits remain primary-only.")
        layout.addWidget(self.group_properties)
        self.grid = QCheckBox("Snap movement to Step", self)
        self.grid.setToolTip('Relative to the position at drag start.')
        layout.addWidget(self.grid)
        self.surface = QCheckBox("Snap dragged origins to track surface", self)
        self.surface.setToolTip("Snaps each selected origin to the highest rendered track surface at its X/Z, including water/roofs. Y-axis drags stay free. This is not the game's collision solver.")
        layout.addWidget(self.surface)
        row = QHBoxLayout()
        row.addWidget(QLabel("Surface height offset", self))
        self.offset = QSpinBox(self)
        self.offset.setRange(-32768, 32767)
        self.offset.setAccessibleName("Surface placement height offset")
        row.addWidget(self.offset)
        layout.addLayout(row)
        self.drop = QPushButton("Drop selected origins to track below", self)
        self.drop.clicked.connect(lambda: self.operation.emit("drop", None))
        layout.addWidget(self.drop)
        row = QHBoxLayout()
        self.align: list[QPushButton] = []
        for axis, name in enumerate("XYZ"):
            button = QPushButton(f"Align {name}", self)
            button.clicked.connect(lambda checked=False, a=axis: self.operation.emit("align", a))
            button.setToolTip("Align to the primary object's coordinate; one undo step.")
            row.addWidget(button)
            self.align.append(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.axis = QComboBox(self)
        self.axis.setAccessibleName("Stored rotation component")
        self.degrees = QDoubleSpinBox(self)
        self.degrees.setRange(-360, 360)
        self.degrees.setValue(15)
        self.degrees.setSuffix("°")
        self.rotate = QPushButton("Rotate", self)
        self.rotate.clicked.connect(lambda: self.operation.emit("rotate", (self.axis.currentData(), self.degrees.value())))
        row.addWidget(self.axis); row.addWidget(self.degrees); row.addWidget(self.rotate)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.factor = QDoubleSpinBox(self)
        self.factor.setRange(.01, 16)
        self.factor.setSingleStep(.1)
        self.factor.setValue(1)
        self.factor.setSuffix("×")
        self.factor.setAccessibleName("Selection scale factor")
        self.scale = QPushButton("Scale selection", self)
        self.scale.clicked.connect(lambda: self.operation.emit("scale", self.factor.value()))
        row.addWidget(self.factor); row.addWidget(self.scale)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.copy = QPushButton("Copy primary position", self)
        self.paste = QPushButton("Paste position", self)
        self.copy.clicked.connect(lambda: self.operation.emit("copy_position", None))
        self.paste.clicked.connect(lambda: self.operation.emit("paste_position", None))
        row.addWidget(self.copy); row.addWidget(self.paste)
        layout.addLayout(row)
        self.message = QLabel("Choose Move, Rotate or Scale beside Camera speed. Drag RGB arrows, rotation rings or the white scale handle. Ctrl during a drag snaps movement / 15° / 0.1×. Escape cancels.", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        hint = QLabel("The primary object is the pivot. Group rotation uses shared yaw; a single Animation controller also exposes pitch/roll components. Only verified stored transforms are enabled. Sprites still face the camera. No new entries are created.", self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8;")
        layout.addWidget(hint)
        layout.addStretch()
        self.set_selection((), False)

    def set_selection(self, objects: tuple[LevelObject, ...], enabled: bool) -> None:
        available = bool(objects) and enabled
        self.summary.setText(f"{len(objects)} selected · primary: {objects[0].definition.name} ({objects[0].key})" if objects else "Ctrl-click artwork/markers, or Ctrl/Shift-select list rows.")
        for widget in (self.drop, self.copy, self.paste, self.group_properties, self.grid, self.surface, self.offset):
            widget.setEnabled(available)
        for button in self.align:
            button.setEnabled(available and len(objects) > 1)
        selected_axis = self.axis.currentData()
        self.axis.clear()
        for axis in rotation_axes(objects):
            self.axis.addItem(("Pitch X", "Yaw Y", "Roll Z")[axis], axis)
        choice = self.axis.findData(selected_axis)
        if choice >= 0:
            self.axis.setCurrentIndex(choice)
        self.rotate.setEnabled(available and self.axis.count() > 0)
        self.axis.setEnabled(self.rotate.isEnabled())
        self.degrees.setEnabled(self.rotate.isEnabled())
        self.scale.setEnabled(available and can_scale(objects))
        self.factor.setEnabled(self.scale.isEnabled())
