from voxconnect.bridge.models import DOMAIN_NOTES, Tombstone


def test_upsert_and_get_entries(cache_store):
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "text": "hello"}])
    entries = cache_store.get_entries(DOMAIN_NOTES)
    assert entries == [{"uid": "a", "text": "hello"}]


def test_upsert_replaces_existing_uid(cache_store):
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "text": "v1"}])
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "text": "v2"}])
    entries = cache_store.get_entries(DOMAIN_NOTES)
    assert len(entries) == 1
    assert entries[0]["text"] == "v2"


def test_apply_tombstones_removes_entry(cache_store):
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "text": "hello"}])
    cache_store.apply_tombstones(DOMAIN_NOTES, [Tombstone(uid="a", deleted_at=123)])
    assert cache_store.get_entries(DOMAIN_NOTES) == []


def test_apply_tombstone_for_unknown_uid_is_a_noop(cache_store):
    cache_store.apply_tombstones(DOMAIN_NOTES, [Tombstone(uid="missing", deleted_at=123)])
    assert cache_store.get_entries(DOMAIN_NOTES) == []


def test_replace_domain_discards_prior_entries(cache_store):
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "text": "old"}])
    cache_store.replace_domain(DOMAIN_NOTES, [{"uid": "b", "text": "new"}])
    entries = cache_store.get_entries(DOMAIN_NOTES)
    assert len(entries) == 1
    assert entries[0]["uid"] == "b"


def test_last_synced_at_roundtrip(cache_store):
    assert cache_store.last_synced_at(DOMAIN_NOTES) == 0
    cache_store.set_last_synced_at(DOMAIN_NOTES, 1234)
    assert cache_store.last_synced_at(DOMAIN_NOTES) == 1234


def test_save_and_reload_roundtrips_through_encryption(cache_store):
    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "text": "hello"}])
    cache_store.set_last_synced_at(DOMAIN_NOTES, 999)
    cache_store.save()

    cache_store.load()  # simulate a fresh process re-reading the same on-disk file
    assert cache_store.get_entries(DOMAIN_NOTES) == [{"uid": "a", "text": "hello"}]
    assert cache_store.last_synced_at(DOMAIN_NOTES) == 999


def test_clear_wipes_data_and_key(cache_store):
    from voxconnect.cache import store as store_module

    cache_store.upsert_entries(DOMAIN_NOTES, [{"uid": "a", "text": "hello"}])
    cache_store.save()
    old_key = cache_store._key

    cache_store.clear()

    assert cache_store.get_entries(DOMAIN_NOTES) == []
    assert cache_store._key != old_key
    assert not store_module._cache_path().exists()


def test_load_with_no_file_leaves_cache_empty(cache_store):
    cache_store.load()
    assert cache_store.get_entries(DOMAIN_NOTES) == []
