"""Minimap settings with a HUD-relative sprite/checkpoint alignment preview."""
from __future__ import annotations

from collections.abc import Sequence
import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPaintEvent
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QSpinBox, QLineEdit, QCheckBox, QScrollArea, QColorDialog)

from src.core.level_model import LevelModel
from src.core.minimap import (MINIMAP_FIELDS, MinimapSettings, SpriteReference,
    edit_minimap, load_minimap_tiles, project_markers, tile_bounds)
from src.core.objects import LevelObject
from src.core.rom import DecompAssets, RomImage
from src.core.textures import SpriteAsset, SpriteTile


class MinimapPreview(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setMinimumHeight(270)
        self.setAccessibleName("Minimap alignment preview")
        self.settings: MinimapSettings | None = None
        self.sprite: SpriteAsset | None = None
        self.tiles: tuple[SpriteTile, ...] = ()
        self.images: tuple[QImage, ...] = ()
        self.objects: tuple[LevelObject, ...] = ()
        self.selected: LevelObject | None = None
        self.mirrored = False
        self.show_checkpoints = True
        self.error = "Select a level."
        self.marker_positions = np.empty((0, 2))

    def set_art(self, sprite: SpriteAsset, tiles: tuple[SpriteTile, ...], settings: MinimapSettings) -> None:
        self.sprite, self.tiles, self.settings = sprite, tiles, settings
        images: list[QImage] = []
        for tile in tiles:
            pixels = tile.frame.pixels.copy()
            pixels[:, :, :3] = (pixels[:, :, :3].astype(np.uint16) * np.array(settings.tint, np.uint16) // 255).astype(np.uint8)
            pixels = np.ascontiguousarray(pixels)
            images.append(QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format.Format_RGBA8888).copy())
        self.images = tuple(images)
        self.error = ""
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111923"))
        if self.error or self.settings is None or self.sprite is None or not self.tiles:
            painter.setPen(QColor("#b8c8d9"))
            painter.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.error or "Sprite first frame is empty.")
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = [tile_bounds(tile, self.sprite.anchor, mirrored=self.mirrored) for tile in self.tiles]
        lower = np.minimum(np.min(np.array(bounds)[:, :2], axis=0), (0, 0)) - 14
        upper = np.maximum(np.max(np.array(bounds)[:, 2:], axis=0), (0, 0)) + 14
        scale = min((self.width() - 24) / max(1, upper[0] - lower[0]), (self.height() - 42) / max(1, upper[1] - lower[1]))
        center = (lower + upper) / 2

        def screen(x: float, y: float) -> QPointF:
            return QPointF(self.width() / 2 + (x - center[0]) * scale, (self.height() - 20) / 2 - (y - center[1]) * scale)

        for image, (left, bottom, right, top) in zip(self.images, bounds):
            rect = QRectF(screen(left, top), screen(right, bottom))
            painter.drawImage(rect, image.mirrored(True, False) if self.mirrored else image)
        origin = screen(0, 0)
        painter.setPen(QPen(QColor("#71869b"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(origin + QPointF(-8, 0), origin + QPointF(8, 0))
        painter.drawLine(origin + QPointF(0, -8), origin + QPointF(0, 8))
        objects = tuple(obj for obj in self.objects if obj.definition.behavior_id == 13) if self.show_checkpoints else ()
        if self.selected is not None and not any(obj.key == self.selected.key for obj in objects):
            objects += (self.selected,)
        try:
            self.marker_positions = project_markers(self.settings, np.array([(obj.position[0], obj.position[2]) for obj in objects]).reshape(-1, 2), self.sprite.anchor, mirrored=self.mirrored)
            for obj, (x, y) in zip(objects, self.marker_positions):
                if abs(x) > 1e6 or abs(y) > 1e6:
                    continue
                pos = screen(x, y)
                if not self.rect().adjusted(-10, -10, 10, 10).contains(pos.toPoint()):
                    continue
                selected = self.selected is not None and obj.key == self.selected.key
                color = QColor("#ffd166" if selected else "#63e6eb")
                painter.setPen(QPen(QColor("#101820"), 1))
                painter.setBrush(color)
                radius = 4 if selected else 2.5
                painter.drawEllipse(pos, radius, radius)
                if selected or int(obj.value("index", -1)) == 0:
                    painter.setPen(color)
                    painter.drawText(pos + QPointF(6, -5), "Selected" if selected else "CP 0")
        except ValueError as error:
            painter.setPen(QColor("#ffad7a"))
            painter.drawText(10, 20, str(error))
        painter.setPen(QColor("#9cb0c5"))
        painter.drawText(8, self.height() - 9, "Cyan: checkpoints · Gold: selected · +: HUD anchor")


class MinimapPanel(QWidget):
    edit_requested = Signal(object)
    revert_requested = Signal()
    image_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model: LevelModel | None = None
        self.source: RomImage | DecompAssets | None = None
        self.refs: Sequence[SpriteReference] = ()
        self._loading = False
        self._enabled = False
        self._base_controls: dict[str, int | str] = {}
        self._art_cache: dict[int, tuple[SpriteAsset, tuple[SpriteTile, ...]]] = {}
        layout = QVBoxLayout(self)
        self.summary = QLabel("Select a level to inspect its minimap.", self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        options = QGridLayout()
        self.adventure = QComboBox(body)
        self.adventure.addItems(["Adventure 1", "Adventure 2 (mirrored)"])
        self.adventure.setAccessibleName("Minimap preview adventure")
        self.adventure.currentIndexChanged.connect(self._preview_options)
        options.addWidget(self.adventure, 0, 0)
        self.checkpoints = QCheckBox("Checkpoint overlay", body)
        self.checkpoints.setChecked(True)
        self.checkpoints.toggled.connect(self._preview_options)
        options.addWidget(self.checkpoints, 0, 1)
        body_layout.addLayout(options)
        self.preview = MinimapPreview(body)
        body_layout.addWidget(self.preview)
        self.metadata = QLabel("", body)
        self.metadata.setWordWrap(True)
        body_layout.addWidget(self.metadata)
        grid = QGridLayout()
        self.controls: dict[str, QSpinBox | QLineEdit | QComboBox] = {}
        for row, field in enumerate(MINIMAP_FIELDS):
            grid.addWidget(QLabel(field.label, body), row, 0)
            if field.key == "sprite":
                control = QComboBox(body)
                control.activated.connect(self._draft_changed)
            elif field.format == ">f":
                control = QLineEdit(body)
                control.setToolTip("Stored float32 multiplier. Finite values only; zero collapses and negative values reverse that marker coordinate. The map image stays fixed.")
                control.textChanged.connect(self._draft_changed)
            else:
                control = QSpinBox(body)
                control.setRange(*( (0, 65535) if field.key == "rotation" else (0, 255) if field.format == ">B" else (-32768, 32767)))
                control.setKeyboardTracking(False)
                control.valueChanged.connect(self._draft_changed)
            control.setAccessibleName(field.label)
            control.setObjectName("minimap_" + field.key)
            if field.key == "rotation":
                control.setToolTip("Stored unsigned16 degrees, converted with degrees × 65535 / 360. Rotates markers, not the sprite artwork.")
            if field.key.startswith("adv"):
                control.setToolTip("HUD coordinate units. Positive X is right; positive Y is up. Moves markers relative to the fixed map image.")
            self.controls[field.key] = control
            grid.addWidget(control, row, 1)
        body_layout.addLayout(grid)
        tint = QPushButton("Choose map tint…", body)
        tint.clicked.connect(self._choose_tint)
        self.tint = tint
        body_layout.addWidget(tint)
        hint = QLabel("Preview uses frame 0, sprite anchors and the game's marker projection. Adventure and overlays are preview only. Tint is shown at full opacity; HUD fade, TV layout and live racers are not simulated. Changes below are drafts until Apply.", body)
        hint.setWordWrap(True)
        body_layout.addWidget(hint)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.apply = QPushButton("Apply minimap settings", self)
        self.apply.clicked.connect(self._apply)
        layout.addWidget(self.apply)
        self.revert = QPushButton("Revert minimap to original ROM", self)
        self.revert.clicked.connect(self.revert_requested)
        layout.addWidget(self.revert)
        self.artwork = QPushButton("Export / replace map PNG…", self)
        self.artwork.setEnabled(False)
        self.artwork.clicked.connect(lambda: self.image_requested.emit(int(self.controls["sprite"].currentData())))
        layout.addWidget(self.artwork)
        self.message = QLabel("", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def show_context(self, model: LevelModel | None, source: RomImage | DecompAssets | None,
                     refs: Sequence[SpriteReference], levels: Sequence[str], enabled: bool, *, changed: bool = False) -> None:
        same = model is not None and self.model is not None and model.model_id == self.model.model_id and source is self.source
        pending = {key: self._control_value(control) for key, control in self.controls.items()
                   if same and key in self._base_controls and self._control_value(control) != self._base_controls[key]}
        self._loading = True
        if source is not self.source:
            self._art_cache.clear()
        self.model, self.source, self.refs, self._enabled = model, source, refs, enabled
        self.summary.setText(f"Geometry {model.model_id} · Shared levels: {', '.join(levels)}" if model else "Select a level to inspect its minimap.")
        self.revert.setEnabled(enabled and changed)
        self.artwork.setEnabled(model is not None)
        self.tint.setEnabled(enabled and model is not None)
        for control in self.controls.values():
            control.setEnabled(enabled and model is not None)
        if model is not None:
            values = MinimapSettings.from_bytes(model.raw_data).values
            sprite = self.controls["sprite"]
            sprite.clear()
            for ref in refs:
                sprite.addItem(ref.label, ref.sprite_id)
            row = sprite.findData(int(values["sprite"]))
            if row < 0:
                sprite.addItem(f"{values['sprite']} · current reference", int(values["sprite"]))
                row = sprite.count() - 1
            sprite.setCurrentIndex(row)
            for key, control in self.controls.items():
                if isinstance(control, QSpinBox):
                    control.setValue(int(values[key]))
                elif isinstance(control, QLineEdit):
                    control.setText(np.format_float_positional(np.float32(values[key]), unique=True, trim="-"))
        self._base_controls = {key: self._control_value(control) for key, control in self.controls.items()} if model else {}
        for key, value in pending.items():
            control = self.controls[key]
            if isinstance(control, QComboBox):
                row = control.findData(value)
                if row >= 0:
                    control.setCurrentIndex(row)
            elif isinstance(control, QLineEdit):
                control.setText(str(value))
            else:
                control.setValue(int(value))
        self._loading = False
        self.message.clear()
        self._draft_changed()

    @staticmethod
    def _control_value(control: QWidget) -> int | str:
        if isinstance(control, QComboBox):
            return int(control.currentData()) if control.currentData() is not None else -1
        if isinstance(control, QLineEdit):
            return control.text()
        return control.value()

    def _changes(self) -> dict[str, int | float]:
        if self.model is None:
            return {}
        result: dict[str, int | float] = {}
        for key, control in self.controls.items():
            if isinstance(control, QComboBox):
                result[key] = int(control.currentData())
            elif isinstance(control, QLineEdit):
                result[key] = float(control.text())
            else:
                result[key] = control.value()
        return result

    def _draft_changed(self, *_: object) -> None:
        if self._loading:
            return
        self.apply.setEnabled(False)
        if self.model is None or self.source is None:
            self.preview.error = "Select a level to preview its minimap."
            self.preview.update()
            self.metadata.clear()
            return
        try:
            raw = edit_minimap(self.model.raw_data, self._changes(), self.refs)
            settings = MinimapSettings.from_bytes(raw)
            index = int(settings.values["sprite"])
            if index not in self._art_cache:
                self._art_cache[index] = load_minimap_tiles(self.source, index)
            sprite, tiles = self._art_cache[index]
            self.preview.set_art(sprite, tiles, settings)
            self.metadata.setText(f"Sprite {index} · anchor {sprite.anchor} · frame 0 of {sprite.frame_count}\nX/Z bounds: {settings.bounds[0]}…{settings.bounds[1]} / {settings.bounds[4]}…{settings.bounds[5]} (read-only)")
            draft = raw != self.model.raw_data
            self.apply.setEnabled(self._enabled and draft)
            self.message.setText("Draft preview — Apply to store as one undo step." if draft else "Stored settings shown. Preview controls do not change saved data.")
        except (ValueError, OSError, OverflowError) as error:
            self.preview.error = str(error)
            self.preview.update()
            self.message.setText(f"Invalid draft: {error}")

    def _preview_options(self, *_: object) -> None:
        self.preview.mirrored = self.adventure.currentIndex() == 1
        self.preview.show_checkpoints = self.checkpoints.isChecked()
        self.preview.update()

    def set_objects(self, objects: tuple[LevelObject, ...], selected: LevelObject | None) -> None:
        self.preview.objects, self.preview.selected = objects, selected
        self.preview.update()

    def _choose_tint(self) -> None:
        value = tuple(self.controls[key].value() for key in ("red", "green", "blue"))
        color = QColorDialog.getColor(QColor(*value), self, "Minimap tint")
        if color.isValid():
            self._loading = True
            for key, component in zip(("red", "green", "blue"), (color.red(), color.green(), color.blue())):
                self.controls[key].setValue(component)
            self._loading = False
            self._draft_changed()

    def _apply(self) -> None:
        if self.apply.isEnabled():
            self.edit_requested.emit(self._changes())
