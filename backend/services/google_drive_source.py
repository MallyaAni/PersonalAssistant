"""Google Drive as a read-only document source.

The household's files that live in Drive reach document knowledge without
being shared one by one: a folder the operator names is listed on an
interval, and every new or changed file goes through the same durable parse
queue a shared file goes through (Docling when the desktop is on, kept until
then), so it lands as cited passages and dated facts like any other document.
Google Docs, Sheets and Slides are exported (Word, PDF, PDF); ordinary files
are downloaded as they are. Nothing is written to Drive, ever.

Consent is the operator's, once: `python -m backend.cli.google_connect`
prints the URL, takes the code, and writes the token file this reads.
Idle unless the folder, the client, and the token are all configured.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)

# What a Google-native file is exported as, and the name it lands under.
_EXPORTS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
}
# What is read at all: the parser's formats and plain text.
_ACCEPTED = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
        "text/markdown",
    }
)


@dataclass(frozen=True, slots=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str
    checksum: str  # md5Checksum, or modifiedTime for Google-native files


def _token_path() -> Path:
    return Path(settings.GOOGLE_TOKEN_PATH)


def load_token() -> dict[str, Any] | None:
    """The stored OAuth token (refresh token and friends), or None."""
    path = _token_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        logger.warning("Google token file is unreadable at %s", path)
        return None


def save_token(token: dict[str, Any]) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token))
    os.chmod(path, 0o600)


def configured() -> bool:
    return bool(
        settings.GOOGLE_OAUTH_CLIENT_ID
        and settings.GOOGLE_OAUTH_CLIENT_SECRET
        and settings.GOOGLE_DRIVE_FOLDER_ID
        and load_token()
    )


class DriveClient:
    """A thin, read-only Drive v3 client over httpx with token refresh."""

    def __init__(self, client_id: str, client_secret: str, token: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = dict(token)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10), transport=self._transport)

    async def _access_token(self) -> str:
        if self.token.get("access_token") and not self.token.get("_expired"):
            return str(self.token["access_token"])
        return await self.refresh()

    async def refresh(self) -> str:
        async with self._client() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.token.get("refresh_token", ""),
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            payload = response.json()
        self.token["access_token"] = payload["access_token"]
        self.token.pop("_expired", None)
        return str(payload["access_token"])

    async def _get(self, url: str, **params: Any) -> httpx.Response:
        token = await self._access_token()
        async with self._client() as client:
            response = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            if response.status_code == 401:
                token = await self.refresh()
                response = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            return response

    async def list_folder(self, folder_id: str) -> list[DriveFile]:
        files: list[DriveFile] = []
        page: str | None = None
        while True:
            response = await self._get(
                DRIVE_FILES,
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum)",
                pageSize=100,
                **({"pageToken": page} if page else {}),
            )
            payload = response.json()
            for item in payload.get("files") or []:
                files.append(
                    DriveFile(
                        str(item.get("id")),
                        str(item.get("name") or "file"),
                        str(item.get("mimeType") or ""),
                        str(item.get("modifiedTime") or ""),
                        str(item.get("md5Checksum") or item.get("modifiedTime") or ""),
                    )
                )
            page = payload.get("nextPageToken")
            if not page:
                return files

    async def download(self, file: DriveFile) -> tuple[str, str, bytes] | None:
        """(filename, media type, bytes) for a file the parser can read, else None."""
        export = _EXPORTS.get(file.mime_type)
        if export:
            media_type, suffix = export
            response = await self._get(f"{DRIVE_FILES}/{file.id}/export", mimeType=media_type)
            name = file.name if file.name.lower().endswith(suffix) else f"{file.name}{suffix}"
            return name, media_type, response.content
        if file.mime_type not in _ACCEPTED:
            return None
        response = await self._get(f"{DRIVE_FILES}/{file.id}", alt="media")
        return file.name, file.mime_type, response.content


def _state_path() -> Path:
    return _token_path().with_name("drive_sync.json")


def load_state() -> dict[str, str]:
    """file id -> checksum already handed to the queue."""
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(path.read_text()).items()}
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, str]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


# Hand every new or changed file in the folder to the parse queue. Returns
# how many were queued. `enqueue` is the queue's enqueue_document, taken as
# a parameter so the decision is testable without a database.
async def sync_once(client: DriveClient, folder_id: str, user_id: str, enqueue, state: dict[str, str] | None = None) -> int:
    state = load_state() if state is None else state
    queued = 0
    for file in await client.list_folder(folder_id):
        if state.get(file.id) == file.checksum:
            continue
        fetched = await client.download(file)
        if fetched is None:
            state[file.id] = file.checksum  # not a document; do not look again until it changes
            continue
        name, media_type, content = fetched
        await enqueue(user_id, name, media_type, content, f"from Google Drive: {file.name}")
        state[file.id] = file.checksum
        queued += 1
    save_state(state)
    return queued


async def _enqueue_to_queue(user_id: str, name: str, media_type: str, content: bytes, note: str) -> None:
    from backend.database.session import AsyncSessionLocal
    from backend.services.document_parse_queue import enqueue_document

    async with AsyncSessionLocal() as session:
        await enqueue_document(session, user_id, name, media_type, content, note, None)


async def sync_drive() -> int:
    """One pass with the configured client and folder; 0 when not configured."""
    if not configured():
        return 0
    token = load_token() or {}
    client = DriveClient(settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET, token)
    queued = await sync_once(client, settings.GOOGLE_DRIVE_FOLDER_ID, settings.GOOGLE_DRIVE_USER_ID or settings.AUTH_LOCAL_USER_ID, _enqueue_to_queue)
    if client.token != token:
        save_token(client.token)
    if queued:
        logger.info("google_drive_queued", extra={"count": queued})
    return queued


# Run sync_drive for the app's lifetime, like the parse queue; idle unless configured.
class DriveSync:
    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:
        while True:
            try:
                await sync_drive()
            except Exception:
                logger.warning("Google Drive sync pass failed", exc_info=True)
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None and self._interval > 0 and configured():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
