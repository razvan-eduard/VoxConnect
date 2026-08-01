"""SyncEngine tests run its background dispatch synchronously (monkeypatched
run_in_background) so results are observable without a real QThreadPool race
— this needs a real QApplication for the QTimer/Signal machinery, hence
pytest-qt's qtbot fixture even though nothing here touches a widget."""

from __future__ import annotations

import json

import pytest

from voxconnect.bridge.models import DOMAIN_CALENDAR, DOMAIN_EXPENSES, DOMAIN_NOTES, VoxResult
from voxconnect.cache.sync import WATERMARK_SAFETY_BUFFER_MS, SyncEngine

TEST_DOMAINS = (DOMAIN_CALENDAR, DOMAIN_EXPENSES, DOMAIN_NOTES)


class FakeClient:
    def __init__(self, result: VoxResult):
        self.result = result
        self.last_command = None

    def send_command(self, command):
        self.last_command = command
        return self.result


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

    monkeypatch.setattr("voxconnect.cache.sync.run_in_background", fake_run_in_background)


def _sync_result_payload(entries=None, tombstones=None) -> str:
    return json.dumps({"entries": entries or [], "tombstones": tombstones or []})


def test_sync_all_upserts_entries_and_advances_watermark(qtbot, cache_store):
    result = VoxResult(ok=True, text=_sync_result_payload(entries=[{"uid": "a", "text": "hi"}]))
    client = FakeClient(result)
    engine = SyncEngine(client, cache_store, list(TEST_DOMAINS))

    synced = []
    engine.domain_synced.connect(synced.append)

    engine.sync_all()

    assert sorted(synced) == sorted(TEST_DOMAINS)
    for domain in TEST_DOMAINS:
        assert cache_store.get_entries(domain) == [{"uid": "a", "text": "hi"}]
        # The persisted watermark trails "now" by the safety buffer, never the raw call time —
        # just confirm it actually advanced past the initial 0.
        assert cache_store.last_synced_at(domain) > 0


def test_force_full_refresh_replaces_rather_than_upserts(qtbot, cache_store):
    cache_store.upsert_entries(DOMAIN_CALENDAR, [{"uid": "stale", "text": "old"}])
    result = VoxResult(ok=True, text=_sync_result_payload(entries=[{"uid": "fresh", "text": "new"}]))
    client = FakeClient(result)
    engine = SyncEngine(client, cache_store, list(TEST_DOMAINS))

    engine.force_full_refresh(DOMAIN_CALENDAR)

    entries = cache_store.get_entries(DOMAIN_CALENDAR)
    assert entries == [{"uid": "fresh", "text": "new"}]


def test_locked_result_emits_domain_locked_not_error(qtbot, cache_store):
    locked_text = "Calendarul este blocat. Deblochează aplicația."
    client = FakeClient(VoxResult(ok=False, text=locked_text))
    engine = SyncEngine(client, cache_store, list(TEST_DOMAINS))

    locked_events = []
    error_events = []
    engine.domain_locked.connect(lambda domain, locked: locked_events.append((domain, locked)))
    engine.domain_error.connect(lambda domain, msg: error_events.append((domain, msg)))

    engine.force_full_refresh(DOMAIN_CALENDAR)

    assert (DOMAIN_CALENDAR, True) in locked_events
    assert error_events == []


def test_unlocked_error_result_emits_domain_error(qtbot, cache_store):
    client = FakeClient(VoxResult(ok=False, text="domain not monitored"))
    engine = SyncEngine(client, cache_store, list(TEST_DOMAINS))

    error_events = []
    engine.domain_error.connect(lambda domain, msg: error_events.append((domain, msg)))

    engine.force_full_refresh(DOMAIN_CALENDAR)

    assert (DOMAIN_CALENDAR, "domain not monitored") in error_events
