"""Property dock for the current reference scene."""

from __future__ import annotations

from src.ui.deferred_edits import defer_edit


from PySide6.QtWidgets import (QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QTabWidget,
                               QLineEdit, QComboBox, QSplitter, QCheckBox, QSpinBox, QPushButton,
                               QGridLayout, QGroupBox, QStyledItemDelegate, QStyleOptionViewItem, QAbstractItemView, QHBoxLayout, QSizePolicy, QHeaderView)

from PySide6.QtCore import Qt, Signal, Slot, QModelIndex, QAbstractItemModel, QItemSelectionModel
from PySide6.QtGui import QColor

from src.core.level_header import LevelEntry
from src.core.rom import AssetType
from src.core.level_model import LevelModel
from src.core.objects import LevelObject
from src.core.editing import EditSession
from src.core.level_settings import LEVEL_FIELDS, FIELD_BY_KEY, field_choices
from src.renderer.gizmos import CATEGORY_COLORS
from src.ui.placement_panel import PlacementPanel
from src.ui.route_panel import RoutePanel
from src.ui.research_panel import ResearchPanel
from src.ui.material_panel import MaterialPanel
from src.ui.geometry_panel import GeometryPanel
from src.ui.minimap_panel import MinimapPanel
from src.ui.cinematic_panel import CinematicPanel

EDIT_ROLE = int(Qt.ItemDataRole.UserRole) + 10
EDIT_VALUE_ROLE = EDIT_ROLE + 1
CHOICES_ROLE = EDIT_ROLE + 2


from src.core.parameter_labels import parameter_info, parameter_label


class PropertyDelegate(QStyledItemDelegate):
    """Edit the clean number/array rather than the formatted hex/decimal display."""
    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget | None:
        if index.column() != 1 or index.data(EDIT_ROLE) is None:
            return None
        choices = index.data(CHOICES_ROLE)
        if choices:
            editor = QComboBox(parent)
            editor.setEditable(True)
            editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            for value, label in choices:
                editor.addItem(f"{value} · {label}", value)
            # Value cells can be narrow; keep the named choices readable.
            width = max(editor.fontMetrics().horizontalAdvance(editor.itemText(i)) for i in range(editor.count())) + 40
            editor.view().setMinimumWidth(min(width, editor.screen().availableGeometry().width() - 40))
            editor.activated.connect(lambda _: self._commit_choice(editor))
            return editor
        return QLineEdit(parent)

    def _commit_choice(self, editor: QComboBox) -> None:
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            value = str(index.data(EDIT_VALUE_ROLE))
            choice = editor.findData(parse_integer(value))
            if choice >= 0:
                editor.setCurrentIndex(choice)
            else:
                editor.setEditText(value)
        elif isinstance(editor, QLineEdit):
            editor.setText(str(index.data(EDIT_VALUE_ROLE)))
            editor.selectAll()

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            text = editor.currentText()
            choice = editor.findText(text)
            model.setData(index, str(editor.itemData(choice)) if choice >= 0 else text, Qt.ItemDataRole.EditRole)
        elif isinstance(editor, QLineEdit):
            model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)


def parse_integer(text: str) -> int:
    text = text.strip()
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 16 if any(char in "abcdefABCDEF" for char in text) else 10)


