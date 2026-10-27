"""Filterable catalog containing tracks, hubs, bosses and cinematic stages."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QHeaderView, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from src.core.level_header import LevelCatalog


class LevelPanel(QWidget):
    level_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Filter by name, ID, world or type…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Filter levels")
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Level", "ID", "Type"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setAccessibleName("Level catalog")
        self.hint = QLabel("Open a USA Rev 1 ROM or choose extracted us.v80 assets.", self)
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setStyleSheet("color: #94a3b8; padding: 8px 0;")
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.hint)
        self.search.textChanged.connect(self.filter_levels)
        self.tree.currentItemChanged.connect(self._selection_changed)

    def set_catalog(self, catalog: LevelCatalog) -> None:
        self.tree.clear()
        self.search.clear()
        self.hint.setToolTip(catalog.source.description)
        for level in catalog.levels:
            header = level.header
            item = QTreeWidgetItem([level.name, str(level.index), header.category])
            item.setData(0, Qt.ItemDataRole.UserRole, level.index)
            search_text = " ".join((
                level.name, level.names.german, level.names.french, level.names.japanese,
                str(level.index), header.world_name, header.category,
            )).casefold()
            item.setData(0, Qt.ItemDataRole.UserRole + 1, search_text)
            item.setToolTip(0, f"{level.name}\n{header.world_name} · {header.category}\nGeometry {header.geometry_id}")
            self.tree.addTopLevelItem(item)
        self.filter_levels("")
        self.select_level(0)

    def select_level(self, index: int) -> None:
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item.data(0, Qt.ItemDataRole.UserRole) == index:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def refresh_names(self, catalog: LevelCatalog) -> None:
        """Update labels/search in place, preserving selection/filter and camera."""
        previous=self.tree.blockSignals(True)
        try:
            for row in range(self.tree.topLevelItemCount()):
                item=self.tree.topLevelItem(row);level=catalog.levels[int(item.data(0,Qt.ItemDataRole.UserRole))]
                item.setText(0,level.name)
                item.setData(0,Qt.ItemDataRole.UserRole+1,' '.join((level.name,level.names.german,level.names.french,level.names.japanese,
                    str(level.index),level.header.world_name,level.header.category)).casefold())
                item.setToolTip(0,f'{level.name}\n{level.header.world_name} · {level.header.category}\nGeometry {level.header.geometry_id}')
        finally:self.tree.blockSignals(previous)
        self.filter_levels(self.search.text())

    def _selection_changed(self, item: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        if item is not None:
            self.level_selected.emit(int(item.data(0, Qt.ItemDataRole.UserRole)))

    @Slot(str)
    def filter_levels(self, text: str) -> None:
        query = text.strip().casefold()
        visible = 0
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            matches = query in str(item.data(0, Qt.ItemDataRole.UserRole + 1))
            item.setHidden(not matches)
            visible += int(matches)
        count = self.tree.topLevelItemCount()
        if count:
            self.hint.setText(f"{visible} of {count} levels")
