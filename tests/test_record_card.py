"""RecordCard is the single generic card driving every domain from a DomainSchema — these tests
exercise the pieces that used to be hand-copied three times (calendar_card.py/expenses_card.py/
notes_card.py, all deleted this pass): schema-driven rendering/sorting/filtering, and the one
shared delete flow parameterized by the selected record."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QToolButton

from voxconnect.bridge.models import DomainSchema
from voxconnect.bridge.outbox import Outbox
from voxconnect.widgets.cards.record_card import RecordCard

CALENDAR_SCHEMA = DomainSchema.from_dict(
    {
        "domain": "calendar",
        "titleField": "title",
        "subtitleFields": ["startMillis"],
        "sortField": "startMillis",
        "sortDescending": False,
        "upcomingOnlyField": "startMillis",
        "fields": [{"key": "title", "label": "Title", "type": "text"}],
    }
)


def _make_card(qtbot, cache_store, client=None):
    client = client or MagicMock()
    sync_engine = MagicMock()
    for sig in ("domain_synced", "domain_locked", "domain_error"):
        m = MagicMock()
        m.connect = lambda *a, **k: None
        setattr(sync_engine, sig, m)
    card = RecordCard(
        client, cache_store, sync_engine, Outbox(),
        open_detail=lambda form: None, close_detail=lambda: None, notify=lambda msg: None,
        schema=CALENDAR_SCHEMA, app_label="Calendar",
    )
    qtbot.addWidget(card)
    return card


def _row_count(card: RecordCard) -> int:
    return card._content_layout.count() - 1  # trailing stretch item


def test_render_hides_past_records_via_upcoming_only_field(qtbot, cache_store):
    now = int(time.time() * 1000)
    cache_store.upsert_entries(
        "calendar",
        [
            {"uid": "past", "title": "Old meeting", "startMillis": now - 100_000, "createdAt": now, "updatedAt": now},
            {"uid": "future", "title": "Team sync", "startMillis": now + 100_000, "createdAt": now, "updatedAt": now},
        ],
    )
    card = _make_card(qtbot, cache_store)
    assert _row_count(card) == 1


def test_filter_box_narrows_visible_rows(qtbot, cache_store):
    now = int(time.time() * 1000)
    cache_store.upsert_entries(
        "calendar",
        [
            {"uid": "a", "title": "Team sync", "startMillis": now + 1000, "createdAt": now, "updatedAt": now},
            {"uid": "b", "title": "Dentist", "startMillis": now + 2000, "createdAt": now, "updatedAt": now},
        ],
    )
    card = _make_card(qtbot, cache_store)
    assert _row_count(card) == 2

    card._filter_edit.setText("dent")
    assert _row_count(card) == 1


@pytest.fixture(autouse=True)
def _synchronous_background(monkeypatch):
    def fake_run_in_background(fn, *, on_result=None, on_error=None):
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001
            if on_error is not None:
                on_error(str(exc))
            return
        if on_result is not None:
            on_result(value)

    monkeypatch.setattr("voxconnect.widgets.cards.record_card.run_in_background", fake_run_in_background)


def test_delete_confirmed_calls_client_with_record_uid_and_hides_row_immediately(qtbot, cache_store):
    from voxconnect.bridge.models import VoxResult

    now = int(time.time() * 1000)
    cache_store.upsert_entries(
        "calendar", [{"uid": "e1", "title": "Team sync", "startMillis": now + 1000, "createdAt": now, "updatedAt": now}]
    )
    client = MagicMock()
    client.delete_record = MagicMock(return_value=VoxResult(ok=True, text=""))
    card = _make_card(qtbot, cache_store, client=client)
    assert _row_count(card) == 1

    record = cache_store.get_entries("calendar")[0]
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        card._delete_record(record)

    client.delete_record.assert_called_once_with("calendar", "e1")
    assert _row_count(card) == 0


def test_delete_declined_does_not_touch_the_client(qtbot, cache_store):
    now = int(time.time() * 1000)
    cache_store.upsert_entries(
        "calendar", [{"uid": "e1", "title": "Team sync", "startMillis": now + 1000, "createdAt": now, "updatedAt": now}]
    )
    client = MagicMock()
    card = _make_card(qtbot, cache_store, client=client)

    record = cache_store.get_entries("calendar")[0]
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        card._delete_record(record)

    client.delete_record.assert_not_called()
    assert _row_count(card) == 1


def test_delete_rejected_by_phone_restores_the_row(qtbot, cache_store):
    from voxconnect.bridge.models import VoxResult

    now = int(time.time() * 1000)
    cache_store.upsert_entries(
        "calendar", [{"uid": "e1", "title": "Team sync", "startMillis": now + 1000, "createdAt": now, "updatedAt": now}]
    )
    client = MagicMock()
    client.delete_record = MagicMock(return_value=VoxResult(ok=False, text="locked"))
    card = _make_card(qtbot, cache_store, client=client)

    record = cache_store.get_entries("calendar")[0]
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(
        QMessageBox, "warning"
    ):
        card._delete_record(record)

    assert _row_count(card) == 1  # put back since the phone rejected it


def test_clicking_the_real_delete_button_passes_the_record_not_the_qt_checked_bool(qtbot, cache_store):
    """Regression test: QToolButton.clicked carries a `checked: bool` argument. A naive
    `on_delete=lambda r=record: self._delete_record(r)` connected straight to that signal gets its
    default silently overridden by Qt's bool — `_delete_record` then receives `False`/`True`
    instead of the record dict. Calling `_delete_record` directly (as the other tests above do)
    can't catch this class of bug; only an actual QTest.mouseClick on the real button can."""
    from voxconnect.bridge.models import VoxResult

    now = int(time.time() * 1000)
    cache_store.upsert_entries(
        "calendar", [{"uid": "e1", "title": "Team sync", "startMillis": now + 1000, "createdAt": now, "updatedAt": now}]
    )
    client = MagicMock()
    client.delete_record = MagicMock(return_value=VoxResult(ok=True, text=""))
    card = _make_card(qtbot, cache_store, client=client)

    delete_button = next(
        btn for btn in card.findChildren(QToolButton) if btn.toolTip() == "Delete"
    )
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        QTest.mouseClick(delete_button, Qt.MouseButton.LeftButton)

    client.delete_record.assert_called_once_with("calendar", "e1")
