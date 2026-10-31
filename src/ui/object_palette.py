"""Visual catalog of all translated types, preserving stock placement templates."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QShowEvent, QResizeEvent
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from src.core.editing import EditSession
from src.core.object_catalog import CatalogLibrary, artwork_bounds, template_object
from src.core.object_models import ModelInstance
from src.core.object_structure import ObjectTemplate
from src.core.textures import Pixels
from src.renderer.viewport import Viewport


def pixmap(pixels: Pixels) -> QPixmap:
    image = np.ascontiguousarray(pixels)
    return QPixmap.fromImage(QImage(image.data, image.shape[1], image.shape[0],
        image.strides[0], QImage.Format.Format_RGBA8888).copy())


def artwork_icon(pixels: Pixels | None, badge: str) -> QIcon:
    image = QPixmap(104, 104)
    image.fill(QColor('#172331'))
    painter = QPainter(image)
    if pixels is not None:
        painter.drawPixmap(4, 4, pixmap(pixels))
    else:
        painter.setPen(QColor('#8da9c4'))
        font = painter.font()
        font.setPointSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, badge)
    painter.end()
    return QIcon(image)


class ObjectPalette(QDialog):
    def __init__(self, session: EditSession, level_id: int, position: tuple[int, int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Add Objects — visual catalog')
        self.setObjectName('objectPalette')
        self.resize(1120, 780)
        self.setMinimumSize(860, 620)
        self.session = session
        self.templates = session.object_catalog
        self.library = CatalogLibrary(session.asset_source)
        self.objects = {t.object_id: template_object(session, t) for t in self.templates}
        self._thumbs: dict[tuple[int, int], QIcon] = {}
        self._pending: list[QListWidgetItem] = []
        self._loading = True
        self._closed = False
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._next_thumbnail)
        root = QVBoxLayout(self)
        split = QSplitter(self)
        root.addWidget(split, 1)
        left = QWidget(split)
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('Search objects by name, ID, category or behavior…')
        self.search.setAccessibleName('Filter object palette')
        layout.addWidget(self.search)
        row = QHBoxLayout()
        self.category = QComboBox(self)
        self.category.setAccessibleName('Object catalog category')
        self.category.addItem('All categories', '')
        for category in sorted({obj.category for obj in self.objects.values()}):
            self.category.addItem(category, category)
        row.addWidget(self.category, 1)
        self.count = QLabel(self)
        row.addWidget(self.count)
        layout.addLayout(row)
        self.list = QListWidget(self)
        self.list.setObjectName('objectPaletteList')
        self.list.setAccessibleName('Visual object catalog')
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setIconSize(QSize(104, 104))
        self.list.setGridSize(QSize(146, 155))
        self.list.setSpacing(4)
        self.list.setWordWrap(False)
        self.list.setUniformItemSizes(True)
        self.list.setStyleSheet('QListWidget::item { border-radius: 5px; padding: 4px; }'
            'QListWidget::item:hover { background: #293b50; }'
            'QListWidget::item:selected { background: #315c87; }')
        for template in self.templates:
            obj = self.objects[template.object_id]
            definition = obj.definition
            item = QListWidgetItem(artwork_icon(None, self._badge(definition.model_type)),
                f'{definition.name}\nID {template.object_id} · {obj.category}', self.list)
            item.setData(Qt.ItemDataRole.UserRole, template)
            item.setToolTip(f'{definition.name} · ID {template.object_id}\n{obj.category}\n'
                f'Header {definition.header_id} · {definition.behavior}\n{template.description}')
        layout.addWidget(self.list, 1)
        self.empty = QLabel('No matching objects. Change the search or category.', self)
        self.empty.setWordWrap(True)
        self.empty.hide()
        layout.addWidget(self.empty)
        right = QWidget(split)
        detail = QVBoxLayout(right)
        detail.setContentsMargins(8, 0, 0, 0)
        self.title = QLabel('Select an object', right)
        self.title.setStyleSheet('font-size: 18px; font-weight: 600;')
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        detail.addWidget(self.title)
        self.art_label = QLabel(right)
        self.art_label.setWordWrap(True)
        detail.addWidget(self.art_label)
        self.preview = QStackedWidget(right)
        self.preview.setMinimumSize(300, 240)
        self.viewport = Viewport(self.preview)
        self.viewport.setMinimumSize(300, 240)
        self.viewport.set_objects_visible(False)
        self.viewport.set_axes_visible(False)
        self.viewport.hud.hide()
        self.image = QLabel(self.preview)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setWordWrap(True)
        self.image.setStyleSheet('background: #172331; color: #9eb3ca; padding: 12px;')
        self.preview.addWidget(self.viewport)
        self.preview.addWidget(self.image)
        detail.addWidget(self.preview, 1)
        fit = QPushButton('Fit artwork preview', right)
        fit.clicked.connect(self.viewport.reset_camera)
        detail.addWidget(fit)
        self.preview_note = QLabel(right)
        self.preview_note.setWordWrap(True)
        detail.addWidget(self.preview_note)
        form = QFormLayout()
        self.map = QComboBox(self)
        self.map.setAccessibleName('New object map')
        header = session.level_header(level_id)
        for label, map_id in (('Collectables', header.object_map_id), ('Secondary', header.secondary_object_map_id)):
            if map_id >= 0 and self.map.findData(map_id) < 0:
                self.map.addItem(f'{label} / map {map_id}', map_id)
        form.addRow('Target map', self.map)
        coordinates = QHBoxLayout()
        self.coordinates: list[QSpinBox] = []
        for name, value in zip('XYZ', position):
            box = QSpinBox(self)
            box.setRange(-32768, 32767)
            box.setValue(value)
            box.setPrefix(name+' ')
            box.setAccessibleName(f'New object position {name}')
            self.coordinates.append(box)
            coordinates.addWidget(box)
        form.addRow('Position', coordinates)
        self.template_mode = QComboBox(self)
        self.template_mode.addItems(['Preferred template', 'Zeroed schema defaults'])
        self.template_mode.setAccessibleName('New object template mode')
        form.addRow('Parameters', self.template_mode)
        detail.addLayout(form)
        self.details = QLabel(self)
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        detail.addWidget(self.details)
        warning = QLabel('Artwork is a reference preview; helpers and runtime assemblies may look different in-game. '
            'Review copied node IDs, checkpoint order and links when adding objects.', self)
        warning.setWordWrap(True)
        root.addWidget(warning)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self)
        self.add_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add_button.setText('Add object')
        self.add_button.setDefault(False)
        self.add_button.setAutoDefault(False)
        self.add_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        for button in self.findChildren(QPushButton):
            button.setDefault(False)
            button.setAutoDefault(False)
        split.setSizes([650, 430])
        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)
        self.list.currentItemChanged.connect(self._details)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept() if self.add_button.isEnabled() else None)
        self.list.verticalScrollBar().valueChanged.connect(self._queue_thumbnails)
        self.map.currentIndexChanged.connect(self._details)
        self.template_mode.currentIndexChanged.connect(self._mode_changed)
        self._loading = False
        self._filter()

    @staticmethod
    def _badge(kind: int) -> str:
        return {0: '3D', 1: '2D', 2: '2D', 4: 'ART'}.get(kind, '◇')

    def _filter(self, *_args: object) -> None:
        needle, category = self.search.text().casefold().strip(), self.category.currentData()
        visible: list[QListWidgetItem] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            obj = self.objects[item.data(Qt.ItemDataRole.UserRole).object_id]
            hidden = bool(category and obj.category != category) or needle not in item.toolTip().casefold()
            item.setHidden(hidden)
            if not hidden:
                visible.append(item)
        self.count.setText(f'{len(visible)} / {len(self.templates)} objects')
        self.empty.setVisible(not visible)
        if self.list.currentItem() is None or self.list.currentItem().isHidden():
            self.list.setCurrentItem(visible[0] if visible else None)
        self._details()
        self._queue_thumbnails()

    def _mode_changed(self, *_args: object) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            obj = self.objects[item.data(Qt.ItemDataRole.UserRole).object_id]
            item.setIcon(self._thumbs.get((obj.object_id, self.template_mode.currentIndex()),
                artwork_icon(None, self._badge(obj.definition.model_type))))
        self._details()
        self._queue_thumbnails()

    def _queue_thumbnails(self, *_args: object) -> None:
        if self._loading or self._closed:
            return
        area = self.list.viewport().rect()
        self._pending = [self.list.item(i) for i in range(self.list.count())
            if not self.list.item(i).isHidden() and self.list.visualItemRect(self.list.item(i)).intersects(area)
            and (self.list.item(i).data(Qt.ItemDataRole.UserRole).object_id, self.template_mode.currentIndex()) not in self._thumbs]
        if self._pending:
            self._thumbnail_timer.start(0)

    def _next_thumbnail(self) -> None:
        if self._closed or not self._pending:
            return
        item = self._pending.pop(0)
        template = item.data(Qt.ItemDataRole.UserRole)
        if self.template_mode.currentIndex() == 1:
            template = ObjectTemplate(template.object_id)
        obj = template_object(self.session, template)
        try:
            pixels = self.library.thumbnail(self.library.artwork(obj))
        except (ValueError, OSError):
            pixels = None
        icon = artwork_icon(pixels, self._badge(obj.definition.model_type))
        self._thumbs[obj.object_id, self.template_mode.currentIndex()] = icon
        item.setIcon(icon)
        if self._pending:
            self._thumbnail_timer.start(0)

    def _details(self, *_args: object) -> None:
        if self._loading:
            return
        item = self.list.currentItem()
        selected = item is not None and not item.isHidden()
        self.add_button.setEnabled(selected and self.map.currentIndex() >= 0)
        self.viewport.set_model_instances(None, ())
        if not selected:
            self.title.setText('Select an object')
            self.art_label.clear()
            self.details.clear()
            self.preview_note.clear()
            self.image.setPixmap(QPixmap())
            self.image.setText('No matching object selected.')
            self.preview.setCurrentWidget(self.image)
            return
        template = self.template()
        obj = template_object(self.session, template)
        definition = obj.definition
        self.title.setText(definition.name)
        uses = [level.name for level in self.session._catalog.levels if self.map.currentData() in (
            self.session.level_header(level.index).object_map_id, self.session.level_header(level.index).secondary_object_map_id)]
        self.details.setText(f'Object {obj.object_id} · header {definition.header_id}\n{obj.category} · {definition.behavior}\n'
            f'{template.description}; {len(template.raw(self.session))} entry bytes.\nShared map affects: {", ".join(uses)}.')
        try:
            art = self.library.artwork(obj)
            self.art_label.setText(art.label)
            self.preview_note.setText(art.note)
            if art.model is not None:
                model = art.model
                instance = ModelInstance(0, definition, model.mesh.model_id, (0., 0., 0.), 1., (0., 0., 0.), clip_index=-1)
                self.viewport.set_model_instances(self.library.models, (instance,))
                bounds = artwork_bounds(model)
                self.viewport.bounds_min = np.array(bounds.minimum, np.float32)
                self.viewport.bounds_max = np.array(bounds.maximum, np.float32)
                self.viewport.reset_camera()
                self.preview.setCurrentWidget(self.viewport)
            else:
                self.image.setPixmap(pixmap(art.pixels).scaled(330, 280, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation) if art.pixels is not None else QPixmap())
                if art.pixels is None:
                    self.image.setText(art.note)
                self.preview.setCurrentWidget(self.image)
        except (ValueError, OSError) as error:
            self.art_label.setText('Artwork preview unavailable')
            self.preview_note.setText(str(error))
            self.image.setPixmap(QPixmap())
            self.image.setText('This object can still be added using its template.')
            self.preview.setCurrentWidget(self.image)

    def template(self) -> ObjectTemplate:
        value = self.list.currentItem().data(Qt.ItemDataRole.UserRole)
        return ObjectTemplate(value.object_id) if self.template_mode.currentIndex() == 1 else value

    def position(self) -> tuple[int, int, int]:
        return tuple(box.value() for box in self.coordinates)

    def accept(self) -> None:
        if self.add_button.isEnabled():
            super().accept()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._closed = False
        self.viewport._timer.start()
        self._queue_thumbnails()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, 'list'):
            QTimer.singleShot(0, self._queue_thumbnails)

    def done(self, result: int) -> None:
        self._closed = True
        self._thumbnail_timer.stop()
        self._pending.clear()
        self.viewport._timer.stop()
        super().done(result)
