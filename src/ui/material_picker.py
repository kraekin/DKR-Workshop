"""Visual batch assignments and shared course-material drafts."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QDialogButtonBox)

from src.core.level_model import LevelModel
from src.core.materials import (MaterialEdit, TextureReference, SURFACES, edit_materials,
                                slot_uses, texture_assignment_error)
from src.core.textures import Texture
from src.core.image_assets import png_rows
from src.ui.image_browser import image_pixmap

DATA = int(Qt.ItemDataRole.UserRole)


def surface_name(value: int) -> str:
    return SURFACES[value] if 0 <= value < len(SURFACES) else f'Unknown {value}'


def material_pixmap(texture: Texture, size: int, flip: bool = False) -> QPixmap:
    return image_pixmap(png_rows(texture.frames[0].pixels, flip_y=flip), QSize(size, size))


class MaterialPicker(QDialog):
    preview_changed = Signal(object)
    edits_applied = Signal(object, str)
    shared_slot_changed = Signal(int)

    def __init__(self, model: LevelModel, original: bytes, refs: Sequence[TextureReference],
                 textures: Mapping[int, Texture], key: tuple[int, int], *, shared: bool,
                 loader: Callable[[int], Texture], flip: Callable[[int], bool],
                 levels: tuple[str, ...] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Edit shared course material' if shared else 'Change this batch’s material')
        self.setObjectName('courseMaterialPicker')
        self.resize(850, 720)
        self.setMinimumSize(580, 480)
        self.model, self.original, self.refs, self.key = model, original, refs, key
        self.shared, self.loader, self.flip = shared, loader, flip
        self.textures = dict(textures)
        self.slot = model.segments[key[0]].batches[key[1]].texture_index
        self.levels = levels
        self.edits: tuple[MaterialEdit, ...] = ()
        self.draft: LevelModel | None = None
        self._icons: dict[int, QIcon] = {}
        self._loading = False
        self._icon_timer = QTimer(self)
        self._icon_timer.setSingleShot(True)
        self._icon_timer.timeout.connect(self._load_visible_icons)
        layout = QVBoxLayout(self)
        self.scope = QLabel(self)
        self.scope.setWordWrap(True)
        self.scope.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.scope)
        self.shared_slot = QComboBox(self)
        self.shared_slot.setAccessibleName('Shared course material to edit')
        for i, info in enumerate(model.textures):
            self.shared_slot.addItem(f'Material {i} · texture {info.texture_id} · {surface_name(info.surface_type)}', i)
        self.shared_slot.setCurrentIndex(self.shared_slot.findData(self.slot))
        self.shared_slot.setVisible(shared)
        self.shared_slot.currentIndexChanged.connect(self._shared_changed)
        layout.addWidget(self.shared_slot)
        row = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('Search texture ID, material, surface, format or dimensions…')
        self.search.setAccessibleName('Filter material thumbnails')
        row.addWidget(self.search, 1)
        self.dimensions = QComboBox(self)
        self.dimensions.addItem('All sizes', None)
        ids = range(len(refs)) if shared else sorted({info.texture_id for info in model.textures})
        for w, h in sorted({(refs[i].header.width, refs[i].header.height) for i in ids}):
            self.dimensions.addItem(f'{w}×{h}', (w, h))
        row.addWidget(self.dimensions)
        layout.addLayout(row)
        self.compatible = QCheckBox('Compatible choices only', self)
        self.compatible.setChecked(True)
        self.compatible.setToolTip('Uncheck to see disabled choices and the reason each one is incompatible.')
        layout.addWidget(self.compatible)
        self.choices = QListWidget(self)
        self.choices.setObjectName('courseMaterialChoices')
        self.choices.setViewMode(QListWidget.ViewMode.IconMode)
        self.choices.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.choices.setMovement(QListWidget.Movement.Static)
        self.choices.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.choices.setIconSize(QSize(88, 88))
        self.choices.setGridSize(QSize(150, 150))
        self.choices.setWordWrap(True)
        self.choices.setUniformItemSizes(True)
        self.choices.currentItemChanged.connect(self._selected)
        self.choices.verticalScrollBar().valueChanged.connect(lambda _: self._icon_timer.start(0))
        layout.addWidget(self.choices, 1)
        previews = QGridLayout()
        self.before, self.after = QLabel(self), QLabel(self)
        for column, (label, image) in enumerate((('Current', self.before), ('Preview', self.after))):
            previews.addWidget(QLabel(label, self), 0, column)
            image.setMinimumHeight(88)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            previews.addWidget(image, 1, column)
        layout.addLayout(previews)
        self.surface = QComboBox(self)
        self.surface.setAccessibleName('Shared material driving surface')
        for code, label in enumerate(SURFACES):
            self.surface.addItem(label, code)
        self.surface.setVisible(shared)
        self.surface.currentIndexChanged.connect(self._selected)
        surface_row = QHBoxLayout()
        surface_label = QLabel('Driving surface', self)
        surface_label.setVisible(shared)
        surface_row.addWidget(surface_label)
        surface_row.addWidget(self.surface, 1)
        layout.addLayout(surface_row)
        self.details = QLabel(self)
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel, self)
        self.apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAutoDefault(False)
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._filter)
        self.dimensions.currentIndexChanged.connect(self._filter)
        self.compatible.toggled.connect(self._filter)
        self._populate()

    def _populate(self) -> None:
        self._loading = True
        self.choices.clear()
        current = self.model.textures[self.slot] if self.slot < len(self.model.textures) else None
        uses = tuple((s, b) for s, b, _ in slot_uses(self.model, self.slot)) if self.shared else (self.key,)
        options = ((ref.texture_id, ref.texture_id, None) for ref in self.refs) if self.shared else (
            (i, info.texture_id, info.surface_type) for i, info in enumerate(self.model.textures) if i < 255)
        selected = None
        placeholder = QPixmap(88, 88)
        placeholder.fill(Qt.GlobalColor.transparent)
        for value, texture_id, surface in options:
            ref = self.refs[texture_id]
            header = ref.header
            reason = texture_assignment_error(self.model, self.refs, texture_id, uses)
            title = f'Texture {texture_id}' if self.shared else f'Material {value} · #{texture_id}'
            line = f'{header.width}×{header.height} {header.format.name}' if self.shared else surface_name(surface)
            item = QListWidgetItem(QIcon(placeholder), title+'\n'+line, self.choices)
            item.setData(DATA, value)
            item.setData(DATA+1, texture_id)
            item.setData(DATA+2, reason)
            item.setData(DATA+3, (header.width, header.height))
            item.setData(DATA+4, f'{title} {line} {header.width}x{header.height} {header.format.name}'.casefold())
            item.setToolTip(reason or f'{title}\n{line}\n{ref.label}')
            if reason:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            if current and value == (current.texture_id if self.shared else self.slot):
                selected = item
        self.surface.blockSignals(True)
        if current and self.surface.findData(current.surface_type) < 0:
            self.surface.addItem(surface_name(current.surface_type), current.surface_type)
        self.surface.setCurrentIndex(self.surface.findData(current.surface_type) if current else 0)
        self.surface.blockSignals(False)
        if current:
            try:
                self.before.setPixmap(material_pixmap(self._texture(current.texture_id), 112, self.flip(current.texture_id)))
            except (ValueError, OSError) as error:
                self.before.setText(f'Image unavailable: {error}')
        self._loading = False
        self._filter()
        self.choices.setCurrentItem(selected)
        if selected:
            self.choices.scrollToItem(selected)
        self._selected()

    def _shared_changed(self) -> None:
        if self._loading or self.shared_slot.currentData() is None:
            return
        self.slot = int(self.shared_slot.currentData())
        self.preview_changed.emit(None)
        self.shared_slot_changed.emit(self.slot)
        self._populate()

    def _texture(self, texture_id: int) -> Texture:
        if texture_id not in self.textures:
            self.textures[texture_id] = self.loader(texture_id)
        return self.textures[texture_id]

    def _filter(self, *_: object) -> None:
        text = self.search.text().casefold().replace('×', 'x')
        size = self.dimensions.currentData()
        for i in range(self.choices.count()):
            item = self.choices.item(i)
            item.setHidden(text not in item.data(DATA+4).replace('×', 'x') or
                           (size is not None and tuple(item.data(DATA+3)) != tuple(size)) or
                           (self.compatible.isChecked() and bool(item.data(DATA+2))))
        self._icon_timer.start(0)

    def _load_visible_icons(self) -> None:
        if not self.isVisible():
            return
        visible = self.choices.viewport().rect().adjusted(0, -150, 0, 150)
        count = 0
        for i in range(self.choices.count()):
            item = self.choices.item(i)
            if item.isHidden() or not self.choices.visualItemRect(item).intersects(visible):
                continue
            texture_id = int(item.data(DATA+1))
            if texture_id not in self._icons:
                try:
                    self._icons[texture_id] = QIcon(material_pixmap(self._texture(texture_id), 88, self.flip(texture_id)))
                except (ValueError, OSError) as error:
                    self._icons[texture_id] = QIcon()
                    item.setToolTip(item.toolTip()+f'\nImage unavailable: {error}')
                count += 1
            item.setIcon(self._icons[texture_id])
            if count >= 10:
                self._icon_timer.start(0)
                break

    def _selected(self, *_: object) -> None:
        if self._loading:
            return
        item = self.choices.currentItem()
        self.edits, self.draft = (), None
        self.apply.setEnabled(False)
        if item is None or item.data(DATA+2):
            self.preview_changed.emit(None)
            return
        old = self.model.textures[self.slot] if self.slot < len(self.model.textures) else None
        value, texture_id = int(item.data(DATA)), int(item.data(DATA+1))
        edits = ((MaterialEdit('texture', (self.slot,), value),
                  MaterialEdit('surface', (self.slot,), int(self.surface.currentData()))) if self.shared else
                 (MaterialEdit('batch_texture', self.key, value),))
        new_surface = int(self.surface.currentData()) if self.shared else self.model.textures[value].surface_type
        uses = slot_uses(self.model, self.slot) if self.shared else ()
        segment = self.model.segments[self.key[0]]
        batch, end = (*segment.batches, segment.terminal_batch)[self.key[1]:self.key[1]+2]
        faces = sum(n for _, _, n in uses) if self.shared else end.faces_offset-batch.faces_offset
        scope = f'Changes {len(uses)} batches / {faces} faces' if self.shared else f'Segment {self.key[0]} / batch {self.key[1]} · {faces} faces'
        self.scope.setText(scope+'\nShared course geometry: '+(', '.join(self.levels) or 'current course'))
        try:
            raw = edit_materials(self.model.raw_data, edits, self.refs, original=self.original)
            self.after.setPixmap(material_pixmap(self._texture(texture_id), 112, self.flip(texture_id)))
            self.details.setText(f'Texture {old.texture_id if old else "none"} → {texture_id}\n'
                f'Driving surface: {surface_name(old.surface_type) if old else "none"} → {surface_name(new_surface)}\n'
                'Preview only. Apply stores one undo step; Cancel restores the current material.')
            if raw != self.model.raw_data:
                self.edits = edits
                self.draft = LevelModel.from_bytes(raw, model_id=self.model.model_id)
                self.apply.setEnabled(True)
                self.preview_changed.emit((self.draft, self.textures))
            else:
                self.preview_changed.emit(None)
        except (ValueError, OSError) as error:
            self.details.setText(f'Cannot apply this choice: {error}')
            self.preview_changed.emit(None)

    def _apply(self) -> None:
        if self.draft is not None and self.edits:
            edits = self.edits
            self.accept()
            self.edits_applied.emit(edits, 'Edit shared course material' if self.shared else 'Change batch material')

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        self._icon_timer.start(0)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._icon_timer.start(0)

    def done(self, result: int) -> None:
        self._icon_timer.stop()
        super().done(result)
