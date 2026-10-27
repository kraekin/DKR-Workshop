"""Project notes and read-only comparisons."""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QComboBox, QLineEdit,
                               QPlainTextEdit, QPushButton, QDialog, QTreeWidget, QTreeWidgetItem, QDialogButtonBox)
from src.core.editing import EditSession
from src.core.objects import LevelObject
from src.core.research import RESULTS, research_fields


class ResearchPanel(QWidget):
    note_changed = Signal(object, str, str, str)
    experiment_changed = Signal(str)
    compare_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session: EditSession | None = None
        self.obj: LevelObject | None = None
        self._field = ""
        self._loading = False
        self._pending = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Project label", self))
        self.experiment = QLineEdit(self)
        self.experiment.setMaxLength(200)
        self.experiment.setAccessibleName("Project label")
        self.experiment.editingFinished.connect(self.flush)
        layout.addWidget(self.experiment)
        self.title = QLabel("Select an object to annotate its fields.", self)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.field = QComboBox(self)
        self.field.setAccessibleName("Parameter")
        self.field.currentIndexChanged.connect(self._select_field)
        layout.addWidget(self.field)
        self.description = QLabel("", self)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.description)
        self.result = QComboBox(self)
        self.result.addItems(RESULTS)
        self.result.setAccessibleName("Observation")
        self.result.currentIndexChanged.connect(self._changed)
        layout.addWidget(self.result)
        self.note = QPlainTextEdit(self)
        self.note.setAccessibleName("Parameter note")
        self.note.setPlaceholderText("Record notes about this parameter. Notes are stored in the project and are not exported to the ROM.")
        self.note.textChanged.connect(self._changed)
        layout.addWidget(self.note, 1)
        self.apply = QPushButton("Apply note", self)
        self.apply.clicked.connect(self.flush)
        layout.addWidget(self.apply)
        compare = QPushButton("Compare project notes…", self)
        compare.clicked.connect(self.compare_requested)
        layout.addWidget(compare)
        self.message = QLabel("Source descriptions distinguish known, unknown and apparently unused fields. Observations do not replace source evidence. Notes apply on field/object change or project save; Ctrl+Z restores them.", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def _changed(self) -> None:
        if not self._loading:
            self._pending = True

    def flush(self) -> None:
        if self._loading or self.session is None:
            return
        if self.isHidden() and not self._pending:
            return
        self._loading = True
        try:
            if self.experiment.text() != self.session.experiment_name:
                self.experiment_changed.emit(self.experiment.text())
            if self._pending and self.obj and self._field:
                self._pending = False
                self.note_changed.emit(self.obj.key, self._field, self.note.toPlainText(), self.result.currentText())
        finally:
            self._loading = False

    def _select_field(self) -> None:
        if self._loading:
            return
        self.flush()
        self._field = str(self.field.currentData() or "")
        self._load_note()

    def _load_note(self) -> None:
        self._loading = True
        self._pending = False
        if self.obj:
            info = next((f for f in research_fields(self.obj) if f.key == self._field), None)
            if info:
                self.description.setText(f"{info.status} · offset 0x{info.offset:02X} · {info.size} byte(s)\nSource key: {info.key}\n{info.description}")
        else:
            self.description.setText("")
        value = self.session.note(self.obj.key, self._field) if self.session and self.obj else None
        self.note.setPlainText(value.text if value else "")
        self.result.setCurrentText(value.result if value else "Untested")
        self._loading = False

    def show_context(self, session: EditSession | None, obj: LevelObject | None) -> None:
        if self._loading:
            return
        same = self.session is session and (self.obj.key if self.obj else None) == (obj.key if obj else None)
        if not same:
            self.flush()
        elif self._pending:
            return  # Keep uncommitted text while selection/preview refreshes.
        self.session, self.obj = session, obj
        if self.isHidden():
            return  # Retired panel: retain session notes without rebuilding widgets.
        self._loading = True
        self.experiment.setEnabled(session is not None)
        if not self.experiment.hasFocus() or not same:
            self.experiment.setText(session.experiment_name if session else "")
        self.title.setText(f"{obj.definition.name} · map {obj.map_id} / entry {obj.index}" if obj else "Select an object to annotate its fields.")
        old_field = self._field
        self.field.clear()
        for field in research_fields(obj) if obj else ():
            self.field.addItem(f"0x{field.offset:02X} {field.label}", field.key)
        self.field.setCurrentIndex(max(0, self.field.findData(old_field)))
        self._field = str(self.field.currentData() or "")
        for widget in (self.field, self.result, self.note, self.apply):
            widget.setEnabled(session is not None and obj is not None)
        self._loading = False
        self._load_note()


class ComparisonDialog(QDialog):
    def __init__(self, rows: tuple[tuple[str, str, str, str], ...], saved_name: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project note comparison")
        self.resize(1100, 650)
        layout = QVBoxLayout(self)
        label = QLabel(f"Saved: {saved_name}\nCurrent: editor state · {len(rows)} differences. Read-only; no values are imported.", self)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Location", "Field", "Saved project", "Current editor"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 180)
        self.tree.setColumnWidth(2, 260)
        for row in rows:
            item = QTreeWidgetItem(list(row))
            for column, text in enumerate(row):
                item.setToolTip(column, text)
            self.tree.addTopLevelItem(item)
        layout.addWidget(self.tree)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
