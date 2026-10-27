"""Stock track reconstruction, validation and explicit export."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from src.core.rom import AssetType, RomImage
from src.core.track_rebuild import StockRebuild, rebuild_stock_track, stock_rebuild_layout, export_stock_rebuild_rom


class StockRebuildWorker(QThread):
    progress = Signal(int)
    completed = Signal(object, str, bool)

    def __init__(self, rom: RomImage, ids: tuple[int, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.rom, self.ids = rom, ids

    def run(self) -> None:
        results: list[StockRebuild] = []
        text = ['Original-ROM stock reconstruction',
                'Existing project edits are kept in the editor and are not part of this stock export.',
                'Stock collision links, BSP and visibility are retained. Use Geometry → Import OBJ for a custom course.',
                'Checks cover serialized data, loader allocations, collision, visibility and ROM layout.', '']
        success = False
        try:
            for i, model_id in enumerate(self.ids):
                if self.isInterruptionRequested():
                    text.append('Cancelled; no project or output was changed.')
                    break
                raw = self.rom.read_asset(AssetType.LEVEL_MODELS, model_id, decompress=True)
                result = rebuild_stock_track(raw, model_id=model_id)
                results.append(result)
                text.extend((result.to_text(), ''))
                self.progress.emit(i+1)
            else:
                _, report = stock_rebuild_layout(self.rom, results)
                text.extend(('ROM layout for this stock rebuild', report.to_text()))
                success = report.can_export
        except (ValueError, OSError) as error:
            text.append(f'FAILED: {error}\nNo project or output was changed.')
        self.completed.emit(tuple(results), '\n'.join(text), success)


class TrackRebuildDialog(QDialog):
    def __init__(self, rom: RomImage, model_id: int, level_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('stockTrackRebuildDialog')
        self.setWindowTitle('Stock track rebuild')
        self.resize(980, 720)
        self.rom, self.model_id = rom, model_id
        self.worker: StockRebuildWorker | None = None
        self.results: tuple[StockRebuild, ...] = ()
        self._close_when_done = False
        layout = QVBoxLayout(self)
        description = QLabel(
            f'{level_name} · original ROM model {model_id}\n'
            'Reconstruct stock records and check collision, visibility, compression and memory budgets. '
            'Stock export uses the original ROM; your current project edits stay in the editor.', self)
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        self.selected = QPushButton('Verify selected stock track', self)
        self.selected.setObjectName('verifySelectedStockTrack')
        self.selected.clicked.connect(lambda: self.start((self.model_id,)))
        row.addWidget(self.selected)
        self.all = QPushButton('Verify all stock tracks', self)
        self.all.setObjectName('verifyAllStockTracks')
        self.all.clicked.connect(lambda: self.start(tuple(range(self.rom.count(AssetType.LEVEL_MODELS)))))
        row.addWidget(self.all)
        self.stop = QPushButton('Stop', self)
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._stop)
        row.addWidget(self.stop)
        layout.addLayout(row)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.summary = QLabel('Choose a stock rebuild check. No ROM is written by verification.', self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.details = QPlainTextEdit(self)
        self.details.setObjectName('stockRebuildDetails')
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        self.copy = QPushButton('Copy report', self)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.details.toPlainText()))
        buttons.addButton(self.copy, QDialogButtonBox.ButtonRole.ActionRole)
        self.export = QPushButton('Export stock rebuild ROM…', self)
        self.export.setObjectName('exportStockRebuildRom')
        self.export.setEnabled(False)
        self.export.clicked.connect(self._export)
        buttons.addButton(self.export, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(buttons)

    def start(self, ids: tuple[int, ...]) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.results = ()
        self.export.setEnabled(False)
        self.selected.setEnabled(False)
        self.all.setEnabled(False)
        self.stop.setEnabled(True)
        self.progress.setRange(0, len(ids))
        self.progress.setValue(0)
        self.summary.setText(f'Verifying {len(ids)} original stock model(s)…')
        self.details.clear()
        self.worker = StockRebuildWorker(self.rom, ids, self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.completed.connect(self._completed)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _completed(self, results: tuple[StockRebuild, ...], text: str, success: bool) -> None:
        self.results = results if success else ()
        self.details.setPlainText(text)
        self.summary.setText(f'PASS: {len(results)} stock model(s) reconstructed exactly; ROM layout fits.' if success else
                             'Check cancelled or failed. The report explains the result; your project is unchanged.')
        self.export.setEnabled(success)

    def _finished(self) -> None:
        self.selected.setEnabled(True)
        self.all.setEnabled(True)
        self.stop.setEnabled(False)
        if self._close_when_done:
            super().reject()

    def _stop(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.summary.setText('Stopping after the current model check…')
            self.stop.setEnabled(False)

    def _export(self) -> None:
        if not self.results:
            return
        chosen, _ = QFileDialog.getSaveFileName(self, 'Export verified stock rebuild ROM',
            str(Path.cwd()/'stock-track-rebuild.z64'), 'Nintendo64 ROM (*.z64)')
        if not chosen:
            return
        try:
            destination = export_stock_rebuild_rom(self.rom, self.results, Path(chosen))
            self.summary.setText(f'Stock rebuild exported: {destination.name}. Your open project is unchanged.')
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, 'Stock rebuild was not exported', str(error))

    def reject(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._close_when_done = True
            self._stop()
        else:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
