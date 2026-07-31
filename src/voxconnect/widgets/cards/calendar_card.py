from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from voxconnect.bridge.models import DOMAIN_CALENDAR, CalendarEntry
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.widgets.cards.base import BaseCard

TOP_N = 5


class CalendarCard(BaseCard):
    def __init__(self, cache: CacheStore, sync_engine: SyncEngine, parent: QWidget | None = None):
        super().__init__("card_calendar", "Upcoming Events", parent)
        self._cache = cache
        self._sync_engine = sync_engine
        sync_engine.domain_synced.connect(self._on_domain_synced)
        sync_engine.domain_locked.connect(self._on_domain_locked)
        sync_engine.domain_error.connect(self._on_domain_error)
        self.render()

    def refresh(self) -> None:
        self._sync_engine.force_full_refresh(DOMAIN_CALENDAR)

    def _on_domain_synced(self, domain: str) -> None:
        if domain == DOMAIN_CALENDAR:
            self.render()

    def _on_domain_locked(self, domain: str, locked: bool) -> None:
        if domain == DOMAIN_CALENDAR and locked:
            self.show_locked("Phone locked — unlock Vox Calendar to sync.")

    def _on_domain_error(self, domain: str, message: str) -> None:
        if domain == DOMAIN_CALENDAR:
            self.show_error(message)

    def render(self) -> None:
        entries = [CalendarEntry.from_dict(raw) for raw in self._cache.get_entries(DOMAIN_CALENDAR)]
        now_millis = int(time.time() * 1000)
        upcoming = sorted(
            (e for e in entries if e.start_millis >= now_millis), key=lambda e: e.start_millis
        )[:TOP_N]

        self.clear_content()
        if not upcoming:
            self.show_empty("No upcoming events.")
            return
        for entry in upcoming:
            self.add_content_row(_build_row(entry))
        self.show_content()


def _build_row(entry: CalendarEntry) -> QWidget:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.addWidget(QLabel(f"<b>{entry.title}</b>"))
    when = datetime.fromtimestamp(entry.start_millis / 1000).strftime("%a %b %d, %H:%M")
    layout.addWidget(QLabel(when))
    if entry.tags:
        tags_label = QLabel(", ".join(entry.tags))
        tags_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(tags_label)
    return row
