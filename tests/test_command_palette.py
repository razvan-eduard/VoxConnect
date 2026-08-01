from voxconnect.bridge.models import DOMAIN_EXPENSES, DOMAIN_NOTES, OP_CREATE, DomainSchema
from voxconnect.widgets.command_palette import fuzzy_search_records, parse_command

NOTES_SCHEMA = DomainSchema.from_dict(
    {"domain": DOMAIN_NOTES, "titleField": "title", "titleFallbackField": "text", "fields": []}
)
CALENDAR_SCHEMA = DomainSchema.from_dict(
    {"domain": "calendar", "titleField": "title", "subtitleFields": ["layerName"], "fields": []}
)
EXPENSES_SCHEMA = DomainSchema.from_dict({"domain": DOMAIN_EXPENSES, "titleField": "title", "fields": []})
SCHEMAS = {DOMAIN_NOTES: NOTES_SCHEMA, "calendar": CALENDAR_SCHEMA, DOMAIN_EXPENSES: EXPENSES_SCHEMA}


def test_parse_command_matches_domain_by_unambiguous_prefix():
    parsed = parse_command("> exp 47 emag", SCHEMAS)
    assert parsed is not None
    assert parsed.command.op == OP_CREATE
    assert parsed.command.domain == DOMAIN_EXPENSES
    assert parsed.command.text == "47 emag"


def test_parse_command_normalizes_leading_comma_decimal():
    parsed = parse_command("> exp 47,50 emag", SCHEMAS)
    assert parsed is not None
    assert parsed.command.text == "47.50 emag"


def test_parse_command_matches_exact_domain_name():
    parsed = parse_command("> notes call the plumber", SCHEMAS)
    assert parsed is not None
    assert parsed.command.op == OP_CREATE
    assert parsed.command.domain == DOMAIN_NOTES
    assert parsed.command.text == "call the plumber"


def test_parse_command_works_for_any_discovered_domain_not_just_expenses_and_notes():
    parsed = parse_command("> cal team sync tomorrow", SCHEMAS)
    assert parsed is not None
    assert parsed.command.domain == "calendar"
    assert parsed.command.text == "team sync tomorrow"


def test_parse_command_none_without_prefix():
    assert parse_command("exp 47 emag", SCHEMAS) is None


def test_parse_command_none_for_unrecognized_domain_keyword():
    assert parse_command("> frobnicate something", SCHEMAS) is None


def test_parse_command_none_for_bare_prefix():
    assert parse_command(">", SCHEMAS) is None
    assert parse_command(">   ", SCHEMAS) is None


def test_parse_command_none_for_domain_keyword_with_no_text():
    assert parse_command("> notes", SCHEMAS) is None


def test_parse_command_none_for_ambiguous_prefix():
    schemas = {**SCHEMAS, "notesarchive": DomainSchema.from_dict({"domain": "notesarchive", "titleField": "title"})}
    assert parse_command("> note something", schemas) is None


def test_fuzzy_search_records_matches_title_and_fallback_field(cache_store):
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "title": "Plumber", "text": "call about the leak"}])
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "b", "title": "Shopping list", "text": "milk, eggs"}])

    assert [(d, r["uid"]) for d, r in fuzzy_search_records(cache_store, SCHEMAS, "plumb")] == [(DOMAIN_NOTES, "a")]
    assert [(d, r["uid"]) for d, r in fuzzy_search_records(cache_store, SCHEMAS, "leak")] == [(DOMAIN_NOTES, "a")]
    assert [(d, r["uid"]) for d, r in fuzzy_search_records(cache_store, SCHEMAS, "milk")] == [(DOMAIN_NOTES, "b")]
    assert fuzzy_search_records(cache_store, SCHEMAS, "nonexistent") == []


def test_fuzzy_search_records_searches_every_discovered_domain_not_just_notes(cache_store):
    cache_store.upsert_entries("calendar", [{"uid": "c1", "title": "Dentist appointment", "layerName": "Personal"}])
    cache_store.upsert_entries(DOMAIN_EXPENSES, [{"uid": "e1", "title": "Dentist bill"}])
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "n1", "title": "Unrelated note", "text": ""}])

    matches = fuzzy_search_records(cache_store, SCHEMAS, "dentist")
    assert {(d, r["uid"]) for d, r in matches} == {("calendar", "c1"), (DOMAIN_EXPENSES, "e1")}


def test_fuzzy_search_records_respects_total_limit_across_domains(cache_store):
    entries = [{"uid": str(i), "title": "note", "text": ""} for i in range(10)]
    cache_store.upsert_entries(DOMAIN_NOTES, entries)
    assert len(fuzzy_search_records(cache_store, SCHEMAS, "note", limit=3)) == 3
