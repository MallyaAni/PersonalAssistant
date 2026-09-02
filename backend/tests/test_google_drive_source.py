"""The Drive source's decisions, against a fake Drive: a new file is queued,
an unchanged one is skipped on the next pass, a changed one is queued again,
a Google Doc is exported as Word under a .docx name, a file the parser cannot
read is remembered and skipped, and an expired access token is refreshed.
The real API needs the operator's consent and is exercised live after that."""
import json

import httpx
import pytest

from backend.services.google_drive_source import DriveClient, DriveFile, sync_once

FOLDER = "folder-1"


def _fake_drive(files: list[dict], contents: dict[str, bytes], refreshes: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        auth = request.headers.get("Authorization", "")
        if url.startswith("https://oauth2.googleapis.com/token"):
            refreshes.append(1)
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        if auth != "Bearer fresh" and auth != "Bearer good":
            return httpx.Response(401, json={"error": "expired"})
        if url.startswith("https://www.googleapis.com/drive/v3/files/"):
            file_id = url.split("/files/")[1].split("/")[0].split("?")[0]
            return httpx.Response(200, content=contents[file_id])
        if url.startswith("https://www.googleapis.com/drive/v3/files"):
            return httpx.Response(200, json={"files": files})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_new_files_are_queued_unchanged_ones_skipped_and_changes_queued_again(monkeypatch, tmp_path):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "GOOGLE_TOKEN_PATH", str(tmp_path / "token.json"))
    files = [
        {"id": "f1", "name": "Itinerary.pdf", "mimeType": "application/pdf", "modifiedTime": "2026-09-01T10:00:00Z", "md5Checksum": "aaa"},
        {"id": "g1", "name": "Trip notes", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-09-01T11:00:00Z"},
        {"id": "z1", "name": "photo.heic", "mimeType": "image/heic", "modifiedTime": "2026-09-01T12:00:00Z", "md5Checksum": "ccc"},
    ]
    contents = {"f1": b"%PDF-1.4 itinerary", "g1": b"PK\x03\x04 docx export"}
    refreshes: list[int] = []
    client = DriveClient("id", "secret", {"access_token": "good", "refresh_token": "r"}, transport=_fake_drive(files, contents, refreshes))
    queued: list[tuple] = []

    async def enqueue(user_id, name, media_type, content, note):
        queued.append((user_id, name, media_type, content, note))

    state: dict[str, str] = {}
    assert await sync_once(client, FOLDER, "ani.mallya", enqueue, state) == 2
    names = {(name, media_type) for _, name, media_type, _, _ in queued}
    assert ("Itinerary.pdf", "application/pdf") in names
    assert ("Trip notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document") in names
    assert all(user == "ani.mallya" and "Google Drive" in note for user, _, _, _, note in queued)
    assert state["z1"] == "ccc", "an unreadable file is remembered so it is not fetched again"
    # Nothing changed: nothing queued.
    queued.clear()
    assert await sync_once(client, FOLDER, "ani.mallya", enqueue, state) == 0 and queued == []
    # The itinerary changed: queued again, once.
    files[0]["md5Checksum"] = "bbb"; contents["f1"] = b"%PDF-1.4 itinerary v2"
    assert await sync_once(client, FOLDER, "ani.mallya", enqueue, state) == 1
    assert queued[0][3] == b"%PDF-1.4 itinerary v2"
    # The state survived on disk beside the token.
    assert json.loads((tmp_path / "drive_sync.json").read_text())["f1"] == "bbb"


@pytest.mark.asyncio
async def test_an_expired_access_token_is_refreshed_once_and_reused(monkeypatch, tmp_path):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "GOOGLE_TOKEN_PATH", str(tmp_path / "token.json"))
    files = [{"id": "f1", "name": "Notes.txt", "mimeType": "text/plain", "modifiedTime": "2026-09-01T10:00:00Z", "md5Checksum": "aaa"}]
    refreshes: list[int] = []
    client = DriveClient("id", "secret", {"access_token": "stale", "refresh_token": "r"}, transport=_fake_drive(files, {"f1": b"hello"}, refreshes))
    queued: list[tuple] = []

    async def enqueue(*args):
        queued.append(args)

    assert await sync_once(client, FOLDER, "ani.mallya", enqueue, {}) == 1
    assert len(refreshes) == 1 and client.token["access_token"] == "fresh"
    assert queued[0][3] == b"hello"


def test_the_source_is_idle_until_client_folder_and_token_are_all_set(monkeypatch, tmp_path):
    from backend.config.settings import settings
    from backend.services.google_drive_source import configured, save_token

    monkeypatch.setattr(settings, "GOOGLE_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "GOOGLE_DRIVE_FOLDER_ID", "folder")
    assert not configured(), "no token yet"
    save_token({"refresh_token": "r"})
    assert configured()
    assert oct((tmp_path / "token.json").stat().st_mode & 0o777) == "0o600"
