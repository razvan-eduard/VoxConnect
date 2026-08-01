from voxconnect.bridge import crypto


def test_key_roundtrip():
    key = crypto.generate_key()
    assert len(key) == crypto.KEY_LENGTH_BYTES
    encoded = crypto.key_to_base64(key)
    assert crypto.key_from_base64(encoded) == key


def test_encrypt_decrypt_roundtrip():
    key = crypto.generate_key()
    plaintext = '{"hello": "world"}'
    token = crypto.encrypt(key, plaintext)
    assert crypto.decrypt(key, token) == plaintext


def test_decrypt_with_wrong_key_fails_closed():
    key = crypto.generate_key()
    other_key = crypto.generate_key()
    token = crypto.encrypt(key, "secret")
    assert crypto.decrypt(other_key, token) is None


def test_decrypt_tampered_body_fails_closed():
    key = crypto.generate_key()
    token = crypto.encrypt(key, "secret")
    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
    assert crypto.decrypt(key, tampered) is None


def test_decrypt_malformed_input_fails_closed():
    key = crypto.generate_key()
    assert crypto.decrypt(key, "not-base64!!!") is None
    assert crypto.decrypt(key, "") is None


def test_two_encryptions_use_different_ivs():
    key = crypto.generate_key()
    assert crypto.encrypt(key, "same plaintext") != crypto.encrypt(key, "same plaintext")
