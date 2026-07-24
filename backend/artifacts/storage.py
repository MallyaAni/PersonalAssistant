import asyncio
import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from backend.artifacts.types import StoredBinary
from backend.core.crypto import get_field_cipher
from backend.core.interfaces import BinaryArtifactStore

_ALLOWED_EXTENSIONS = {"jpg", "png", "webp"}


# Write bytes to a temporary file and atomically replace the final path.
def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


class LocalBinaryArtifactStore(BinaryArtifactStore):
    # Resolve the configured root once for safe opaque-key containment checks.
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    # Store bytes under a user namespace without exposing the raw user identifier.
    async def write(
        self,
        user_id: str,
        artifact_id: str,
        extension: str,
        content: bytes,
    ) -> StoredBinary:
        normalized_extension = extension.lower().lstrip(".")
        if normalized_extension not in _ALLOWED_EXTENSIONS:
            raise ValueError("Unsupported artifact extension")
        user_namespace = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        storage_key = f"{user_namespace}/{artifact_id}.{normalized_extension}"
        # Integrity is recorded over the plaintext, so the SHA-256 and size in the
        # database describe the image regardless of whether the bytes on disk are
        # sealed. A read decrypts before the caller re-checks, so the check holds.
        stored = StoredBinary(
            storage_key=storage_key,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        at_rest = get_field_cipher().encrypt_bytes(content)
        await asyncio.to_thread(
            _write_atomic,
            self._path_for_key(storage_key),
            at_rest,
        )
        return stored

    # Read a stored binary without blocking the request event loop.
    async def read(self, storage_key: str) -> bytes:
        at_rest = await asyncio.to_thread(self._path_for_key(storage_key).read_bytes)
        return get_field_cipher().decrypt_bytes(at_rest)

    # Delete a stored binary idempotently without leaving its user directory behind.
    async def delete(self, storage_key: str) -> None:
        path = self._path_for_key(storage_key)
        await asyncio.to_thread(path.unlink, missing_ok=True)
        with suppress(OSError):
            await asyncio.to_thread(path.parent.rmdir)

    # Resolve an opaque key while refusing absolute paths and traversal.
    def _path_for_key(self, storage_key: str) -> Path:
        candidate_key = Path(storage_key)
        if candidate_key.is_absolute() or ".." in candidate_key.parts:
            raise ValueError("Invalid artifact storage key")
        candidate = (self.root / candidate_key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Artifact storage key escaped its root") from exc
        return candidate
