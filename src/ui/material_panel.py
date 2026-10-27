"""Selection-driven course materials with separate shared-asset drafts."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import numpy as np
from PySide6.QtCore import Qt, Signal, QModelIndex
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QCheckBox, QComboBox, QPushButton, QTreeWidget, QTreeWidgetItem, QTabWidget, QSpinBox,
    QDoubleSpinBox, QColorDialog, QAbstractItemView, QStyledItemDelegate,
    QStyleOptionViewItem, QToolButton, QHeaderView, QScrollArea)

from src.ui.deferred_edits import defer_edit
from src.core.level_model import LevelModel
from src.core.textures import Texture
from src.core.materials import MaterialEdit, TextureReference, BATCH_FLAGS, slot_uses, batch_for_face
from src.ui.material_picker import MaterialPicker, material_pixmap, surface_name

ROLE = int(Qt.ItemDataRole.UserRole)


class ValueDelegate(QStyledItemDelegate):
    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget | None:
        return super().createEditor(parent, option, index) if index.column() == 1 and index.data(ROLE + 1) else None


class MaterialPanel(QWidget):
    edit_requested = Signal(int, object, str)
    image_requested = Signal(int)
    revert_requested = Signal()
    selection_changed = Signal()
    focus_requested = Signal(int, int)
    preview_changed = Signal(object)
    prepare_edit = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model: LevelModel | None = None
        self.textures: Mapping[int, Texture] = {}
        self.refs: Sequence[TextureReference] = ()
        self.original: bytes | None = None
        self.loader: Callable[[int], Texture] | None = None
        self.flip: Callable[[int], bool] = lambda _: False
        self.levels: tuple[str, ...] = ()
        self.enabled = False
        self.key = (0, 0)
        self.slot = 0
        self._loading = False
        self._picker: MaterialPicker | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        contents = QWidget(scroll)
        scroll.setWidget(contents)
        layout = QVBoxLayout(contents)
        self.summary = QLabel('Select a level to edit its materials.', contents)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.pick = QCheckBox('Select batches in viewport', contents)
        self.pick.setChecked(True)
        self.pick.setToolTip('Click any visible face to select and highlight its entire batch.')
        self.pick.toggled.connect(self.selection_changed)
        layout.addWidget(self.pick)
        self.batch_title = QLabel(contents)
        self.batch_title.setWordWrap(True)
        layout.addWidget(self.batch_title)
        card = QHBoxLayout()
        self.thumbnail = QLabel(contents)
        self.thumbnail.setFixedSize(76, 76)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.addWidget(self.thumbnail)
        self.texture_info = QLabel(contents)
        self.texture_info.setWordWrap(True)
        self.texture_info.setTextFormat(Qt.TextFormat.PlainText)
        card.addWidget(self.texture_info, 1)
        layout.addLayout(card)
        self.change_material = QPushButton('Change this batch’s material…', contents)
        self.change_material.setObjectName('changeBatchMaterial')
        self.change_material.clicked.connect(lambda: self._open_picker(False))
        layout.addWidget(self.change_material)
        row = QHBoxLayout()
        self.focus = QPushButton('Focus', contents)
        self.focus.clicked.connect(lambda: self.focus_requested.emit(*self.key))
        self.isolate = QPushButton('Isolate batch', contents)
        self.isolate.setCheckable(True)
        self.isolate.setToolTip('Show only this track batch. Turn off to restore the course view.')
        self.isolate.toggled.connect(self.selection_changed)
        row.addWidget(self.focus); row.addWidget(self.isolate)
        layout.addLayout(row)
        self.shared = QPushButton('Edit shared material…', contents)
        self.shared.setObjectName('editSharedCourseMaterial')
        self.shared.clicked.connect(lambda: self._open_picker(True))
        layout.addWidget(self.shared)
        self.artwork = QPushButton('Edit texture image…', contents)
        self.artwork.clicked.connect(self._open_artwork)
        layout.addWidget(self.artwork)
        self.uses = QLabel(contents)
        self.uses.setWordWrap(True)
        layout.addWidget(self.uses)
        self.batches = QTreeWidget(contents)
        self.batches.setObjectName('courseBatches')
        self.batches.setHeaderLabels(['Segment / batch', 'Material'])
        self.batches.header().setStretchLastSection(False)
        self.batches.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.batches.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.batches.setMinimumHeight(120)
        self.batches.itemSelectionChanged.connect(self._batch_selected)
        self.batches.itemDoubleClicked.connect(self._batch_double_clicked)
        layout.addWidget(self.batches, 1)
        self.advanced_button = QToolButton(contents)
        self.advanced_button.setText('UVs, colors and rendering')
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._advanced_toggled)
        layout.addWidget(self.advanced_button)
        self.tabs = QTabWidget(contents)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self.selection_changed)
        self.tabs.hide()
        layout.addWidget(self.tabs)
        render = QWidget(self.tabs)
        render_layout = QVBoxLayout(render)
        frame_row = QHBoxLayout()
        frame_row.addWidget(QLabel('Frame offset', render))
        self.frame = QSpinBox(render)
        self.frame.setRange(0, 255)
        self.frame.setAccessibleName('Batch texture frame offset')
        self.frame.setToolTip('Stored byte: frame = offset >> 2 if in range; otherwise frame 0.')
        self.frame.editingFinished.connect(self._frame_changed)
        frame_row.addWidget(self.frame)
        render_layout.addLayout(frame_row)
        self.flags: dict[int, QCheckBox] = {}
        for mask, label in BATCH_FLAGS:
            checkbox = QCheckBox(label, render)
            checkbox.setToolTip(f'Stored flag 0x{mask:08X}. Other bits stay unchanged.')
            checkbox.clicked.connect(lambda checked, m=mask: self._flag_changed(m, checked))
            self.flags[mask] = checkbox
            render_layout.addWidget(checkbox)
        self.other_flags = QLabel(render)
        self.other_flags.setWordWrap(True)
        render_layout.addWidget(self.other_flags)
        render_layout.addStretch()
        self.tabs.addTab(render, 'Rendering')
        uv = QWidget(self.tabs)
        uv_layout = QVBoxLayout(uv)
        self.faces = QTreeWidget(uv)
        self.faces.setObjectName('trackFaceProperties')
        self.faces.setHeaderLabels(['Face', 'Raw corner UVs', 'Both sides'])
        self.faces.setColumnWidth(0, 45)
        self.faces.setColumnWidth(1, 170)
        self.faces.setItemDelegate(ValueDelegate(self.faces))
        self.faces.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.faces.itemChanged.connect(self._face_changed)
        self.faces.itemSelectionChanged.connect(self.selection_changed)
        uv_layout.addWidget(self.faces)
        hint = QLabel('Select faces below, then scale or offset their texture coordinates. Raw UVs use 32 units per texel.', uv)
        hint.setWordWrap(True)
        uv_layout.addWidget(hint)
        grid = QGridLayout()
        self.uv_u, self.uv_v, self.uv_scale = (QDoubleSpinBox(uv) for _ in range(3))
        for spin in (self.uv_u, self.uv_v):
            spin.setRange(-2048, 2048); spin.setDecimals(3)
        self.uv_scale.setRange(.001, 100); self.uv_scale.setDecimals(3); self.uv_scale.setValue(1)
        for i, (label, spin) in enumerate((('U offset (texels)', self.uv_u), ('V offset (texels)', self.uv_v), ('Texture scale', self.uv_scale))):
            grid.addWidget(QLabel(label, uv), i, 0); grid.addWidget(spin, i, 1)
        uv_layout.addLayout(grid)
        self.uv_apply = QPushButton('Apply UV transform', uv)
        self.uv_apply.clicked.connect(self._transform_uv)
        uv_layout.addWidget(self.uv_apply)
        all_faces = QPushButton('Select all faces in batch', uv)
        all_faces.clicked.connect(self.faces.selectAll)
        uv_layout.addWidget(all_faces)
        self.tabs.addTab(uv, 'UVs')
        colors = QWidget(self.tabs)
        color_layout = QVBoxLayout(colors)
        self.vertices = QTreeWidget(colors)
        self.vertices.setObjectName('trackVertexColors')
        self.vertices.setHeaderLabels(['Vertex', 'Stored R,G,B,A', 'XYZ'])
        self.vertices.setColumnWidth(0, 45); self.vertices.setColumnWidth(1, 150)
        self.vertices.setItemDelegate(ValueDelegate(self.vertices))
        self.vertices.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.vertices.itemChanged.connect(self._color_changed)
        self.vertices.itemSelectionChanged.connect(self.selection_changed)
        color_layout.addWidget(self.vertices)
        self.color = QPushButton('Color selected vertices…', colors)
        self.color.clicked.connect(self._choose_color)
        color_layout.addWidget(self.color)
        all_vertices = QPushButton('Select all vertices in batch', colors)
        all_vertices.clicked.connect(self.vertices.selectAll)
        color_layout.addWidget(all_vertices)
        note = QLabel('Colors are shared by faces using the same vertex. The game treats R=G=1 as a special alpha encoding.', colors)
        note.setWordWrap(True); color_layout.addWidget(note)
        self.tabs.addTab(colors, 'Colors')
        self.revert = QPushButton('Revert this course’s material edits', contents)
        self.revert.clicked.connect(self.revert_requested)
        layout.addWidget(self.revert)
        self.message = QLabel('Choose a batch or click the track. Material and shared-material dialogs preview changes before Apply. Advanced edits apply directly and support Ctrl+Z.', contents)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self._populate_batch()

    def _emit(self, edits: tuple[MaterialEdit, ...], label: str, *, model_id: int | None = None) -> None:
        if self.enabled and not self._loading and self.model is not None:
            self.edit_requested.emit(self.model.model_id if model_id is None else model_id, edits, label)

    def _frame_changed(self) -> None:
        if self.model and not self._loading:
            old = self.model.segments[self.key[0]].batches[self.key[1]].texture_offset
            if self.frame.value() != old:
                self._emit((MaterialEdit("frame", self.key, self.frame.value()),), "Change batch frame offset")

    def _flag_changed(self, mask: int, checked: bool) -> None:
        if self.model and not self._loading:
            value = self.model.segments[self.key[0]].batches[self.key[1]].flags
            self._emit((MaterialEdit("flags", self.key, (value | mask) if checked else value & ~mask),), "Change batch flag")

    def _face_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or not self.enabled:
            return
        key = tuple(item.data(0, ROLE))
        try:
            if column == 1:
                values = tuple(int(part.strip(), 0) if part.strip().lower().startswith(("0x", "-0x", "0b", "-0b")) else int(part.strip()) for part in item.text(1).split(","))
                edit = MaterialEdit("uv", key, values)
            elif column == 2:
                edit = MaterialEdit("backface", key, int(item.checkState(2) == Qt.CheckState.Checked))
            else:
                return
            model_id = self.model.model_id
            defer_edit(self, lambda: self._emit((edit,), "Change track face", model_id=model_id))
        except ValueError:
            self.message.setText("UVs require six comma-separated signed16 integers.")
            defer_edit(self, self._populate_batch)

    def _color_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or not self.enabled or column != 1:
            return
        try:
            edit = MaterialEdit("color", tuple(item.data(0, ROLE)), tuple(int(part.strip()) for part in item.text(1).split(",")))
            model_id = self.model.model_id
            defer_edit(self, lambda: self._emit((edit,), "Change vertex RGBA", model_id=model_id))
        except ValueError:
            self.message.setText("RGBA requires four comma-separated integers 0..255.")
            defer_edit(self, self._populate_batch)

    def _choose_color(self) -> None:
        keys = self.selected_vertices()
        if not keys or self.model is None:
            self.message.setText("Select one or more vertex rows first.")
            return
        raw = self.model.segments[keys[0][0]].colors[keys[0][1]]
        color = QColorDialog.getColor(QColor(*map(int, raw)), self, "Stored vertex RGBA", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            value = color.red(), color.green(), color.blue(), color.alpha()
            self._emit(tuple(MaterialEdit("color", key, value) for key in keys), "Color selected vertices")

    def _transform_uv(self) -> None:
        keys = self.selected_faces()
        if not keys or self.model is None:
            self.message.setText("Select one or more face rows first.")
            return
        offset = np.array([self.uv_u.value(), self.uv_v.value()]) * 32
        edits = tuple(MaterialEdit("uv", (segment, face), tuple(int(v) for v in np.rint(
            self.model.segments[segment].uvs[face] * self.uv_scale.value() + offset).reshape(-1))) for segment, face in keys)
        self._emit(edits, "Transform selected UVs")

    def selected_faces(self) -> tuple[tuple[int, int], ...]:
        return tuple(tuple(item.data(0, ROLE)) for item in self.faces.selectedItems())

    def selected_vertices(self) -> tuple[tuple[int, int], ...]:
        return tuple(tuple(item.data(0, ROLE)) for item in self.vertices.selectedItems())

    def _advanced_toggled(self, enabled: bool) -> None:
        self.tabs.setVisible(enabled)
        self.advanced_button.setArrowType(Qt.ArrowType.DownArrow if enabled else Qt.ArrowType.RightArrow)
        self.selection_changed.emit()

    def _batch_selected(self) -> None:
        item = self.batches.currentItem()
        if self._loading or item is None or item.data(0, ROLE) is None:
            return
        key = tuple(item.data(0, ROLE))
        if key != self.key:
            self.cancel_preview()
        self.key = key
        self._populate_batch()

    def _batch_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, ROLE) is not None:
            self.focus_requested.emit(*tuple(item.data(0, ROLE)))

    def _open_artwork(self) -> None:
        self.cancel_preview()
        if self.model is not None:
            slot = self.model.segments[self.key[0]].batches[self.key[1]].texture_index
            if slot < len(self.model.textures):
                self.image_requested.emit(self.model.textures[slot].texture_id)

    def _open_picker(self, shared: bool) -> None:
        self.prepare_edit.emit()
        if not self.enabled or self.model is None or self.loader is None or self.original is None:
            return
        slot = self.model.segments[self.key[0]].batches[self.key[1]].texture_index
        if shared and slot >= len(self.model.textures):
            return
        self.cancel_preview()
        self.slot = slot
        picker = MaterialPicker(self.model, self.original, self.refs, self.textures, self.key,
            shared=shared, loader=self.loader, flip=self.flip, levels=self.levels, parent=self.window())
        self._picker = picker
        index = self.model.model_id
        picker.preview_changed.connect(self.preview_changed)
        picker.edits_applied.connect(lambda edits, label: self.edit_requested.emit(index, edits, label))
        picker.shared_slot_changed.connect(self._shared_slot_changed)
        picker.finished.connect(lambda _: self._picker_finished(picker))
        picker.show()
        self.selection_changed.emit()

    def _shared_slot_changed(self, slot: int) -> None:
        self.slot = slot
        self.selection_changed.emit()

    def _picker_finished(self, picker: MaterialPicker) -> None:
        if self._picker is picker:
            self._picker = None
            self.preview_changed.emit(None)
            self._populate_batch()
        picker.deleteLater()

    def cancel_preview(self) -> None:
        if self._picker is not None:
            self._picker.reject()

    def highlighted_faces(self) -> tuple[tuple[int, int], ...]:
        if self.model is None or not self.model.segments[self.key[0]].batches:
            return ()
        if self._picker is not None and self._picker.shared:
            return tuple((s, face) for s, b, _ in slot_uses(self.model, self.slot)
                for face in range(self.model.segments[s].batches[b].faces_offset,
                                  (*self.model.segments[s].batches, self.model.segments[s].terminal_batch)[b+1].faces_offset))
        if self.advanced_button.isChecked() and self.tabs.currentIndex() == 1 and self.selected_faces():
            return self.selected_faces()
        segment = self.model.segments[self.key[0]]
        batch, end = (*segment.batches, segment.terminal_batch)[self.key[1]:self.key[1]+2]
        return tuple((segment.index, i) for i in range(batch.faces_offset, end.faces_offset))

    def highlighted_vertices(self) -> tuple[tuple[int, int], ...]:
        return self.selected_vertices() if self.advanced_button.isChecked() and self.tabs.currentIndex() == 2 else ()

    @property
    def isolated_batch(self) -> tuple[int, int] | None:
        # A shared edit must show every affected use, even after isolating one batch.
        if self._picker is not None and self._picker.shared:
            return None
        return self.key if self.isolate.isChecked() else None

    def pick_face(self, segment: int, face: int) -> None:
        if self.model is None:
            return
        self.cancel_preview()
        self.key = segment, batch_for_face(self.model, segment, face)
        self._select_batch_row()
        self._populate_batch()
        if self.advanced_button.isChecked() and self.tabs.currentIndex() == 1:
            for i in range(self.faces.topLevelItemCount()):
                item = self.faces.topLevelItem(i)
                if tuple(item.data(0, ROLE)) == (segment, face):
                    self.faces.setCurrentItem(item); self.faces.scrollToItem(item)
                    break
        self.selection_changed.emit()

    def _select_batch_row(self) -> None:
        self.batches.blockSignals(True)
        for i in range(self.batches.topLevelItemCount()):
            parent = self.batches.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if tuple(child.data(0, ROLE)) == self.key:
                    self.batches.setCurrentItem(child)
                    parent.setExpanded(True)
                    self.batches.scrollToItem(child)
        self.batches.blockSignals(False)

    def show_context(self, model: LevelModel | None, textures: Mapping[int, Texture], refs: Sequence[TextureReference],
                     levels: tuple[str, ...], enabled: bool, *, changed: bool = False,
                     original: bytes | None = None, loader: Callable[[int], Texture] | None = None,
                     flip: Callable[[int], bool] | None = None) -> None:
        same = self.model is not None and model is not None and self.model.model_id == model.model_id
        if self._picker is not None and (not same or self.model.raw_data != model.raw_data or self.textures is not textures):
            self.cancel_preview()
        self._loading = True
        self.model, self.textures, self.refs, self.enabled = model, textures, refs, enabled
        self.original, self.loader = original if original is not None else model.raw_data if model else None, loader
        self.flip, self.levels = flip or (lambda _: False), levels
        if not same:
            self.key = (0, 0)
            self.isolate.setChecked(False)
        expanded = {self.batches.topLevelItem(i).data(0, ROLE+1) for i in range(self.batches.topLevelItemCount())
                    if self.batches.topLevelItem(i).isExpanded()}
        self.batches.clear()
        if model is not None:
            self.summary.setText('Course materials · shared geometry: '+(', '.join(levels) or str(model.model_id)))
            icons: dict[int, QIcon] = {}
            for segment in model.segments:
                parent = QTreeWidgetItem([f'Segment {segment.index}'])
                parent.setData(0, ROLE+1, segment.index)
                self.batches.addTopLevelItem(parent)
                parent.setExpanded(segment.index in expanded)
                for i, batch in enumerate(segment.batches):
                    end = (*segment.batches, segment.terminal_batch)[i+1]
                    item = QTreeWidgetItem([f'Batch {i} · {end.faces_offset-batch.faces_offset} faces', str(batch.texture_index)])
                    item.setData(0, ROLE, (segment.index, i)); parent.addChild(item)
                    if batch.texture_index < len(model.textures):
                        tid = model.textures[batch.texture_index].texture_id
                        if tid in textures:
                            if tid not in icons:
                                icons[tid] = QIcon(material_pixmap(textures[tid], 28, self.flip(tid)))
                            item.setIcon(0, icons[tid])
                        item.setToolTip(1, f'Material {batch.texture_index} · texture {tid}')
            if not (0 <= self.key[0] < len(model.segments) and 0 <= self.key[1] < len(model.segments[self.key[0]].batches)):
                self.key = next(((s.index, 0) for s in model.segments if s.batches), (0, 0))
        else:
            self.summary.setText('Select a level to edit its materials.')
        self.revert.setEnabled(enabled and changed)
        self._loading = False
        self._select_batch_row()
        self._populate_batch()

    def _populate_batch(self) -> None:
        valid = self.model is not None and bool(self.model.segments[self.key[0]].batches)
        for widget in (self.change_material, self.focus, self.isolate, self.frame, self.uv_apply, self.color, *self.flags.values()):
            widget.setEnabled(valid and (self.enabled or widget in (self.focus, self.isolate)))
        self.shared.setEnabled(False); self.artwork.setEnabled(False)
        if not valid:
            self.faces.clear(); self.vertices.clear(); self.thumbnail.clear()
            self.texture_info.clear(); self.batch_title.setText('Click the track or choose a batch below.')
            self.uses.clear()
            return
        face_keys, vertex_keys = set(self.selected_faces()), set(self.selected_vertices())
        self.change_material.setEnabled(self.enabled and bool(self.model.textures))
        self._loading = True
        segment = self.model.segments[self.key[0]]
        batch, end = (*segment.batches, segment.terminal_batch)[self.key[1]:self.key[1]+2]
        self.batch_title.setText(f'Segment {segment.index} / batch {self.key[1]} · {end.faces_offset-batch.faces_offset} faces')
        self.slot = batch.texture_index if self._picker is None else self.slot
        self.thumbnail.clear()
        if batch.texture_index < len(self.model.textures):
            info = self.model.textures[batch.texture_index]
            texture = self.textures.get(info.texture_id)
            if texture:
                self.thumbnail.setPixmap(material_pixmap(texture, 72, self.flip(info.texture_id)))
            self.texture_info.setText(f'Texture {info.texture_id}\n{surface_name(info.surface_type)}\nMaterial {batch.texture_index}')
            uses = slot_uses(self.model, batch.texture_index)
            self.uses.setText(f'This material is shared by {len(uses)} batches / {sum(n for _,_,n in uses)} faces. Changing this batch’s assignment leaves those other batches unchanged.')
            self.shared.setEnabled(self.enabled)
            self.artwork.setEnabled(True)
        else:
            self.texture_info.setText('Untextured batch')
            self.uses.setText('Choose an existing course material to texture this batch.')
        self.frame.setValue(batch.texture_offset)
        for mask, checkbox in self.flags.items():
            checkbox.setChecked(bool(batch.flags & mask))
        self.other_flags.setText(f'Flags: 0x{batch.flags:08X}. Unknown bits, batch order and collision arrays remain protected.')
        self.faces.blockSignals(True); self.vertices.blockSignals(True)
        self.faces.clear(); self.vertices.clear()
        for i in range(batch.faces_offset, end.faces_offset):
            item = QTreeWidgetItem([str(i), ', '.join(map(str, segment.uvs[i].reshape(-1))), ''])
            item.setData(0, ROLE, (segment.index, i))
            if self.enabled:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
                item.setData(1, ROLE+1, True)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(2, Qt.CheckState.Checked if segment.triangle_flags[i] & 0x40 else Qt.CheckState.Unchecked)
            self.faces.addTopLevelItem(item)
            item.setSelected((segment.index, i) in face_keys)
        for i in range(batch.vertices_offset, end.vertices_offset):
            item = QTreeWidgetItem([str(i), ', '.join(map(str, segment.colors[i])), ', '.join(map(str, map(int, segment.vertices[i])))])
            item.setData(0, ROLE, (segment.index, i))
            if self.enabled:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setData(1, ROLE+1, True)
            self.vertices.addTopLevelItem(item)
            item.setSelected((segment.index, i) in vertex_keys)
        self.faces.blockSignals(False); self.vertices.blockSignals(False)
        self._loading = False
        self.selection_changed.emit()
