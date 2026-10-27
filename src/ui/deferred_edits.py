"""Finish queued cell edits without re-entering Qt's general event loop."""
from __future__ import annotations

from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


class DeferredEdits(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.pending: deque[Callable[[], None]] = deque()
        self.flushing = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.flush)

    def defer(self, callback: Callable[[], None]) -> None:
        self.pending.append(callback)
        if not self.flushing:
            self.timer.start(0)

    def flush(self) -> None:
        if self.flushing:
            return
        self.timer.stop()
        self.flushing = True
        try:
            while self.pending:
                self.pending.popleft()()
        finally:
            self.flushing = False


def defer_edit(owner: QObject, callback: Callable[[], None]) -> None:
    queue = getattr(owner, '_deferred_edits', None)
    if queue is None:
        queue = DeferredEdits(owner)
        owner._deferred_edits = queue
    queue.defer(callback)


def flush_edits(owner: QObject) -> None:
    for queue in owner.findChildren(DeferredEdits):
        queue.flush()
