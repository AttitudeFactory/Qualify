"""Pure encryptor tests (C-03): roundtrip, ciphertext hides plaintext, key_id selects the
key (rotation-ready)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from qualify_api.connections.crypto import DevEncryptor


def test_encrypt_decrypt_roundtrip() -> None:
    enc = DevEncryptor()
    ciphertext = enc.encrypt("super-secret-token")
    assert enc.decrypt(ciphertext, key_id=enc.key_id) == "super-secret-token"


def test_ciphertext_does_not_contain_plaintext() -> None:
    enc = DevEncryptor()
    ciphertext = enc.encrypt("PLAINTOKEN")
    assert b"PLAINTOKEN" not in ciphertext


def test_decrypt_with_unknown_key_id_raises() -> None:
    enc = DevEncryptor()
    ciphertext = enc.encrypt("t")
    with pytest.raises(KeyError):
        enc.decrypt(ciphertext, key_id="does-not-exist")


def test_key_id_selects_the_right_key() -> None:
    keys = {"k1": Fernet.generate_key().decode(), "k2": Fernet.generate_key().decode()}
    enc1 = DevEncryptor(key_id="k1", keys=keys)
    enc2 = DevEncryptor(key_id="k2", keys=keys)
    ct1 = enc1.encrypt("hello")
    # A resolver holding both keys decrypts by the row's key_id.
    both = DevEncryptor(key_id="k1", keys=keys)
    assert both.decrypt(ct1, key_id="k1") == "hello"
    # Wrong key_id for this ciphertext fails to decrypt.
    with pytest.raises(Exception):  # noqa: B017 - InvalidToken
        both.decrypt(ct1, key_id="k2")
    assert enc2.key_id == "k2"
