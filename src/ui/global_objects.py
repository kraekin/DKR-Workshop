"""Separate shared-definition editor with isolated drafts and staged Apply."""
from __future__ import annotations

import struct
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QHeaderView, QSplitter,
    QPushButton, QPlainTextEdit, QTabWidget, QDialogButtonBox, QComboBox, QSizePolicy)

from src.core.editing import EditSession
from src.core.global_objects import (FIELDS, FIELD_BY_KEY, MODEL_TYPES, GlobalObjectPlan,
    edit_definition, definition_changes, definition_uses, plan_global_objects)
from src.core.objects import ObjectDefinition
from src.core.rom import AssetType
from src.ui.material_panel import ValueDelegate, ROLE


class GlobalObjectsDialog(QDialog):
    definitions_changed = Signal()
    history_requested = Signal(bool)

    def __init__(self, session: EditSession, selected: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('globalObjectsDialog')
        self.setWindowTitle('Global Object Properties — USA Rev 1')
        self.resize(1120, 820)
        self.session = session
        self.current = selected
        self.drafts: dict[int, bytes] = {}
        self.plan: GlobalObjectPlan | None = None
        self._loading = False
        self.uses = definition_uses(session)
        layout = QVBoxLayout(self)
        intro = QLabel('Edit shared object definitions. Changes affect every use of a header, including other levels. '
            'Double-click a property value to edit. Preview and Apply drafts, then save a project and export your ROM. '
            'Closing discards unapplied drafts.', self)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        split = QSplitter(self)
        layout.addWidget(split, 1)
        left = QWidget(split)
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 6, 0)
        self.search = QLineEdit(left)
        self.search.setPlaceholderText('Filter name, header, object ID or behavior…')
        self.search.setAccessibleName('Filter global object definitions')
        col.addWidget(self.search)
        self.list = QTreeWidget(left)
        self.list.setObjectName('globalObjectList')
        self.list.setHeaderLabels(('Header', 'Shared definition', 'Artwork'))
        self.list.setRootIsDecorated(False)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        col.addWidget(self.list, 1)
        right = QWidget(split)
        form = QVBoxLayout(right)
        form.setContentsMargins(6, 0, 0, 0)
        self.caption = QLabel(right)
        self.caption.setWordWrap(True)
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        form.addWidget(self.caption)
        self.tabs = QTabWidget(right)
        form.addWidget(self.tabs, 2)
        self.properties = QTreeWidget(right)
        self.properties.setObjectName('globalObjectProperties')
        self.properties.setHeaderLabels(('Property / offset', 'Value'))
        self.properties.setRootIsDecorated(False)
        self.properties.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.properties.setColumnWidth(1, 130)
        self.properties.setItemDelegate(ValueDelegate(self.properties))
        self.tabs.addTab(self.properties, 'Properties')
        self.artwork = QTreeWidget(right)
        self.artwork.setObjectName('globalObjectArtwork')
        self.artwork.setHeaderLabels(('Slot', 'Existing artwork ID / known owners'))
        self.artwork.setRootIsDecorated(False)
        self.artwork.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.artwork.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.artwork, 'Artwork')
        self.dependencies = QPlainTextEdit(right)
        self.dependencies.setReadOnly(True)
        self.tabs.addTab(self.dependencies, 'Known uses')
        self.protected = QPlainTextEdit(right)
        self.protected.setReadOnly(True)
        self.tabs.addTab(self.protected, 'Protected data')
        row = QHBoxLayout()
        self.original = QPushButton('Restore original definition (draft)', right)
        self.original.clicked.connect(self._original)
        row.addWidget(self.original)
        self.reset = QPushButton('Reset this draft', right)
        self.reset.clicked.connect(self._reset)
        row.addWidget(self.reset)
        form.addLayout(row)
        report_tabs = QTabWidget(right)
        form.addWidget(report_tabs, 1)
        self.changes = QPlainTextEdit(right)
        self.changes.setReadOnly(True)
        report_tabs.addTab(self.changes, 'Pending changes')
        self.budget = QPlainTextEdit(right)
        self.budget.setReadOnly(True)
        report_tabs.addTab(self.budget, 'ROM budget')
        self.message = QLabel('Scale and compatible artwork update the viewport after Apply. '
            'Lighting, draw distance, shadows and water effects are saved game properties; preview remains approximate. '
            'Resource checks do not prove peak game RAM or scripted model behavior.', right)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.message.setMinimumHeight(self.message.fontMetrics().lineSpacing()*4+6)
        form.addWidget(self.message)
        split.setSizes([370, 750])
        bottom = QHBoxLayout()
        layout.addLayout(bottom)
        self.undo = QPushButton('Undo project edit', self)
        self.undo.clicked.connect(lambda: self._history(False))
        self.redo = QPushButton('Redo project edit', self)
        self.redo.clicked.connect(lambda: self._history(True))
        bottom.addWidget(self.undo)
        bottom.addWidget(self.redo)
        bottom.addStretch(1)
        self.preview = QPushButton('Preview pending changes', self)
        self.preview.setObjectName('previewGlobalObjects')
        self.preview.clicked.connect(self.build_preview)
        bottom.addWidget(self.preview)
        self.apply = QPushButton('Apply pending definitions', self)
        self.apply.setObjectName('applyGlobalObjects')
        self.apply.clicked.connect(self._apply)
        bottom.addWidget(self.apply)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.rejected.connect(self.reject)
        bottom.addWidget(close)
        self.search.textChanged.connect(self._filter)
        self.list.currentItemChanged.connect(self._selected)
        self.properties.itemChanged.connect(self._edited)
        self.reload()
        # Enter commits a text field; it must not activate Restore/Reset/Apply.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)

    def reload(self) -> None:
        self._loading = True
        self.list.clear()
        self.uses = definition_uses(self.session)
        for definition in self.session.database.definitions:
            kind = MODEL_TYPES[definition.model_type] if 0 <= definition.model_type < len(MODEL_TYPES) else str(definition.model_type)
            item = QTreeWidgetItem([str(definition.header_id), definition.name, kind])
            item.setData(0, ROLE, definition.header_id)
            self.list.addTopLevelItem(item)
            if definition.header_id == self.current:
                self.list.setCurrentItem(item)
        self._loading = False
        self._load_fields()
        self._filter()
        self._invalidate()

    def _raw(self) -> bytes:
        return self.drafts.get(self.current, self.session.current_asset(AssetType.OBJECTS, self.current))

    def _load_fields(self) -> None:
        self._loading = True
        self.properties.clear()
        raw = self._raw()
        d = ObjectDefinition.from_bytes(raw, self.current)
        use = self.uses[self.current]
        self.caption.setText(f'Header {d.header_id}: {d.name} · {d.behavior}\n'
            f'{len(raw)} bytes · {use.instances} known placed instance(s) · {len(use.levels)} known level(s)')
        for field in FIELDS:
            value = field.read(raw)
            item = QTreeWidgetItem([f'{field.label} · 0x{field.offset:02X}', format(value, '.9g')])
            item.setData(1, ROLE+1, field.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(0, field.help)
            item.setToolTip(1, field.help)
            self.properties.addTopLevelItem(item)
        self._load_artwork(d)
        self.dependencies.setPlainText('Object IDs sharing this header:\n'+(', '.join(map(str, use.aliases)) or 'None in translation table')+
            '\n\nKnown placed map IDs:\n'+(', '.join(map(str, use.maps)) or 'None')+
            '\n\nKnown affected levels (including actor targets / attachments):\n'+('\n'.join(use.levels) or 'None found')+
            '\n\nAttachment parent headers:\n'+(', '.join(map(str, use.parents)) or 'None')+
            '\n\nCompiled spawns, racers, menus and other game code may add uses. This is a shared definition, not a placed-object edit.')
        self.protected.setPlainText(f'Behavior: {d.behavior}\nModel type: {d.model_type}\nArtwork count: {len(d.model_ids)}\n'
            f'Flags: 0x{struct.unpack_from(">H", raw, 0x30)[0]:04X}\n'
            f'Attachment / particle / light counts: {raw[0x56]} / {raw[0x57]} / {raw[0x5A]}\n'
            'Behavior, types, allocation flags, counts, pointers, internal name, attachment/particle/light/misc data and unknown bytes are retained.\n\n'
            + '\n'.join(f'{i:04X}: {raw[i:i+16].hex(" ")}' for i in range(0, len(raw), 16)))
        self._loading = False

    def _load_artwork(self, definition: ObjectDefinition) -> None:
        self.artwork.clear()
        kind = definition.model_type
        labels: dict[int, set[str]] = {}
        for d in self.session.database.definitions:
            if d.model_type == kind:
                for index in d.model_ids:
                    labels.setdefault(index, set()).add(d.name)
        if kind == 0:
            candidates = range(self.session.rom.count(AssetType.OBJECT_MODELS))
        elif kind in (1, 2):
            candidates = range(self.session.rom.count(AssetType.SPRITES))
        elif kind == 4:
            candidates = (*range(self.session.rom.count(AssetType.TEXTURES_2D)),
                *(0x8000+i for i in range(self.session.asset_source.count(AssetType.TEXTURES_3D))))
        else:
            candidates = ()
        for slot, index in enumerate(definition.model_ids):
            item = QTreeWidgetItem([str(slot), ''])
            self.artwork.addTopLevelItem(item)
            combo = QComboBox(self.artwork)
            combo.setObjectName(f'globalArtworkSlot{slot}')
            combo.setEditable(True)
            combo.setMinimumContentsLength(20)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.setAccessibleName(f'Global artwork slot {slot}')
            for candidate in candidates:
                text = f'{candidate}' + (' (3D texture)' if kind == 4 and candidate & 0x8000 else '')
                if candidate in labels:
                    text += ': '+', '.join(sorted(labels[candidate]))
                combo.addItem(text, candidate)
            combo.setCurrentIndex(combo.findData(index))
            combo.setToolTip('Existing assets only. Search/select an ID; preview checks frame, animation, lighting and attachment compatibility. '
                'Matching these data capacities does not guarantee identical scripted behavior.')
            combo.activated.connect(lambda _, widget=combo, key=f'model_{slot}', owner=self.current:
                self._artwork_changed(key, widget.currentData(), owner))
            combo.lineEdit().editingFinished.connect(lambda widget=combo, key=f'model_{slot}', owner=self.current:
                self._finish_artwork(key, widget, owner))
            self.artwork.setItemWidget(item, 1, combo)

    def _finish_artwork(self, key: str, combo: QComboBox, owner: int) -> None:
        if self._loading or owner != self.current:
            return
        text = combo.currentText().strip()
        try:
            value = int(text.split(':', 1)[0].split(' ', 1)[0], 0)
            index = combo.findData(value)
            if index < 0:
                raise ValueError('Choose an existing artwork ID from this list')
            combo.setCurrentIndex(index)
            self._artwork_changed(key, value, owner)
        except ValueError as error:
            self.message.setText(str(error))
            combo.setCurrentIndex(combo.findData(ObjectDefinition.from_bytes(self._raw(), self.current).model_ids[int(key[6:])]))

    def _selected(self, item: QTreeWidgetItem | None, *_: object) -> None:
        if self._loading or item is None:
            return
        self.current = int(item.data(0, ROLE))
        self._load_fields()

    def _filter(self, *_: object) -> None:
        query = self.search.text().strip().casefold()
        for i in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(i)
            index = int(item.data(0, ROLE))
            d = self.session.database.definitions[index]
            text = f'{index} {d.name} {d.behavior} {self.uses[index].aliases}'
            item.setHidden(query not in text.casefold())

    def _set_draft(self, raw: bytes) -> None:
        if raw == self.session.current_asset(AssetType.OBJECTS, self.current):
            self.drafts.pop(self.current, None)
        else:
            self.drafts[self.current] = raw
        item = self.list.currentItem()
        if item is not None:
            item.setText(1, self.session.database.definitions[self.current].name+(' *' if self.current in self.drafts else ''))
        self._invalidate()

    def _edited(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or column != 1:
            return
        key = item.data(1, ROLE+1)
        field = FIELD_BY_KEY[key]
        try:
            value = float(item.text(1)) if field.format == 'f' else int(item.text(1), 0) if item.text(1).lower().startswith(('0x', '-0x', '0b')) else int(item.text(1))
            self._set_draft(edit_definition(self._raw(), key, value))
            self.message.setText('Draft changed. Preview pending changes before Apply.')
        except (ValueError, OverflowError) as error:
            self.message.setText(str(error))
            self._loading = True
            item.setText(1, format(field.read(self._raw()), '.9g'))
            self._loading = False

    def _artwork_changed(self, key: str, value: object, owner: int) -> None:
        if self._loading or owner != self.current:
            return
        try:
            self._set_draft(edit_definition(self._raw(), key, value))
            self.message.setText('Artwork draft changed. Preview checks compatibility; Apply updates supported artwork in the viewport.')
        except ValueError as error:
            self.message.setText(str(error))

    def _invalidate(self) -> None:
        self.plan = None
        self.apply.setEnabled(False)
        self.budget.clear()
        self.preview.setEnabled(bool(self.drafts))
        self.undo.setEnabled(not self.drafts and self.session.can_undo)
        self.redo.setEnabled(not self.drafts and self.session.can_redo)
        lines: list[str] = []
        for index, raw in sorted(self.drafts.items()):
            name = self.session.database.definitions[index].name
            lines.append(f'Header {index}: {name}')
            lines.extend('  '+line for line in definition_changes(self.session.current_asset(AssetType.OBJECTS, index), raw))
        self.changes.setPlainText('\n'.join(lines) or 'No pending changes.')

    def _original(self) -> None:
        self._set_draft(self.session.original_asset(AssetType.OBJECTS, self.current))
        self._load_fields()

    def _reset(self) -> None:
        self._set_draft(self.session.current_asset(AssetType.OBJECTS, self.current))
        self._load_fields()

    def build_preview(self) -> None:
        self.properties.clearFocus()
        self.plan = None
        self.apply.setEnabled(False)
        try:
            self.plan = plan_global_objects(self.session, self.drafts)
            self.budget.setPlainText(self.plan.report.to_text())
            self.message.setText(f'{len(self.plan.after)} shared definition(s) ready. Review Known uses and ROM budget. '
                'Definition sizes and array counts remain fixed. Review the affected objects and memory budget before applying.')
            self.apply.setEnabled(bool(self.plan.after))
        except (ValueError, OSError) as error:
            self.message.setText(f'Preview rejected: {error}')

    def _apply(self) -> None:
        if self.plan is None:
            return
        try:
            self.session.apply_global_objects(self.plan)
            self.drafts.clear()
            self.reload()
            self.definitions_changed.emit()
            self.message.setText('Shared definitions applied. Ctrl+Z undoes the change.')
        except (ValueError, OSError) as error:
            self.message.setText(f'Apply rejected: {error}')
            self.apply.setEnabled(False)

    def _history(self, redo: bool) -> None:
        if self.drafts:
            return
        self.history_requested.emit(redo)
        self.reload()
