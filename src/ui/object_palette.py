"""All translated object IDs, stock template provenance and explicit placement."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from src.core.editing import EditSession
from src.core.object_structure import ObjectTemplate


class ObjectPalette(QDialog):
    def __init__(self, session: EditSession, level_id: int, position: tuple[int, int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Add object - full catalog')
        self.setObjectName('objectPalette')
        self.resize(700, 640)
        self.session = session
        self.templates = session.object_catalog
        layout = QVBoxLayout(self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('Filter all object types by name, ID or behavior...')
        self.search.setAccessibleName('Filter object palette')
        layout.addWidget(self.search)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName('objectPaletteList')
        self.tree.setHeaderLabels(['Object', 'ID', 'Template'])
        self.tree.setColumnWidth(0, 260)
        self.tree.setRootIsDecorated(False)
        for template in self.templates:
            definition = session.database.resolve(template.object_id)
            item = QTreeWidgetItem([definition.name, str(template.object_id), template.description])
            item.setData(0, Qt.ItemDataRole.UserRole, template)
            item.setToolTip(0, f'Header {definition.header_id} / {definition.behavior}')
            self.tree.addTopLevelItem(item)
        layout.addWidget(self.tree, 1)
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
            box.setPrefix(name + ' ')
            box.setAccessibleName(f'New object position {name}')
            self.coordinates.append(box)
            coordinates.addWidget(box)
        form.addRow('Position', coordinates)
        self.template_mode = QComboBox(self)
        self.template_mode.addItems(['Preferred template', 'Zeroed schema defaults'])
        self.template_mode.setAccessibleName('New object template mode')
        form.addRow('Parameters', self.template_mode)
        layout.addLayout(form)
        self.details = QLabel(self)
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.details)
        warning = QLabel('Choose an object type and destination map. Types without stock templates use default parameters. '
            'Review copied node IDs, checkpoint order and links before applying.', self)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self)
        self.add_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add_button.setText('Add object')
        self.add_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(self._details)
        self.tree.itemDoubleClicked.connect(lambda *_: self.accept() if self.add_button.isEnabled() else None)
        self.map.currentIndexChanged.connect(self._details)
        self.template_mode.currentIndexChanged.connect(self._details)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _filter(self, value: str) -> None:
        needle = value.casefold().strip()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item.setHidden(needle not in ' '.join((item.text(0), item.text(1), item.toolTip(0))).casefold())
        self._details()

    def _details(self, *_args: object) -> None:
        item = self.tree.currentItem()
        self.add_button.setEnabled(item is not None and not item.isHidden() and self.map.currentIndex() >= 0)
        if item is None:
            self.details.clear()
            return
        template = self.template()
        definition = self.session.database.resolve(template.object_id)
        uses = [level.name for level in self.session._catalog.levels if self.map.currentData() in (
            self.session.level_header(level.index).object_map_id, self.session.level_header(level.index).secondary_object_map_id)]
        self.details.setText(f'{definition.name} / {definition.behavior}\n{template.description}; '
            f'{len(template.raw(self.session))} entry bytes. Shared map affects: {", ".join(uses)}.')

    def template(self) -> ObjectTemplate:
        value = self.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
        return ObjectTemplate(value.object_id) if self.template_mode.currentIndex() == 1 else value

    def position(self) -> tuple[int, int, int]:
        return tuple(box.value() for box in self.coordinates)
