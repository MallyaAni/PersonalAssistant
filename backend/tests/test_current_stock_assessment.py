"""Fresh stock assessments reach the read-only board without an account preview."""

import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


# Exercise owner HTTP reads with fresh, expired and mismatched candle evidence.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["fresh", "expired", "wrong_decision", "old_bar", "missing_read"]
)
async def test_current_assessment_requires_fresh_matching_evidence(
    tmp_path, monkeypatch, mode
):
    now = datetime(2026, 10, 14, 16, 1, tzinfo=UTC)

    # Freeze request time without changing the evidence's own timestamps.
    class Clock(datetime):
        # Supply the current regular-session instant to the API.
        @classmethod
        def now(cls, tz=None):
            return now

    record = {
        "session": "2026-10-13",
        "grades": {
            "AAA": {
                "grade": "B",
                "score": 0.2,
                "stances": {
                    "fundamental": 1,
                    "technical": -1,
                    "sentiment": 1,
                    "value": 0,
                },
                "ranks": {"fundamental": 0.9, "technical": 0.1, "sentiment": 0.9},
            }
        },
        "targets": {"weights": {"AAA": 0}},
    }
    snapshot = {
        "as_of": "2026-10-14T16:00:29+00:00",
        "decision_session": record["session"],
        "quotes": {"AAA": {"last": 66, "bar": "2026-10-14T15:45:00+00:00"}},
        "technical": {"AAA": {"now": 0.95, "close": 0.1, "stance": 1}},
        "value": {},
    }
    if mode == "expired":
        snapshot["as_of"] = "2026-10-14T15:40:00+00:00"
    elif mode == "wrong_decision":
        snapshot["decision_session"] = "2026-10-12"
    elif mode == "old_bar":
        snapshot["quotes"]["AAA"]["bar"] = "2026-10-13T15:45:00+00:00"
    elif mode == "missing_read":
        snapshot["technical"] = {}
    original = deepcopy(record)
    folder = tmp_path / "desk"
    folder.mkdir()
    source = json.dumps(snapshot).encode()
    (folder / "live.json").write_bytes(source)
    monkeypatch.setattr(market, "datetime", Clock)
    monkeypatch.setattr(market.deskrecord, "latest_pair", lambda root: (record, None))
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "owner")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/owner/desk/live",
            headers={"Authorization": f"Bearer {issue_user_token('owner')}"},
        )
        anonymous = await client.get("/api/v1/market/owner/desk/live")
        foreign = await client.get(
            "/api/v1/market/owner/desk/live",
            headers={"Authorization": f"Bearer {issue_user_token('foreign')}"},
        )
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    assert anonymous.status_code == 401
    assert foreign.status_code == 403
    data = response.json()
    if mode == "fresh":
        assert data["grades_live"]["AAA"]["grade_live"] == "A+"
        assert data["grades_live"]["AAA"]["technical_now"] == 0.95
        assert data["grade_valid_until"]["AAA"] == "2026-10-14T16:15:00+00:00"
    else:
        assert data["grades_live"] == data["grade_valid_until"] == {}
    assert record == original
    assert (folder / "live.json").read_bytes() == source
    assert list(folder.iterdir()) == [folder / "live.json"]
