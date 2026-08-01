from __future__ import annotations

import base64
import json

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QStyle, QVBoxLayout, QWidget

from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.models import MEDIA_PERMISSION_INSTRUCTIONS, NowPlaying, VoxResult, is_media_permission_missing
from voxconnect.util.workers import run_in_background
from voxconnect.widgets.cards.base import BaseCard

REFRESH_INTERVAL_MS = 15_000
TICK_INTERVAL_MS = 1_000
ART_SIZE = 64


class MediaCard(BaseCard):
    """Live, not cached — unlike the domain cards, polls the bridge directly on its own timer
    rather than going through cache/sync.py. Modeled after Android's own media notification: art
    thumbnail + title/artist, a progress bar, and icon transport controls — a 1s local timer
    interpolates the progress bar between the 15s network polls (only while playing) so it reads
    as live rather than visibly stepping once every 15 seconds."""

    def __init__(self, client: BridgeClient, parent: QWidget | None = None):
        super().__init__("card_media", "Now Playing", parent)
        self._client = client
        self._position_millis = 0
        self._duration_millis = 0
        self._playing = False

        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self._art_label = QLabel()
        self._art_label.setFixedSize(ART_SIZE, ART_SIZE)
        self._art_label.setScaledContents(True)
        self._art_label.setStyleSheet("background-color: rgba(128, 128, 128, 60);")
        header_layout.addWidget(self._art_label)

        text_column = QVBoxLayout()
        self._title_label = QLabel("Nothing playing")
        self._title_label.setProperty("class", "title")
        self._title_label.setWordWrap(True)
        self._artist_label = QLabel("")
        self._artist_label.setWordWrap(True)
        self._artist_label.setProperty("class", "metadata")
        text_column.addWidget(self._title_label)
        text_column.addWidget(self._artist_label)
        header_layout.addLayout(text_column, 1)
        self._content_layout.insertWidget(0, header_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 0)
        self._content_layout.insertWidget(1, self._progress_bar)

        button_row = QWidget()
        row_layout = QHBoxLayout(button_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        style = self.style()
        self._prev_button = self._transport_button(style, QStyle.StandardPixmap.SP_MediaSkipBackward, "prev")
        self._play_pause_button = QPushButton()
        self._play_pause_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self._play_pause_button.setIconSize(QSize(20, 20))
        self._play_pause_button.setProperty("class", "transport")
        # Deliberately not routed through _transport_button — the action to send depends on
        # self._playing at *click* time, not on whatever the icon showed when the button was
        # built, so it can't be a fixed string baked into a lambda default like the other buttons.
        self._play_pause_button.clicked.connect(self._on_play_pause_clicked)
        self._next_button = self._transport_button(style, QStyle.StandardPixmap.SP_MediaSkipForward, "next")
        self._buttons = [self._prev_button, self._play_pause_button, self._next_button]
        for button in self._buttons:
            row_layout.addWidget(button)
        self._content_layout.insertWidget(2, button_row)
        self.show_content()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(REFRESH_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.refresh)
        self._poll_timer.start()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_INTERVAL_MS)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self.refresh()

    def _transport_button(self, style, icon: QStyle.StandardPixmap, action: str) -> QPushButton:
        button = QPushButton()
        button.setIcon(style.standardIcon(icon))
        button.setIconSize(QSize(20, 20))
        button.setProperty("class", "transport")
        button.clicked.connect(lambda _checked=False, a=action: self._send_action(a))
        return button

    def refresh(self) -> None:
        run_in_background(self._client.get_media, on_result=self._on_result, on_error=self._on_error)

    def _on_result(self, result: VoxResult) -> None:
        if not result.ok:
            if is_media_permission_missing(result):
                self._show_message(MEDIA_PERMISSION_INSTRUCTIONS)
            else:
                self._show_message(result.text)
            self._set_buttons_enabled(False)
            return
        self._set_buttons_enabled(True)
        now_playing = NowPlaying.from_dict(json.loads(result.text))
        self._apply(now_playing)

    def _on_error(self, message: str) -> None:
        self._show_message(message)
        self._set_buttons_enabled(False)

    def _show_message(self, message: str) -> None:
        self._title_label.setText(message)
        self._artist_label.setText("")
        self._art_label.setPixmap(QPixmap())
        self._progress_bar.setRange(0, 0)
        self._playing = False
        self._play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def _apply(self, now_playing: NowPlaying) -> None:
        self._playing = now_playing.playing
        self._play_pause_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaPause if now_playing.playing else QStyle.StandardPixmap.SP_MediaPlay
            )
        )

        if not now_playing.playing and not now_playing.title:
            self._title_label.setText("Nothing playing")
            self._artist_label.setText("")
        else:
            self._title_label.setText(now_playing.title or "Unknown title")
            self._artist_label.setText(now_playing.artist or "")

        if now_playing.album_art_base64:
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(now_playing.album_art_base64))
            self._art_label.setPixmap(pixmap)
        else:
            self._art_label.setPixmap(QPixmap())

        self._position_millis = now_playing.position_millis or 0
        self._duration_millis = now_playing.duration_millis or 0
        if self._duration_millis > 0:
            self._progress_bar.setRange(0, self._duration_millis)
            self._progress_bar.setValue(min(self._position_millis, self._duration_millis))
        else:
            self._progress_bar.setRange(0, 0)

    def _tick(self) -> None:
        if not self._playing or self._duration_millis <= 0:
            return
        self._position_millis = min(self._position_millis + TICK_INTERVAL_MS, self._duration_millis)
        self._progress_bar.setValue(self._position_millis)

    def _send_action(self, action: str) -> None:
        self._set_buttons_enabled(False)

        def do_action() -> VoxResult:
            return self._client.media_action(action)

        def on_result(_result: VoxResult) -> None:
            self._set_buttons_enabled(True)
            self.refresh()

        def on_error(message: str) -> None:
            self._set_buttons_enabled(True)
            self._show_message(message)

        run_in_background(do_action, on_result=on_result, on_error=on_error)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)

    def _on_play_pause_clicked(self) -> None:
        self._send_action("pause" if self._playing else "play")
