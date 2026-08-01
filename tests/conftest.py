"""Shared fixtures. CacheStore touches the real OS keyring and a real on-disk
path by default (same constants the production app uses) — tests must never
touch either, or they'd clobber whatever the actually-installed app has
stored on this machine."""

from __future__ import annotations

import pytest


@pytest.fixture
def cache_store(tmp_path, monkeypatch):
    from voxconnect.cache import store as store_module

    fake_keyring: dict[tuple[str, str], str] = {}

    def fake_get_password(service, username):
        return fake_keyring.get((service, username))

    def fake_set_password(service, username, password):
        fake_keyring[(service, username)] = password

    def fake_delete_password(service, username):
        if (service, username) not in fake_keyring:
            raise store_module.keyring.errors.PasswordDeleteError()
        del fake_keyring[(service, username)]

    monkeypatch.setattr(store_module.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(store_module.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(store_module.keyring, "delete_password", fake_delete_password)
    monkeypatch.setattr(store_module, "_cache_path", lambda: tmp_path / "cache.enc")

    return store_module.CacheStore()
