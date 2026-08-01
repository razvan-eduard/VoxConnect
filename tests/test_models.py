from voxconnect.bridge.models import (
    DIRECTION_INCOMING,
    DOMAIN_EXPENSES,
    CalendarEntry,
    DomainSchema,
    Expense,
    ExpenseLineItem,
    FormField,
    Note,
    NowPlaying,
    VoxResult,
    is_locked,
    is_media_permission_missing,
)


def test_calendar_entry_roundtrip():
    entry = CalendarEntry(
        uid="u1",
        type="EVENT",
        title="Standup",
        start_millis=1000,
        created_at=1,
        updated_at=2,
        description="daily sync",
        location="Room A",
        end_millis=2000,
        all_day=False,
        completed=False,
        recurrence_frequency="WEEKLY",
        recurrence_until_millis=9999,
        layer_name="Work",
        tags=["work", "recurring"],
    )
    restored = CalendarEntry.from_dict(entry.to_dict())
    assert restored == entry


def test_calendar_entry_roundtrip_with_optional_fields_absent():
    entry = CalendarEntry(uid="u1", type="TASK", title="Buy milk", start_millis=1000, created_at=1, updated_at=2)
    restored = CalendarEntry.from_dict(entry.to_dict())
    assert restored == entry


def test_expense_roundtrip_including_line_items():
    expense = Expense(
        uid="e1",
        total_amount=42.5,
        currency_code="RON",
        date_time=1000,
        created_at=1,
        updated_at=2,
        title="Groceries",
        vendor="Store",
        direction=DIRECTION_INCOMING,
        line_items=[
            ExpenseLineItem(name="Bread", quantity=2, unit_price=5.0, position=0),
            ExpenseLineItem(name="Milk", quantity=1, unit_price=6.0, position=1, net_amount=5.0, vat_amount=1.0),
        ],
    )
    restored = Expense.from_dict(expense.to_dict())
    assert restored == expense


def test_expense_to_dict_always_includes_line_items_key_even_when_empty():
    expense = Expense(uid="e1", total_amount=10.0, currency_code="RON", date_time=1000, created_at=1, updated_at=2)
    d = expense.to_dict()
    assert d["lineItems"] == []


def test_note_roundtrip():
    note = Note(uid="n1", text="body", created_at=1, updated_at=2, title="Title", category_name="Ideas")
    restored = Note.from_dict(note.to_dict())
    assert restored == note


def test_is_locked_matches_exact_domain_message():
    locked_result = VoxResult(ok=False, text="Cheltuielile sunt blocate. Deblochează aplicația.")
    assert is_locked(DOMAIN_EXPENSES, locked_result) is True


def test_is_locked_false_for_unrelated_error():
    error_result = VoxResult(ok=False, text="domain not monitored")
    assert is_locked(DOMAIN_EXPENSES, error_result) is False


def test_is_locked_false_when_ok():
    ok_result = VoxResult(ok=True, text="anything")
    assert is_locked(DOMAIN_EXPENSES, ok_result) is False


def test_is_media_permission_missing_matches_exact_text():
    result = VoxResult(ok=False, text="notification access not granted")
    assert is_media_permission_missing(result) is True


def test_is_media_permission_missing_false_for_other_errors():
    assert is_media_permission_missing(VoxResult(ok=False, text="no active media session")) is False
    assert is_media_permission_missing(VoxResult(ok=True, text="notification access not granted")) is False


def test_now_playing_from_dict_with_all_fields():
    now_playing = NowPlaying.from_dict(
        {
            "playing": True,
            "packageName": "com.spotify.music",
            "title": "Song",
            "artist": "Artist",
            "albumArtBase64": "abcd",
            "positionMillis": 5000,
            "durationMillis": 200000,
        }
    )
    assert now_playing == NowPlaying(
        playing=True,
        package_name="com.spotify.music",
        title="Song",
        artist="Artist",
        album_art_base64="abcd",
        position_millis=5000,
        duration_millis=200000,
    )


def test_now_playing_from_dict_missing_optional_fields():
    now_playing = NowPlaying.from_dict({"playing": False})
    assert now_playing == NowPlaying(playing=False)


def test_domain_schema_from_dict_parses_fields_and_layout_hints():
    schema = DomainSchema.from_dict(
        {
            "domain": "expenses",
            "titleField": "title",
            "titleFallbackField": "vendor",
            "subtitleFields": ["categoryName"],
            "sortField": "dateTime",
            "sortDescending": True,
            "upcomingOnlyField": None,
            "fields": [
                {"key": "title", "label": "Title", "type": "text"},
                {"key": "totalAmount", "label": "Total amount", "type": "number", "required": True},
                {"key": "categoryName", "label": "Category", "type": "category", "options": ["Groceries", "Bills"]},
            ],
        }
    )
    assert schema.domain == "expenses"
    assert schema.title_field == "title"
    assert schema.title_fallback_field == "vendor"
    assert schema.subtitle_fields == ["categoryName"]
    assert schema.sort_field == "dateTime"
    assert schema.sort_descending is True
    assert schema.upcoming_only_field is None
    assert [f.key for f in schema.fields] == ["title", "totalAmount", "categoryName"]
    assert schema.fields[1].required is True
    assert schema.fields[2].options == ["Groceries", "Bills"]


def test_domain_schema_from_dict_defaults_optional_layout_hints():
    schema = DomainSchema.from_dict({"domain": "notes", "titleField": "title", "fields": []})
    assert schema.title_fallback_field is None
    assert schema.subtitle_fields == []
    assert schema.sort_field is None
    assert schema.sort_descending is True
    assert schema.upcoming_only_field is None
    assert schema.fields == []


def test_form_field_from_dict_parses_nested_item_fields_for_list_type():
    field = FormField.from_dict(
        {
            "key": "lineItems",
            "label": "Line items",
            "type": "list",
            "itemFields": [
                {"key": "name", "label": "Name", "type": "text"},
                {"key": "quantity", "label": "Qty", "type": "number"},
            ],
        }
    )
    assert field.type == "list"
    assert [f.key for f in field.item_fields] == ["name", "quantity"]
    assert field.item_fields[1].type == "number"


def test_form_field_from_dict_defaults_required_false_and_no_options():
    field = FormField.from_dict({"key": "title", "label": "Title", "type": "text"})
    assert field.required is False
    assert field.options == []
    assert field.item_fields == []
