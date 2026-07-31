"""VoxConnect entry point: a tray-resident PySide6 app hosting the widget
dashboard. The phone is the only source of truth for domain data — this
process keeps no persistent local copy, only paired-device/layout settings
(see settings.py)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt

from voxconnect.widgets.dashboard import DashboardWindow


class TrayApp:
    def __init__(self, app: QApplication):
        self._app = app
        self._window = DashboardWindow()

        icon = self._app.style().standardIcon(self._app.style().StandardPixmap.SP_ComputerIcon)
        self._tray = QSystemTrayIcon(icon, parent=self._app)
        self._tray.setToolTip("VoxConnect")

        menu = QMenu()
        show_action = QAction("Show dashboard", menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("VoxConnect")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray unavailable on this platform; showing window directly.", file=sys.stderr)

    tray_app = TrayApp(app)
    tray_app._show_window()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
