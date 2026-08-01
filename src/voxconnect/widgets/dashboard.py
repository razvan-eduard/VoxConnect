"""The main dashboard window: a CTA to pair when unpaired, or the card dashboard once paired —
docked cards around a full-width top "Ask" toolbar, with a central detail pane that opens a
record inline (click a row in any card) instead of a modal dialog."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from voxconnect import settings
from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.events import EventsClient
from voxconnect.bridge.models import DOMAIN_CALENDAR, DomainSchema, VoxResult
from voxconnect.bridge.outbox import Outbox
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.util.workers import run_in_background
from voxconnect.widgets.calendar_grid import CalendarGridView
from voxconnect.widgets.cards.base import ClickableRow
from voxconnect.widgets.cards.media_card import MediaCard
from voxconnect.widgets.cards.notifications_card import NotificationsCard
from voxconnect.widgets.cards.record_card import RecordCard
from voxconnect.widgets.command_palette import ParsedCommand, fuzzy_search_records, parse_command

# Bumped whenever the dock/toolbar structure changes incompatibly (e.g. the top Ask QToolBar and
# central detail-pane swap added in this pass) — restoreState() applies saved geometry blindly by
# objectName with no structural validation, so an old blob reapplied onto a changed widget tree
# corrupts dock/splitter rectangles (cards rendering into each other's space) instead of just
# failing cleanly. Bumping this makes restoreState() reject the stale blob and fall back to
# _apply_default_layout() instead.
LAYOUT_VERSION = 5
ASK_BAR_MAX_WIDTH = 900  # sanity cap for ultra-wide windows; normal sizing comes from the 60% stretch
RECORD_AREA_WIDTH_FRACTION = 0.35


class DashboardWindow(QMainWindow):
    pair_requested = Signal()
    rediscover_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("main_window")
        self.setWindowTitle("VoxConnect")
        self.resize(900, 600)

        self._client: BridgeClient | None = None
        self._cache: CacheStore | None = None
        self._sync_engine: SyncEngine | None = None
        self._events: EventsClient | None = None
        self._outbox = Outbox()
        self._last_bridge_state = "connected"
        self._docks: list = []
        self._schemas: dict[str, DomainSchema] = {}
        self._app_labels: dict[str, str] = {}
        self._record_cards: dict[str, RecordCard] = {}
        self._media_card: MediaCard | None = None
        self._notifications_card: NotificationsCard | None = None
        self._calendar_grid: CalendarGridView | None = None
        self._calendar_grid_domain: str | None = None
        self._pre_edit_grid_height: int | None = None

        self._cta_widget = self._build_cta_widget()
        self._detail_pane, self._detail_idle_page = self._build_detail_pane()
        self._central_splitter, self._calendar_grid_slot = self._build_central_container()
        self._ask_toolbar = self._build_ask_toolbar()
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._ask_toolbar)
        self._ask_toolbar.setVisible(False)
        self.setCentralWidget(self._cta_widget)

    # -- paired / unpaired transitions -----------------------------------------

    def set_paired(
        self,
        client: BridgeClient,
        cache: CacheStore,
        sync_engine: SyncEngine,
        events: EventsClient,
        schemas: dict[str, DomainSchema],
        app_labels: dict[str, str],
    ) -> None:
        self._client = client
        self._cache = cache
        self._sync_engine = sync_engine
        self._events = events
        self._schemas = schemas
        self._app_labels = app_labels
        self._events.event_received.connect(self._on_bridge_event)
        self._events.state_changed.connect(self._on_bridge_state_changed)
        self._sync_engine.domain_synced.connect(self._on_domain_synced_for_calendar_grid)
        self.setCentralWidget(self._central_splitter)
        self._ask_toolbar.setVisible(True)
        self._build_cards(schemas, app_labels)
        grid_domain = self._pick_calendar_grid_domain(schemas)
        if grid_domain is not None:
            self._show_calendar_grid(grid_domain, schemas[grid_domain])
        self._build_view_menu()
        self._restore_layout()

    def _on_domain_synced_for_calendar_grid(self, domain: str) -> None:
        if domain == self._calendar_grid_domain and self._calendar_grid is not None:
            self._calendar_grid.refresh()

    def _on_bridge_event(self, event: dict) -> None:
        if event.get("op") != "monitored_domains_changed" or self._sync_engine is None:
            return
        # A domain we were previously blocked from (or newly dropped) just changed on the
        # phone side — retry immediately rather than waiting for the next poll tick.
        self._sync_engine.sync_all()
        # The event only lists domain names, not full app info/schemas — if any of them aren't
        # already known here, discovery at connect time must have missed them (satellite briefly
        # unreachable, phone not fully booted yet, etc). Ask app.py to redo discovery rather than
        # silently sitting on a stale card set until the next full app restart.
        domains = event.get("domains")
        if isinstance(domains, list) and any(d not in self._schemas for d in domains):
            self.rediscover_requested.emit()

    def _on_bridge_state_changed(self, state: str) -> None:
        # The phone can't push a "the network's back" message to a WebSocket session that already
        # died when it dropped off WiFi — there's no channel left to push it over. But EventsClient
        # reconnecting successfully *is* exactly that signal, arriving the moment the phone becomes
        # reachable again (bounded by its own short reconnect backoff) — so treat "connected" as the
        # cue to retry every domain immediately instead of waiting for the next poll tick, and to
        # flush anything that was queued while the phone was unreachable.
        if state == "connected":
            if self._sync_engine is not None:
                self._sync_engine.sync_all()
            if self._client is not None:
                self._outbox.flush_in_background(self._client)
            # Reconnecting doesn't require anything to have changed on the phone side — it's also
            # exactly what happens when a satellite that was frozen/unreachable during the very
            # first discovery pass (see e.g. Honor's "Fast App Hibernation") becomes reachable
            # again, with no monitored-apps toggle ever flipped to tell us so. Retrying discovery
            # here means a missing tab fixes itself on the next reconnect instead of needing the
            # user to go flip something in Hub's settings just to trigger the other event path.
            self.rediscover_requested.emit()
        self._update_connection_banner(state)

    def notify(self, message: str, timeout_ms: int = 4000) -> None:
        """A one-off status message for events that don't fit the persistent connection banner
        (e.g. "queued, will retry once your phone reconnects" for a single delete/save) — so
        silently-queued writes aren't silently invisible too. Restores the persistent banner
        afterward instead of just going blank, in case a connection-lost message was already
        showing when this fired."""
        self.statusBar().showMessage(message)
        QTimer.singleShot(timeout_ms, lambda: self._update_connection_banner(self._last_bridge_state))

    def _update_connection_banner(self, state: str) -> None:
        self._last_bridge_state = state
        queued = len(self._outbox)
        suffix = f" ({queued} change{'s' if queued != 1 else ''} pending)" if queued else ""
        if state == "connected":
            self.statusBar().clearMessage()
        elif state in ("connecting", "reconnecting"):
            self.statusBar().showMessage(f"Connection lost — showing cached data{suffix}")
        elif state == "stopped":
            self.statusBar().showMessage(f"Disconnected{suffix}")

    def set_unpaired(self) -> None:
        self.close_detail()
        self._hide_calendar_grid()
        self._teardown_cards()
        self.menuBar().clear()
        self.statusBar().clearMessage()
        self._ask_toolbar.setVisible(False)
        self._client = None
        self._cache = None
        self._sync_engine = None
        self._events = None
        self._schemas = {}
        self._app_labels = {}
        self.setCentralWidget(self._cta_widget)

    def _build_cards(self, schemas: dict[str, DomainSchema], app_labels: dict[str, str]) -> None:
        # One RecordCard per domain the phone actually advertised (via GET /apps, already filtered
        # by Hub's "monitored apps" toggle) AND answered the field-schema op for — a domain missing
        # either just doesn't get a card, no hardcoded 3-way assumption left anywhere here.
        self._record_cards = {
            domain: RecordCard(
                self._client, self._cache, self._sync_engine, self._outbox,
                self.show_detail_form, self.close_detail, self.notify,
                schema, app_labels.get(domain, domain.title()), self,
            )
            for domain, schema in schemas.items()
        }
        self._media_card = MediaCard(self._client, self)
        self._notifications_card = NotificationsCard(self._events, self)

        self._docks = [*self._record_cards.values(), self._media_card, self._notifications_card]
        self._apply_default_layout()

    def add_domains(self, schemas: dict[str, DomainSchema], app_labels: dict[str, str]) -> None:
        """Adds cards for domains discovered after the initial pairing — e.g. a satellite that
        was briefly unreachable at connect time and only shows up once app.py re-runs discovery
        in response to a `monitored_domains_changed` event (see `_on_bridge_event`). Existing
        cards are left untouched, not rebuilt, so their scroll position/filter text survive."""
        new_domains = {d: s for d, s in schemas.items() if d not in self._schemas}
        if not new_domains:
            return
        self._schemas.update(new_domains)
        self._app_labels.update(app_labels)
        new_cards = {
            domain: RecordCard(
                self._client, self._cache, self._sync_engine, self._outbox,
                self.show_detail_form, self.close_detail, self.notify,
                schema, self._app_labels.get(domain, domain.title()), self,
            )
            for domain, schema in new_domains.items()
        }
        self._record_cards.update(new_cards)
        self._docks.extend(new_cards.values())
        self._apply_default_layout()

        preferred_grid_domain = self._pick_calendar_grid_domain(self._schemas)
        if preferred_grid_domain is not None and preferred_grid_domain != self._calendar_grid_domain:
            self._show_calendar_grid(preferred_grid_domain, self._schemas[preferred_grid_domain])

    def _teardown_cards(self) -> None:
        for dock in self._docks:
            self.removeDockWidget(dock)
            dock.deleteLater()
        self._docks = []
        self._record_cards = {}
        self._media_card = None
        self._notifications_card = None

    # -- layout presets -----------------------------------------------------------
    #
    # Drag-to-move, drag-to-float, and drag-the-splitter-to-resize are all native
    # QDockWidget/QMainWindow behavior (see BaseCard's DockWidgetMovable|DockWidgetFloatable
    # features) — nothing extra needed for those. Presets just give a one-click way back to a
    # known-good arrangement; whatever the user leaves it at (preset or freely dragged) is what
    # save_layout()/_restore_layout() persists across restarts, same as before this feature.

    def _build_view_menu(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.clear()
        view_menu = menu_bar.addMenu("&View")

        reset_action = QAction("Reset layout", self)
        reset_action.triggered.connect(self._apply_default_layout)
        view_menu.addAction(reset_action)

    def _apply_default_layout(self) -> None:
        """Every discovered record card tabs together in ONE dock area on the left (switchable via
        the tab strip, not stacked one below another — with N discovered domains, stacking would
        squeeze every card's visible height instead of giving each one the full column when it's
        the active tab). Notifications+Media stay right, split vertically (notifications on top)."""
        if not self._docks:
            return
        for dock in self._docks:
            dock.setFloating(False)
        record_cards = [self._record_cards[domain] for domain in sorted(self._record_cards)]
        if record_cards:
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, record_cards[0])
            for card in record_cards[1:]:
                self.tabifyDockWidget(record_cards[0], card)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._notifications_card)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._media_card)
        self.splitDockWidget(self._notifications_card, self._media_card, Qt.Orientation.Vertical)
        for dock in self._docks:
            dock.show()
        if record_cards:
            record_cards[0].raise_()  # the tab that ends up active/on top
            # The tabbed record area gets ~35% of the window's width, right column the rest — an
            # initial split, not a lock; the user can still drag the splitter freely afterward
            # (see the module comment on presets vs. free dragging).
            total_width = max(self.width(), 900)
            left_width = int(total_width * RECORD_AREA_WIDTH_FRACTION)
            self.resizeDocks(
                [record_cards[0], self._notifications_card],
                [left_width, total_width - left_width],
                Qt.Orientation.Horizontal,
            )

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
        if not data:
            return
        self.restoreState(data, LAYOUT_VERSION)
        if any(dock.isHidden() for dock in self._docks):
            # A saved layout can have one or more cards closed — each tab has its own close
            # button, so an accidental click before the app was last quit is easy to hit — and
            # restoreState() would otherwise silently reproduce that as "missing" cards on every
            # future launch, with no way back short of knowing "Reset layout" exists. Falling back
            # to the known-good default is safer than faithfully restoring a broken-looking state.
            self._apply_default_layout()

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

    # -- Detail pane (paired, central widget) --------------------------------------
    #
    # Clicking a record row in any card opens its edit form here, inline, instead of as a modal
    # dialog — the middle column is otherwise idle screen real estate. Only one form is shown at
    # a time; opening a new one (or the card that owns the current one calling close_detail())
    # tears down the previous form widget rather than stacking them.

    def _build_detail_pane(self) -> tuple[QStackedWidget, QWidget]:
        stack = QStackedWidget()
        idle_page = QLabel("Select a record from a list to view or edit it here.")
        idle_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle_page.setWordWrap(True)
        idle_page.setProperty("class", "metadata")
        stack.addWidget(idle_page)
        return stack, idle_page

    def show_detail_form(self, form: QWidget) -> None:
        self.close_detail()
        self._detail_pane.addWidget(form)
        self._detail_pane.setCurrentWidget(form)
        # Give the form the full central column while it's open rather than fighting the grid for
        # space — collapsed via splitter sizes (not torn down/rebuilt like _hide_calendar_grid),
        # so the grid's selected date/scroll position survives and just reappears as-is on close.
        if self._calendar_grid is not None:
            sizes = self._central_splitter.sizes()
            if sizes[0] > 0:
                self._pre_edit_grid_height = sizes[0]
            self._central_splitter.setSizes([0, sum(sizes)])

    def close_detail(self) -> None:
        current = self._detail_pane.currentWidget()
        if current is None or current is self._detail_idle_page:
            return
        self._detail_pane.setCurrentWidget(self._detail_idle_page)
        self._detail_pane.removeWidget(current)
        current.deleteLater()
        if self._calendar_grid is not None and self._pre_edit_grid_height:
            total = sum(self._central_splitter.sizes())
            self._central_splitter.setSizes([self._pre_edit_grid_height, total - self._pre_edit_grid_height])

    # -- Calendar grid (paired, top of the central column) --------------------------
    #
    # A month-grid browsing view sitting above the detail pane — visible by default whenever the
    # calendar domain is discovered (no toggle needed), hidden entirely otherwise. Clicking a day
    # opens that day's record inline below the grid (same detail pane every other click-to-open
    # path already uses); clicking an empty day starts a new record seeded for that date; a day
    # with more than one record shows a small pick-one list first.

    def _build_central_container(self) -> tuple[QSplitter, QWidget]:
        splitter = QSplitter(Qt.Orientation.Vertical)
        grid_slot = QWidget()
        grid_slot.setMaximumHeight(0)  # collapsed until a calendar domain is actually discovered
        splitter.addWidget(grid_slot)
        splitter.addWidget(self._detail_pane)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(1, False)
        return splitter, grid_slot

    def _pick_calendar_grid_domain(self, schemas: dict[str, DomainSchema]) -> str | None:
        """Prefers the literal calendar domain when it's been discovered, but falls back to any
        other domain with a usable date-anchor field (upcoming_only_field or sort_field) —
        CalendarGridView itself is already schema-driven, not calendar-specific, so there's no
        reason to hide the grid entirely just because the phone's own calendar app happened to be
        unreachable/undiscovered this session while e.g. expenses (which has its own dateTime
        field) came through fine."""
        if DOMAIN_CALENDAR in schemas:
            return DOMAIN_CALENDAR
        for domain in sorted(schemas):
            schema = schemas[domain]
            if schema.upcoming_only_field or schema.sort_field:
                return domain
        return None

    def _show_calendar_grid(self, domain: str, schema: DomainSchema) -> None:
        grid = CalendarGridView(self._cache, schema, self._on_calendar_day_activated, self)
        old = self._calendar_grid_slot
        self._central_splitter.replaceWidget(0, grid)
        old.deleteLater()
        self._calendar_grid_slot = grid
        self._calendar_grid = grid
        self._calendar_grid_domain = domain
        # QSplitter.replaceWidget() deliberately keeps the outgoing widget's size allocation
        # rather than sizing the incoming one to fit — the placeholder it's replacing was pinned
        # to 0px, so without this the grid would render fully collapsed despite being correctly
        # in the widget tree. Force an explicit split instead of relying on the inherited size.
        total_height = max(self._central_splitter.height(), 600)
        grid_height = max(grid.sizeHint().height(), 320)
        self._central_splitter.setSizes([grid_height, total_height - grid_height])

    def _hide_calendar_grid(self) -> None:
        if self._calendar_grid is None:
            return
        placeholder = QWidget()
        placeholder.setMaximumHeight(0)
        self._central_splitter.replaceWidget(0, placeholder)
        self._calendar_grid.deleteLater()
        self._calendar_grid_slot = placeholder
        self._calendar_grid = None
        self._calendar_grid_domain = None
        self._central_splitter.setSizes([0, max(self._central_splitter.height(), 600)])

    def _on_calendar_day_activated(self, date: QDate, records: list[dict]) -> None:
        domain = self._calendar_grid_domain
        if domain is None:
            return
        card = self._record_cards.get(domain)
        if card is None:
            return
        schema = self._schemas[domain]
        if not records:
            date_field = schema.upcoming_only_field or schema.sort_field
            if date_field:
                seeded_at = int(datetime(date.year(), date.month(), date.day()).timestamp() * 1000)
                card.add_record({date_field: seeded_at})
            else:
                card.add_record()
            return
        if len(records) == 1:
            card.open_record(records[0])
            return
        agenda = _DayAgendaWidget(date.toString(Qt.DateFormat.TextDate), records, schema, card.open_record)
        self.show_detail_form(agenda)

    # -- Ask bar (paired, top toolbar) -----------------------------------------------
    #
    # A full-width toolbar spanning above all three dock columns, its content constrained to
    # ~60% of that width (via stretch factors, not a fixed pixel width, so it scales with the
    # window) and padded left/right by the remaining space. It's a command/search entry point,
    # not the main content. Three things can happen as you type, mutually exclusive:
    #  1. Starts with ">" and matches a known shorthand (see command_palette.py) — the hint line
    #     shows exactly what will be sent, clearly labeled as a phone-side command, not a search.
    #  2. Otherwise — an instant, local, no-network fuzzy filter of the notes already cached on
    #     the desktop expands below the bar if anything matches.
    #  3. No local matches, or the user presses Enter anyway — falls through to the free-form
    #     /query op, i.e. a real request sent to the phone, not a local search.

    def _build_ask_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Ask", self)
        toolbar.setObjectName("ask_toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)

        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        padded = QHBoxLayout(container)
        padded.setContentsMargins(0, 4, 0, 4)
        padded.addStretch(1)  # left padding

        inner = QWidget()
        inner.setMaximumWidth(ASK_BAR_MAX_WIDTH)
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        row = QHBoxLayout()
        self._ask_edit = QLineEdit()
        self._ask_edit.setPlaceholderText("Ask, search notes, or type > for a command…")
        self._ask_edit.textChanged.connect(self._on_ask_text_changed)
        self._ask_edit.returnPressed.connect(self._on_ask_submit)
        row.addWidget(self._ask_edit)
        self._ask_button = QPushButton("Ask")
        self._ask_button.clicked.connect(self._on_ask_submit)
        row.addWidget(self._ask_button)
        outer.addLayout(row)

        self._ask_hint_label = QLabel("")
        self._ask_hint_label.setProperty("class", "metadata")
        self._ask_hint_label.setWordWrap(True)
        outer.addWidget(self._ask_hint_label)

        self._ask_results_list = QListWidget()
        self._ask_results_list.setMaximumHeight(140)
        self._ask_results_list.hide()
        outer.addWidget(self._ask_results_list)

        self._ask_response = QLabel("")
        self._ask_response.setWordWrap(True)
        self._ask_response.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._ask_response)

        padded.addWidget(inner, 3)  # ~60% of the toolbar width (3 of 1+3+1 stretch units)
        padded.addStretch(1)  # right padding

        toolbar.addWidget(container)
        return toolbar

    def _on_ask_text_changed(self, text: str) -> None:
        text = text.strip()
        self._ask_response.setText("")
        if not text:
            self._ask_hint_label.setText("")
            self._ask_results_list.hide()
            return

        parsed = parse_command(text, self._schemas)
        if parsed is not None:
            self._ask_hint_label.setText(f"{parsed.description}  (press Enter to send)")
            self._ask_results_list.hide()
            return
        if text.startswith(">"):
            self._ask_hint_label.setText("Unrecognized command — press Enter to ask your phone instead")
            self._ask_results_list.hide()
            return

        if self._cache is not None:
            matches = fuzzy_search_records(self._cache, self._schemas, text)
        else:
            matches = []
        if matches:
            self._ask_results_list.clear()
            for domain, record in matches:
                schema = self._schemas[domain]
                title = record.get(schema.title_field) or (
                    record.get(schema.title_fallback_field) if schema.title_fallback_field else None
                ) or "(untitled)"
                label = self._app_labels.get(domain, domain.title())
                self._ask_results_list.addItem(f"[{label}] {title}")
            self._ask_results_list.show()
            self._ask_hint_label.setText(f"{len(matches)} matching record(s) — press Enter to also ask your phone")
        else:
            self._ask_results_list.hide()
            self._ask_hint_label.setText("No local matches — Enter sends this as a command/question to your phone")

    def _on_ask_submit(self) -> None:
        if self._client is None:
            return
        text = self._ask_edit.text().strip()
        if not text:
            return

        parsed = parse_command(text, self._schemas)
        if parsed is not None:
            self._submit_command(parsed)
            return
        self._submit_query(text)

    def _submit_command(self, parsed: ParsedCommand) -> None:
        self._ask_button.setEnabled(False)
        self._ask_response.setText("Sent to phone — no confirmation is returned for this op.")

        def do_send() -> VoxResult:
            return self._client.send_command(parsed.command)

        def on_result(_result: VoxResult) -> None:
            self._ask_button.setEnabled(True)
            self._ask_edit.clear()

        def on_error(message: str) -> None:
            self._ask_button.setEnabled(True)
            self._ask_response.setText(message)

        run_in_background(do_send, on_result=on_result, on_error=on_error)

    def _submit_query(self, text: str) -> None:
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


class _DayAgendaWidget(QWidget):
    """Shown in the detail pane when a calendar-grid day click hits more than one record — a
    short pick-one list rather than guessing which the user meant. Selecting a row hands off to
    the same open_record path a normal card-row click already uses, so it behaves identically
    once past this disambiguation step."""

    def __init__(self, date_label: str, records: list[dict], schema: DomainSchema, on_select: Callable[[dict], None]):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel(f"<h3>{date_label}</h3>")
        layout.addWidget(title)
        for record in records:
            row_label = QLabel(str(record.get(schema.title_field) or "(untitled)"))
            row_label.setProperty("class", "title")
            row = ClickableRow(row_label)
            row.clicked.connect(lambda r=record: on_select(r))
            layout.addWidget(row)
        layout.addStretch(1)
