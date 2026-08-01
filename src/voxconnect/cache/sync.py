"""Keeps CacheStore fresh from the phone via periodic sync_export calls.

/events (bridge/events.py) is still an inert stub server-side, so polling is
the real design for domain-data freshness today, not push — see the kickoff
doc's "Sync design" section. Runs on a QTimer plus once immediately on start.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.models import (
    OP_SYNC_EXPORT,
    SyncResult,
    VoxCommand,
    VoxResult,
    is_locked,
)
from voxconnect.cache.store import CacheStore
from voxconnect.util.workers import run_in_background

DEFAULT_INTERVAL_MS = 60_000

# Subtracted from the wall-clock time a sync_export call was made before
# persisting it as the next `since` watermark — cheap insurance against
# desktop/phone clock skew or a write landing mid-round-trip, which could
# otherwise put a record's updatedAt strictly between the old and new
# watermark and never have it re-requested (since filtering is strict `>`).
WATERMARK_SAFETY_BUFFER_MS = 5_000


def _now_millis() -> int:
    return int(time.time() * 1000)


class SyncEngine(QObject):
    domain_synced = Signal(str)
    domain_locked = Signal(str, bool)
    domain_error = Signal(str, str)

    def __init__(
        self,
        client: BridgeClient,
        cache: CacheStore,
        domains: list[str],
        interval_ms: int = DEFAULT_INTERVAL_MS,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._client = client
        self._cache = cache
        self._domains = domains
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.sync_all)

    def add_domains(self, domains: list[str]) -> None:
        """Extends the polled domain set at runtime — used when discovery finds a domain that
        wasn't known at construction time (see DashboardWindow.add_domains)."""
        for d in domains:
            if d not in self._domains:
                self._domains.append(d)

    def start(self) -> None:
        self.sync_all()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def sync_all(self) -> None:
        for domain in self._domains:
            self._sync_domain(domain, since=self._cache.last_synced_at(domain), full_refresh=False)

    def force_full_refresh(self, domain: str | None = None) -> None:
        domains = [domain] if domain else list(self._domains)
        for d in domains:
            self._sync_domain(d, since=0, full_refresh=True)

    def _sync_domain(self, domain: str, since: int, full_refresh: bool) -> None:
        command = VoxCommand(op=OP_SYNC_EXPORT, domain=domain, since=since)
        started_at = _now_millis()

        def fetch() -> VoxResult:
            return self._client.send_command(command)

        def on_result(result: VoxResult) -> None:
            self._handle_result(domain, result, started_at, full_refresh)

        def on_error(message: str) -> None:
            self.domain_error.emit(domain, message)

        run_in_background(fetch, on_result=on_result, on_error=on_error)

    def _handle_result(self, domain: str, result: VoxResult, started_at: int, full_refresh: bool) -> None:
        if not result.ok:
            if is_locked(domain, result):
                self.domain_locked.emit(domain, True)
            else:
                self.domain_error.emit(domain, result.text)
            return

        sync_result = SyncResult.from_json_text(result.text)
        if full_refresh:
            self._cache.replace_domain(domain, sync_result.entries)
        else:
            self._cache.upsert_entries(domain, sync_result.entries)
            self._cache.apply_tombstones(domain, sync_result.tombstones)
        self._cache.set_last_synced_at(domain, started_at - WATERMARK_SAFETY_BUFFER_MS)
        self._cache.save()

        self.domain_locked.emit(domain, False)
        self.domain_synced.emit(domain)
