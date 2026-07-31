"""AES-256-GCM encrypt/decrypt for VoxConnect bridge bodies.

Mirrors the Android side's `AesGcmCipher.kt` bit-for-bit: 256-bit key, 12-byte
random IV, 128-bit tag, token = base64(iv || ciphertext || tag). Decrypt fails
closed (returns None) on a bad tag or malformed input, matching the Kotlin
side's behavior, since a caller there treats that as "reject", not a crash.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_LENGTH_BYTES = 32
IV_LENGTH_BYTES = 12


def generate_key() -> bytes:
    return os.urandom(KEY_LENGTH_BYTES)


def key_to_base64(key: bytes) -> str:
    return base64.b64encode(key).decode("ascii")


def key_from_base64(text: str) -> bytes:
    return base64.b64decode(text)


def encrypt(key: bytes, plaintext: str) -> str:
    """Returns base64(iv || ciphertext || tag), a single self-contained token
    safe to put in an HTTP body."""
    iv = os.urandom(IV_LENGTH_BYTES)
    ciphertext = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(iv + ciphertext).decode("ascii")


def decrypt(key: bytes, token: str) -> str | None:
    """Inverse of encrypt(). Returns None on any malformed input or a failed
    tag check (tampered/wrong key) rather than raising."""
    try:
        raw = base64.b64decode(token, validate=True)
    except Exception:
        return None
    if len(raw) <= IV_LENGTH_BYTES:
        return None
    iv, ciphertext = raw[:IV_LENGTH_BYTES], raw[IV_LENGTH_BYTES:]
    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext, None)
    except (InvalidTag, ValueError):
        return None
    return plaintext.decode("utf-8")
