"""In-memory retry queue for writes that failed purely because the phone was unreachable
(BridgeError) — not for validation/logic failures, which retrying wouldn't fix. A write that
times out gets queued here instead of just failing; DashboardWindow flushes it automatically the
moment EventsClient's /events WebSocket reconnects (the earliest reliable "phone is reachable
again" signal — see dashboard.py's _on_bridge_state_changed), so an edit/create/delete made while
the phone was briefly asleep or off WiFi still lands once it's back, without the user re-doing it.

RAM-only, deliberately — this queue does not survive an app restart. Anything still pending when
the app closes is lost; that's an accepted limitation, not a bug, given the phone is always the
real source of truth and nothing here represents data that isn't recoverable by just re-editing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from voxconnect.bridge.client import BridgeClient, BridgeError
from voxconnect.bridge.models import VoxCommand, VoxResult
from voxconnect.util.workers import run_in_background


@dataclass
class _QueuedCommand:
    command: VoxCommand
    on_result: Callable[[VoxResult], None] | None
    on_error: Callable[[str], None] | None


class Outbox:
    def __init__(self) -> None:
        self._pending: list[_QueuedCommand] = []

    def __len__(self) -> int:
        return len(self._pending)

    def enqueue(
        self,
        command: VoxCommand,
        *,
        on_result: Callable[[VoxResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._pending.append(_QueuedCommand(command, on_result, on_error))

    def flush_in_background(self, client: BridgeClient) -> None:
        """Best-effort, non-blocking (runs on a QThreadPool worker, matching every other network
        call in this app — see util/workers.py). Anything that still fails on this attempt (e.g.
        the phone dropped again mid-flush) goes back on the queue for the next reconnect rather
        than being silently dropped."""
        if not self._pending:
            return
        items, self._pending = self._pending, []

        def do_flush() -> list[tuple[_QueuedCommand, VoxResult | None, str | None]]:
            results = []
            for item in items:
                try:
                    result = client.send_command(item.command)
                    results.append((item, result, None))
                except BridgeError as exc:
                    results.append((item, None, str(exc)))
            return results

        def on_done(results: list[tuple[_QueuedCommand, VoxResult | None, str | None]]) -> None:
            for item, result, error in results:
                if result is not None:
                    if item.on_result is not None:
                        item.on_result(result)
                else:
                    self._pending.append(item)
                    if item.on_error is not None:
                        item.on_error(error or "still unreachable")

        run_in_background(do_flush, on_result=on_done)
