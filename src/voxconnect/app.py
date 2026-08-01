"""VoxConnect entry point: a tray-resident PySide6 app hosting the widget
dashboard. The phone is the source of truth for domain data; this process
keeps only a derived, encrypted local cache (cache/store.py) kept fresh by a
background sync engine (cache/sync.py), plus paired-device/layout settings
(settings.py)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from qt_material import apply_stylesheet

from voxconnect import settings
from voxconnect.bridge.client import BridgeClient, BridgeError
from voxconnect.bridge.events import EventsClient
from voxconnect.bridge.models import DomainSchema
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.pairing.wizard import PairingWizard
from voxconnect.settings import PairedDevice
from voxconnect.util.workers import run_in_background
from voxconnect.widgets.dashboard import DashboardWindow

MAX_BACKGROUND_THREADS = 4


class TrayApp:
    def __init__(self, app: QApplication):
        self._app = app
        self._cache = CacheStore()
        self._client: BridgeClient | None = None
        self._sync_engine: SyncEngine | None = None
        self._events: EventsClient | None = None

        # The window is built unpaired first (CTA screen) regardless — which domains it can show
        # cards for isn't known until discovery (an async network round trip) completes, even for
        # a device that was already paired on a previous run.
        self._window = DashboardWindow()
        self._window.pair_requested.connect(self._open_pairing_wizard)
        self._window.rediscover_requested.connect(self._rediscover)

        device = settings.load_paired_device()
        if device is not None:
            self._connect_device(device, start=True)

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

    @staticmethod
    def _fetch_schemas(client: BridgeClient) -> tuple[dict[str, DomainSchema], dict[str, str]]:
        """GET /apps (already filtered by Hub's monitored-apps toggle) plus one field-schema
        fetch per domain. A domain whose satellite doesn't answer the schema op (an old APK, or
        briefly unreachable) is just skipped rather than failing discovery outright — used both
        for the initial connect and for `_rediscover`'s follow-up pass."""
        schemas: dict[str, DomainSchema] = {}
        labels: dict[str, str] = {}
        for app_info in client.get_apps():
            if not app_info.domain:
                continue
            try:
                schemas[app_info.domain] = client.get_field_schema(app_info.domain)
            except BridgeError:
                continue
            labels[app_info.domain] = app_info.label or app_info.domain.title()
        return schemas, labels

    def _connect_device(self, device: PairedDevice, *, start: bool) -> None:
        """Discovers which domains the phone actually advertises and builds the paired dashboard
        from that — never a hardcoded 3-domain assumption."""
        client = BridgeClient(device)
        events = EventsClient(device)

        def on_result(result: tuple[dict[str, DomainSchema], dict[str, str]]) -> None:
            schemas, labels = result
            self._client = client
            self._events = events
            self._sync_engine = SyncEngine(client, self._cache, list(schemas.keys()))
            self._window.set_paired(client, self._cache, self._sync_engine, events, schemas, labels)
            if start:
                self._sync_engine.start()
                events.start()

        def on_error(_message: str) -> None:
            # The phone was unreachable for discovery itself — leave the window in its current
            # (unpaired-looking) state rather than crash; nothing to build cards from yet.
            client.close()

        run_in_background(lambda: self._fetch_schemas(client), on_result=on_result, on_error=on_error)

    def _rediscover(self) -> None:
        """Re-runs discovery against the already-connected client — triggered when a
        `monitored_domains_changed` event names a domain the dashboard doesn't have a card for
        yet (see DashboardWindow._on_bridge_event), so a satellite that was unreachable at
        connect time still shows up once it becomes available, without needing a full app
        restart."""
        client = self._client
        if client is None:
            return

        def on_result(result: tuple[dict[str, DomainSchema], dict[str, str]]) -> None:
            schemas, labels = result
            if self._sync_engine is not None:
                self._sync_engine.add_domains(list(schemas.keys()))
                self._sync_engine.sync_all()
            self._window.add_domains(schemas, labels)

        run_in_background(lambda: self._fetch_schemas(client), on_result=on_result, on_error=lambda _m: None)

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
    apply_stylesheet(app, theme="dark_teal.xml")
    # Layered on top of qt-material's base theme — card elevation, title/metadata typography,
    # borderless transport buttons, quieter dock separators. See resources/style.qss.
    custom_qss = (Path(__file__).parent / "resources" / "style.qss").read_text()
    app.setStyleSheet(app.styleSheet() + "\n" + custom_qss)
    QThreadPool.globalInstance().setMaxThreadCount(MAX_BACKGROUND_THREADS)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray unavailable on this platform; showing window directly.", file=sys.stderr)

    tray_app = TrayApp(app)
    tray_app._show_window()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
