"""Staged track-to-minimap artwork and projection alignment."""
from __future__ import annotations

from dataclasses import replace
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QPushButton, QTextEdit, QFileDialog)

from src.core.editing import EditSession
from src.core.image_assets import sprite_canvas, export_png
from src.core.materials import SURFACES
from src.core.minimap import MinimapSettings, load_minimap_tiles
from src.core.minimap_generation import (GeneratedMinimap, MinimapGenerationOptions,
    generate_minimap, apply_generated_minimap)
from src.core.rom import AssetType
from src.ui.minimap_panel import MinimapPreview


class MinimapGeneratorDialog(QDialog):
    assets_changed = Signal()

    def __init__(self, session: EditSession, model_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate course minimap")
        self.resize(700, 760)
        self.session, self.model_id = session, model_id
        self.plan: GeneratedMinimap | None = None
        layout = QVBoxLayout(self)
        intro = QLabel("Generate a top-down silhouette from the current track. Preview the stored N64 artwork and checkpoint alignment, then apply both as one undo step.", self)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.sprite = QComboBox(self)
        for ref in session.minimap_references:
            self.sprite.addItem(ref.label, ref.sprite_id)
        current = int(MinimapSettings.from_bytes(session.track_model(model_id).raw_data).values["sprite"])
        self.sprite.setCurrentIndex(self.sprite.findData(current))
        row.addWidget(QLabel("Existing map canvas", self))
        row.addWidget(self.sprite, 1)
        self.surface = QComboBox(self)
        self.surface.addItem("All visible collision surfaces", None)
        available = sorted({t.surface_type for t in session.track_model(model_id).textures} | {0})
        for value in available:
            self.surface.addItem(f"{value}: {SURFACES[value] if 0 <= value < len(SURFACES) else 'Surface'}", value)
        self.surface.setCurrentIndex(self.surface.findData(0))
        row = QHBoxLayout()
        layout.addLayout(row)
        row.addWidget(QLabel("Faces", self))
        row.addWidget(self.surface, 1)
        self.rotation = QComboBox(self)
        for angle in (0, 90, 180, 270):
            self.rotation.addItem(f"{angle}°", angle)
        row.addWidget(self.rotation)
        self.padding = QSpinBox(self)
        self.padding.setRange(0, 32)
        self.padding.setValue(3)
        row.addWidget(QLabel("Padding", self))
        row.addWidget(self.padding)
        self.slope = QDoubleSpinBox(self)
        self.slope.setRange(0, 1)
        self.slope.setSingleStep(.1)
        self.slope.setValue(.3)
        self.slope.setToolTip("Minimum absolute upward normal component. Higher values exclude steeper faces; vertical walls and hidden/non-collision batches are excluded.")
        row.addWidget(QLabel("Slope filter", self))
        row.addWidget(self.slope)
        self.preview = MinimapPreview(self)
        maps = dict.fromkeys(map_id for level in session._catalog.levels if level.header.geometry_id == model_id
            for map_id in (level.header.object_map_id, level.header.secondary_object_map_id) if map_id >= 0)
        self.preview.objects = tuple(obj for map_id in maps for obj in session.current_map(map_id).objects if obj.definition.behavior_id == 13)
        layout.addWidget(self.preview, 1)
        self.adventure = QComboBox(self)
        self.adventure.addItems(("Adventure 1", "Adventure 2 (mirrored)"))
        self.adventure.currentIndexChanged.connect(self._adventure)
        layout.addWidget(self.adventure)
        self.details = QTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.generate = QPushButton("Generate preview", self)
        self.generate.clicked.connect(self.generate_preview)
        self.export = QPushButton("Export preview PNG…", self)
        self.export.clicked.connect(self._export)
        self.apply = QPushButton("Apply artwork + alignment", self)
        self.apply.clicked.connect(self.apply_plan)
        close = QPushButton("Close", self)
        close.clicked.connect(self.reject)
        for button in (self.generate, self.export, self.apply, close):
            button.setAutoDefault(False)
            row.addWidget(button)
        for control in (self.sprite, self.surface, self.rotation):
            control.currentIndexChanged.connect(self._invalidate)
        for control in (self.padding, self.slope):
            control.valueChanged.connect(self._invalidate)
        self._invalidate()

    def _adventure(self) -> None:
        self.preview.mirrored = self.adventure.currentIndex() == 1
        self.preview.update()

    def _invalidate(self, *_: object) -> None:
        self.plan = None
        self.apply.setEnabled(False)
        self.export.setEnabled(False)
        self.preview.error = "Generate a preview for the selected faces and canvas."
        self.preview.update()

    def generate_preview(self) -> None:
        self._invalidate()
        try:
            surface = self.surface.currentData()
            options = MinimapGenerationOptions(None if surface is None else (surface,),
                self.rotation.currentData(), self.padding.value(), self.slope.value())
            self.plan = generate_minimap(self.session, self.model_id, options, self.sprite.currentData())
            sprite, tiles = load_minimap_tiles(self.session.asset_source, self.plan.sprite_id)
            canvas = sprite_canvas(self.session.asset_source, self.plan.sprite_id)
            positions = {index: (x, y, w, h) for index, x, y, w, h in canvas.tiles}
            decoded = []
            for tile in tiles:
                x, y, w, h = positions[tile.texture_id]
                decoded.append(replace(tile, frame=replace(tile.frame, pixels=self.plan.pixels[y:y+h, x:x+w].copy())))
            self.preview.set_art(sprite, tuple(decoded), self.plan.settings)
            self.details.setPlainText(f"{self.plan.face_count} faces → {canvas.pixels.shape[1]}×{canvas.pixels.shape[0]} pixels.\n"
                "Uses the existing sprite layout; replacing its pixels affects shared users. Known uses (additional runtime uses may exist):\n"
                + "\n".join(self.plan.shared_uses))
            self.apply.setEnabled(True)
            self.export.setEnabled(True)
        except (ValueError, OSError) as error:
            self.plan = None
            self.details.setPlainText(str(error))

    def apply_plan(self) -> None:
        if self.plan is None:
            return
        try:
            changed = apply_generated_minimap(self.session, self.plan)
            if changed:
                self.assets_changed.emit()
            self.apply.setEnabled(False)
            self.details.append("Applied as one undo step." if changed else "Already matches the project.")
        except (ValueError, OSError) as error:
            self.details.append(str(error))

    def _export(self) -> None:
        if self.plan is None:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Export generated minimap", "minimap.png", "PNG (*.png)")
        if filename:
            from pathlib import Path
            try:
                export_png(self.plan.pixels, Path(filename), asset_type=AssetType.SPRITES)
            except (ValueError, OSError) as error:
                self.details.append(str(error))
