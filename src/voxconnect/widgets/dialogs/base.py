"""Shared scaffolding for record-edit forms (see record_form.py's GenericRecordForm, the sole
concrete subclass): a title, a form area, an inline status/error label, and Save/Cancel buttons
wired to push the edit through BridgeClient.push_edit (sync_merge) in the background. Embedded
directly in DashboardWindow's central detail pane (see dashboard.py) rather than shown as a modal
dialog — clicking a record opens it inline in the middle column instead of popping a separate
window.

Subclasses populate the form and build the outgoing dict; this base handles the request lifecycle
so that async/error-handling boilerplate exists exactly once."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.models import VoxResult
from voxconnect.bridge.outbox import Outbox
from voxconnect.util.workers import run_in_background


def bumped_updated_at(cached_updated_at: int) -> int:
    """A value sync_merge is guaranteed to accept as newer than what's stored — a tie or older
    value is silently ignored (last-write-wins), so this can't just be `now()` if the desktop and
    phone clocks are close or skewed backwards."""
    return max(cached_updated_at + 1, int(time.time() * 1000))


class RecordEditForm(QWidget):
    """Emits `saved` once the write has genuinely gone through (immediately, or later via the
    outbox — see `on_synced`) and `cancelled` on an explicit Cancel click. The detail pane (see
    DashboardWindow.show_detail_form) listens to both to know when to clear itself back to idle;
    this widget has no opinion about being "closed" itself, since it isn't a window."""

    saved = Signal()
    cancelled = Signal()

    def __init__(
        self,
        client: BridgeClient,
        domain: str,
        title: str,
        parent: QWidget | None = None,
        *,
        outbox: Outbox | None = None,
        on_synced: Callable[[], None] | None = None,
        notify: Callable[[str], None] | None = None,
    ):
        super().__init__(parent)
        self._client = client
        self._domain = domain
        # If saving fails purely because the phone is unreachable, queue it here instead of
        # just failing — see bridge/outbox.py. `on_synced` fires once that queued write actually
        # lands (this form is long gone from the detail pane by then), so the card can pull the
        # confirmed change into its cache.
        self._outbox = outbox
        self._on_synced = on_synced
        self._notify = notify

        layout = QVBoxLayout(self)
        title_label = QLabel(f"<h3>{title}</h3>")
        layout.addWidget(title_label)

        self._form = QFormLayout()
        layout.addLayout(self._form)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._save_button = QPushButton("Save")
        self._save_button.clicked.connect(self._on_save)
        button_row.addWidget(self._save_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancelled.emit)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)
        layout.addStretch(1)

    def add_row(self, label: str, field: QWidget) -> None:
        self._form.addRow(label, field)

    def entry_dict(self) -> dict:
        """Subclasses build the full edited record here (dataclass.to_dict()), with updatedAt
        already bumped via bumped_updated_at()."""
        raise NotImplementedError

    def _on_save(self) -> None:
        entry = self.entry_dict()
        self._save_button.setEnabled(False)
        self._status_label.setText("Saving…")

        def do_push() -> VoxResult:
            return self._client.push_edit(self._domain, entry)

        def on_result(result: VoxResult) -> None:
            if result.ok:
                self.saved.emit()
            else:
                self._save_button.setEnabled(True)
                self._status_label.setText(result.text or "Save failed.")

        def on_error(message: str) -> None:
            # push_edit's only failure mode is BridgeError (connectivity/decode) — safe to treat
            # every on_error call here as "queue it" rather than needing to distinguish causes.
            if self._outbox is not None:
                command = self._client.sync_merge_command(self._domain, [entry], [])
                on_synced = self._on_synced
                self._outbox.enqueue(command, on_result=lambda _r: on_synced() if on_synced else None)
                if self._notify is not None:
                    self._notify("Saved locally — will sync once your phone reconnects.")
                self.saved.emit()  # queued — treat as saved from the user's perspective
                return
            self._save_button.setEnabled(True)
            self._status_label.setText(message)

        run_in_background(do_push, on_result=on_result, on_error=on_error)
