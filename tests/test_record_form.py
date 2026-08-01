"""GenericRecordForm is the single schema-driven edit form driving every domain — replaces the old
one-class-per-domain calendar_entry_dialog.py/expense_dialog.py/note_dialog.py (all deleted this
pass). These tests build a form from a schema exercising every field type (including the
generalized nested-list editor that used to be Expense-only code) and confirm entry_dict() reads
back what the widgets actually hold."""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtWidgets import QTableWidgetItem

from voxconnect.bridge.models import DomainSchema
from voxconnect.widgets.dialogs.record_form import GenericRecordForm, _append_list_row

SCHEMA = DomainSchema.from_dict(
    {
        "domain": "expenses",
        "titleField": "title",
        "fields": [
            {"key": "title", "label": "Title", "type": "text"},
            {"key": "totalAmount", "label": "Total amount", "type": "number", "required": True},
            {"key": "dateTime", "label": "Date", "type": "datetime", "required": True},
            {"key": "endMillis", "label": "End", "type": "datetime"},
            {"key": "isStub", "label": "Stub", "type": "bool"},
            {"key": "direction", "label": "Direction", "type": "enum", "required": True, "options": ["OUTGOING", "INCOMING"]},
            {"key": "categoryName", "label": "Category", "type": "category", "options": ["Groceries", "Bills"]},
            {"key": "tags", "label": "Tags", "type": "tags"},
            {"key": "receiptImageName", "label": "Receipt", "type": "readonly"},
            {
                "key": "lineItems",
                "label": "Line items",
                "type": "list",
                "itemFields": [
                    {"key": "name", "label": "Name", "type": "text"},
                    {"key": "quantity", "label": "Qty", "type": "number", "required": True},
                ],
            },
        ],
    }
)

SEED = {
    "uid": "e1",
    "title": "Lunch",
    "totalAmount": 12.5,
    "dateTime": 1_700_000_000_000,
    "endMillis": None,
    "isStub": False,
    "direction": "OUTGOING",
    "categoryName": "Groceries",
    "tags": ["work", "urgent"],
    "receiptImageName": "receipt.jpg",
    "lineItems": [{"name": "Coffee", "quantity": 2, "position": 0}],
    "createdAt": 1_699_999_000_000,
    "updatedAt": 1_699_999_000_000,
}


def _build_form(qtbot, seed=SEED):
    form = GenericRecordForm(MagicMock(), SCHEMA, seed, "Edit expense")
    qtbot.addWidget(form)
    return form


def test_unedited_form_round_trips_seed_values(qtbot):
    form = _build_form(qtbot)
    entry = form.entry_dict()

    assert entry["title"] == "Lunch"
    assert entry["totalAmount"] == 12.5
    assert entry["dateTime"] == 1_700_000_000_000
    assert entry["endMillis"] is None  # unset in the seed -> checkbox starts unchecked
    assert entry["isStub"] is False
    assert entry["direction"] == "OUTGOING"
    assert entry["categoryName"] == "Groceries"
    assert entry["tags"] == ["work", "urgent"]
    assert "receiptImageName" not in entry or entry["receiptImageName"] == "receipt.jpg"  # readonly, untouched
    assert entry["lineItems"] == [{"name": "Coffee", "quantity": 2.0, "position": 0}]
    assert entry["updatedAt"] > SEED["updatedAt"]  # bumped_updated_at


def test_nullable_datetime_checkbox_defaults_checked_when_seed_has_a_value(qtbot):
    seed = dict(SEED, endMillis=1_700_100_000_000)
    form = _build_form(qtbot, seed=seed)
    checkbox, dt_edit = form._nullable_datetime_widgets["endMillis"]
    assert checkbox.isChecked() is True
    assert form.entry_dict()["endMillis"] == 1_700_100_000_000


def test_unchecking_nullable_datetime_clears_it(qtbot):
    seed = dict(SEED, endMillis=1_700_100_000_000)
    form = _build_form(qtbot, seed=seed)
    checkbox, _dt_edit = form._nullable_datetime_widgets["endMillis"]
    checkbox.setChecked(False)
    assert form.entry_dict()["endMillis"] is None


def test_category_combo_accepts_a_typed_name_not_in_options(qtbot):
    form = _build_form(qtbot)
    combo = form._widgets["categoryName"]
    assert combo.isEditable() is True
    combo.setEditText("Brand New Category")
    assert form.entry_dict()["categoryName"] == "Brand New Category"


def test_enum_combo_is_not_editable(qtbot):
    form = _build_form(qtbot)
    combo = form._widgets["direction"]
    assert combo.isEditable() is False


def test_editing_tags_field_reparses_comma_separated_text(qtbot):
    form = _build_form(qtbot)
    form._widgets["tags"].setText("a, b ,  c")
    assert form.entry_dict()["tags"] == ["a", "b", "c"]


def test_list_editor_adding_a_row_and_leaving_anchor_blank_skips_it(qtbot):
    form = _build_form(qtbot)
    table, item_fields = form._list_tables["lineItems"]
    _append_list_row(table, item_fields, None)  # blank anchor row
    assert form.entry_dict()["lineItems"] == [{"name": "Coffee", "quantity": 2.0, "position": 0}]


def test_list_editor_adding_a_filled_row_appends_with_correct_position(qtbot):
    form = _build_form(qtbot)
    table, item_fields = form._list_tables["lineItems"]
    _append_list_row(table, item_fields, None)
    table.setItem(1, 0, QTableWidgetItem("Tea"))
    table.setItem(1, 1, QTableWidgetItem("3"))

    line_items = form.entry_dict()["lineItems"]
    assert line_items == [
        {"name": "Coffee", "quantity": 2.0, "position": 0},
        {"name": "Tea", "quantity": 3.0, "position": 1},
    ]
