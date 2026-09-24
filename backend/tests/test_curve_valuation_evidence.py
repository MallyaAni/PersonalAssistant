"""Historical returns require complete held valuations before current display."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.tests.test_market_desk_api import _write


# Reading old curves must withhold their metrics without rewriting the original file.
@pytest.mark.parametrize("validated", [False, True])
@pytest.mark.asyncio
async def test_curve_validation_over_http_preserves_original_record(
    tmp_path, monkeypatch, validated
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    backtest = {"dates": ["2026-09-11"], "rules": [0.0], "stats": {"total": 0.0}}
    if validated:
        backtest["valuation_model"] = "complete-held-marks-v1"
    curve = {"backtest": backtest, "paper": {"equity": [100000]}}
    _write(tmp_path, "2026-09-11", {"AAPL": "A"}, [("AAPL", 0.1)], [], curve)
    path = tmp_path / "desk/asof=2026-09-11/desk.json"
    before = path.read_bytes()
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get("/api/v1/market/desk_user/desk")
    assert response.status_code == 200
    payload = response.json()
    assert payload["curve"]["paper"] == curve["paper"]
    assert payload["latest"]["curve"] == curve
    if validated:
        assert payload["curve"]["backtest"] == backtest
        assert "backtest_unavailable_reason" not in payload["curve"]
    else:
        assert payload["curve"]["backtest"] is None
        assert (
            "missing prices on held stocks"
            in payload["curve"]["backtest_unavailable_reason"]
        )
    assert path.read_bytes() == before
    assert json.loads(before)["curve"] == curve
