import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import pytest

from backend.config.settings import settings
from backend.core.crypto import (
    DecryptionError,
    EncryptionKeyError,
    FieldCipher,
    generate_key,
    reset_field_cipher,
)
from backend.database.types import EncryptedText

_KEY = generate_key()


def test_a_disabled_cipher_is_a_transparent_passthrough():
    cipher = FieldCipher(None)

    assert cipher.enabled is False
    assert cipher.encrypt("hello") == "hello"
    assert cipher.decrypt("hello") == "hello"


def test_an_enabled_cipher_seals_and_opens_a_value():
    cipher = FieldCipher(_KEY)

    sealed = cipher.encrypt("my private note")

    assert FieldCipher.is_sealed(sealed)
    assert "my private note" not in sealed
    assert cipher.decrypt(sealed) == "my private note"


def test_the_same_plaintext_seals_to_different_ciphertext():
    # A fresh nonce each time is why encryption must never be applied to a column
    # used for equality or deduplication.
    cipher = FieldCipher(_KEY)

    assert cipher.encrypt("same") != cipher.encrypt("same")


def test_legacy_plaintext_is_read_back_unchanged_when_enabled():
    # This is what lets encryption be turned on without migrating existing rows.
    cipher = FieldCipher(_KEY)

    assert cipher.decrypt("a plaintext row written before encryption") == (
        "a plaintext row written before encryption"
    )


def test_a_sealed_value_cannot_be_read_after_the_key_is_removed():
    sealed = FieldCipher(_KEY).encrypt("secret")

    with pytest.raises(DecryptionError):
        FieldCipher(None).decrypt(sealed)


def test_a_wrong_key_is_rejected_rather_than_returning_garbage():
    sealed = FieldCipher(_KEY).encrypt("secret")

    with pytest.raises(DecryptionError):
        FieldCipher(generate_key()).decrypt(sealed)


def test_a_tampered_ciphertext_is_rejected():
    cipher = FieldCipher(_KEY)
    sealed = cipher.encrypt("secret")
    tampered = sealed[:-2] + ("aa" if not sealed.endswith("aa") else "bb")

    with pytest.raises(DecryptionError):
        cipher.decrypt(tampered)


def test_a_malformed_key_fails_loudly():
    with pytest.raises(EncryptionKeyError):
        FieldCipher("not-base64-and-too-short")


def test_bytes_round_trip_and_passthrough():
    enabled = FieldCipher(_KEY)
    blob = os.urandom(2048)

    sealed = enabled.encrypt_bytes(blob)
    assert sealed != blob
    assert enabled.decrypt_bytes(sealed) == blob

    disabled = FieldCipher(None)
    assert disabled.encrypt_bytes(blob) == blob
    assert disabled.decrypt_bytes(blob) == blob


def test_encrypted_column_seals_on_bind_and_opens_on_result():
    column = EncryptedText()
    settings.ENCRYPTION_KEY = _KEY
    reset_field_cipher()
    try:
        bound = column.process_bind_param("column value", dialect=None)
        assert bound is not None
        assert FieldCipher.is_sealed(bound)
        assert column.process_result_value(bound, dialect=None) == "column value"
        # None stays None so a nullable column is untouched.
        assert column.process_bind_param(None, dialect=None) is None
        assert column.process_result_value(None, dialect=None) is None
    finally:
        settings.ENCRYPTION_KEY = ""
        reset_field_cipher()
