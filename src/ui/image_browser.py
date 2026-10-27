"""Existing texture/sprite browser with PNG export and staged quantized import."""
from __future__ import annotations

from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtGui import QImage, QPixmap, QIcon, QPainter, QColor, QAction, QKeySequence
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QLineEdit, QTreeWidget, QTreeWidgetItem, QSplitter, QPushButton,
    QSpinBox, QFileDialog, QTextEdit)

from src.core.editing import EditSession
from src.core.rom import RomImage, DecompAssets, AssetType
from src.core.textures import TextureHeader, load_texture, load_sprite, Pixels
from src.core.image_assets import (read_png, export_png, sprite_canvas, texture_from_raw,
                                   png_flip_default, png_rows)
from src.core.image_usage import ImageUses, build_image_uses
from src.core.objects import ObjectDatabase

ROLE = int(Qt.ItemDataRole.UserRole)


def image_pixmap(pixels: Pixels, maximum: QSize) -> QPixmap:
    p = np.ascontiguousarray(pixels)
    image = QImage(p.data, p.shape[1], p.shape[0], p.strides[0], QImage.Format.Format_RGBA8888).copy()
    scaled = QPixmap.fromImage(image).scaled(maximum, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
    result = QPixmap(scaled.size())
    result.fill(QColor("#2b3440"))
    painter = QPainter(result)
    for y in range(0, result.height(), 10):
        for x in range(0, result.width(), 10):
            if (x // 10 + y // 10) % 2:
                painter.fillRect(x, y, 10, 10, QColor("#414d5a"))
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return result


class ImageBrowser(QDialog):
    assets_changed = Signal()
    history_requested = Signal(bool)

    def __init__(self, source: RomImage | DecompAssets, session: EditSession | None,
                 database: ObjectDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Texture & Sprite Browser — PNG export / import")
        self.setObjectName("imageAssetBrowser")
        self.resize(1050, 820)
        self.source, self.session, self.database = source, session, database
        self.key = (AssetType.TEXTURES_3D, 0)
        self.pixels: Pixels | None = None
        self.draft: Pixels | None = None
        self.quantized: Pixels | None = None
        self._shown_asset: bytes | None = None
        self._loading = False
        self._uses: ImageUses | None = None
        self._thumbnail_keys: set[tuple[AssetType, int]] = set()
        self._last_directory = Path.cwd()
        layout = QVBoxLayout(self)
        intro = QLabel("Export a PNG frame, edit it, then import and Apply. Keep its size and tile layout. Images are shared assets; known uses appear below.", self)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        split = QSplitter(self)
        left = QWidget(split); left_layout = QVBoxLayout(left)
        self.kind = QComboBox(left)
        for section in (AssetType.TEXTURES_3D, AssetType.TEXTURES_2D, AssetType.SPRITES):
            self.kind.addItem(section.name.replace("_", " ").title(), int(section))
        self.kind.currentIndexChanged.connect(self._populate)
        left_layout.addWidget(self.kind)
        self.search = QLineEdit(left)
        self.search.setPlaceholderText("Filter ID, format or dimensions…")
        self.search.setAccessibleName("Filter image assets")
        self.search.textChanged.connect(self._filter)
        left_layout.addWidget(self.search)
        self.assets = QTreeWidget(left)
        self.assets.setObjectName("imageAssetList")
        self.assets.setHeaderLabels(["ID", "Format / tiles", "Pixels", "Frames"])
        self.assets.setRootIsDecorated(False)
        self.assets.setIconSize(QSize(40, 40))
        self.assets.setColumnWidth(0, 100); self.assets.setColumnWidth(1, 105); self.assets.setColumnWidth(2, 85)
        self.assets.setColumnWidth(3, 55)
        self.assets.currentItemChanged.connect(self._selected)
        self.assets.verticalScrollBar().valueChanged.connect(lambda *_: QTimer.singleShot(0, self._thumbnails))
        left_layout.addWidget(self.assets, 1)
        self.count = QLabel("", left); left_layout.addWidget(self.count)
        right = QWidget(split); right_layout = QVBoxLayout(right)
        self.title = QLabel("", right); self.title.setWordWrap(True); right_layout.addWidget(self.title)
        frame_row = QHBoxLayout()
        frame_row.addWidget(QLabel("Frame", right))
        self.frame = QSpinBox(right); self.frame.setAccessibleName("Image frame")
        self.frame.valueChanged.connect(self._show_asset)
        frame_row.addWidget(self.frame)
        self.view = QComboBox(right)
        self.view.addItems(["Stored", "Imported PNG", "N64 result"])
        self.view.currentIndexChanged.connect(self._draw_image)
        frame_row.addWidget(self.view, 1)
        right_layout.addLayout(frame_row)
        orientation_row = QHBoxLayout()
        orientation_row.addWidget(QLabel("PNG orientation", right))
        self.png_orientation = QComboBox(right)
        self.png_orientation.addItem("Automatic (3D editing orientation)", "auto")
        self.png_orientation.addItem("Raw ROM rows (legacy PNGs)", "raw")
        self.png_orientation.setAccessibleName("PNG orientation")
        self.png_orientation.setToolTip("Automatic follows the local extractor: flip 3D PNGs vertically for editing, then reverse on import. 2D textures/sprites stay unchanged. For old untagged raw PNGs, choose Raw ROM rows before importing. New PNG orientation metadata is honored automatically.")
        self.png_orientation.currentIndexChanged.connect(self._orientation_changed)
        orientation_row.addWidget(self.png_orientation, 1)
        right_layout.addLayout(orientation_row)
        self.image = QLabel(right)
        self.image.setMinimumSize(300, 240)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background: #131c26; border: 1px solid #4a596b;")
        self.image.setAccessibleName("Image PNG preview")
        right_layout.addWidget(self.image)
        self.info = QLabel("", right); self.info.setWordWrap(True); right_layout.addWidget(self.info)
        self.orientation_note = QLabel("", right)
        self.orientation_note.setWordWrap(True)
        right_layout.addWidget(self.orientation_note)
        buttons = QGridLayout()
        self.export = QPushButton("Export stored frame PNG…", right)
        self.export.clicked.connect(self._export_dialog)
        self.import_button = QPushButton("Import frame PNG…", right)
        self.import_button.clicked.connect(self._import_dialog)
        self.apply = QPushButton("Apply imported frame", right)
        self.apply.clicked.connect(self._apply)
        self.discard = QPushButton("Discard import preview", right)
        self.discard.clicked.connect(self._show_asset)
        buttons.addWidget(self.export, 0, 0); buttons.addWidget(self.import_button, 0, 1)
        buttons.addWidget(self.apply, 1, 0); buttons.addWidget(self.discard, 1, 1)
        right_layout.addLayout(buttons)
        metadata = QGridLayout()
        self.anchor_x, self.anchor_y = QSpinBox(right), QSpinBox(right)
        for spin, name in ((self.anchor_x, "Sprite anchor X"), (self.anchor_y, "Sprite anchor Y")):
            spin.setRange(-32768, 32767); spin.setAccessibleName(name)
        metadata.addWidget(QLabel("Sprite anchor X / Y", right), 0, 0)
        metadata.addWidget(self.anchor_x, 0, 1); metadata.addWidget(self.anchor_y, 0, 2)
        self.anchor_apply = QPushButton("Apply anchor", right)
        self.anchor_apply.clicked.connect(self._anchor)
        metadata.addWidget(self.anchor_apply, 0, 3)
        self.timing = QSpinBox(right); self.timing.setRange(0, 65535)
        self.timing.setAccessibleName("Texture raw frame advance")
        self.timing.setToolTip("Raw unsigned16 advance per 60 Hz update in a 256-units-per-frame counter. Bigger values advance faster; zero pauses. Game flags determine whether it is used. This is not a sprite speed field.")
        metadata.addWidget(QLabel("Texture frame advance", right), 1, 0)
        metadata.addWidget(self.timing, 1, 1, 1, 2)
        self.timing_apply = QPushButton("Apply timing", right)
        self.timing_apply.clicked.connect(self._timing)
        metadata.addWidget(self.timing_apply, 1, 3)
        right_layout.addLayout(metadata)
        self.revert = QPushButton("Revert asset artwork to original ROM", right)
        self.revert.setToolTip("For a sprite, restores its anchor and every referenced 2D tile across all frames. Shared users of these tiles also revert.")
        self.revert.clicked.connect(self._revert)
        right_layout.addWidget(self.revert)
        self.uses = QTextEdit(right); self.uses.setReadOnly(True)
        self.uses.setAccessibleName("Known shared image uses")
        right_layout.addWidget(self.uses, 1)
        split.addWidget(left); split.addWidget(right); split.setSizes([420, 630])
        layout.addWidget(split, 1)
        self.message = QLabel("", self); self.message.setWordWrap(True); layout.addWidget(self.message)
        history = QHBoxLayout()
        self.undo = QPushButton("Undo", self); self.redo = QPushButton("Redo", self)
        self.undo.clicked.connect(lambda: self.history_requested.emit(False))
        self.redo.clicked.connect(lambda: self.history_requested.emit(True))
        history.addWidget(self.undo); history.addWidget(self.redo); layout.addLayout(history)
        for shortcut, forward in (("Ctrl+Z", False), ("Ctrl+Y", True), ("Ctrl+Shift+Z", True)):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda checked=False, redo=forward: self.history_requested.emit(redo))
            self.addAction(action)
        close = QPushButton("Close", self); close.clicked.connect(self.close); layout.addWidget(close)
        self._populate()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if hasattr(self, "image"):
            self._draw_image()

    def _populate(self, *_: object) -> None:
        self._loading = True
        section = AssetType(self.kind.currentData())
        self.assets.clear(); self._thumbnail_keys.clear()
        for index in range(self.source.count(section)):
            if section == AssetType.SPRITES:
                sprite = load_sprite(self.source, index)
                values = [str(index), f"{sprite.frame_offsets[-1]} tiles", "Sprite", str(sprite.frame_count)]
            else:
                header = TextureHeader.from_bytes(self.source.read_asset(section, index))
                values = [str(index), header.format.name, f"{header.width}×{header.height}", str(header.frame_count)]
            item = QTreeWidgetItem(values); item.setData(0, ROLE, index)
            item.setSizeHint(0, QSize(40, 42))
            self.assets.addTopLevelItem(item)
        self._loading = False
        self._filter()
        self.assets.setCurrentItem(self.assets.topLevelItem(0))
        QTimer.singleShot(0, self._thumbnails)

    def _filter(self, *_: object) -> None:
        text = self.search.text().casefold().strip()
        shown = 0
        for row in range(self.assets.topLevelItemCount()):
            item = self.assets.topLevelItem(row)
            hidden = text not in " ".join(item.text(i) for i in range(4)).casefold()
            item.setHidden(hidden); shown += not hidden
        self.count.setText(f"{shown} of {self.assets.topLevelItemCount()} assets")
        QTimer.singleShot(0, self._thumbnails)

    def _thumbnails(self) -> None:
        if not self.isVisible():
            return
        section = AssetType(self.kind.currentData())
        for row in range(self.assets.topLevelItemCount()):
            item = self.assets.topLevelItem(row)
            key = section, int(item.data(0, ROLE))
            if item.isHidden() or key in self._thumbnail_keys or not self.assets.visualItemRect(item).intersects(self.assets.viewport().rect()):
                continue
            self._thumbnail_keys.add(key)
            try:
                pixels = sprite_canvas(self.source, key[1]).pixels if section == AssetType.SPRITES else load_texture(self.source, key[1], asset_type=section).frames[0].pixels
                flip = self.png_orientation.currentData() == "auto" and png_flip_default(self.source, *key)
                item.setIcon(0, QIcon(image_pixmap(png_rows(pixels, flip_y=flip), QSize(40, 40))))
            except (ValueError, OSError) as error:
                item.setToolTip(0, str(error))

    def select_asset(self, section: AssetType, index: int) -> None:
        self.kind.setCurrentIndex(self.kind.findData(int(section)))
        self.search.clear()
        item = self.assets.topLevelItem(index)
        if item is not None:
            self.assets.setCurrentItem(item); self.assets.scrollToItem(item)

    def _selected(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        if self._loading or current is None:
            return
        self.key = AssetType(self.kind.currentData()), int(current.data(0, ROLE))
        self.frame.blockSignals(True); self.frame.setValue(0); self.frame.blockSignals(False)
        self._show_asset()

    def _show_asset(self, *_: object) -> None:
        self.draft = self.quantized = None
        self.apply.setEnabled(False); self.discard.setEnabled(False)
        self.view.setCurrentIndex(0)
        section, index = self.key
        self.title.setText(f"{section.name} {index} · frame {self.frame.value()}")
        self.uses.clear()
        self.pixels = None
        self.png_orientation.setEnabled(section == AssetType.TEXTURES_3D)
        self.export.setEnabled(False); self.import_button.setEnabled(False)
        self.anchor_apply.setEnabled(False); self.timing_apply.setEnabled(False)
        self.anchor_x.setEnabled(False); self.anchor_y.setEnabled(False); self.timing.setEnabled(False)
        self.revert.setEnabled(self.session is not None)
        try:
            self._shown_asset = self.source.read_asset(section, index)
            self._update_orientation_note()
            if section == AssetType.SPRITES:
                sprite = load_sprite(self.source, index)
                frames = sprite.frame_count
                self.frame.setMaximum(frames - 1)
                self.anchor_x.setValue(sprite.anchor[0]); self.anchor_y.setValue(sprite.anchor[1])
                for control in (self.anchor_x, self.anchor_y, self.anchor_apply): control.setEnabled(self.session is not None)
                canvas = sprite_canvas(self.source, index, self.frame.value())
                self.pixels = canvas.pixels
                details = f"{canvas.layout} · {len(canvas.tiles)} tile(s) · anchor {sprite.anchor}\nPNG omits the anchor; keep tile layout and transparent gaps. Sprite speed comes from its behavior/object, not this definition."
            else:
                texture = load_texture(self.source, index, asset_type=section)
                frames = len(texture.frames)
                self.frame.setMaximum(frames - 1)
                tex = texture.frames[self.frame.value()]
                self.pixels = tex.pixels
                self.timing.setValue(tex.header.frame_advance)
                for control in (self.timing, self.timing_apply): control.setEnabled(self.session is not None)
                details = f"{tex.header.format.name} · row swap {'on' if tex.header.flags & 0x400 else 'off'} · original format, headers and frame count retained"
            self.title.setText(f"{section.name} {index} · frame {self.frame.value()} of {frames}")
            self.info.setText(f"{self.pixels.shape[1]}×{self.pixels.shape[0]} PNG\n{details}")
            self.export.setEnabled(True); self.import_button.setEnabled(self.session is not None)
            self._draw_image()
            self.refresh_context()
            self.message.setText("Export is read-only. Import previews the quantized result; Apply stores it as one undo step." if self.session else "Extracted assets: PNG export and inspection only. Open the original Rev 1 ROM to edit.")
        except (ValueError, OSError) as error:
            self.image.clear(); self.info.setText(str(error)); self.message.setText(f"Artwork unavailable: {error}")

    def _draw_image(self, *_: object) -> None:
        pixels = (self.pixels, self.draft, self.quantized)[self.view.currentIndex()]
        if pixels is not None:
            self.image.setPixmap(image_pixmap(png_rows(pixels, flip_y=self._png_flip()), QSize(max(1, self.image.width() - 12), max(1, self.image.height() - 12))))

    def _png_flip(self) -> bool:
        return self.png_orientation.currentData() == "auto" and png_flip_default(self.source, *self.key)

    def _update_orientation_note(self) -> None:
        if self.key[0] != AssetType.TEXTURES_3D:
            note = "PNG orientation: stored rows. 2D textures and sprites keep their existing orientation."
        elif self._png_flip():
            note = "3D PNGs shown/exported vertically flipped for editing; import automatically restores stored rows."
        elif self.png_orientation.currentData() == "auto":
            note = "PNG orientation: this extracted asset records no vertical flip."
        else:
            note = "PNG orientation: raw stored rows. Use for older untagged raw exports."
        self.orientation_note.setText(note)

    def _orientation_changed(self, *_: object) -> None:
        self._update_orientation_note()
        self._draw_image()
        self._thumbnail_keys.clear()
        self._thumbnails()

    def export_to(self, path: Path) -> Path:
        if self.pixels is None:
            raise ValueError("Choose a nonempty image frame")
        return export_png(self.pixels, path, asset_type=self.key[0], flip_y=self._png_flip())

    def import_from(self, path: Path) -> None:
        if self.pixels is None or self.session is None:
            raise ValueError("Open an editable image first")
        pixels = read_png(path, (self.pixels.shape[1], self.pixels.shape[0]), asset_type=self.key[0], flip_y=self._png_flip())
        updates = self.session.image_updates(*self.key, self.frame.value(), pixels)
        if self.key[0] == AssetType.SPRITES:
            canvas = sprite_canvas(self.source, self.key[1], self.frame.value())
            quantized = self.pixels.copy()
            for index, x, y, width, height in canvas.tiles:
                raw = updates[AssetType.TEXTURES_2D, index]
                quantized[y:y + height, x:x + width] = texture_from_raw(raw, index).frames[0].pixels
        else:
            quantized = texture_from_raw(updates[self.key], self.key[1]).frames[self.frame.value()].pixels
        self.draft, self.quantized = pixels, quantized
        changed = any(raw != self.session.current_asset(*key) for key, raw in updates.items())
        self.apply.setEnabled(changed); self.discard.setEnabled(True)
        self.view.setCurrentIndex(2); self._draw_image()
        differences = int(np.count_nonzero(np.any(pixels != quantized, axis=2)))
        self.message.setText(f"Import preview: {differences:,} pixels adjusted to the existing N64 format. " + ("Apply to store this frame. Shared users change too." if changed else "Encoded pixels are unchanged; no edit needed."))

    def _export_dialog(self) -> None:
        filename = f"{self.key[0].name.lower()}_{self.key[1]}_frame{self.frame.value():03d}.png"
        chosen, _ = QFileDialog.getSaveFileName(self, "Export image frame", str(self._last_directory / filename), "PNG images (*.png)")
        if chosen:
            try:
                path = Path(chosen)
                if not path.suffix: path = path.with_suffix(".png")
                self.export_to(path); self._last_directory = path.parent
                self.message.setText(f"Exported {path.name}; saved project/ROM data is unchanged.")
            except (ValueError, OSError) as error: self.message.setText(f"Export failed: {error}")

    def _import_dialog(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "Import image frame", str(self._last_directory), "PNG images (*.png)")
        if chosen:
            try:
                self.import_from(Path(chosen)); self._last_directory = Path(chosen).parent
            except (ValueError, OSError) as error: self.message.setText(f"Import rejected: {error}")

    def _apply(self) -> None:
        if self.draft is None or self.session is None:
            return
        try:
            self.session.import_image(*self.key, self.frame.value(), self.draft)
            self.assets_changed.emit()
            self.refresh()
            self.message.setText("PNG applied. Ctrl+Z undoes the change. Save the project or export your ROM.")
        except (ValueError, OSError) as error: self.message.setText(f"Import rejected: {error}")

    def _anchor(self) -> None:
        if self.session is not None:
            try:
                self.session.set_sprite_anchor(self.key[1], self.anchor_x.value(), self.anchor_y.value())
                self.assets_changed.emit(); self.refresh()
            except (ValueError, OSError) as error: self.message.setText(f"Anchor rejected: {error}")

    def _timing(self) -> None:
        if self.session is not None:
            try:
                self.session.set_texture_timing(*self.key, self.timing.value())
                self.assets_changed.emit(); self.refresh()
            except (ValueError, OSError) as error: self.message.setText(f"Timing rejected: {error}")

    def _revert(self) -> None:
        if self.session is not None:
            try:
                self.session.revert_image(*self.key)
                self.assets_changed.emit(); self.refresh()
            except (ValueError, OSError) as error: self.message.setText(f"Revert rejected: {error}")

    def refresh(self) -> None:
        # Model/header refreshes also update dependency information. Keep a PNG
        # draft if its actual selected source asset has not changed underneath it.
        key, frame, view = self.key, self.frame.value(), self.view.currentIndex()
        draft, quantized = self.draft, self.quantized
        apply_enabled = self.apply.isEnabled()
        unchanged = (key[1] < self.source.count(key[0]) and self._shown_asset is not None
                     and self.source.read_asset(*key) == self._shown_asset)
        self._uses = None
        self._thumbnail_keys.clear()
        if self.assets.topLevelItemCount()!=self.source.count(AssetType(self.kind.currentData())):
            previous=self.key
            self._populate()
            if previous[1]<self.source.count(previous[0]):self.select_asset(*previous)
        else:
            self._show_asset()
        if unchanged and draft is not None and self.key == key:
            self.frame.setValue(frame)
            self.draft, self.quantized = draft, quantized
            self.apply.setEnabled(apply_enabled)
            self.discard.setEnabled(True)
            self.view.setCurrentIndex(view)
            self._draw_image()
            self.message.setText('Pending PNG preview retained. Apply or discard it when ready.')
        elif draft is not None:
            self.message.setText('The selected artwork changed; its previous PNG preview was cleared. Import it again to review against the current asset.')
        self._thumbnails()

    def refresh_context(self) -> None:
        """Update dependencies/history without discarding a pending PNG import."""
        self.undo.setEnabled(self.session is not None and self.session.can_undo)
        self.redo.setEnabled(self.session is not None and self.session.can_redo)
        if self.session is not None:
            self._uses = self.session.image_uses
        elif self._uses is None:
            self._uses = build_image_uses(self.source, self.database)
        uses = self._uses
        self.uses.setPlainText("Known shared uses (HUD/menu/code may add more):\n" + "\n".join(sorted(uses.direct.get(self.key, set()))) +
            "\n\nKnown affected levels:\n" + ("\n".join(sorted(uses.levels.get(self.key, set()))) or "No level reference found in scanned assets."))
