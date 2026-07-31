"""The main dashboard window: a CTA to pair when unpaired, or the card
dashboard (docked cards around a central "Ask" box) once paired."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voxconnect import settings
from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.events import EventsClient
from voxconnect.bridge.models import VoxResult
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.util.workers import run_in_background
from voxconnect.widgets.cards.calendar_card import CalendarCard
from voxconnect.widgets.cards.expenses_card import ExpensesCard
from voxconnect.widgets.cards.media_card import MediaCard
from voxconnect.widgets.cards.notes_card import NotesCard
from voxconnect.widgets.cards.notifications_card import NotificationsCard

LAYOUT_VERSION = 1


class DashboardWindow(QMainWindow):
    pair_requested = Signal()

    def __init__(
        self,
        client: BridgeClient | None = None,
        cache: CacheStore | None = None,
        sync_engine: SyncEngine | None = None,
        events: EventsClient | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("main_window")
        self.setWindowTitle("VoxConnect")
        self.resize(900, 600)

        self._client: BridgeClient | None = None
        self._cache: CacheStore | None = None
        self._sync_engine: SyncEngine | None = None
        self._events: EventsClient | None = None
        self._docks: list = []
        self._media_card: MediaCard | None = None

        self._cta_widget = self._build_cta_widget()
        self._ask_widget = self._build_ask_widget()

        if client is not None and cache is not None and sync_engine is not None and events is not None:
            self.set_paired(client, cache, sync_engine, events)
        else:
            self.setCentralWidget(self._cta_widget)

    # -- paired / unpaired transitions -----------------------------------------

    def set_paired(
        self, client: BridgeClient, cache: CacheStore, sync_engine: SyncEngine, events: EventsClient
    ) -> None:
        self._client = client
        self._cache = cache
        self._sync_engine = sync_engine
        self._events = events
        self.setCentralWidget(self._ask_widget)
        self._build_cards()
        self._restore_layout()

    def set_unpaired(self) -> None:
        self._teardown_cards()
        self._client = None
        self._cache = None
        self._sync_engine = None
        self._events = None
        self.setCentralWidget(self._cta_widget)

    def _build_cards(self) -> None:
        calendar_card = CalendarCard(self._cache, self._sync_engine, self)
        expenses_card = ExpensesCard(self._cache, self._sync_engine, self)
        notes_card = NotesCard(self._cache, self._sync_engine, self)
        media_card = MediaCard(self._client, self)
        notifications_card = NotificationsCard(self._events, self)
        self._media_card = media_card

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, calendar_card)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, expenses_card)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, notes_card)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, media_card)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, notifications_card)

        self._docks = [calendar_card, expenses_card, notes_card, media_card, notifications_card]

    def _teardown_cards(self) -> None:
        for dock in self._docks:
            self.removeDockWidget(dock)
            dock.deleteLater()
        self._docks = []
        self._media_card = None

    def refresh_all(self) -> None:
        if self._sync_engine is not None:
            self._sync_engine.sync_all()
        if self._media_card is not None:
            self._media_card.refresh()

    # -- layout persistence -----------------------------------------------------

    def save_layout(self) -> None:
        if not self._docks:
            return
        settings.save_layout(bytes(self.saveState(LAYOUT_VERSION)))

    def _restore_layout(self) -> None:
        data = settings.load_layout()
        if data:
            self.restoreState(data, LAYOUT_VERSION)

    # -- CTA (unpaired) -----------------------------------------------------------

    def _build_cta_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addStretch(1)
        label = QLabel("Pair with your phone to get started.")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        button = QPushButton("Pair device…")
        button.clicked.connect(self.pair_requested.emit)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        return widget

    # -- Ask box (paired, central widget) ----------------------------------------

    def _build_ask_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addStretch(1)
        title = QLabel("<b>Ask</b>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        row = QHBoxLayout()
        self._ask_edit = QLineEdit()
        self._ask_edit.setPlaceholderText("Ask a question…")
        self._ask_edit.returnPressed.connect(self._on_ask_clicked)
        row.addWidget(self._ask_edit)
        self._ask_button = QPushButton("Ask")
        self._ask_button.clicked.connect(self._on_ask_clicked)
        row.addWidget(self._ask_button)
        layout.addLayout(row)

        self._ask_response = QLabel("")
        self._ask_response.setWordWrap(True)
        self._ask_response.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._ask_response)
        layout.addStretch(1)
        return widget

    def _on_ask_clicked(self) -> None:
        if self._client is None:
            return
        text = self._ask_edit.text().strip()
        if not text:
            return
        self._ask_button.setEnabled(False)
        self._ask_response.setText("Asking…")

        def do_query() -> VoxResult:
            return self._client.query(text)

        def on_result(result: VoxResult) -> None:
            self._ask_button.setEnabled(True)
            self._ask_response.setText(result.text)

        def on_error(message: str) -> None:
            self._ask_button.setEnabled(True)
            self._ask_response.setText(message)

        run_in_background(do_query, on_result=on_result, on_error=on_error)
