"""World-aligned editing planes and a screen-space orientation indicator."""
from __future__ import annotations

import math
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


def grid_spacing(span: float) -> float:
    """Keep about thirty cells visible using 1/2/5 steps in game units."""
    wanted = max(float(span)/30, 1.)
    base = 10.**math.floor(math.log10(wanted))
    return next(step*base for step in (1., 2., 5., 10.) if step*base >= wanted)


def grid_lines(center: np.ndarray, span: float, view: str) -> tuple[np.ndarray, float]:
    spacing = grid_spacing(span)
    radius = spacing*24
    axes = (0, 1) if view == 'Front' else (2, 1) if view == 'Right' else (0, 2)
    rows = []
    for axis, cross in (axes, axes[::-1]):
        first = math.floor((float(center[axis])-radius)/spacing)
        last = math.ceil((float(center[axis])+radius)/spacing)
        for i in range(first, last+1):
            shade = .48 if i % 5 == 0 else .29
            for side in (-1, 1):
                point = center.copy()
                point[axis] = i*spacing
                point[cross] += side*radius
                rows.append((*point, shade*.8, shade*.9, shade))
    return np.asarray(rows, np.float32), spacing


class OrientationIndicator(QWidget):
    """A camera-relative XYZ reference that never obscures viewport input."""
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.rotation = np.eye(3)

    def set_view(self, view: np.ndarray) -> None:
        if not np.array_equal(self.rotation, view[:3, :3]):
            self.rotation = view[:3, :3].copy()
            self.update()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 22, 32, 150))
        painter.drawEllipse(QPointF(48, 48), 43, 43)
        colors = (QColor('#ff655c'), QColor('#65e582'), QColor('#629eff'))
        for axis in np.argsort(self.rotation[2])[::-1]:
            tip = QPointF(48+float(self.rotation[0, axis])*29, 48-float(self.rotation[1, axis])*29)
            painter.setPen(QPen(colors[axis], 2))
            painter.drawLine(QPointF(48, 48), tip)
            painter.setBrush(colors[axis])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(tip, 9, 9)
            painter.setPen(QColor('#101820'))
            painter.drawText(int(tip.x()-9), int(tip.y()-9), 18, 18,
                             Qt.AlignmentFlag.AlignCenter, 'XYZ'[axis])
