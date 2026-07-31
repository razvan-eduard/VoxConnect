from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.models import NowPlaying, VoxResult
from voxconnect.util.workers import run_in_background
from voxconnect.widgets.cards.base import BaseCard

REFRESH_INTERVAL_MS = 15_000


class MediaCard(BaseCard):
    """Live, not cached — unlike the domain cards, polls the bridge directly
    on its own timer rather than going through cache/sync.py."""

    def __init__(self, client: BridgeClient, parent: QWidget | None = None):
        super().__init__("card_media", "Now Playing", parent)
        self._client = client

        self._status_label = QLabel("Nothing playing")
        self._content_layout.insertWidget(0, self._status_label)

        button_row = QWidget()
        row_layout = QHBoxLayout(button_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self._buttons = []
        for label, action in (("Play", "play"), ("Pause", "pause"), ("Next", "next"), ("Prev", "prev")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, a=action: self._send_action(a))
            row_layout.addWidget(button)
            self._buttons.append(button)
        self._content_layout.insertWidget(1, button_row)
        self.show_content()

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        run_in_background(self._client.get_media, on_result=self._on_result, on_error=self._on_error)

    def _on_result(self, result: VoxResult) -> None:
        if not result.ok:
            self._status_label.setText(result.text)
            return
        now_playing = NowPlaying.from_dict(json.loads(result.text))
        if not now_playing.playing:
            self._status_label.setText("Nothing playing")
            return
        parts = [p for p in (now_playing.title, now_playing.artist) if p]
        self._status_label.setText(" — ".join(parts) if parts else "Playing")

    def _on_error(self, message: str) -> None:
        self._status_label.setText(message)

    def _send_action(self, action: str) -> None:
        for button in self._buttons:
            button.setEnabled(False)

        def do_action() -> VoxResult:
            return self._client.media_action(action)

        def on_result(_result: VoxResult) -> None:
            self._set_buttons_enabled(True)
            self.refresh()

        def on_error(message: str) -> None:
            self._set_buttons_enabled(True)
            self._status_label.setText(message)

        run_in_background(do_action, on_result=on_result, on_error=on_error)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)
