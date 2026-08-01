"""Client for the bridge's `WS /events` endpoint.

Per the real Kotlin server (VoxConnectServer.kt): the path is `/events`,
gated by the same `Authorization: Bearer <deviceId>` header every other
route requires (checked manually right after the upgrade, since Ktor's
`webSocket {}` DSL has no route-level auth hook). Today it pushes one real
event, `{"op": "monitored_domains_changed", "domains": [...]}`, whenever
Hub's monitored-apps toggles change — see dashboard.py's `_on_bridge_event`
for what reacts to it. Domain-data freshness itself is still handled by
cache/sync.py's polling; this client just feeds the Notifications card's
connection state and forwards whatever the server pushes.

Not a QThread — websockets is asyncio-native, so this runs a daemon thread
with its own event loop; only the Qt signal emissions need to cross back to
the GUI thread, which plain cross-thread signal emission already handles.
"""

from __future__ import annotations

import asyncio
import json
import threading
from enum import Enum

import websockets
from PySide6.QtCore import QObject, Signal

from voxconnect.settings import PairedDevice


class ConnectionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"


def _parse_frame(raw: str) -> dict:
    """Pure/testable without a real socket: decodes a frame defensively since
    no message envelope is defined server-side yet."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"data": parsed}


class EventsClient(QObject):
    state_changed = Signal(str)  # ConnectionState.value
    event_received = Signal(dict)

    def __init__(self, device: PairedDevice, parent: QObject | None = None):
        super().__init__(parent)
        self._device = device
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.get_loop().call_soon_threadsafe(self._task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _thread_main(self) -> None:
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        self._task = asyncio.current_task()
        url = f"ws://{self._device.host}:{self._device.port}/events"
        headers = {"Authorization": f"Bearer {self._device.device_id}"}
        backoff = 1.0
        first_attempt = True
        try:
            while not self._stop_event.is_set():
                state = ConnectionState.CONNECTING if first_attempt else ConnectionState.RECONNECTING
                self.state_changed.emit(state.value)
                try:
                    async with websockets.connect(
                        url, additional_headers=headers, open_timeout=10, ping_interval=20, ping_timeout=20
                    ) as ws:
                        self.state_changed.emit(ConnectionState.CONNECTED.value)
                        backoff = 1.0
                        first_attempt = False
                        async for raw in ws:
                            self.event_received.emit(_parse_frame(raw))
                except (OSError, websockets.exceptions.WebSocketException, asyncio.TimeoutError):
                    pass
                if self._stop_event.is_set():
                    break
                await asyncio.sleep(backoff)
                # Capped low (not the more typical 30s+) so a phone that drops off WiFi and comes
                # back is noticed within a few seconds, not up to half a minute later.
                backoff = min(backoff * 2, 5.0)
        except asyncio.CancelledError:
            pass
        finally:
            self.state_changed.emit(ConnectionState.STOPPED.value)
