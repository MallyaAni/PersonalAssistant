"""Pin the unchanged backend meanings displayed by the desk history corrections.

Prices, grades and records are synthetic. These tests exercise real history
calculation, serialization and authenticated ASGI HTTP readback, not investment
performance, a deployed server, model inference or external market data.
"""

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from backend.agents.trading.desk.grading import ORDINAL, A, Graded
from backend.cli import market_daily
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.market import decision_view, deskrecord, execution_quotes
from backend.market.panel import Panel
from backend.market.store import MarketStore
from backend.tests.test_decision_view import FIRING, setup


# Supply fixed grades while real history functions calculate adjusted-price outcomes.
def _history_report():
    dates = np.arange("2026-09-21", "2026-09-25", dtype="datetime64[D]")
    close = np.full((4, 2), 100.0)
    adjusted = np.column_stack(([100.0, 200.0, 100.0, 100.0], np.full(4, 100.0)))
    panel = Panel(
        dates,
        ("SYNTH", "SPY"),
        close,
        close,
        close,
        close,
        adjusted,
        np.ones_like(close),
        {},
        "SPY",
    )
    graded = Graded(
        np.full((4, 2), ORDINAL[A]),
        np.ones((4, 2)),
        {"fundamental": np.ones((4, 2), dtype=int)},
    )
    state = SimpleNamespace(exposure=1.0, selection_confidence=1.0)
    return SimpleNamespace(
        panel=panel,
        graded=graded,
        opinions={},
        sides={"SYNTH": "ai"},
        regime=SimpleNamespace(states=[state] * 4),
    )


# Preserve log-return units and missing/partial published votes through HTTP.
@pytest.mark.parametrize(
    ("published_stances", "published_votes", "record_votes"),
    [
        (None, None, False),
        ({}, 0, True),
        ({"technical": 0}, 0, True),
        ({}, None, True),
        ({}, None, False),
    ],
)
@pytest.mark.asyncio
async def test_history_retains_log_units_and_original_vote_missingness(
    tmp_path, monkeypatch, published_stances, published_votes, record_votes
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    report = _history_report()
    assert market_daily.write_history(MarketStore(tmp_path), report, horizon=1) == 1
    path = tmp_path / "history" / "SYNTH.json"
    persisted = json.loads(path.read_text())
    if published_stances is not None:
        published = {
            "session": "2026-09-21",
            "grades": {
                "SYNTH": {
                    "grade": "C",
                    "stances": published_stances,
                }
            },
        }
        if record_votes:
            published["grades"]["SYNTH"]["votes"] = published_votes
        folder = deskrecord.folder(tmp_path, published["session"])
        folder.mkdir(parents=True)
        (folder / "desk.json").write_text(json.dumps(published))
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*.json")
    }
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get("/api/v1/market/desk_user/desk/history/SYNTH")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["horizon"] == 1
    rows = payload["rows"]
    # The prices double, halve, then stay flat, although raw closes are unchanged.
    assert [r["forward"] for r in rows] == [
        round(math.log(2), 6),
        round(math.log(0.5), 6),
        0.0,
        None,
    ]
    assert [r["forward"] for r in rows] == [r["forward"] for r in persisted["rows"]]
    np.testing.assert_allclose(
        [math.expm1(r["forward"]) for r in rows[:3]],
        [1.0, -0.5, 0.0],
        atol=1e-6,
    )
    if published_stances is None:
        assert rows[0]["stances"] == {"fundamental": 1}
        assert rows[0]["grade"] == "A"
        assert rows[0]["said"] is False
    else:
        assert rows[0]["stances"] == published_stances
        assert rows[0]["votes"] == published_votes
        assert "fundamental" not in rows[0]["stances"]
        assert rows[0]["grade"] == "C"
        assert rows[0]["said"] is True
    assert rows[1]["stances"] == {"fundamental": 1}
    assert rows[1]["said"] is False
    assert {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*.json")
    } == before


# A closed or unknown session blocks execution without erasing intent or quotes.
@pytest.mark.parametrize("market_open", [False, None])
def test_regular_session_uncertainty_preserves_intent_and_dated_quote(market_open):
    record, snapshot, quoted, now = setup()
    quoted["market_open"] = market_open
    raw = quoted["quotes"]["S11"]
    described = execution_quotes.describe(raw, "sip", market_open, now)
    assert described["reason"] == "Market closed or clock unavailable"
    assert described["eligible"] is False
    assert described["bid"] == raw["bp"]
    assert described["ask"] == raw["ap"]
    assert described["at"] == now.isoformat()
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries=FIRING,
        cash=100000,
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert row["executable"] is False
    assert row["move_weight"] == 0
