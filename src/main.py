"""Run with ``python -m src.main`` from the project root."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPalette, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from src import __version__
from src.ui.main_window import MainWindow


def configure_surface_format() -> None:
    """Request the GL format before constructing QApplication or any widget."""
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)


def configure_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#202733"),
        (QPalette.ColorRole.WindowText, "#d9e2ee"),
        (QPalette.ColorRole.Base, "#171e28"),
        (QPalette.ColorRole.AlternateBase, "#1c2531"),
        (QPalette.ColorRole.Text, "#d9e2ee"),
        (QPalette.ColorRole.Button, "#293444"),
        (QPalette.ColorRole.ButtonText, "#d9e2ee"),
        (QPalette.ColorRole.Highlight, "#315c87"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
        (QPalette.ColorRole.ToolTipBase, "#293444"),
        (QPalette.ColorRole.ToolTipText, "#d9e2ee"),
    ):
        palette.setColor(role, QColor(color))
        
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#697789"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#697789"))
    app.setPalette(palette)
    app.setStyleSheet(
        "QToolBar { spacing: 4px; padding: 3px 5px; border-bottom: 1px solid #354153; }"
        "QToolButton { padding: 5px 9px; border-radius: 3px; }"
        "QToolBar QToolButton { padding: 3px 7px; }"
        "QToolButton:checked { background: #315c87; color: #edf6ff; }"
        "QDockWidget::title { padding: 8px; font-weight: 600; }"
        "QLineEdit { padding: 7px; border: 1px solid #354153; border-radius: 3px; }"
        # Delegate editors must fit the row height; search-box padding consumes it.
        "QAbstractItemView QLineEdit { padding: 0px 2px; border: none; border-radius: 0px;"
        " color: #d9e2ee; background: #171e28; selection-color: #ffffff;"
        " selection-background-color: #315c87; }"
        "QAbstractItemView QComboBox { padding: 0px; border: none; }"
        "QTabBar QToolButton { padding: 0px; }"
        "QTreeWidget { border: 1px solid #303b4b; }"
        "QHeaderView::section { padding: 6px; border: none; background: #293444; }"
        "QStatusBar { border-top: 1px solid #354153; }"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", help="Run real-window GL/input checks and exit")
    parser.add_argument("--screenshot", type=Path, default=Path("artifacts/viewport-check.png"))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--rom", type=Path, help="Open a USA Rev 1 ROM at startup")
    source.add_argument("--project", type=Path, help="Open a saved Workshop project (.dkrproj)")
    parser.add_argument("--level", type=int, help="Select a level ID from the loaded catalog")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    configure_surface_format()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("DKR Workshop")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("DKR Viewer")
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "ui" / "resources" / "workshop.ico")))
    configure_theme(app)
    window = MainWindow()
    window.show()
    if args.rom is not None and not window.load_rom(args.rom, show_errors=not args.smoke_test):
        logging.error("Could not open ROM: %s", args.rom)
        window.close()
        return 1
    if args.project is not None and not window.load_project(args.project, show_errors=not args.smoke_test):
        logging.error("Could not open object project: %s", args.project)
        window.close()
        return 1
    if window.catalog is not None and args.level is not None:
        if not 0 <= args.level < len(window.catalog.levels):
            logging.error("Level index %s is outside the catalog", args.level)
            window.close()
            return 1
        window.level_panel.select_level(args.level)
    if args.smoke_test:
        from src.ui.smoke_checks import smoke_test
        return smoke_test(app, window, args.screenshot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
