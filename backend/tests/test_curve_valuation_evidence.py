"""The Historical simulation box reads the installed rule's replay only."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.cli import market_policy_replay_research as research
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.tests.test_market_desk_api import _write

POLICY = "grade-led-leader-weight/1"
SESSION = "2026-09-11"


# A replay folder for the session, as the 20:40 job writes it.
def _replay(root):
    manifest = {
        "schema": research.SCHEMA,
        "arm": research.INSTALLED_ARMS[POLICY],
        "through": SESSION,
        "generated_at": "2026-09-12T00:44:00+00:00",
        "note": "In-sample research.",
        "book": {
            "capital": 100000.0,
            "all": {"cagr": 0.34, "max_drawdown": -0.29, "sharpe": 1.36, "total": 2.5},
            "to_2022": {"cagr": 0.17, "max_drawdown": -0.29},
            "from_2023": {"cagr": 0.77, "max_drawdown": -0.25},
            "fills": 7009,
            "costs": 56984.1,
            "period": {"start": "2026-09-10", "through": SESSION, "sessions": 2},
            "benchmark": {"symbol": "SPY", "basis": "b", "cagr": 0.14, "total": 0.01},
            "rule": {"cost_bps": 10.0},
            "curve_file": research.BOOK_FILE,
        },
        "curve": {
            "dates": ["2026-09-10", SESSION],
            "equity": [0.0, 2.5],
            "benchmark": [0.0, 0.01],
        },
    }
    research.write(root, POLICY, manifest, {})
    return manifest


async def _desk(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get("/api/v1/market/desk_user/desk")
    assert response.status_code == 200
    return response.json()


# A record carrying an old daily-price curve: the box shows the installed
# rule's replay when it exists and says it is missing when it does not, never
# the record's stored curve; reading never rewrites the record.
@pytest.mark.parametrize("replayed", [False, True])
@pytest.mark.asyncio
async def test_the_box_never_falls_back_to_the_records_curve(
    tmp_path, monkeypatch, replayed
):
    backtest = {"dates": [SESSION], "rules": [0.0], "stats": {"total": 0.0}}
    curve = {"backtest": backtest, "paper": {"equity": [100000]}}
    _write(tmp_path, SESSION, {"AAPL": "A"}, [("AAPL", 0.1)], [], curve)
    path = tmp_path / f"desk/asof={SESSION}/desk.json"
    record = json.loads(path.read_text())
    record["targets"] = {"policy": POLICY, "weights": {"AAPL": 0.1}}
    path.write_text(json.dumps(record))
    before = path.read_bytes()
    manifest = _replay(tmp_path) if replayed else None
    payload = await _desk(tmp_path, monkeypatch)
    shown = payload["policy_simulation"]
    assert "curve" not in payload
    if replayed:
        assert shown["status"] == "available"
        assert shown["policy"] == POLICY
        assert shown["session"] == SESSION
        assert shown["book"] == manifest["book"]
        assert shown["equity"] == manifest["curve"]["equity"]
        assert shown["benchmark"] == manifest["curve"]["benchmark"]
    else:
        assert shown["status"] == "missing"
        assert shown["policy"] == POLICY
        assert "20:40" in shown["reason"]
        assert "book" not in shown
    assert path.read_bytes() == before
