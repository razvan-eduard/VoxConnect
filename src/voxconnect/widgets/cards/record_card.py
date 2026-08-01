"""A single generic card class for every dynamically-discovered domain (calendar/expenses/notes/
whatever else self-registers on the phone) — replaces the old one-class-per-domain
calendar_card.py/expenses_card.py/notes_card.py. Row rendering, sorting, filtering, and the
open/add/delete flows are all driven by the DomainSchema fetched from the phone
(BridgeClient.get_field_schema), not hardcoded per app."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Callable

from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.models import (
    FIELD_TYPE_BOOL,
    FIELD_TYPE_CATEGORY,
    FIELD_TYPE_DATETIME,
    FIELD_TYPE_ENUM,
    FIELD_TYPE_LIST,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_TAGS,
    DomainSchema,
    FormField,
    VoxResult,
)
from voxconnect.bridge.outbox import Outbox
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.util.workers import run_in_background
from voxconnect.widgets.cards.base import BaseCard
from voxconnect.widgets.dialogs.record_form import GenericRecordForm


class RecordCard(BaseCard):
    def __init__(
        self,
        client: BridgeClient,
        cache: CacheStore,
        sync_engine: SyncEngine,
        outbox: Outbox,
        open_detail: Callable[[QWidget], None],
        close_detail: Callable[[], None],
        notify: Callable[[str], None],
        schema: DomainSchema,
        app_label: str,
        parent: QWidget | None = None,
    ):
        super().__init__(f"card_{schema.domain}", app_label, parent, on_add=self._add_record, filterable=True)
        self._client = client
        self._cache = cache
        self._sync_engine = sync_engine
        self._outbox = outbox
        self._open_detail = open_detail
        self._close_detail = close_detail
        self._notify = notify
        self._schema = schema
        self._app_label = app_label
        self._fields_by_key = {f.key: f for f in schema.fields}
        self._pending_delete_uids: set[str] = set()

        self.filter_changed.connect(lambda _text: self.render())
        sync_engine.domain_synced.connect(self._on_domain_synced)
        sync_engine.domain_locked.connect(self._on_domain_locked)
        sync_engine.domain_error.connect(self._on_domain_error)
        self.render()

    def refresh(self) -> None:
        self._sync_engine.force_full_refresh(self._schema.domain)

    def _on_domain_synced(self, domain: str) -> None:
        if domain == self._schema.domain:
            self.render()

    def _on_domain_locked(self, domain: str, locked: bool) -> None:
        if domain == self._schema.domain and locked:
            self.show_locked(f"Phone locked — unlock {self._app_label} to sync.")

    def _on_domain_error(self, domain: str, message: str) -> None:
        if domain != self._schema.domain:
            return
        # A pure connectivity blip shouldn't wipe an already-populated list — the cached data is
        # still true as of the last successful sync; a global status banner (see dashboard.py)
        # already communicates the connection problem. Only fall back to the error page when
        # there's genuinely nothing cached yet to show instead.
        if not self._cache.get_entries(self._schema.domain):
            self.show_error(message)

    # -- rendering --------------------------------------------------------------

    def render(self) -> None:
        records = [
            r for r in self._cache.get_entries(self._schema.domain) if r.get("uid") not in self._pending_delete_uids
        ]

        if self._schema.upcoming_only_field:
            now_millis = int(time.time() * 1000)
            field = self._schema.upcoming_only_field
            records = [r for r in records if (r.get(field) or 0) >= now_millis]

        filter_text = self.filter_text().strip().lower()
        if filter_text:
            records = [r for r in records if filter_text in self._searchable_text(r)]

        if self._schema.sort_field:
            key = self._schema.sort_field
            records = sorted(records, key=lambda r: _sort_key(r.get(key)), reverse=self._schema.sort_descending)

        self.clear_content()
        if not records:
            self.show_empty(f"No {self._app_label.lower()} records." if not filter_text else "No matches.")
            return
        for record in records:
            self.add_clickable_row(
                self._build_row(record),
                lambda r=record: self._open_record(r),
                on_delete=lambda r=record: self._delete_record(r),
            )
        self.show_content()

    def _record_title(self, record: dict) -> str:
        title = record.get(self._schema.title_field)
        if title:
            return str(title)
        if self._schema.title_fallback_field:
            fallback = record.get(self._schema.title_fallback_field)
            if fallback:
                return str(fallback)
        return "(untitled)"

    def _format_field(self, key: str, value) -> str:
        if value in (None, "", []):
            return ""
        field_def = self._fields_by_key.get(key)
        field_type = field_def.type if field_def else None
        if field_type == FIELD_TYPE_DATETIME and isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000).strftime("%a %b %d, %H:%M")
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

    def _searchable_text(self, record: dict) -> str:
        parts = [self._record_title(record)]
        for key in self._schema.subtitle_fields:
            formatted = self._format_field(key, record.get(key))
            if formatted:
                parts.append(formatted)
        return " ".join(parts).lower()

    def _build_subtitle(self, record: dict) -> str:
        parts = []
        for key in self._schema.subtitle_fields:
            formatted = self._format_field(key, record.get(key))
            if formatted:
                parts.append(formatted)
        for f in self._schema.fields:
            if f.type == FIELD_TYPE_LIST:
                count = len(record.get(f.key) or [])
                if count:
                    parts.append(f"{count} item(s)")
        return " · ".join(parts)

    def _build_row(self, record: dict) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        title_label = QLabel(self._record_title(record))
        title_label.setProperty("class", "title")
        layout.addWidget(title_label)

        subtitle = self._build_subtitle(record)
        if subtitle:
            meta_label = QLabel(subtitle)
            meta_label.setProperty("class", "metadata")
            layout.addWidget(meta_label)
        return row

    # -- open / add / delete ------------------------------------------------------

    def open_record(self, record: dict) -> None:
        """Public entry point for opening a record from outside this card — e.g. CalendarGridView
        routing a day click into the matching RecordCard. Internal callers (row clicks) go through
        this too, so there's exactly one open path regardless of caller."""
        self._open_record(record)

    def add_record(self, seed_overrides: dict | None = None) -> None:
        """Public entry point for creating a record with specific field values pre-filled — e.g. a
        calendar grid day click seeding the new entry's date field to the clicked day instead of
        "now". `seed_overrides` wins over the type-based default for any field it names."""
        self._add_record(seed_overrides)

    def _open_record(self, record: dict) -> None:
        form = GenericRecordForm(
            self._client, self._schema, record, f"Edit {self._app_label}",
            outbox=self._outbox, on_synced=self.refresh, notify=self._notify,
        )
        form.saved.connect(self._on_form_saved)
        form.cancelled.connect(self._close_detail)
        self._open_detail(form)

    def _add_record(self, seed_overrides: dict | None = None) -> None:
        now = int(time.time() * 1000)
        seed = {"uid": str(uuid.uuid4()), "createdAt": now, "updatedAt": now}
        for f in self._schema.fields:
            seed[f.key] = _default_for_field(f, now)
        if seed_overrides:
            seed.update(seed_overrides)
        form = GenericRecordForm(
            self._client, self._schema, seed, f"New {self._app_label}",
            outbox=self._outbox, on_synced=self.refresh, notify=self._notify,
        )
        form.saved.connect(self._on_form_saved)
        form.cancelled.connect(self._close_detail)
        self._open_detail(form)

    def _on_form_saved(self) -> None:
        self._sync_engine.force_full_refresh(self._schema.domain)
        self._close_detail()

    def _delete_record(self, record: dict) -> None:
        """The single delete implementation for every domain — title/domain/uid all come from the
        selected record + this card's schema, not a hand-copied per-domain method."""
        uid = record["uid"]
        label = self._record_title(record)
        domain = self._schema.domain
        if (
            QMessageBox.question(self, f"Delete {self._app_label.lower()}", f'Delete "{label}"?')
            != QMessageBox.StandardButton.Yes
        ):
            return

        # Hide the row the instant the user confirms, regardless of what the network does next —
        # otherwise a slow/unreachable phone makes the click look like it did nothing at all. If
        # the phone ends up rejecting the delete, on_result puts it back.
        self._pending_delete_uids.add(uid)
        self.render()

        def do_delete() -> VoxResult:
            return self._client.delete_record(domain, uid)

        def on_result(result: VoxResult) -> None:
            if result.ok:
                self.refresh()
            else:
                self._pending_delete_uids.discard(uid)
                self.render()
                QMessageBox.warning(self, "Delete failed", result.text or "The phone rejected this delete.")

        def on_error(message: str) -> None:
            command = self._client.sync_merge_command(
                domain, [], [{"uid": uid, "deletedAt": int(time.time() * 1000)}]
            )
            self._outbox.enqueue(command, on_result=lambda _r: self.refresh())
            self._notify(f'"{label}" will be deleted once your phone reconnects.')

        run_in_background(do_delete, on_result=on_result, on_error=on_error)


def _sort_key(value):
    # Puts missing values consistently at one end without ever comparing None to a real value
    # (which raises in Python 3) — see the call site's `sorted(..., key=_sort_key)`.
    return (value is None, value)


def _default_for_field(field: FormField, now_millis: int):
    if field.type == FIELD_TYPE_NUMBER:
        return 0
    if field.type == FIELD_TYPE_BOOL:
        return False
    if field.type == FIELD_TYPE_DATETIME:
        return now_millis
    if field.type == FIELD_TYPE_ENUM:
        return field.options[0] if field.options else ""
    if field.type == FIELD_TYPE_CATEGORY:
        return ""
    if field.type in (FIELD_TYPE_TAGS, FIELD_TYPE_LIST):
        return []
    return ""
