"""Existing track vertex/face selection and constrained XYZ edits."""
from __future__ import annotations

from src.ui.deferred_edits import defer_edit

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QCheckBox, QComboBox, QTreeWidget, QTreeWidgetItem, QSpinBox, QPushButton, QAbstractItemView, QHeaderView)

from src.core.level_model import LevelModel
from src.core.geometry import GeometryProfile, VertexKey, linked_vertices, selection_center
from src.core.materials import batch_for_face
from src.ui.material_panel import ValueDelegate, ROLE


class GeometryPanel(QWidget):
    selection_changed = Signal()
    move_requested = Signal(int, object, object)
    revert_requested = Signal()
    focus_requested = Signal()
    material_requested = Signal(int, int)
    rebuild_requested = Signal()
    import_requested = Signal()
    stock_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model: LevelModel | None = None
        self.profile: GeometryProfile | None = None
        self.enabled = False
        self._loading = False
        layout = QVBoxLayout(self)
        self.summary = QLabel('Select a level to reshape its existing geometry.', self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.segment = QComboBox(self)
        self.segment.setAccessibleName('Geometry segment')
        self.segment.currentIndexChanged.connect(self.populate)
        row.addWidget(self.segment, 1)
        self.mode = QComboBox(self)
        self.mode.setAccessibleName('Geometry selection mode')
        self.mode.addItems(('Vertices', 'Faces'))
        self.mode.currentIndexChanged.connect(self.populate)
        row.addWidget(self.mode)
        layout.addLayout(row)
        self.pick = QCheckBox('Select and move geometry in viewport', self)
        self.pick.setChecked(True)
        self.pick.toggled.connect(self.selection_changed)
        layout.addWidget(self.pick)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName('trackGeometry')
        self.tree.setAccessibleName('Track geometry vertices or faces')
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setItemDelegate(ValueDelegate(self.tree))
        self.tree.itemSelectionChanged.connect(self._selected)
        self.tree.itemChanged.connect(self._coordinate_changed)
        self.tree.itemDoubleClicked.connect(lambda _, column: self.focus_requested.emit() if column == 0 else None)
        self.tree.setColumnWidth(0, 55)
        self.tree.setColumnWidth(1, 190)
        layout.addWidget(self.tree, 1)
        self.selection = QLabel('Select vertices or faces. Ctrl/Shift selects multiple rows.', self)
        self.selection.setWordWrap(True)
        layout.addWidget(self.selection)
        grid = QGridLayout()
        self.coordinates: list[QSpinBox] = []
        self.nudges: list[QPushButton] = []
        for axis, name in enumerate('XYZ'):
            spin = QSpinBox(self)
            spin.setRange(-32768, 32767)
            spin.setPrefix(name+' ')
            spin.setAccessibleName(f'Geometry selection center {name}')
            spin.setKeyboardTracking(False)
            spin.editingFinished.connect(lambda a=axis: self._center_changed(a))
            self.coordinates.append(spin)
            grid.addWidget(spin, axis, 0)
            for column, sign in enumerate((-1, 1)):
                button = QPushButton(name+('−' if sign < 0 else '+'), self)
                button.setAccessibleName(f'Move geometry {name} {"negative" if sign < 0 else "positive"}')
                button.setFixedWidth(42)
                button.clicked.connect(lambda _, a=axis, d=sign: self._nudge(a, d))
                self.nudges.append(button)
                grid.addWidget(button, axis, 1+column)
        layout.addLayout(grid)
        row = QHBoxLayout()
        self.step = QSpinBox(self)
        self.step.setRange(1, 1024)
        self.step.setValue(16)
        self.step.setPrefix('Step ')
        self.step.setAccessibleName('Geometry movement step')
        self.step.valueChanged.connect(lambda _: self.selection_changed.emit())
        row.addWidget(self.step)
        self.focus = QPushButton('Focus selection', self)
        self.focus.clicked.connect(self.focus_requested)
        row.addWidget(self.focus)
        layout.addLayout(row)
        self.material = QPushButton('Edit face material…', self)
        self.material.setToolTip('Open Geometry → Materials for the selected face’s batch. Texture changes affect its entire batch.')
        self.material.clicked.connect(self._open_material)
        self.material.setEnabled(False)
        layout.addWidget(self.material)
        self.revert = QPushButton('Revert this model’s geometry', self)
        self.revert.clicked.connect(self.revert_requested)
        layout.addWidget(self.revert)
        self.message = QLabel('Edits stay within existing segments; linked vertices move together. Generated water and unresolved collision links are protected. Use OBJ import to replace track topology.', self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        self.import_obj = QPushButton('Import OBJ…', self)
        self.import_obj.setObjectName('importTrackObj')
        self.import_obj.clicked.connect(self.import_requested)
        self.import_obj.setEnabled(False)
        row.addWidget(self.import_obj)
        self.stock = QPushButton('Restore stock track', self)
        self.stock.setObjectName('restoreStockTrack')
        self.stock.clicked.connect(self.stock_requested)
        self.stock.setEnabled(False)
        self.stock.setToolTip('Restore the original ROM model, including its materials, geometry and minimap settings. One undo step.')
        row.addWidget(self.stock)
        layout.addLayout(row)
        self.rebuild = QPushButton('Verify stock rebuild…', self)
        self.rebuild.setToolTip('Reconstruct original track records, inspect collision and memory budgets, and optionally export an unmodified stock rebuild.')
        self.rebuild.clicked.connect(self.rebuild_requested)
        self.rebuild.setEnabled(False)
        layout.addWidget(self.rebuild)

    def selected_faces(self) -> tuple[tuple[int, int], ...]:
        return tuple(tuple(i.data(0, ROLE)) for i in self.tree.selectedItems()) if self.mode.currentIndex() == 1 else ()

    def _open_material(self) -> None:
        faces = self.selected_faces()
        if faces:
            self.material_requested.emit(*faces[0])

    def selected_vertices(self) -> tuple[VertexKey, ...]:
        if self.model is None:
            return ()
        if self.mode.currentIndex() == 0:
            return tuple(tuple(i.data(0, ROLE)) for i in self.tree.selectedItems())
        return tuple(sorted({(s, int(v)) for s, f in self.selected_faces() for v in self.model.segments[s].indices[f]}))

    def show_context(self, model: LevelModel | None, profile: GeometryProfile | None,
                     levels: tuple[str, ...], enabled: bool, changed: bool) -> None:
        same = self.model is not None and model is not None and self.model.model_id == model.model_id
        selected = {tuple(i.data(0, ROLE)) for i in self.tree.selectedItems()} if same else set()
        segment = self.segment.currentData() if same else 0
        self._loading = True
        self.model, self.profile, self.enabled = model, profile, enabled and profile is not None
        self.rebuild.setEnabled(enabled and model is not None)
        self.import_obj.setEnabled(enabled and model is not None)
        self.segment.clear()
        if model is not None:
            for s in model.segments:
                self.segment.addItem(f'Segment {s.index} · {s.vertex_count} vertices', s.index)
            self.segment.setCurrentIndex(max(0, self.segment.findData(segment)))
            self.summary.setText(f'Model {model.model_id} · existing topology\nShared levels: '+(', '.join(levels) or 'none'))
        else:
            self.summary.setText('Select a level to reshape its existing geometry.')
        self.revert.setEnabled(self.enabled and changed)
        self._loading = False
        self.populate(selected=selected)

    def populate(self, *_: object, selected: set[VertexKey] | None = None) -> None:
        if self._loading:
            return
        self._loading = True
        self.tree.clear()
        vertices = self.mode.currentIndex() == 0
        self.tree.setHeaderLabels(['Vertex', 'X, Y, Z', 'Linked'] if vertices else ['Face', 'Vertices', 'Batch'])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        if self.model is not None and self.segment.currentData() is not None:
            s = self.model.segments[int(self.segment.currentData())]
            for i in range(s.vertex_count if vertices else s.triangle_count):
                key = s.index, i
                if vertices:
                    point = tuple(map(int, s.vertices[i]))
                    group = self.profile.groups[tuple(map(int, self.profile.model.segments[s.index].vertices[i]))] if self.profile else ()
                    reason = next((self.profile.locked[k] for k in group if k in self.profile.locked), '') if self.profile else ''
                    item = QTreeWidgetItem([str(i), ', '.join(map(str, point)), str(len(group))])
                    item.setToolTip(1, reason or 'Double-click XYZ, or drag the selection’s arrows in the viewport.')
                    if self.enabled:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        item.setData(1, ROLE+1, True)
                else:
                    item = QTreeWidgetItem([str(i), ', '.join(map(str, s.indices[i])), str(batch_for_face(self.model, s.index, i))])
                item.setData(0, ROLE, key)
                self.tree.addTopLevelItem(item)
                item.setSelected(key in (selected or set()))
        self._loading = False
        self._selected()

    def _selected(self) -> None:
        if self._loading:
            return
        keys = self.selected_vertices()
        valid = self.enabled and bool(keys)
        if keys and self.model is not None:
            center = selection_center(self.model, keys)
            for spin, value in zip(self.coordinates, center):
                spin.setValue(value)
            linked = linked_vertices(self.profile, keys) if self.profile else keys
            self.selection.setText(f'{len(keys)} selected vertices · {len(linked)} linked copies. XYZ controls translate their rounded center.')
        else:
            self.selection.setText('Select vertices or faces. Ctrl/Shift selects multiple rows.')
        for widget in (*self.coordinates, *self.nudges, self.focus):
            widget.setEnabled(valid)
        self.material.setEnabled(bool(self.selected_faces()))
        self.selection_changed.emit()

    def preview(self, model: LevelModel) -> None:
        """Update the current table without repopulating other asset editors."""
        self.model = model
        self._loading = True
        if self.mode.currentIndex() == 0:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                segment, vertex = item.data(0, ROLE)
                item.setText(1, ', '.join(map(str,map(int,model.segments[segment].vertices[vertex]))))
        self._loading = False
        self._selected()

    def pick_item(self, segment: int, index: int, additive: bool = False) -> None:
        if self.model is None:
            return
        self.segment.setCurrentIndex(self.segment.findData(segment))
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if tuple(item.data(0, ROLE)) == (segment, index):
                if not additive:
                    self.tree.clearSelection()
                item.setSelected(not item.isSelected() if additive else True)
                self.tree.scrollToItem(item)
                break

    def _nudge(self, axis: int, sign: int) -> None:
        delta = tuple(sign*self.step.value() if i == axis else 0 for i in range(3))
        if self.model is not None:
            self.move_requested.emit(self.model.model_id, self.selected_vertices(), delta)

    def _center_changed(self, axis: int) -> None:
        keys = self.selected_vertices()
        if self._loading or self.model is None or not keys:
            return
        center = selection_center(self.model, keys)
        amount = self.coordinates[axis].value()-center[axis]
        if amount:
            self._loading = True
            try:
                self.move_requested.emit(self.model.model_id, keys, tuple(amount if i == axis else 0 for i in range(3)))
            finally:
                self._loading = False

    def _coordinate_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or not self.enabled or self.model is None or column != 1 or self.mode.currentIndex() != 0:
            return
        try:
            position = tuple(int(p.strip()) for p in item.text(1).split(','))
            if len(position) != 3:
                raise ValueError('Expected three coordinates')
            key = tuple(item.data(0, ROLE))
            current = tuple(map(int, self.model.segments[key[0]].vertices[key[1]]))
            delta = tuple(a-b for a, b in zip(position, current))
            model_id = self.model.model_id
            defer_edit(self, lambda: self.move_requested.emit(model_id, (key,), delta))
        except ValueError:
            self.message.setText('XYZ requires three comma-separated signed16 integers.')
            defer_edit(self, self.populate)