class LevelSettingsPanel(QWidget):
    edit_requested = Signal(int, str, object)
    revert_requested = Signal(int)
    preview_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session: EditSession | None = None
        self.level: LevelEntry | None = None
        layout = QVBoxLayout(self)
        self.title = QLabel("Select a level to edit its saved defaults.", self)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("levelSettings")
        self.tree.setAccessibleName("Saved level settings")
        self.tree.setHeaderLabels(["Setting / offset", "Value"])
        # Keep the entire value editor, including its arrow, inside a narrow dock.
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(1, 128)
        self.tree.setAlternatingRowColors(True)
        self.tree.setItemDelegate(PropertyDelegate(self.tree))
        self.tree.itemChanged.connect(self._changed)
        layout.addWidget(self.tree, 1)
        self.preview_fov = QCheckBox("Preview saved camera FOV", self)
        self.preview_fov.setToolTip("Use the saved field of view in the editor camera. This checkbox is preview-only; wheel zoom does not edit the saved value.")
        self.preview_fov.toggled.connect(self.preview_changed)
        layout.addWidget(self.preview_fov)
        self.revert = QPushButton("Revert this level's settings", self)
        self.revert.clicked.connect(lambda: self.revert_requested.emit(self.level.index) if self.level else None)
        layout.addWidget(self.revert)
        self.message = QLabel("Double-click a value to edit. Save a project to keep your work or export a ROM to use your changes.", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        hint = QLabel("Fog and sky defaults can be previewed in the Environment toolbar. Weather and audio playback are deferred. IDs, geometry/maps, world, race type and unknown header bytes stay protected.", self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8;")
        layout.addWidget(hint)

    def show_level(self, level: LevelEntry) -> None:
        same = self.level is not None and self.level.index == level.index
        expansion = {self.tree.topLevelItem(i).text(0): self.tree.topLevelItem(i).isExpanded()
                     for i in range(self.tree.topLevelItemCount())}
        scroll = self.tree.verticalScrollBar().value()
        current = self.tree.currentItem()
        selected = current.data(1, EDIT_ROLE) if current is not None else None
        self.level = level
        self.tree.blockSignals(True)
        self.tree.clear()
        self.title.setText(f"{level.name} · Saved level defaults")
        raw = level.header.raw_data
        enabled = self.session is not None and raw is not None
        self.preview_fov.setEnabled(raw is not None)
        self.revert.setEnabled(enabled and raw != self.session.rom.read_asset(AssetType.LEVEL_HEADERS, level.index))
        references = self.session.level_references(level.index) if enabled else None
        groups: dict[str, QTreeWidgetItem] = {}
        if raw is not None:
            for field in LEVEL_FIELDS:
                if field.group not in groups:
                    group = QTreeWidgetItem([field.group, ""])
                    groups[field.group] = group
                    self.tree.addTopLevelItem(group)
                    group.setExpanded(expansion.get(field.group, field.group in ("Race and vehicles", "Environment")))
                value = field.read(raw)
                clean = ", ".join(map(str, value)) if isinstance(value, tuple) else str(value)
                choices = field_choices(field, references) if references is not None else field.choices
                choice = dict(choices).get(value) if isinstance(value, int) else None
                item = QTreeWidgetItem([f"{field.label} · 0x{field.offset:02X}", f"{value} · {choice}" if choice else clean])
                groups[field.group].addChild(item)
                item.setToolTip(0, field.description)
                item.setToolTip(1, field.description + "\nDouble-click; arrays use comma-separated integers. Decimal, 0x hex and 0b binary are accepted.")
                if enabled:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    item.setData(1, EDIT_ROLE, ("level", field.key))
                    item.setData(1, EDIT_VALUE_ROLE, clean)
                    item.setData(1, CHOICES_ROLE, choices)
                if selected == ("level", field.key):
                    self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        if same:
            self.tree.verticalScrollBar().setValue(scroll)
        if not enabled:
            self.message.setText("Level editing requires the original USA Rev 1 ROM. Extracted assets remain view-only.")
        elif references is not None:
            sets = ", ".join(map(str, references.checkpoint_sets)) or "none"
            self.message.setText(f"Double-click to edit. AI presets: 0–{references.ai_count - 1}; main checkpoint sets: {sets}. Ctrl+Z undoes an edit.")

    @Slot(QTreeWidgetItem, int)
    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        target = item.data(1, EDIT_ROLE)
        if column != 1 or not target or self.session is None or self.level is None:
            return
        index, key = self.level.index, str(target[1])
        try:
            parts = tuple(parse_integer(part) for part in item.text(1).strip().strip("()[]").split(",") if part.strip())
            value = parts if isinstance(FIELD_BY_KEY[key].read(self.level.header.raw_data), tuple) else parts[0] if len(parts) == 1 else parts
        except (ValueError, IndexError):
            self.message.setText("Invalid integer or array. Use comma-separated decimal, 0x hex or 0b binary values.")
            message = self.message.text()
            def restore() -> None:
                if self.level is not None:
                    self.show_level(self.level)
                    self.message.setText(message)
            defer_edit(self, restore)
            return
        defer_edit(self, lambda: self.edit_requested.emit(index, key, value))


class ObjectInspector(QWidget):
    selection_changed = Signal(object, int)
    object_selected = Signal(int)
    object_focused = Signal(int)
    visible_objects_changed = Signal(object)
    edit_requested = Signal(object, str, object, object)
    nudge_requested = Signal(int, int)
    move_mode_changed = Signal(bool)
    move_step_changed = Signal(int)
    mouse_move_changed = Signal(bool)
    revert_requested = Signal()
    add_requested = Signal()
    duplicate_requested = Signal()
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        self.label = QLabel("Reference scene", self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-weight: 600; padding-bottom: 6px;")
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.setColumnWidth(0, 118)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        for name, value in (
            ("Scene", "Reference grid"), ("Plane", "XZ / Y = 0"),
            ("Minor spacing", "1 unit"), ("Major spacing", "10 units"),
            ("X axis", "Red"), ("Y axis", "Green"), ("Z axis", "Blue"),
            ("Target ROM", "USA Rev 1 / v80"),
        ):
            self.tree.addTopLevelItem(QTreeWidgetItem([name, value]))
        self.hint = QLabel("Choose a level to inspect its header.", self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #94a3b8; padding: 8px 0;")
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("inspectorTabs")
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setStyleSheet('QTabBar::tab { padding: 5px; }')
        info = QWidget(self)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0,0,0,0)
        info_layout.addWidget(self.label)
        info_layout.addWidget(self.tree, 1)
        info_layout.addWidget(self.hint)
        self.tabs.addTab(info,"Level")
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0,8,0,0)
        self.object_search = QLineEdit(self)
        self.object_search.setPlaceholderText("Filter objects by name, ID or behavior…")
        self.object_search.setAccessibleName("Filter objects")
        self.category = QComboBox(self)
        self.category.setAccessibleName("Object category")
        self.category.addItem("All categories", "")
        for category, color in CATEGORY_COLORS.items():
            self.category.addItem(category,category)
            self.category.setItemData(self.category.count()-1,QColor.fromRgbF(*color),Qt.ItemDataRole.ForegroundRole)
        self.object_list = QTreeWidget(self)
        self.object_list.setObjectName("objectList")
        self.object_list.setAccessibleName("Level objects")
        self.object_list.setHeaderLabels(["Object", "Map", "ID"])
        self.object_list.setColumnWidth(0,145)
        self.object_list.setColumnWidth(1,45)
        self.object_list.setRootIsDecorated(False)
        self.object_list.setAlternatingRowColors(True)
        self.object_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.properties = QTreeWidget(self)
        self.properties.setObjectName("objectProperties")
        self.properties.setHeaderLabels(["Property / offset", "Value"])
        self.properties.setColumnWidth(0,190)
        self.properties.setAlternatingRowColors(True)
        self.properties.setItemDelegate(PropertyDelegate(self.properties))
        self.properties.itemChanged.connect(self._property_changed)
        splitter = QSplitter(Qt.Orientation.Vertical,self)
        splitter.addWidget(self.object_list);splitter.addWidget(self.properties)
        splitter.setSizes([260,320])
        self.object_count = QLabel("No objects loaded",self)
        self.object_count.setWordWrap(True)
        structure_row = QHBoxLayout()
        self.add_button = QPushButton('Add...', self)
        self.duplicate_button = QPushButton('Duplicate', self)
        self.delete_button = QPushButton('Delete', self)
        for button, signal in ((self.add_button, self.add_requested),
                               (self.duplicate_button, self.duplicate_requested), (self.delete_button, self.delete_requested)):
            structure_row.addWidget(button)
            button.clicked.connect(signal)
        self.add_button.setToolTip('All translated object types; choose a stock template or explicit zeroed schema defaults.')
        self.duplicate_button.setToolTip('Copy selected entries and their parameters; offset along X by Step. Ctrl+D.')
        self.delete_button.setToolTip('Delete selected entries; Ctrl+Z restores them. Links are not automatically repaired.')
        instructions = QLabel("Select a marker or list row; double-click to focus. Double-click a property value to edit. Raw bytes accept 0xFF, decimal or 0b11111111.",self)
        instructions.setWordWrap(True)
        self.edit_group = QGroupBox("Move selected object", self)
        move_layout = QGridLayout(self.edit_group)
        move_layout.setContentsMargins(7, 7, 7, 7)
        self.coordinates: list[QSpinBox] = []
        self.nudge_buttons: list[QPushButton] = []
        for axis, name in enumerate("XYZ"):
            coordinate = QSpinBox(self)
            coordinate.setRange(-32768, 32767)
            coordinate.setPrefix(name + " ")
            coordinate.setAccessibleName(f"Object position {name}")
            coordinate.setKeyboardTracking(False)
            coordinate.editingFinished.connect(self._position_finished)
            self.coordinates.append(coordinate)
            move_layout.addWidget(coordinate, axis, 0)
            for direction, suffix in ((-1, "−"), (1, "+")):
                button = QPushButton(name + suffix, self)
                button.setFixedWidth(42)
                button.setAccessibleName(f"Move {name} {'negative' if direction < 0 else 'positive'}")
                button.clicked.connect(lambda checked=False, a=axis, d=direction: self.nudge_requested.emit(a, d * self.move_step.value()))
                self.nudge_buttons.append(button)
                move_layout.addWidget(button, axis, 1 + (direction > 0))
        self.move_step = QSpinBox(self)
        self.move_step.setRange(1, 4096)
        self.move_step.setValue(16)
        self.move_step.setPrefix("Step ")
        self.move_step.setAccessibleName("Object movement step")
        self.move_step.valueChanged.connect(self.move_step_changed)
        move_layout.addWidget(self.move_step, 3, 0)
        self.move_keys = QCheckBox("Arrow key move", self)
        self.move_keys.setToolTip("In viewport: Left/Right = X, Up/Down = Z, PageUp/PageDown = Y. Shift = 4× step. WASD still moves the camera.")
        self.move_keys.toggled.connect(self.move_mode_changed)
        move_layout.addWidget(self.move_keys, 3, 1, 1, 2)
        self.mouse_move = QCheckBox("Mouse move in viewport", self)
        self.mouse_move.setChecked(True)
        self.mouse_move.setToolTip("Drag an object/white center in the view plane, or an RGB X/Y/Z arrow along its axis. Ctrl snaps to Step; Escape cancels. Each drag is one undo step.")
        self.mouse_move.toggled.connect(lambda enabled: self.mouse_move_changed.emit(self.editing_enabled and enabled))
        move_layout.addWidget(self.mouse_move, 4, 0, 1, 3)
        self.raw_edit = QCheckBox("Edit raw parameter bytes / bits", self)
        self.raw_edit.setToolTip("Advanced: edit raw parameter bytes and bits, including unknown and reserved fields. Object ID and entry size are protected.")
        self.raw_edit.toggled.connect(self._raw_mode_changed)
        self.revert_button = QPushButton("Revert selected object", self)
        self.revert_button.clicked.connect(self.revert_requested)
        self.edit_message = QLabel(self)
        self.edit_message.setWordWrap(True)
        self.edit_message.setStyleSheet("color: #94a3b8;")
        page_layout.addWidget(self.object_search);page_layout.addWidget(self.category)
        page_layout.addWidget(splitter,1);page_layout.addWidget(self.object_count)
        page_layout.addLayout(structure_row)
        page_layout.addWidget(self.edit_group);page_layout.addWidget(self.raw_edit)
        page_layout.addWidget(self.revert_button);page_layout.addWidget(self.edit_message);page_layout.addWidget(instructions)
        self.tabs.addTab(page,"Objects")
        self.level_settings = LevelSettingsPanel(self)
        self.tabs.addTab(self.level_settings, "Settings")
        self.tools = QTabWidget(self)
        self.tools.setUsesScrollButtons(True)
        self.placement = PlacementPanel(self)
        self.tools.addTab(self.placement, "Placement")
        self.routes = RoutePanel(self)
        self.tools.addTab(self.routes, "Routes")
        self.research = ResearchPanel(self)
        # Keep project-note compatibility without exposing the retired Research page.
        self.research.hide()
        self.materials = MaterialPanel(self)
        self.geometry_panel = GeometryPanel(self)
        self.geometry_tabs = QTabWidget(self)
        self.geometry_tabs.setObjectName('geometryViews')
        self.geometry_tabs.addTab(self.geometry_panel, 'Mesh')
        self.geometry_tabs.addTab(self.materials, 'Materials')
        self.tabs.insertTab(2, self.geometry_tabs, 'Geometry')
        self.minimap = MinimapPanel(self)
        self.tools.addTab(self.minimap, "Minimap")
        self.cinematics = CinematicPanel(self)
        self.tools.addTab(self.cinematics, "Cinematics")
        self.tabs.addTab(self.tools, "Tools")
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.tabs)
        self.objects: tuple[LevelObject,...] = ()
        self.editing_enabled = False
        self._property_key: tuple[int, int] | None = None
        self._selection_pending = False
        self.set_editing_enabled(False)
        self.object_search.textChanged.connect(self._filter_objects)
        self.category.currentIndexChanged.connect(self._filter_objects)
        self.object_list.currentItemChanged.connect(self._list_selection)
        self.object_list.itemSelectionChanged.connect(self._queue_selection)
        self.object_list.itemDoubleClicked.connect(self._focus_selection)

    def show_level(self, level: LevelEntry) -> None:
        self.level_settings.show_level(level)
        header = level.header
        self.label.setText(f"{level.name} · Level {level.index}")
        self.tree.clear()
        vehicles = ("Car", "Hovercraft", "Plane")
        available = ", ".join(name for bit, name in enumerate(vehicles) if header.available_vehicles & (1 << bit))
        default_vehicle = vehicles[header.vehicle] if 0 <= header.vehicle < 3 else str(header.vehicle)
        for name, value in (
            ("Level ID", str(level.index)), ("Type", header.category),
            ("World", f"{header.world_name} ({header.world})"),
            ("Geometry ID", str(header.geometry_id)),
            ("Collectables map", str(header.object_map_id)),
            ("Second object map", str(header.secondary_object_map_id)),
            ("Skybox ID", "None (-1)" if header.skybox_id == -1 else str(header.skybox_id)),
            ("Fog near / far", f"{header.fog.near} / {header.fog.far}"),
            ("Fog RGB", str(header.fog.color)), ("Background RGB", str(header.background_color)),
            ("Gradient bottom", str(header.background_bottom)), ("Gradient top", str(header.background_top)),
            ("Default vehicle", default_vehicle), ("Available vehicles", available or "None"),
            ("Laps", str(header.laps)), ("Camera FOV", str(header.camera_fov)),
            ("Course height", f"{header.course_height:g}"), ("Race type", str(header.race_type)),
            ("Special sky", str(header.special_sky)), ("Sky texture ID", str(header.special_sky_texture)),
            ("English", level.names.english), ("German", level.names.german),
            ("French", level.names.french), ("Japanese", level.names.japanese or "—"),
            ("Build ID", level.build_id or "ROM table entry"),
            ("Header", f"{len(header.raw_data)} bytes" if header.raw_data is not None else "Decomp JSON"),
        ):
            item = QTreeWidgetItem([name, value])
            item.setToolTip(1, value)
            self.tree.addTopLevelItem(item)
        self.hint.setText("Loading track geometry…")

    def show_model(self, model: LevelModel, *, selected_segment: int = -1) -> None:
        for row in reversed(range(self.tree.topLevelItemCount())):
            if self.tree.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole) == 'model-summary':
                self.tree.takeTopLevelItem(row)
        rows = [
            ("Segments", str(len(model.segments))), ("Vertices", f"{model.vertex_count:,}"),
            ("Triangles", f"{model.triangle_count:,}"), ("Texture references", str(len(model.textures))),
            ("BSP nodes", str(len(model.bsp_nodes))),
        ]
        if selected_segment >= 0:
            segment = model.segments[selected_segment]
            rows.extend((
                ("Selected segment", str(selected_segment)), ("Segment vertices", str(segment.vertex_count)),
                ("Segment triangles", str(segment.triangle_count)), ("Segment batches", str(len(segment.batches))),
                ("Segment minimum", str(segment.bounds.minimum)), ("Segment maximum", str(segment.bounds.maximum)),
            ))
        for name, value in rows:
            item = QTreeWidgetItem([name, value])
            item.setData(0, Qt.ItemDataRole.UserRole, 'model-summary')
            item.setToolTip(1, value)
            self.tree.addTopLevelItem(item)
        self.hint.setText("Textured track geometry. Inspect gameplay markers in the Objects tab. OBJ exports track geometry.")

    def set_objects(self, objects: tuple[LevelObject,...]) -> None:
        self.objects = objects
        self.object_list.blockSignals(True)
        self.object_list.clear();self.properties.clear()
        for index,obj in enumerate(objects):
            item = QTreeWidgetItem([f"{obj.index}: {obj.definition.name}",str(obj.map_id),str(obj.object_id)])
            item.setData(0,Qt.ItemDataRole.UserRole,index)
            item.setForeground(0,QColor.fromRgbF(*CATEGORY_COLORS[obj.category]))
            item.setToolTip(0,f"{obj.category} · {obj.definition.behavior} · {obj.position}")
            self.object_list.addTopLevelItem(item)
        self.object_list.blockSignals(False)
        self._property_key = None
        self._enable_selected_controls(False)
        self._filter_objects()

    def replace_objects(self, objects: tuple[LevelObject, ...], selection: int) -> None:
        """Refresh edits without resetting the filter, selection or property expansion."""
        if tuple(obj.key for obj in objects) != tuple(obj.key for obj in self.objects):
            self.set_objects(objects)
        self.objects = objects
        for index, obj in enumerate(objects):
            self.object_list.topLevelItem(index).setToolTip(0, f"{obj.category} · {obj.definition.behavior} · {obj.position}")
        self._filter_objects()
        self.select_object(selection, reveal=False)

    def preview_position(self, objects: tuple[LevelObject, ...], selection: int) -> None:
        """A drag changes XYZ only; retain the raw-byte tree and open bit rows."""
        if len(objects) != len(self.objects) or selection < 0 or self._property_key != objects[selection].key:
            self.replace_objects(objects, selection)
            return
        self.objects = objects
        obj = objects[selection]
        self.object_list.topLevelItem(selection).setToolTip(0, f"{obj.category} · {obj.definition.behavior} · {obj.position}")
        for box,value in zip(self.coordinates,obj.position):
            box.setValue(value)
        self.properties.blockSignals(True)
        try:
            for index in range(self.properties.topLevelItemCount()):
                item = self.properties.topLevelItem(index)
                if item.text(0).startswith("Position "):
                    value = str(obj.position["XYZ".index(item.text(0)[-1])])
                    item.setText(1,value)
                    item.setData(1,EDIT_VALUE_ROLE,value)
                elif item.text(0) == "Raw entry" and obj.raw_data is not None:
                    item.setText(1,obj.raw_data.hex(" "))
        finally:
            self.properties.blockSignals(False)

    @Slot()
    def _filter_objects(self) -> None:
        query = self.object_search.text().casefold().strip()
        category = self.category.currentData()
        visible: list[int] = []
        removed_selection = False
        prior_block = self.object_list.blockSignals(True)
        for index,obj in enumerate(self.objects):
            text = f"{obj.definition.name} {obj.object_id} {obj.definition.header_id} {obj.definition.behavior} {obj.category} {obj.map_id}".casefold()
            show = (not category or category == obj.category) and query in text
            item = self.object_list.topLevelItem(index)
            item.setHidden(not show)
            if not show and item.isSelected():
                item.setSelected(False)
                removed_selection = True
            if show:visible.append(index)
        self.object_list.blockSignals(prior_block)
        self.object_count.setText(f"{len(visible)} of {len(self.objects)} objects · "
                                  f"{len(set(obj.map_id for obj in self.objects))} maps")
        self.visible_objects_changed.emit(tuple(visible))
        if removed_selection and not prior_block:
            self._queue_selection()

    def select_object(self, index: int, *, reveal: bool = True) -> None:
        scroll = self.properties.verticalScrollBar().value()
        expanded: set[str] = set()
        raw_expanded = self.raw_edit.isChecked()
        for row in range(self.properties.topLevelItemCount()):
            parent = self.properties.topLevelItem(row)
            if parent.text(0) == "Raw entry":
                raw_expanded = parent.isExpanded()
                for child in range(parent.childCount()):
                    if parent.child(child).isExpanded(): expanded.add(parent.child(child).text(0))
        same_object = 0 <= index < len(self.objects) and self._property_key == self.objects[index].key
        self.object_list.blockSignals(True)
        self.properties.blockSignals(True)
        self.properties.clear()
        if not 0 <= index < len(self.objects):
            self.object_list.clearSelection()
            self.object_list.setCurrentItem(None)
            self.object_list.blockSignals(False)
            self.properties.blockSignals(False)
            self._property_key = None
            self._enable_selected_controls(False)
            return
        item = self.object_list.topLevelItem(index)
        if not item.isSelected():
            self.object_list.clearSelection()
            item.setSelected(True)
        self.object_list.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.object_list.scrollToItem(item)
        self.object_list.blockSignals(False)
        obj = self.objects[index]
        self._property_key = obj.key
        self._enable_selected_controls(True)
        for coordinate, value in zip(self.coordinates, obj.position):
            coordinate.setValue(value)
        if reveal:
            self.tabs.setCurrentIndex(1)
        rows = (
            ("Internal name",obj.definition.name),("Object ID (9-bit)",str(obj.object_id)),
            ("Header ID",str(obj.definition.header_id)),("Behavior",f"{obj.definition.behavior_id}: {obj.definition.behavior}"),
            ("Category",obj.category),("Map / editor ID",f"{obj.map_id} / {obj.index}"),
            ("Serialized entry", str(next(i for i, value in enumerate(o for o in self.objects if o.map_id == obj.map_id) if value.key == obj.key))),
            ("Position X",str(obj.position[0])),("Position Y",str(obj.position[1])),("Position Z",str(obj.position[2])),
            ("Entry bytes",str(obj.byte_size)),("Map offset",f"0x{obj.offset:X}" if obj.offset is not None else "Not retained in glTF"),
            ("Size bit 6",str(int(obj.size_bit6)) if obj.raw_data is not None else "Not retained in glTF"),
            ("Source", "ROM / binary" if obj.raw_data is not None else "Extracted glTF; alias ID canonicalized"),
        )
        for name,value in rows:
            row = QTreeWidgetItem([name,value])
            self.properties.addTopLevelItem(row)
            if name.startswith("Position "):
                self._editable(row, ("position", "XYZ".index(name[-1])), value)
        from src.core.special_art import artwork_note
        note = artwork_note(obj.definition.behavior_id)
        if note:
            row = QTreeWidgetItem(['Artwork preview', note])
            row.setToolTip(1, note)
            self.properties.addTopLevelItem(row)
        decoded = QTreeWidgetItem(["Parameters",str(len(obj.parameters))])
        for parameter in obj.parameters:
            info = parameter_info(obj.definition.behavior_id, parameter.name)
            choices = info.choices if info is not None else ()
            choice_label = dict(choices).get(parameter.value) if isinstance(parameter.value, int) else None
            display = f"{parameter.value} · {choice_label}" if choice_label is not None else str(parameter.value)
            row = QTreeWidgetItem(decoded,[f"0x{parameter.offset:02X} {parameter_label(obj.definition.behavior_id, parameter.name, parameter.offset)}",display])
            row.setToolTip(0, f'Stored field: {parameter.name} · offset 0x{parameter.offset:02X}')
            value = ", ".join(str(v) for v in parameter.value) if isinstance(parameter.value,tuple) else str(parameter.value)
            self._editable(row, ("parameter", parameter.name), value)
            if info is not None:
                help_text = f"{row.text(0)}\nOriginal field: {parameter.name}\n{info.description}"
                row.setToolTip(0, help_text)
                row.setToolTip(1, help_text + "\nDouble-click to edit; type a raw integer or choose a named value." if self.editing_enabled else help_text)
                row.setData(1, CHOICES_ROLE, choices)
        self.properties.addTopLevelItem(decoded);decoded.setExpanded(True)
        if obj.raw_data is not None:
            raw = QTreeWidgetItem(["Raw entry",obj.raw_data.hex(" ")])
            for offset,value in enumerate(obj.raw_data[8:],8):
                row = QTreeWidgetItem(raw,[f"0x{offset:02X} u8 / s8",f"0x{value:02X} · {value} / {value if value<128 else value-256} · {value:08b}"])
                self._editable(row, ("raw", offset), f"0x{value:02X}", raw=True)
                if self.raw_edit.isChecked() and self.editing_enabled:
                    for bit in range(8):
                        child = QTreeWidgetItem(row, [f"Bit {bit} · 0x{1<<bit:02X}", ""])
                        child.setData(1, EDIT_ROLE, ("bit", offset, bit))
                        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        child.setCheckState(1, Qt.CheckState.Checked if value & (1<<bit) else Qt.CheckState.Unchecked)
                row.setExpanded(same_object and row.text(0) in expanded)
            self.properties.addTopLevelItem(raw)
            raw.setExpanded(raw_expanded if same_object else self.raw_edit.isChecked())
        for row in range(self.properties.topLevelItemCount()):
            self.properties.topLevelItem(row).setToolTip(1,self.properties.topLevelItem(row).text(1))
        self.properties.blockSignals(False)
        if same_object:
            self.properties.verticalScrollBar().setValue(scroll)

    def _editable(self, item: QTreeWidgetItem, target: tuple[object, ...], value: str, *, raw: bool = False) -> None:
        if self.editing_enabled and (not raw or self.raw_edit.isChecked()):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(1, EDIT_ROLE, target)
            item.setData(1, EDIT_VALUE_ROLE, value)
            item.setToolTip(1, "Double-click to edit. Decimal, 0x hex or 0b binary; arrays use comma-separated integers.")

    def set_editing_enabled(self, enabled: bool) -> None:
        self.editing_enabled = enabled
        self.add_button.setEnabled(enabled)
        self.mouse_move_changed.emit(enabled and self.mouse_move.isChecked())
        self.raw_edit.setEnabled(enabled)
        if not enabled: self.move_keys.setChecked(False)
        self.edit_message.setText("Edits update the viewport immediately. Ctrl+Z undoes the change." if enabled else "Editing requires the original USA Rev 1 ROM; extracted assets remain view-only.")
        self._enable_selected_controls(self._property_key is not None)

    def _enable_selected_controls(self, selected: bool) -> None:
        self.edit_group.setEnabled(self.editing_enabled and selected)
        self.revert_button.setEnabled(self.editing_enabled and selected)
        self.duplicate_button.setEnabled(self.editing_enabled and selected)
        self.delete_button.setEnabled(self.editing_enabled and selected)

    @Slot(bool)
    def _raw_mode_changed(self, enabled: bool) -> None:
        item = self.object_list.currentItem()
        if item is not None:
            self.select_object(int(item.data(0,Qt.ItemDataRole.UserRole)))
            for row in range(self.properties.topLevelItemCount()):
                parent = self.properties.topLevelItem(row)
                if parent.text(0) == "Raw entry": parent.setExpanded(enabled)

    @Slot()
    def _position_finished(self) -> None:
        if self.editing_enabled and self._property_key is not None:
            position = tuple(box.value() for box in self.coordinates)
            current = next((obj for obj in self.objects if obj.key == self._property_key), None)
            if current is not None and position != current.position:
                self.edit_requested.emit(self._property_key, "position", None, position)

    @Slot(QTreeWidgetItem, int)
    def _property_changed(self, item: QTreeWidgetItem, column: int) -> None:
        target = item.data(1, EDIT_ROLE)
        key = self._property_key
        if column != 1 or target is None or key is None or not self.editing_enabled:
            return
        kind = target[0]
        try:
            if kind == "bit":
                field = (target[1], target[2])
                value: object = item.checkState(1) == Qt.CheckState.Checked
            elif kind == "parameter":
                text = item.text(1).strip().strip("()[]")
                parts = tuple(parse_integer(part) for part in text.split(",") if part.strip())
                obj = next(obj for obj in self.objects if obj.key == key)
                value = parts if isinstance(obj.value(str(target[1])), tuple) else parts[0] if len(parts) == 1 else parts
                field = target[1]
            else:
                field = target[1]
                value = parse_integer(item.text(1))
        except (ValueError, IndexError):
            self.edit_message.setText("Invalid integer. Use decimal, 0xFF or 0b11111111; separate array values with commas.")
            defer_edit(self, lambda: self.select_object(next((i for i,o in enumerate(self.objects) if o.key == key), -1)))
            return
        # Let the delegate finish committing before rebuilding its property items.
        defer_edit(self, lambda: self.edit_requested.emit(key, kind, field, value))

    @Slot(QTreeWidgetItem,QTreeWidgetItem)
    def _list_selection(self, item: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        self._queue_selection()

    def set_selection(self, indices: tuple[int, ...], primary: int, *, reveal: bool = False) -> None:
        self.object_list.blockSignals(True)
        self.object_list.clearSelection()
        for index in indices:
            if 0 <= index < len(self.objects):
                self.object_list.topLevelItem(index).setSelected(True)
        self.object_list.blockSignals(False)
        self.select_object(primary, reveal=reveal)

    @Slot()
    def _queue_selection(self) -> None:
        if not self._selection_pending:
            self._selection_pending = True
            defer_edit(self, self._sync_list_selection)

    def _sync_list_selection(self) -> None:
        self._selection_pending = False
        indices = tuple(sorted(int(item.data(0, Qt.ItemDataRole.UserRole)) for item in self.object_list.selectedItems() if not item.isHidden()))
        item = self.object_list.currentItem()
        current = int(item.data(0, Qt.ItemDataRole.UserRole)) if item is not None else -1
        primary = current if current in indices else indices[0] if indices else -1
        self.select_object(primary, reveal=False)
        self.selection_changed.emit(indices, primary)
        self.object_selected.emit(primary)

    @Slot(QTreeWidgetItem,int)
    def _focus_selection(self, item: QTreeWidgetItem, column: int) -> None:
        self.object_focused.emit(int(item.data(0,Qt.ItemDataRole.UserRole)))
