"""Read-only export preflight and project diff."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget, QTabWidget

from src.core.export_report import ExportReport
from src.core.structure import StructuralAudit
from src.core.rom import AssetType, RomImage
from src.core.runtime_audit import (MAX_CAPTURE_BYTES, RuntimeAuditError, RuntimeSnapshot,
                                   read_runtime_capture, snapshot_summary)


class ExportReportDialog(QDialog):
    def __init__(self, report: ExportReport, parent: QWidget | None = None, *, structural: StructuralAudit | None = None,
                 runtime_source: RomImage | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("exportReportDialog")
        self.setWindowTitle("ROM budget and project changes")
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        summary = QLabel(report.summary, self)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.details = QPlainTextEdit(self)
        self.details.setObjectName("exportReportDetails")
        self.details.setAccessibleName("ROM budget and project changes")
        self.details.setReadOnly(True)
        self.details.setPlainText(report.to_text())
        self.tabs = QTabWidget(self)
        self.runtime_source = runtime_source
        self.runtime_snapshots: list[RuntimeSnapshot] = []
        self.tabs.addTab(self.details, 'ROM storage / changes')
        self.structural_details = QPlainTextEdit(self)
        self.structural_details.setObjectName('structuralAuditDetails')
        self.structural_details.setAccessibleName('Structural object feasibility audit')
        self.structural_details.setReadOnly(True)
        if structural is not None:
            self.structural_details.setPlainText(structural.to_text())
            self.tabs.addTab(self.structural_details, 'Object capacity audit')
        self.runtime_details = QPlainTextEdit(self)
        self.runtime_details.setObjectName('runtimeAuditDetails')
        self.runtime_details.setAccessibleName('Read-only RDRAM resource measurements')
        self.runtime_details.setReadOnly(True)
        self.runtime_details.setPlainText(
            'Load a BizHawk 2.10 Mupen64Plus savestate or raw 4 MiB / 8 MiB RDRAM dump.\n'
            'Big-endian, 16-bit byte-swapped and 32-bit word-swapped dumps are recognized\n'
            'by three Rev 1 executable fingerprints. Other savestate layouts are unsupported.\n\n'
            'The report measures object slots, free/largest allocator blocks, descriptors,\n'
            'header/sprite/texture references and particle-buffer counts. It does not\n'
            'connect to an emulator, modify memory, dirty the project or enable editing.\n\n'
            'Capture several gameplay conditions to compare observations. A single snapshot\n'
            'does not establish a peak or a safe number of additional objects.\n'
            'Samples are kept only while this dialog is open; Copy report preserves the text.')
        if runtime_source is not None:
            self.tabs.addTab(self.runtime_details, 'Runtime measurements')
        self.tabs.currentChanged.connect(lambda index: summary.setText(report.summary if index == 0 else
            'Object and memory usage estimate. Dynamic allocations depend on the active scene.'))
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        copy = QPushButton("Copy report", self)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.tabs.currentWidget().toPlainText()))
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        if runtime_source is not None:
            load = QPushButton('Load runtime snapshot…', self)
            load.setObjectName('loadRuntimeSnapshot')
            load.clicked.connect(self._choose_snapshot)
            buttons.addButton(load, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def load_snapshot(self, path: Path) -> None:
        """Read first, then publish a successful sample atomically; no project edits."""
        if self.runtime_source is None:
            raise RuntimeAuditError('Open a source ROM before inspecting RDRAM')
        if len(self.runtime_snapshots) >= 64:
            raise RuntimeAuditError('This report already contains 64 samples; copy it and open a new report')
        if path.stat().st_size > MAX_CAPTURE_BYTES:
            raise RuntimeAuditError('Runtime capture exceeds the 32 MiB input limit')
        with path.open('rb') as capture:
            data = capture.read(MAX_CAPTURE_BYTES+1)
        snapshot = read_runtime_capture(data, self.runtime_source, self.runtime_source.count(AssetType.OBJECTS))
        samples = (*self.runtime_snapshots, snapshot)
        text = snapshot_summary(samples) + '\n\nLATEST SAMPLE\n\n' + snapshot.to_text()
        self.runtime_snapshots.append(snapshot)
        self.runtime_details.setPlainText(text)
        self.tabs.setCurrentWidget(self.runtime_details)

    def _choose_snapshot(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, 'Open runtime snapshot', '', 'BizHawk state / RDRAM (*.State *.bin *.ram *.rdram);;All files (*)')
        if chosen:
            try:
                self.load_snapshot(Path(chosen))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'RDRAM snapshot was not loaded', str(error))
