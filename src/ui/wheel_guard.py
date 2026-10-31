"""Keep wheel gestures for scrolling rather than changing editor values."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication,
    QComboBox, QLineEdit, QScrollBar, QWidget,
)


def _is_value_control(widget: QObject | None) -> bool:
    return isinstance(widget, (QAbstractSpinBox, QComboBox)) or (
        isinstance(widget, QAbstractSlider) and not isinstance(widget, QScrollBar)
    )


def _remove_wheel_focus(widget: QWidget) -> None:
    # Retain the widget's existing click/tab behavior, including NoFocus sliders.
    wheel_bit = Qt.FocusPolicy.WheelFocus.value ^ Qt.FocusPolicy.StrongFocus.value
    widget.setFocusPolicy(Qt.FocusPolicy(widget.focusPolicy().value & ~wheel_bit))


class ValueWheelGuard(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Polish and _is_value_control(watched):
            _remove_wheel_focus(watched)
        elif isinstance(event, QWheelEvent) and isinstance(watched, QWidget):
            control = watched
            if isinstance(control, QLineEdit) and _is_value_control(control.parentWidget()):
                control = control.parentWidget()
            if _is_value_control(control):
                self._scroll_parent(control, event)
                # Consume even when no pane can scroll. Neither focused nor
                # unfocused fields may turn a scroll gesture into an edit.
                event.accept()
                return True
        return False

    @staticmethod
    def _scroll_parent(control: QWidget, event: QWheelEvent) -> None:
        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                viewport = parent.viewport()
                forwarded = QWheelEvent(
                    viewport.mapFromGlobal(event.globalPosition()), event.globalPosition(),
                    event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(),
                    event.phase(), event.inverted(), event.source(), event.pointingDevice(),
                )
                forwarded.setTimestamp(event.timestamp())
                forwarded.ignore()
                QApplication.sendEvent(viewport, forwarded)
                if forwarded.isAccepted():
                    return
            # A dialog's QObject parent may belong to another window. Do not
            # scroll that window when the pointer is over this dialog's field.
            if parent.isWindow():
                return
            parent = parent.parentWidget()


def install_wheel_guard(app: QApplication) -> ValueWheelGuard:
    """Install once for all windows, including future dialogs and cell editors."""
    guard = getattr(app, '_value_wheel_guard', None)
    if guard is None:
        guard = ValueWheelGuard(app)
        app._value_wheel_guard = guard
        app.installEventFilter(guard)
        for widget in app.allWidgets():
            if _is_value_control(widget):
                _remove_wheel_focus(widget)
    return guard
