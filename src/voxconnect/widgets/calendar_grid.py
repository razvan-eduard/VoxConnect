"""A month-grid calendar view for browsing calendar records visually — QCalendarWidget as the
navigation shell (year/month/day picker comes for free from Qt: click the header to drill from
month → year grid → month grid), with a custom cell painter marking which days have records and
a click-through to view/create one on that day.

Deliberately calendar-domain-specific, unlike RecordCard/GenericRecordForm which work for any
domain — a day grid is only meaningful for records that have a date, and generalizing it to
"any domain with a datetime field" isn't something anything has asked for."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QDate, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCalendarWidget, QWidget

from voxconnect.bridge.models import DomainSchema
from voxconnect.cache.store import CacheStore

EVENT_DOT_COLOR = QColor("#2ecc9a")
EVENT_DOT_SIZE = 5


class CalendarGridView(QCalendarWidget):
    def __init__(
        self,
        cache: CacheStore,
        schema: DomainSchema,
        on_day_activated: Callable[[QDate, list[dict]], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._cache = cache
        self._schema = schema
        self._on_day_activated = on_day_activated
        # The field that anchors a record to a specific day — calendar's schema already marks
        # this via upcoming_only_field ("startMillis"); sort_field is a reasonable fallback for
        # a differently-shaped schema rather than hardcoding a field name here.
        self._date_field = schema.upcoming_only_field or schema.sort_field
        self._records_by_date: dict[QDate, list[dict]] = {}
        self.setMinimumHeight(260)
        self.clicked.connect(self._on_clicked)
        self.refresh()

    def refresh(self) -> None:
        self._records_by_date = {}
        if self._date_field:
            for record in self._cache.get_entries(self._schema.domain):
                millis = record.get(self._date_field)
                if not isinstance(millis, (int, float)):
                    continue
                dt = datetime.fromtimestamp(millis / 1000)
                day = QDate(dt.year, dt.month, dt.day)
                self._records_by_date.setdefault(day, []).append(record)
        self.updateCells()

    def paintCell(self, painter: QPainter, rect: QRect, date: QDate) -> None:  # noqa: N802 - Qt override
        super().paintCell(painter, rect, date)
        if not self._records_by_date.get(date):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(EVENT_DOT_COLOR)
        painter.setPen(Qt.PenStyle.NoPen)
        x = rect.center().x() - EVENT_DOT_SIZE / 2
        y = rect.bottom() - EVENT_DOT_SIZE - 3
        painter.drawEllipse(int(x), int(y), EVENT_DOT_SIZE, EVENT_DOT_SIZE)
        painter.restore()

    def _on_clicked(self, date: QDate) -> None:
        self._on_day_activated(date, list(self._records_by_date.get(date, [])))
