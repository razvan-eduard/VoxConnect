"""CalendarGridView computes which days have records from the cache + schema, and reports them
back via the day-click callback — the pure logic worth locking in, separate from Qt's own
QCalendarWidget painting/navigation (not this app's code to test)."""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QDate

from voxconnect.bridge.models import DomainSchema
from voxconnect.widgets.calendar_grid import CalendarGridView

SCHEMA = DomainSchema.from_dict(
    {
        "domain": "calendar",
        "titleField": "title",
        "sortField": "startMillis",
        "upcomingOnlyField": "startMillis",
        "fields": [{"key": "title", "label": "Title", "type": "text"}],
    }
)


def _millis_for(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 10, 0).timestamp() * 1000)


def test_refresh_groups_records_by_day(qtbot, cache_store):
    day1 = _millis_for(2026, 3, 5)
    day2 = _millis_for(2026, 3, 5)  # same day, second record
    day3 = _millis_for(2026, 3, 6)
    cache_store.upsert_entries(
        "calendar",
        [
            {"uid": "a", "title": "First", "startMillis": day1},
            {"uid": "b", "title": "Second", "startMillis": day2},
            {"uid": "c", "title": "Third", "startMillis": day3},
        ],
    )
    grid = CalendarGridView(cache_store, SCHEMA, on_day_activated=lambda *a: None)
    qtbot.addWidget(grid)

    assert len(grid._records_by_date[QDate(2026, 3, 5)]) == 2
    assert len(grid._records_by_date[QDate(2026, 3, 6)]) == 1
    assert QDate(2026, 3, 7) not in grid._records_by_date


def test_refresh_skips_records_missing_the_date_field(qtbot, cache_store):
    cache_store.upsert_entries("calendar", [{"uid": "a", "title": "No date"}])
    grid = CalendarGridView(cache_store, SCHEMA, on_day_activated=lambda *a: None)
    qtbot.addWidget(grid)
    assert grid._records_by_date == {}


def test_clicking_a_day_reports_its_records(qtbot, cache_store):
    millis = _millis_for(2026, 3, 5)
    cache_store.upsert_entries("calendar", [{"uid": "a", "title": "Event", "startMillis": millis}])

    seen = []
    grid = CalendarGridView(cache_store, SCHEMA, on_day_activated=lambda date, records: seen.append((date, records)))
    qtbot.addWidget(grid)

    grid._on_clicked(QDate(2026, 3, 5))
    assert len(seen) == 1
    date, records = seen[0]
    assert date == QDate(2026, 3, 5)
    assert [r["uid"] for r in records] == ["a"]


def test_clicking_an_empty_day_reports_no_records(qtbot, cache_store):
    seen = []
    grid = CalendarGridView(cache_store, SCHEMA, on_day_activated=lambda date, records: seen.append(records))
    qtbot.addWidget(grid)

    grid._on_clicked(QDate(2026, 3, 5))
    assert seen == [[]]


def test_refresh_after_cache_change_updates_grouping(qtbot, cache_store):
    grid = CalendarGridView(cache_store, SCHEMA, on_day_activated=lambda *a: None)
    qtbot.addWidget(grid)
    assert grid._records_by_date == {}

    cache_store.upsert_entries("calendar", [{"uid": "a", "title": "Later", "startMillis": _millis_for(2026, 5, 1)}])
    grid.refresh()
    assert QDate(2026, 5, 1) in grid._records_by_date
