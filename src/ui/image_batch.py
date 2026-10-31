"""Batch export and staged package import with decoded N64 previews."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QTextEdit, QComboBox, QInputDialog)

from src.core.editing import EditSession
from src.core.image_assets import texture_from_raw
from src.core.image_batch import (BatchImagePlan, export_image_batch, stage_image_batch,
    apply_image_batch, changed_image)
from src.core.rom import AssetType


class BatchImageDialog(QDialog):
    assets_changed = Signal()

    def __init__(self, session: EditSession, selected: tuple[tuple[AssetType, int], ...],
                 visible: tuple[tuple[AssetType, int], ...], parent: QWidget | None = None,
                 *, category: AssetType | None = None) -> None:
        super().__init__(parent)
        self.session, self.selected, self.visible = session, selected, visible
        self.category = category if category is not None else (visible or selected or ((AssetType.TEXTURES_3D, 0),))[0][0]
        self.plan: BatchImagePlan | None = None
        self.setWindowTitle("Batch image tools")
        self.resize(850, 760)
        layout = QVBoxLayout(self)
        note = QLabel("Export PNGs with asset/frame IDs and orientation in images.json. Edit the PNGs, then review and apply the package as one undo step. Dimensions, formats and animation lengths stay fixed.", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.scope = QComboBox(self)
        self.scope.addItems((f"Selected assets ({len(selected)})", f"Visible filtered assets ({len(visible)})", "Changed assets in current category"))
        row.addWidget(self.scope, 1)
        self.sheets = QCheckBox("Animation sheets", self)
        row.addWidget(self.sheets)
        self.export = QPushButton("Export package…", self)
        self.export.clicked.connect(self._export)
        row.addWidget(self.export)
        self.import_button = QPushButton("Review images.json…", self)
        self.import_button.clicked.connect(self._import)
        layout.addWidget(self.import_button)
        self.frames = QTreeWidget(self)
        self.frames.setHeaderLabels(("N64 result", "Frame"))
        self.frames.setColumnWidth(0, 350)
        self.frames.currentItemChanged.connect(self._preview)
        layout.addWidget(self.frames, 1)
        self.image = QLabel(self)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(180)
        layout.addWidget(self.image)
        self.report = QTextEdit(self)
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.apply = QPushButton("Apply imported package", self)
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self.apply_plan)
        row.addWidget(self.apply)
        close = QPushButton("Close", self)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)

    def _export(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose parent folder for new image package")
        if not directory:
            return
        try:
            name, accepted = QInputDialog.getText(self, "New image package", "New folder name", text="workshop-images")
            if not accepted:
                return
            if not name or Path(name).name != name or name in (".", ".."):
                raise ValueError("Enter one new folder name")
            if self.scope.currentIndex() == 0:
                keys = self.selected
            elif self.scope.currentIndex() == 1:
                keys = self.visible
            else:
                section = self.category
                keys = tuple((section, index) for index in range(self.session.asset_source.count(section))
                             if changed_image(self.session, (section, index)))
            path = export_image_batch(self.session, keys, Path(directory) / name, sheets=self.sheets.isChecked())
            self.report.setPlainText(f"Exported {len(keys)} assets and their nonempty frames.\n{path}")
        except (ValueError, OSError, IndexError) as error:
            self.report.setPlainText(str(error))

    def _import(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Review image package", "", "Workshop image manifest (images.json)")
        if filename:
            self.review(Path(filename))

    def review(self, path: Path) -> None:
        self.plan = None
        self.apply.setEnabled(False)
        self.frames.clear()
        self.image.clear()
        try:
            self.plan = stage_image_batch(self.session, path)
            self.report.setPlainText("\n".join(self.plan.report) + "\n\nKnown shared uses (additional runtime uses may exist):\n" + "\n".join(self.plan.uses))
            for key, before, after in self.plan.changes:
                texture = texture_from_raw(after, key[1], self.session.rom.section(AssetType.EMPTY_14))
                for frame in range(len(texture.frames)):
                    item = QTreeWidgetItem((f"{key[0].name} {key[1]}", str(frame)))
                    item.setData(0, Qt.ItemDataRole.UserRole, (key, frame))
                    self.frames.addTopLevelItem(item)
            self.apply.setEnabled(bool(self.plan.changes))
            if self.frames.topLevelItemCount():
                self.frames.setCurrentItem(self.frames.topLevelItem(0))
            else:
                self.report.setPlainText("No edited image frames found. Project is unchanged.")
        except (ValueError, OSError) as error:
            self.plan = None
            self.report.setPlainText(str(error))

    def _preview(self, item: QTreeWidgetItem | None, *_: object) -> None:
        if item is None or self.plan is None:
            return
        from src.ui.image_browser import image_pixmap
        key, frame = item.data(0, Qt.ItemDataRole.UserRole)
        raw = next(after for k, _, after in self.plan.changes if k == key)
        texture = texture_from_raw(raw, key[1], self.session.rom.section(AssetType.EMPTY_14))
        self.image.setPixmap(image_pixmap(texture.frames[frame].pixels, QSize(500, 200)))

    def apply_plan(self) -> None:
        if self.plan is None:
            return
        try:
            changed = apply_image_batch(self.session, self.plan)
            if changed:
                self.assets_changed.emit()
            self.apply.setEnabled(False)
            self.report.append("Applied as one undo step." if changed else "Already matches the project.")
        except (ValueError, OSError) as error:
            self.report.append(str(error))
