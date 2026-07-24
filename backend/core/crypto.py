"""Application-level encryption for sensitive personal content at rest.

This is defence in depth, not a substitute for full-disk encryption. It is
opt-in: with no ``ENCRYPTION_KEY`` configured the cipher is a transparent
pass-through, so zero-config local development is unchanged. When a key is
configured, free-text personal content (conversation turns, episodic and
semantic memory content, generated/uploaded image bytes) is sealed with
AES-256-GCM before it reaches PostgreSQL or the artifact volume.

Threat model. This protects data that leaves the running process without the
key: a database dump or backup, a copied storage volume, or a disk read while
the app is stopped. It does NOT protect against an attacker who already has the
running process and its key in memory, and it is weaker than, not a replacement
for, OS full-disk encryption (BitLocker/LUKS), which remains the at-rest
baseline. It also does not encrypt embedding vectors - those stay searchable and
remain a residual disclosure vector, since an embedding can be partially
inverted. See docs/SECURITY.md.

Format. A sealed value is ``enc:1:<base64(nonce || ciphertext)>``. The marker
lets the same column hold legacy plaintext and sealed rows at once, so enabling
encryption needs no big-bang migration: existing plaintext is read back
unchanged and rewritten sealed the next time it is saved. Each value uses a
fresh random 96-bit nonce, so identical plaintext seals to different ciphertext;
that is why encryption is applied only to content retrieved by id or vector, and
never to a column used for equality, uniqueness, or deduplication.
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config.settings import settings

# Self-describing prefix for a sealed value. The version allows the algorithm or
# key-wrapping to change later without ambiguity about how to read an old value.
_MARKER = "enc:1:"
_NONCE_BYTES = 12  # 96-bit nonce, the standard size for AES-GCM.
_KEY_BYTES = 32  # AES-256.


class EncryptionKeyError(RuntimeError):
    """Raised when encryption is requested but the key is missing or malformed."""


class DecryptionError(RuntimeError):
    """Raised when a sealed value cannot be opened with the configured key."""


def generate_key() -> str:
    """Return a new urlsafe-base64 AES-256 key suitable for ``ENCRYPTION_KEY``."""
    return base64.urlsafe_b64encode(os.urandom(_KEY_BYTES)).decode()


def _load_key(raw: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(_pad(raw))
    except (ValueError, TypeError) as exc:
        raise EncryptionKeyError(
            "ENCRYPTION_KEY is not valid urlsafe base64; "
            "generate one with `python -m backend.cli.generate_encryption_key`"
        ) from exc
    if len(key) != _KEY_BYTES:
        raise EncryptionKeyError(
            f"ENCRYPTION_KEY must decode to {_KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def _pad(value: str) -> str:
    return value + "=" * (-len(value) % 4)


class FieldCipher:
    """Seals and opens individual string values with AES-256-GCM.

    Constructed once from settings and shared. When no key is configured the
    cipher is disabled and both operations are transparent, so the same code
    path serves an encrypted and an unencrypted deployment.
    """

    def __init__(self, key_material: str | None) -> None:
        self._aesgcm: AESGCM | None = None
        if key_material:
            self._aesgcm = AESGCM(_load_key(key_material))

    @property
    def enabled(self) -> bool:
        return self._aesgcm is not None

    @staticmethod
    def is_sealed(value: str) -> bool:
        return value.startswith(_MARKER)

    def encrypt(self, plaintext: str) -> str:
        # Disabled: store as-is. A later read passes it straight back.
        if self._aesgcm is None:
            return plaintext
        # Already sealed: never double-seal, so re-saving a decrypted value that
        # was loaded through this cipher is idempotent.
        if self.is_sealed(plaintext):
            return plaintext
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return _MARKER + base64.urlsafe_b64encode(nonce + sealed).decode()

    def decrypt(self, value: str) -> str:
        # Legacy plaintext (or a value written while disabled) is returned as-is,
        # which is what lets encryption be turned on without migrating old rows.
        if not self.is_sealed(value):
            return value
        if self._aesgcm is None:
            # A sealed value exists but no key is configured: refuse rather than
            # hand back the ciphertext as if it were content. Turning encryption
            # off while sealed data exists is an operator error, not a silent one.
            raise DecryptionError(
                "encountered encrypted data but ENCRYPTION_KEY is not configured"
            )
        raw = base64.urlsafe_b64decode(_pad(value[len(_MARKER) :]))
        nonce, sealed = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        try:
            opened = self._aesgcm.decrypt(nonce, sealed, None)
        except InvalidTag as exc:
            # Wrong key or tampered ciphertext. GCM authenticates, so this is a
            # real integrity signal, not a decode nuisance.
            raise DecryptionError(
                "failed to decrypt a sealed value; the key may be wrong or the "
                "data may have been tampered with"
            ) from exc
        return opened.decode("utf-8")

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        if self._aesgcm is None:
            return plaintext
        nonce = os.urandom(_NONCE_BYTES)
        return _MARKER.encode() + nonce + self._aesgcm.encrypt(nonce, plaintext, None)

    def decrypt_bytes(self, value: bytes) -> bytes:
        if not value.startswith(_MARKER.encode()):
            return value
        if self._aesgcm is None:
            raise DecryptionError(
                "encountered encrypted data but ENCRYPTION_KEY is not configured"
            )
        body = value[len(_MARKER) :]
        nonce, sealed = body[:_NONCE_BYTES], body[_NONCE_BYTES:]
        try:
            return self._aesgcm.decrypt(nonce, sealed, None)
        except InvalidTag as exc:
            raise DecryptionError(
                "failed to decrypt a sealed binary; the key may be wrong or the "
                "data may have been tampered with"
            ) from exc


_cipher: FieldCipher | None = None


def get_field_cipher() -> FieldCipher:
    """Return the process-wide cipher, building it from settings on first use."""
    global _cipher
    if _cipher is None:
        _cipher = FieldCipher(settings.ENCRYPTION_KEY or None)
    return _cipher


def reset_field_cipher() -> None:
    """Drop the cached cipher so a settings change is picked up. For tests."""
    global _cipher
    _cipher = None
