"""The user's animated About banner, painted with artwork from the open ROM."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import random

import numpy as np
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Slot
from PySide6.QtGui import (
    QPainter, QColor, QFont, QImage, QMouseEvent, QPaintEvent,
    QShowEvent, QHideEvent, QKeyEvent,
)
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from src.core.about_artwork import load_about_artwork
from src.core.rom import RomImage
from src.core.textures import Pixels


def _image(pixels: Pixels) -> QImage:
    data = np.ascontiguousarray(pixels)
    return QImage(data.data, data.shape[1], data.shape[0], data.strides[0],
                  QImage.Format.Format_RGBA8888).copy()


@dataclass
class _Balloon:
    x: float
    y: float
    speed: float
    phase: float
    variant: int
    scale: float


@dataclass
class _Pop:
    x: float
    y: float
    scale: float
    frame: int = 0


class TimberIslandCanvas(QWidget):
    """Real game balloons, pop frames, sky, sun, logo and zipper; UI animation only."""

    def __init__(self, parent: QWidget | None = None, *, source: RomImage | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(460, 190)
        self.tick = 0.0
        self.rainbow_boost = False
        self.artwork_error = ""
        self.balloon_images: tuple[QImage, ...] = ()
        self.pop_images: tuple[QImage, ...] = ()
        self.logo = self.background = self.sun = self.zipper = QImage()
        if source is not None:
            try:
                artwork = load_about_artwork(source)
                self.balloon_images = tuple(_image(p) for p in artwork.balloons)
                self.pop_images = tuple(_image(p) for p in artwork.pop_frames)
                self.logo, self.background = _image(artwork.logo), _image(artwork.background)
                self.sun, self.zipper = _image(artwork.sun), _image(artwork.zipper)
            except (ValueError, OSError) as error:
                self.artwork_error = str(error)
                logging.warning("About artwork unavailable: %s", error)
        self.balloons = [self._spawn_balloon(random_y=True) for _ in range(9)]
        self.particles: list[_Pop] = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_frame)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self.balloon_images:
            self.timer.start(16)

    def hideEvent(self, event: QHideEvent) -> None:
        self.timer.stop()
        super().hideEvent(event)

    def _spawn_balloon(self, random_y: bool = False) -> _Balloon:
        return _Balloon(
            random.uniform(30, self.width()-30),
            random.uniform(20, self.height()+20) if random_y else self.height()+40.0,
            random.uniform(0.6, 1.3), random.uniform(0, math.tau),
            random.randrange(6), random.uniform(0.75, 1.15),
        )

    def _balloon_rect(self, balloon: _Balloon) -> QRectF:
        image = self.balloon_images[balloon.variant]
        width = 36*balloon.scale
        height = width*image.height()/image.width()
        x = balloon.x + math.sin(self.tick+balloon.phase)*10
        return QRectF(x-width/2, balloon.y-height/2, width, height)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.balloon_images:
            point = event.position()
            # Later balloons draw on top. Ignore transparent corners of their images.
            for index in range(len(self.balloons)-1, -1, -1):
                balloon = self.balloons[index]
                rect = self._balloon_rect(balloon)
                if not rect.contains(point):
                    continue
                image = self.balloon_images[balloon.variant]
                x = min(image.width()-1, int((point.x()-rect.x())*image.width()/rect.width()))
                y = min(image.height()-1, int((point.y()-rect.y())*image.height()/rect.height()))
                if image.pixelColor(x, y).alpha() < 26:
                    continue
                self.particles.append(_Pop(rect.center().x(), rect.center().y(), balloon.scale))
                self.balloons[index] = self._spawn_balloon()
                event.accept()
                return
        super().mousePressEvent(event)

    @Slot()
    def _update_frame(self) -> None:
        speed_mult = 2.5 if self.rainbow_boost else 1.0
        self.tick += 0.05*speed_mult
        for index, balloon in enumerate(self.balloons):
            balloon.y -= balloon.speed*speed_mult
            if balloon.y < -60:
                self.balloons[index] = self._spawn_balloon()
        for pop in self.particles:
            pop.frame += 1
        self.particles = [p for p in self.particles if p.frame < len(self.pop_images)*2]
        self.update()

    def _draw_zipper(self, painter: QPainter, cx: float, cy: float) -> None:
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self.tick*25)
        painter.setOpacity(0.75 if self.rainbow_boost else 0.35)
        for _ in range(8):
            painter.rotate(45)
            painter.drawImage(QRectF(-12, -83, 24, 24), self.zipper)
        painter.restore()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        if not self.balloon_images:
            painter.fillRect(self.rect(), QColor("#202b40"))
            painter.setPen(QColor("#f4ca48"))
            painter.setFont(QFont("Arial Black", 28, QFont.Weight.Black))
            painter.drawText(self.rect().adjusted(0, -20, 0, -20),
                             Qt.AlignmentFlag.AlignCenter, "DKR")
            painter.setPen(QColor("#d9e2ee"))
            painter.setFont(QFont("Segoe UI", 10))
            message = "Game artwork unavailable" if self.artwork_error else "Open a ROM to see the game artwork"
            painter.drawText(self.rect().adjusted(0, 65, 0, 0), Qt.AlignmentFlag.AlignCenter, message)
            return

        # The actual island/sea sky texture replaces the invented sun/island/wave shapes.
        scale = max(self.width()/self.background.width(), self.height()/self.background.height())
        width, height = self.background.width()*scale, self.background.height()*scale
        painter.drawImage(QRectF((self.width()-width)/2, (self.height()-height)/2, width, height),
                          self.background)
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.drawImage(QRectF(self.width()-96, 0, 82, 82), self.sun)
        painter.restore()
        self._draw_zipper(painter, self.width()/2, self.height()/2)
        for balloon in self.balloons:
            painter.drawImage(self._balloon_rect(balloon), self.balloon_images[balloon.variant])
        for pop in self.particles:
            size = 70*pop.scale
            painter.drawImage(QRectF(pop.x-size/2, pop.y-size/2, size, size),
                              self.pop_images[pop.frame//2])

        # The original title is assembled from the same menu tiles, including its TM.
        bob = math.sin(self.tick*1.4)*5
        width = 278.0
        height = width*self.logo.height()/self.logo.width()
        painter.drawImage(QRectF((self.width()-width)/2, 34+bob, width, height), self.logo)
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(0, 145+bob, self.width(), 30), Qt.AlignmentFlag.AlignCenter, "WORKSHOP")


class AboutDialog(QDialog):
    """Standalone custom About window for DKR Workshop."""
    def __init__(self, version: str, parent: QWidget | None = None, *, source: RomImage | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About DKR Workshop")
        self.setFixedSize(460, 370)

        self.setStyleSheet("""
            QDialog {
                background-color: #161925;
                color: #ECEFF4;
            }
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                color: #D8DEE9;
            }
            QLabel#versionBadge {
                background-color: #242938;
                color: #FFD700;
                font-weight: bold;
                font-family: 'Consolas', monospace;
                padding: 4px 12px;
                border-radius: 4px;
                border: 1px solid #EBCB8B;
            }
            QPushButton {
                background-color: #E53935;
                color: #FFFFFF;
                font-weight: bold;
                border: 2px solid #FFCA28;
                border-radius: 6px;
                padding: 7px 22px;
            }
            QPushButton:hover {
                background-color: #F44336;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 16)
        layout.setSpacing(12)

        # Top Timber's Island banner
        self.canvas = TimberIslandCanvas(self, source=source)
        layout.addWidget(self.canvas)

        # Info section
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(24, 6, 24, 0)
        info_layout.setSpacing(8)

        badge_layout = QHBoxLayout()
        version_label = QLabel(f"GOLDEN BALLOON BUILD v{version}")
        version_label.setObjectName("versionBadge")
        badge_layout.addStretch()
        badge_layout.addWidget(version_label)
        badge_layout.addStretch()
        info_layout.addLayout(badge_layout)

        desc_label = QLabel(
            "Level, track, and asset editor for <b>Diddy Kong Racing</b>.<br>"
            "<i>\"My name is Taj the Genie of the island. I am here to help you!\"</i>"
        )
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)

        self.secret_label = QLabel(
            "<i>Tip: Click balloons to pop them, or type 'FREEFORALL'!</i>"
        )
        self.secret_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.secret_label.setStyleSheet("color: #7C889B; font-size: 11px;")
        info_layout.addWidget(self.secret_label)

        layout.addLayout(info_layout)
        layout.addStretch()

        btn_layout = QHBoxLayout()
        close_btn = QPushButton("Select Vehicle && Go!")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._key_buffer = ""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Listen for DKR Magic Codes (FREEFORALL, ZAP, TT)."""
        text = event.text().upper()
        if text.isalpha():
            self._key_buffer = (self._key_buffer + text)[-12:]
            if any(code in self._key_buffer for code in ("FREEFORALL", "ZAP", "TT")):
                self.canvas.rainbow_boost = True
                self.secret_label.setText(
                    "🌈 <b>GREEN ZIPPER RAINBOW BOOST!</b> Let go of the A button!"
                )
                self.secret_label.setStyleSheet("color: #FFD700; font-size: 12px;")
        super().keyPressEvent(event)
