import hashlib
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import pytest

from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.config.settings import settings
from backend.core.crypto import generate_key, reset_field_cipher

_KEY = generate_key()
_PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(1024)


@pytest.fixture
def enable_encryption():
    settings.ENCRYPTION_KEY = _KEY
    reset_field_cipher()
    try:
        yield
    finally:
        settings.ENCRYPTION_KEY = ""
        reset_field_cipher()


@pytest.mark.asyncio
async def test_bytes_are_sealed_on_disk_but_read_back_in_the_clear(
    tmp_path, enable_encryption
):
    store = LocalBinaryArtifactStore(tmp_path)

    stored = await store.write("ani.mallya", "artifact-1", "png", _PNG)

    on_disk = (tmp_path / stored.storage_key).read_bytes()
    assert on_disk != _PNG
    assert not on_disk.startswith(b"\x89PNG")  # the image header is not exposed
    assert await store.read(stored.storage_key) == _PNG


@pytest.mark.asyncio
async def test_recorded_integrity_describes_the_plaintext(tmp_path, enable_encryption):
    # The SHA-256 and size stored in the database are of the image, not of the
    # sealed bytes, so the existing integrity re-check after a read still holds.
    store = LocalBinaryArtifactStore(tmp_path)

    stored = await store.write("ani.mallya", "artifact-2", "png", _PNG)

    assert stored.sha256 == hashlib.sha256(_PNG).hexdigest()
    assert stored.byte_size == len(_PNG)


@pytest.mark.asyncio
async def test_storage_is_plaintext_when_encryption_is_disabled(tmp_path):
    reset_field_cipher()
    store = LocalBinaryArtifactStore(tmp_path)

    stored = await store.write("ani.mallya", "artifact-3", "png", _PNG)

    assert (tmp_path / stored.storage_key).read_bytes() == _PNG
