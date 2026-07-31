"""VoxConnect entry point: a tray-resident PySide6 app hosting the widget
dashboard. The phone is the source of truth for domain data; this process
keeps only a derived, encrypted local cache (cache/store.py) kept fresh by a
background sync engine (cache/sync.py), plus paired-device/layout settings
(settings.py)."""

from __future__ import annotations

import sys

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from voxconnect import settings
from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.events import EventsClient
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.pairing.wizard import PairingWizard
from voxconnect.settings import PairedDevice
from voxconnect.widgets.dashboard import DashboardWindow

MAX_BACKGROUND_THREADS = 4


class TrayApp:
    def __init__(self, app: QApplication):
        self._app = app
        self._cache = CacheStore()
        self._client: BridgeClient | None = None
        self._sync_engine: SyncEngine | None = None
        self._events: EventsClient | None = None

        device = settings.load_paired_device()
        if device is not None:
            self._connect_device(device, start=False)

        self._window = DashboardWindow(
            client=self._client, cache=self._cache, sync_engine=self._sync_engine, events=self._events
        )
        self._window.pair_requested.connect(self._open_pairing_wizard)

        if self._sync_engine is not None:
            self._sync_engine.start()
        if self._events is not None:
            self._events.start()

        icon = self._app.style().standardIcon(self._app.style().StandardPixmap.SP_ComputerIcon)
        self._tray = QSystemTrayIcon(icon, parent=self._app)
        self._tray.setToolTip("VoxConnect")

        menu = QMenu()
        show_action = QAction("Show dashboard", menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        menu.addSeparator()

        self._pair_action = QAction("Pair device…", menu)
        self._pair_action.triggered.connect(self._open_pairing_wizard)
        menu.addAction(self._pair_action)

        self._forget_action = QAction("Forget device", menu)
        self._forget_action.triggered.connect(self._forget_device)
        self._forget_action.setEnabled(device is not None)
        menu.addAction(self._forget_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self._app.aboutToQuit.connect(self._on_about_to_quit)

    def _connect_device(self, device: PairedDevice, *, start: bool) -> None:
        self._client = BridgeClient(device)
        self._sync_engine = SyncEngine(self._client, self._cache)
        self._events = EventsClient(device)
        if start:
            self._sync_engine.start()
            self._events.start()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self._window.refresh_all()

    def _open_pairing_wizard(self) -> None:
        wizard = PairingWizard(self._window)
        if wizard.exec() != PairingWizard.DialogCode.Accepted:
            return
        device = wizard.paired_device()
        if device is None:
            return
        self._connect_device(device, start=True)
        self._window.set_paired(self._client, self._cache, self._sync_engine, self._events)
        self._forget_action.setEnabled(True)
        self._show_window()

    def _forget_device(self) -> None:
        if self._sync_engine is not None:
            self._sync_engine.stop()
        if self._events is not None:
            self._events.stop()
        if self._client is not None:
            self._client.close()
        settings.clear_paired_device()
        self._cache.clear()
        self._client = None
        self._sync_engine = None
        self._events = None
        self._window.set_unpaired()
        self._forget_action.setEnabled(False)

    def _on_about_to_quit(self) -> None:
        self._window.save_layout()
        if self._sync_engine is not None:
            self._sync_engine.stop()
        if self._events is not None:
            self._events.stop()
        if self._client is not None:
            self._client.close()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("VoxConnect")
    QThreadPool.globalInstance().setMaxThreadCount(MAX_BACKGROUND_THREADS)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray unavailable on this platform; showing window directly.", file=sys.stderr)

    tray_app = TrayApp(app)
    tray_app._show_window()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
