"""Unfocused controls scroll panes; focused controls retain wheel editing."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateTimeEdit, QDialog, QDial, QDoubleSpinBox,
    QLineEdit, QScrollArea, QSlider, QSpinBox, QTableWidget, QVBoxLayout, QWidget,
)

from src.ui.wheel_guard import install_wheel_guard


@pytest.fixture(scope='module')
def app() -> QApplication:
    application = QApplication.instance() or QApplication([])
    install_wheel_guard(application)
    return application


@pytest.fixture
def pane(app: QApplication) -> Iterator[tuple[QScrollArea, QVBoxLayout]]:
    scroll = QScrollArea()
    scroll.resize(300, 220)
    content = QWidget()
    content.setMinimumSize(600, 1000)
    layout = QVBoxLayout(content)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    yield scroll, layout
    scroll.close()
    scroll.deleteLater()
    app.processEvents()


def wheel(widget: QWidget, *, angle: QPoint | None = None,
          pixel: QPoint | None = None, phase: Qt.ScrollPhase = Qt.ScrollPhase.NoScrollPhase,
          inverted: bool = False) -> QWheelEvent:
    point = QPointF(widget.rect().center())
    event = QWheelEvent(point, widget.mapToGlobal(point), pixel or QPoint(),
                        angle if angle is not None else QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        phase, inverted)
    QApplication.sendEvent(widget, event)
    return event


def combo(*, editable: bool = False) -> QComboBox:
    widget = QComboBox()
    widget.addItems([str(i) for i in range(40)])
    widget.setCurrentIndex(10)
    widget.setEditable(editable)
    return widget


def value(widget: QWidget) -> object:
    if isinstance(widget, QComboBox):
        return widget.currentIndex(), widget.currentText()
    if isinstance(widget, QDateTimeEdit):
        return widget.dateTime()
    return widget.value()


@pytest.mark.parametrize('factory', [QSpinBox, QDoubleSpinBox, combo,
    lambda: combo(editable=True), QSlider, QDial, QDateTimeEdit])
@pytest.mark.parametrize('focused', [False, True])
def test_wheel_edits_only_the_focused_control(
    app: QApplication, pane: tuple[QScrollArea, QVBoxLayout],
    factory: Callable[[], QWidget], focused: bool,
) -> None:
    scroll, layout = pane
    control = factory()
    if isinstance(control, (QSpinBox, QDoubleSpinBox, QSlider, QDial)):
        control.setValue(50)
    layout.addWidget(control)
    other = QLineEdit()
    layout.addWidget(other)
    scroll.show()
    app.processEvents()
    (control if focused else other).setFocus()
    app.processEvents()
    focus = app.focusWidget()
    before = value(control)
    wheel(control)
    if focused:
        assert value(control) != before
        assert scroll.verticalScrollBar().value() == 0
    else:
        assert value(control) == before
        assert scroll.verticalScrollBar().value() > 0
    assert app.focusWidget() is focus
    assert control.focusPolicy() != Qt.FocusPolicy.WheelFocus


@pytest.mark.parametrize('factory', [QSpinBox, lambda: combo(editable=True)])
def test_wheel_over_embedded_line_edit_scrolls_parent(
    app: QApplication, pane: tuple[QScrollArea, QVBoxLayout], factory: Callable[[], QWidget],
) -> None:
    scroll, layout = pane
    control = factory()
    layout.addWidget(control)
    other = QLineEdit()
    layout.addWidget(other)
    scroll.show()
    app.processEvents()
    other.setFocus()
    before = value(control)
    wheel(control.findChild(QLineEdit))
    assert value(control) == before
    assert scroll.verticalScrollBar().value() > 0


def test_click_and_keyboard_still_edit_focused_values(app: QApplication) -> None:
    spin = QSpinBox()
    spin.setValue(50)
    spin.show()
    app.processEvents()
    spin.setFocus()
    QTest.keyClick(spin, Qt.Key.Key_Up)
    assert spin.value() == 51
    spin.selectAll()
    QTest.keyClicks(spin, '23')
    QTest.keyClick(spin, Qt.Key.Key_Return)
    assert spin.value() == 23
    # The arrow buttons remain an intentional way to adjust a value.
    QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=QPoint(spin.width()-6, 5))
    assert spin.value() == 24
    wheel(spin)
    assert spin.value() == 23
    spin.close()
    spin.deleteLater()


def test_horizontal_scroll_and_scrollbar_wheel_remain_available(
    app: QApplication, pane: tuple[QScrollArea, QVBoxLayout],
) -> None:
    scroll, layout = pane
    control = QSpinBox()
    layout.addWidget(control)
    scroll.show()
    app.processEvents()
    control.clearFocus()
    wheel(control, angle=QPoint(-120, 0))
    assert scroll.horizontalScrollBar().value() > 0
    wheel(scroll.verticalScrollBar())
    assert scroll.verticalScrollBar().value() > 0


def test_open_dropdown_list_still_scrolls(app: QApplication) -> None:
    control = combo()
    control.show()
    control.showPopup()
    app.processEvents()
    bar = control.view().verticalScrollBar()
    bar.setValue(0)
    wheel(control.view().viewport())
    assert bar.value() > 0
    assert control.currentIndex() == 10
    control.hidePopup()
    QTest.keyClick(control, Qt.Key.Key_Down)
    assert control.currentIndex() == 11
    control.close()
    control.deleteLater()


def test_table_cell_editor_scrolls_table_without_editing(app: QApplication) -> None:
    table = QTableWidget(100, 1)
    table.resize(300, 220)
    editor = QSpinBox()
    editor.setValue(50)
    table.setCellWidget(0, 0, editor)
    table.show()
    app.processEvents()
    table.setFocus()
    wheel(editor)
    assert table.verticalScrollBar().value() > 0
    assert editor.value() == 50
    table.close()
    table.deleteLater()


def test_wheel_forwarding_preserves_touchpad_data_and_stops_at_dialog(app: QApplication) -> None:
    class CapturePane(QScrollArea):
        received: QWheelEvent | None = None
        consume = True

        def wheelEvent(self, event: QWheelEvent) -> None:
            self.received = QWheelEvent(event)
            event.setAccepted(self.consume)

    outer = CapturePane()
    outer.setWidget(QWidget())
    inner = CapturePane(outer.widget())
    spin = QSpinBox(inner)
    inner.show()
    outer.show()
    app.processEvents()
    spin.clearFocus()
    event = wheel(spin, angle=QPoint(0, -15), pixel=QPoint(0, -9),
                  phase=Qt.ScrollPhase.ScrollUpdate, inverted=True)
    received = inner.received
    assert received is not None
    assert received.pixelDelta() == event.pixelDelta()
    assert received.angleDelta() == event.angleDelta()
    assert received.phase() == event.phase() and received.inverted()
    assert received.globalPosition() == event.globalPosition()
    assert received.pointingDevice() == event.pointingDevice()
    assert received.position() == inner.viewport().mapFromGlobal(event.globalPosition())
    assert outer.received is None
    inner.consume = False
    wheel(spin)
    assert outer.received is not None
    outer.received = None
    # A parented dialog must never scroll the window behind it.
    dialog = QDialog(outer.widget())
    dialog_spin = QSpinBox(dialog)
    dialog.show()
    app.processEvents()
    dialog_spin.clearFocus()
    wheel(dialog_spin)
    assert outer.received is None
    dialog.close()
    outer.close()
    outer.deleteLater()


def test_camera_wheel_is_untouched(app: QApplication) -> None:
    from src.renderer.viewport import Viewport
    viewport = Viewport()
    before = viewport.camera.fov
    wheel(viewport)
    assert viewport.camera.fov != before
    viewport.deleteLater()


def test_course_builder_scrolling_creates_no_draft_edits(app: QApplication) -> None:
    from src.core.editing import EditSession
    from src.core.rom import RomImage
    from src.ui.course_builder import CourseBuilder
    rom = RomImage.from_file(next(Path.cwd().glob('*.z64')))
    session = EditSession(rom)
    builder = CourseBuilder(session, 5)
    # Do not show the GL preview in a headless test; the real pane still lays out.
    scroll = builder.pages.widget(1)
    scroll.setParent(None)
    scroll.resize(400, 230)
    scroll.show()
    app.processEvents()
    spin = next(iter(builder.lane_values.values()))
    spin.clearFocus()
    scroll.ensureWidgetVisible(spin)
    scroll.verticalScrollBar().setValue(0)
    builder._record_history()
    before = builder._state()
    cursor = builder._cursor
    wheel(spin)
    assert scroll.verticalScrollBar().value() > 0
    assert builder._state() == before
    builder._record_history()
    assert builder._cursor == cursor
    assert not session.dirty
    scroll.close()
    scroll.setParent(builder)
    builder.reject()
    builder.deleteLater()
    app.processEvents()
