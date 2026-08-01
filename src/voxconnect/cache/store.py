"""Encrypted on-disk cache of synced domain data (calendar/expenses/notes).

This is a *derived* copy kept in sync via sync_export deltas — never edited
independently, never a second source of truth (see cache/sync.py). Stored as
one AES-GCM-encrypted JSON blob, deliberately separate from settings.json
(pairing/layout are small app settings; this is domain data). The AES-256 key
lives in the OS keyring (Keychain/Credential Manager/Secret Service), never
written to a plain file — only the encrypted blob touches disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import keyring
from platformdirs import user_data_dir

from voxconnect.bridge import crypto
from voxconnect.bridge.models import Tombstone

APP_NAME = "VoxConnect"
APP_AUTHOR = "razvan-eduard"
KEYRING_SERVICE = "VoxConnect"
KEYRING_USERNAME = "cache-key"


def _cache_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path() -> Path:
    return _cache_dir() / "cache.enc"


def _load_or_create_key() -> bytes:
    existing = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    if existing:
        return crypto.key_from_base64(existing)
    key = crypto.generate_key()
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, crypto.key_to_base64(key))
    return key


def _empty_domain() -> dict:
    return {"entries": {}, "last_synced_at": 0}


class CacheStore:
    """Domain-agnostic — the set of domains isn't known upfront (it's discovered dynamically per
    session, see BridgeClient.get_apps()), so every domain key is created lazily on first access
    rather than pre-declared. A never-before-seen domain just starts out empty; there's nothing to
    validate against."""

    def __init__(self) -> None:
        self._key = _load_or_create_key()
        self._data: dict[str, dict] = {}
        self.load()

    def _domain(self, domain: str) -> dict:
        return self._data.setdefault(domain, _empty_domain())

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        path = _cache_path()
        if not path.exists():
            return
        token = path.read_text()
        plaintext = crypto.decrypt(self._key, token)
        if plaintext is None:
            # Bad key or tampered/corrupt file — fail closed to an empty cache
            # rather than crash; the next sync repopulates it from scratch.
            return
        raw = json.loads(plaintext)
        for domain, data in raw.items():
            self._data[domain] = data

    def save(self) -> None:
        plaintext = json.dumps(self._data)
        token = crypto.encrypt(self._key, plaintext)
        path = _cache_path()
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(token)
        os.replace(tmp_path, path)

    def clear(self) -> None:
        """Wipes cached data and the encryption key — used when forgetting a
        paired device, so a stale phone's data never lingers for whoever
        pairs next."""
        self._data = {}
        path = _cache_path()
        if path.exists():
            path.unlink()
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except keyring.errors.PasswordDeleteError:
            pass
        self._key = _load_or_create_key()

    # -- domain data ----------------------------------------------------------

    def get_entries(self, domain: str) -> list[dict]:
        return list(self._domain(domain)["entries"].values())

    def upsert_entries(self, domain: str, entries: list[dict]) -> None:
        entries_by_uid = self._domain(domain)["entries"]
        for entry in entries:
            entries_by_uid[entry["uid"]] = entry

    def apply_tombstones(self, domain: str, tombstones: list[Tombstone]) -> None:
        entries_by_uid = self._domain(domain)["entries"]
        for tombstone in tombstones:
            entries_by_uid.pop(tombstone.uid, None)

    def replace_domain(self, domain: str, entries: list[dict]) -> None:
        self._domain(domain)["entries"] = {entry["uid"]: entry for entry in entries}

    def last_synced_at(self, domain: str) -> int:
        return self._domain(domain)["last_synced_at"]

    def set_last_synced_at(self, domain: str, value: int) -> None:
        self._domain(domain)["last_synced_at"] = value
