"""The desk endpoint: the day's record and its changes reach the page, and
only for the user whose token asks."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


def _write(root, session, grades, book, flags):
    path = root / "desk" / f"asof={session}" / "desk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "session": session,
                "regime": {
                    "flags": flags,
                    "selection_confidence": 0.5,
                    "exposure": 1.0,
                },
                "grades": {t: {"grade": g} for t, g in grades.items()},
                "book": [{"ticker": t, "weight": w} for t, w in book],
                "briefs": {},
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_the_endpoint_returns_the_record_and_the_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-03", {"SNDK": "A", "MU": "A+"}, [("MU", 0.07)], [])
    _write(tmp_path, "2026-09-04", {"SNDK": "A+", "MU": "B"}, [("SNDK", 0.08)], ["x"])
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
        earlier = await client.get(
            "/api/v1/market/desk_user/desk/2026-09-03",
            headers={"Authorization": f"Bearer {token}"},
        )
        missing = await client.get(
            "/api/v1/market/desk_user/desk/2020-01-01",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["latest"]["session"] == "2026-09-04"
    assert payload["summary"]["counts"] == {"A+": 1, "A": 0, "B": 1, "C": 0}
    assert payload["changes"]["since"] == "2026-09-03"
    assert payload["changes"]["upgrades"] == [
        {"ticker": "SNDK", "from": "A", "to": "A+"}
    ]
    assert {o["ticker"]: o["action"] for o in payload["changes"]["orders"]} == {
        "MU": "sell",
        "SNDK": "buy",
    }
    assert payload["changes"]["flags_raised"] == ["x"]
    assert payload["sessions"] == ["2026-09-03", "2026-09-04"]
    assert earlier.status_code == 200
    assert earlier.json()["record"]["session"] == "2026-09-03"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_no_record_is_an_empty_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": "desk_user", "latest": None, "sessions": []}


@pytest.mark.asyncio
async def test_another_users_token_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code in (401, 403), response.text


@pytest.mark.asyncio
async def test_a_user_who_is_not_the_operator_is_refused_with_their_own_token(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+"}, [("SNDK", 0.08)], [])
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/someone_else/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403, response.text
