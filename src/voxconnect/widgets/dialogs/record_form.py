"""A single generic record-edit form driven entirely by a DomainSchema — replaces the old
one-class-per-domain calendar_entry_dialog.py/expense_dialog.py/note_dialog.py. Builds one widget
per schema field by type, including a generalized nested-table editor for `type: "list"` fields
(e.g. an expense's line items), which used to be Expense-specific code."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from voxconnect.bridge.client import BridgeClient
from voxconnect.bridge.models import (
    FIELD_TYPE_BOOL,
    FIELD_TYPE_CATEGORY,
    FIELD_TYPE_DATETIME,
    FIELD_TYPE_ENUM,
    FIELD_TYPE_LIST,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_READONLY,
    FIELD_TYPE_TAGS,
    FIELD_TYPE_TEXT,
    DomainSchema,
    FormField,
)
from voxconnect.bridge.outbox import Outbox
from voxconnect.widgets.dialogs.base import RecordEditForm, bumped_updated_at


class GenericRecordForm(RecordEditForm):
    def __init__(
        self,
        client: BridgeClient,
        schema: DomainSchema,
        seed: dict,
        title: str,
        parent: QWidget | None = None,
        *,
        outbox: Outbox | None = None,
        on_synced: Callable[[], None] | None = None,
        notify: Callable[[str], None] | None = None,
    ):
        super().__init__(client, schema.domain, title, parent, outbox=outbox, on_synced=on_synced, notify=notify)
        self._schema = schema
        self._seed = dict(seed)
        self._widgets: dict[str, QWidget] = {}
        self._nullable_datetime_widgets: dict[str, tuple[QCheckBox, QDateTimeEdit]] = {}
        self._list_tables: dict[str, tuple[QTableWidget, list[FormField]]] = {}

        for f in schema.fields:
            self.add_row(f.label, self._build_field_widget(f))

    def _build_field_widget(self, f: FormField) -> QWidget:
        value = self._seed.get(f.key)

        if f.type == FIELD_TYPE_TEXT:
            widget = QLineEdit(str(value) if value else "")
            self._widgets[f.key] = widget
            return widget

        if f.type == FIELD_TYPE_NUMBER:
            widget = QDoubleSpinBox()
            widget.setRange(-1_000_000_000, 1_000_000_000)
            widget.setDecimals(2)
            widget.setValue(float(value) if isinstance(value, (int, float)) else 0.0)
            self._widgets[f.key] = widget
            return widget

        if f.type == FIELD_TYPE_DATETIME:
            millis = int(value) if isinstance(value, (int, float)) else int(time.time() * 1000)
            dt_edit = QDateTimeEdit(QDateTime.fromMSecsSinceEpoch(millis))
            dt_edit.setCalendarPopup(True)
            if f.required:
                self._widgets[f.key] = dt_edit
                return dt_edit
            # Optional datetime (e.g. a calendar entry's end time) needs a way to represent
            # "unset", which a bare QDateTimeEdit can't — pair it with a checkbox instead of
            # silently coercing "no value" to "now".
            checkbox = QCheckBox("Set")
            checkbox.setChecked(value is not None)
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(checkbox)
            row.addWidget(dt_edit, 1)
            self._nullable_datetime_widgets[f.key] = (checkbox, dt_edit)
            return container

        if f.type == FIELD_TYPE_BOOL:
            widget = QCheckBox()
            widget.setChecked(bool(value))
            self._widgets[f.key] = widget
            return widget

        if f.type in (FIELD_TYPE_ENUM, FIELD_TYPE_CATEGORY):
            widget = QComboBox()
            widget.setEditable(f.type == FIELD_TYPE_CATEGORY)  # a category name not seen yet is fine
            widget.addItems(f.options)
            current = str(value) if value else ""
            if current:
                index = widget.findText(current)
                if index >= 0:
                    widget.setCurrentIndex(index)
                elif widget.isEditable():
                    widget.setEditText(current)
            self._widgets[f.key] = widget
            return widget

        if f.type == FIELD_TYPE_TAGS:
            widget = QLineEdit(", ".join(value) if value else "")
            widget.setPlaceholderText("comma-separated")
            self._widgets[f.key] = widget
            return widget

        if f.type == FIELD_TYPE_LIST:
            return self._build_list_table(f, value or [])

        if f.type == FIELD_TYPE_READONLY:
            return QLabel(str(value) if value else "—")

        widget = QLineEdit(str(value) if value else "")
        self._widgets[f.key] = widget
        return widget

    def _build_list_table(self, f: FormField, rows: list[dict]) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        table = QTableWidget(0, len(f.item_fields))
        table.setHorizontalHeaderLabels([item_field.label for item_field in f.item_fields])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(120)
        for row_data in rows:
            _append_list_row(table, f.item_fields, row_data)
        layout.addWidget(table)

        button_row = QHBoxLayout()
        add_button = QPushButton(f"+ Add row")
        add_button.clicked.connect(lambda: _append_list_row(table, f.item_fields, None))
        button_row.addWidget(add_button)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(lambda: _remove_selected_rows(table))
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._list_tables[f.key] = (table, f.item_fields)
        return container

    def entry_dict(self) -> dict:
        entry = dict(self._seed)
        for f in self._schema.fields:
            if f.key in self._nullable_datetime_widgets:
                checkbox, dt_edit = self._nullable_datetime_widgets[f.key]
                entry[f.key] = dt_edit.dateTime().toMSecsSinceEpoch() if checkbox.isChecked() else None
                continue
            if f.type == FIELD_TYPE_LIST:
                table, item_fields = self._list_tables[f.key]
                entry[f.key] = _read_list_rows(table, item_fields)
                continue
            if f.type == FIELD_TYPE_READONLY:
                continue  # never user-editable — whatever was in the seed stays
            widget = self._widgets.get(f.key)
            if widget is not None:
                entry[f.key] = _read_widget_value(f, widget)
        entry["updatedAt"] = bumped_updated_at(int(self._seed.get("updatedAt", 0)))
        return entry


def _read_widget_value(f: FormField, widget: QWidget):
    if f.type == FIELD_TYPE_TEXT:
        return widget.text().strip() or None
    if f.type == FIELD_TYPE_NUMBER:
        return widget.value()
    if f.type == FIELD_TYPE_DATETIME:
        return widget.dateTime().toMSecsSinceEpoch()
    if f.type == FIELD_TYPE_BOOL:
        return widget.isChecked()
    if f.type in (FIELD_TYPE_ENUM, FIELD_TYPE_CATEGORY):
        return widget.currentText().strip() or None
    if f.type == FIELD_TYPE_TAGS:
        return [t.strip() for t in widget.text().split(",") if t.strip()]
    return None


def _append_list_row(table: QTableWidget, item_fields: list[FormField], row_data: dict | None) -> None:
    row = table.rowCount()
    table.insertRow(row)
    for col, item_field in enumerate(item_fields):
        value = (row_data or {}).get(item_field.key)
        table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))


def _remove_selected_rows(table: QTableWidget) -> None:
    for row in sorted({index.row() for index in table.selectedIndexes()}, reverse=True):
        table.removeRow(row)


def _read_list_rows(table: QTableWidget, item_fields: list[FormField]) -> list[dict]:
    """The first item field is the row's anchor — a blank value there means "not a real row",
    skipped rather than erroring (matches the old line-items table's "blank name = skip" rule).
    `position` is assigned by final row order, not user-editable, mirroring ExpenseLineItem.position
    even for domains that don't otherwise use it (an extra unused key is harmless)."""
    rows = []
    for row in range(table.rowCount()):
        anchor_item = table.item(row, 0)
        if not anchor_item or not anchor_item.text().strip():
            continue
        record: dict = {}
        for col, item_field in enumerate(item_fields):
            cell = table.item(row, col)
            text = cell.text().strip() if cell is not None else ""
            if item_field.type == FIELD_TYPE_NUMBER:
                try:
                    number = float(text) if text else 0.0
                except ValueError:
                    number = 0.0
                if text or item_field.required:
                    record[item_field.key] = number
            elif text:
                record[item_field.key] = text
        rows.append(record)
    for index, record in enumerate(rows):
        record["position"] = index
    return rows
