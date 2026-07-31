from __future__ import annotations

import json

from PySide6.QtWidgets import QLabel, QListWidget, QWidget

from voxconnect.bridge.events import EventsClient
from voxconnect.widgets.cards.base import BaseCard

STATE_LABELS = {
    "connecting": "Connecting…",
    "connected": "Connected. Waiting for notifications…",
    "reconnecting": "Reconnecting…",
    "stopped": "Disconnected.",
}


class NotificationsCard(BaseCard):
    """No BridgeClient/cache involvement — purely a live feed off EventsClient.
    /events pushes nothing today, so the empty state reads as "waiting", not
    an error."""

    def __init__(self, events_client: EventsClient, parent: QWidget | None = None):
        super().__init__("card_notifications", "Live Notifications", parent)
        self._events_client = events_client
        events_client.state_changed.connect(self._on_state_changed)
        events_client.event_received.connect(self._on_event_received)

        self._status_label = QLabel("Connecting…")
        self._content_layout.insertWidget(0, self._status_label)
        self._feed_list = QListWidget()
        self._content_layout.insertWidget(1, self._feed_list)
        self.show_content()

    def refresh(self) -> None:
        pass  # push-driven; nothing to poll

    def _on_state_changed(self, state: str) -> None:
        self._status_label.setText(STATE_LABELS.get(state, state))

    def _on_event_received(self, event: dict) -> None:
        self._feed_list.insertItem(0, json.dumps(event, indent=2))
