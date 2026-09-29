"""The fifteen-minute ticker chart: bars from the SIP store, decisions marked.

What has to hold: the last N complete stored sessions come back as
fifteen-minute bars stamped with their New York start (26 on a normal day,
14 on an early close, plus the closing-auction bar flagged as such); a
decision sits on its session's last regular bar and the fill it leads to
on the next session's opening bar (a buy) or closing bar (a sell); a
recorded fill sits on the bar its side's convention puts it on; a gap in
the store is reported rather than closed over; and a name with no
partition is None, which the route answers with a 404.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from backend.market import intraday_sip as sip
from backend.market import ticker_chart_intraday as chart
from backend.market.alpaca import IntradayBar
from backend.market.store import MarketStore
from backend.tests.test_intraday_sip import PROVENANCE, _bars

EARLY = date(2025, 11, 28)  # 13:00 close: 14 regular slots
MON = date(2025, 12, 1)
TUE = date(2025, 12, 2)
WED = date(2025, 12, 3)


# One session's bars with the closing-auction bar appended: `_bars` gives
# the regular slots from 09:30 EST; the cross starts at the session close.
def _with_auction(day: date, base: float, count: int) -> list[IntradayBar]:
    bars = _bars(day, base=base, count=count)
    close = bars[-1].start + timedelta(minutes=15)
    return bars + [
        IntradayBar(close, base + 50, base + 50.5, base + 49.5, base + 50, 5000.0)
    ]


# A store holding the early close (14 bars + auction) and two full December
# sessions (26 bars + auction each), or whichever of those are asked for.
def _store(tmp_path: Path, days=(EARLY, MON, TUE)) -> MarketStore:
    store = MarketStore(tmp_path)
    for day in days:
        count = 14 if day == EARLY else 26
        sip.write_session(
            store, "AAPL", day, _with_auction(day, 100.0, count), PROVENANCE
        )
    return store


# A history file for the name: a buy decided at the early close, a sell
# decided on Monday, holds elsewhere, and the paper account's buy fill on
# Monday and sell fill on Tuesday.
def _history(tmp_path: Path, **extra) -> dict:
    history = {
        "ticker": "AAPL",
        "asof": TUE.isoformat(),
        "policy": "graded-equal-weight/4",
        "decision_note": "decisions at the close, filled at the next open",
        "rows": [
            {
                "date": EARLY.isoformat(),
                "grade": "A",
                "action": "buy",
                "target_weight": 0.14,
            },
            {
                "date": MON.isoformat(),
                "grade": "B",
                "action": "sell",
                "target_weight": 0.0,
            },
            {
                "date": TUE.isoformat(),
                "grade": "B",
                "action": "hold",
                "target_weight": 0.0,
            },
        ],
        "fills": [
            {"date": MON.isoformat(), "side": "buy", "qty": 63, "price": 224.81},
            {"date": TUE.isoformat(), "side": "sell", "qty": 63, "price": 230.5},
        ],
        **extra,
    }
    import json

    base = tmp_path / "history"
    base.mkdir(exist_ok=True)
    (base / "AAPL.json").write_text(json.dumps(history), encoding="utf-8")
    return history


# Every complete session comes back, oldest first, with its regular slots
# and the auction bar as a flagged 27th (15th) bar, stamped in New York.
def test_bars_cover_the_last_sessions_with_auction_flags(tmp_path):
    store = _store(tmp_path)
    out = chart.payload(store, tmp_path, "AAPL", 10, None)
    assert out is not None
    assert out["timeframe"] == "15m"
    assert out["adjusted"] is False
    assert out["basis"] == "raw prices as printed (consolidated SIP)"
    assert out["sessions"] == 3
    assert out["data_status"] == "complete"
    assert out["missing_sessions"] == []
    assert out["overlays"].keys() == {"session_vwap"}
    assert out["levels"] == {}
    assert out["entries"] == []
    by_day = {}
    for bar in out["bars"]:
        by_day.setdefault(bar["date"], []).append(bar)
    assert [len(v) for v in by_day.values()] == [15, 27, 27]
    early = by_day[EARLY.isoformat()]
    assert early[0]["time"] == "2025-11-28T09:30:00-05:00"
    assert early[13]["time"] == "2025-11-28T12:45:00-05:00"
    assert "auction" not in early[13]
    assert early[14]["time"] == "2025-11-28T13:00:00-05:00"
    assert early[14]["auction"] is True
    monday = by_day[MON.isoformat()]
    assert monday[25]["time"] == "2025-12-01T15:45:00-05:00"
    assert monday[26]["time"] == "2025-12-01T16:00:00-05:00"
    assert monday[26]["auction"] is True
    assert len(out["overlays"]["session_vwap"]) == len(out["bars"])
    assert out["overlays"]["session_vwap"][0] == pytest.approx(100.0)


# `sessions` is honoured and clamped: asking for one draws the newest only.
def test_sessions_selects_the_newest_and_is_clamped(tmp_path):
    store = _store(tmp_path)
    out = chart.payload(store, tmp_path, "AAPL", 1, None)
    assert out["sessions"] == 1
    assert {b["date"] for b in out["bars"]} == {TUE.isoformat()}
    assert chart.clamp_sessions(None) == 10
    assert chart.clamp_sessions(0) == 1
    assert chart.clamp_sessions(500) == 60


# The buy decided at the early close sits on that session's last regular
# bar (12:45 on a 13:00 close) and fills at Monday's 09:30 bar; the sell
# decided Monday sits on the 15:45 bar and fills at Tuesday's 15:45 bar.
def test_decisions_and_their_fills_are_placed_by_the_executor_rule(tmp_path):
    store = _store(tmp_path)
    history = _history(tmp_path)
    out = chart.payload(store, tmp_path, "AAPL", 10, history)
    assert out["decisions"] == [
        {
            "time": "2025-11-28T12:45:00-05:00",
            "date": EARLY.isoformat(),
            "action": "buy",
            "target_weight": 0.14,
            "label": "Buy 14% decided at the close",
        },
        {
            "time": "2025-12-01T15:45:00-05:00",
            "date": MON.isoformat(),
            "action": "sell",
            "target_weight": 0.0,
            "label": "Sell decided at the close",
        },
    ]
    assert out["fills_at"] == [
        {
            "time": "2025-12-01T09:30:00-05:00",
            "date": MON.isoformat(),
            "action": "buy",
            "target_weight": 0.14,
            "label": "Buy 14% fills at the open",
        },
        {
            "time": "2025-12-02T15:45:00-05:00",
            "date": TUE.isoformat(),
            "action": "sell",
            "target_weight": 0.0,
            "label": "Sell fills at the close",
        },
    ]
    # The hold row draws nothing.
    assert all(d["action"] != "hold" for d in out["decisions"])


# A recorded buy fill sits on the opening bar and a sell fill on the
# closing bar of its date; an explicit instant overrides the convention.
def test_fills_follow_the_side_convention_or_an_explicit_instant(tmp_path):
    store = _store(tmp_path)
    history = _history(tmp_path)
    out = chart.payload(store, tmp_path, "AAPL", 10, history)
    assert out["fills"] == [
        {
            "time": "2025-12-01T09:30:00-05:00",
            "date": MON.isoformat(),
            "side": "buy",
            "qty": 63,
            "price": 224.81,
            "label": "Filled buy 63 @ 224.81",
        },
        {
            "time": "2025-12-02T15:45:00-05:00",
            "date": TUE.isoformat(),
            "side": "sell",
            "qty": 63,
            "price": 230.5,
            "label": "Filled sell 63 @ 230.50",
        },
    ]
    timed = _history(
        tmp_path,
        fills=[
            {
                "date": MON.isoformat(),
                "side": "buy",
                "qty": 10,
                "price": 101.0,
                "filled_at": "2025-12-01T15:52:10+00:00",
            }
        ],
    )
    out = chart.payload(store, tmp_path, "AAPL", 10, timed)
    # 15:52 UTC is 10:52 New York, inside the 10:45 bar.
    assert [f["time"] for f in out["fills"]] == ["2025-12-01T10:45:00-05:00"]


# The payload names the policy and the reset note the history carries,
# and a decision carries its session's reset flag when the row has one.
def test_payload_carries_the_policy_and_the_reset_flags(tmp_path):
    store = _store(tmp_path)
    history = _history(tmp_path, rebalance_note="reset sessions from the clock")
    history["rows"][0]["rebalance"] = True
    history["rows"][1]["rebalance"] = False
    out = chart.payload(store, tmp_path, "AAPL", 10, history)
    assert out["policy"] == "graded-equal-weight/4"
    assert out["rebalance_note"] == "reset sessions from the clock"
    assert [d["rebalance"] for d in out["decisions"]] == [True, False]
    assert [d["rebalance"] for d in out["fills_at"]] == [True, False]
    # A file from before the flag existed carries none, and neither does the marker.
    plain = chart.payload(store, tmp_path, "AAPL", 10, _history(tmp_path))
    assert plain["policy"] == "graded-equal-weight/4"
    assert plain["rebalance_note"] is None
    assert all("rebalance" not in d for d in plain["decisions"])
    assert chart.payload(store, tmp_path, "AAPL", 10, {"rows": []})["policy"] is None


# Under the equal-weight policy an add or a trim is the reset's rebalance,
# labelled as the move it places; under a sizing policy it is the level
# it leads to, as before. Sizes are whole percents, or one decimal when
# they are not whole, the way the board writes BUY 9.1%.
def test_decision_text_is_policy_aware():
    text = chart.decision_text
    assert text("buy", 0.0909) == "Buy 9.1%"
    assert text("buy", 0.14) == "Buy 14%"
    assert text("sell", 0.0) == "Sell"
    assert text("hold", 0.1) is None
    # Both equal-weight versions, `/4` and `/5` (the account's since
    # 2026-09-29), read the reset's rebalance.
    assert chart.EQUAL_WEIGHT_POLICIES == (
        "graded-equal-weight/4",
        "graded-equal-weight/5",
    )
    for policy in chart.EQUAL_WEIGHT_POLICIES:
        assert text("add", 0.125, 0.025, policy) == "Rebalance +2.5%"
        assert text("trim", 0.10, -0.025, policy) == "Rebalance \u22122.5%"
        assert text("add", 0.20, None, policy) == "Rebalance \u219220%"
    assert text("add", 0.25, 0.05, "graded-equal-weight/5") == "Rebalance +5%"
    assert text("add", 0.20, 0.06, "some-sizing/3") == "Add \u219220%"
    assert text("trim", 0.20, -0.06, None) == "Trim \u219220%"
    # A version outside the family - the `/3` era's, or one sharing only the
    # prefix - keeps the sizing reading.
    assert text("add", 0.20, 0.06, "graded-equal-weight/3") == "Add \u219220%"
    assert text("add", 0.20, 0.06, "graded-equal-weight/40") == "Add \u219220%"


# A reset-day add in a /4 history is drawn as the rebalance it is.
def test_a_reset_add_is_labelled_as_a_rebalance(tmp_path):
    store = _store(tmp_path)
    history = _history(tmp_path)
    history["rows"][0] = {
        "date": EARLY.isoformat(),
        "grade": "A",
        "action": "add",
        "target_weight": 0.125,
        "delta_weight": 0.025,
        "rebalance": True,
    }
    out = chart.payload(store, tmp_path, "AAPL", 10, history)
    assert out["decisions"][0]["label"] == "Rebalance +2.5% decided at the close"
    assert out["decisions"][0]["rebalance"] is True
    assert out["fills_at"][0]["label"] == "Rebalance +2.5% fills at the open"


# The same reset-day add in a `/5` history - the account's policy since
# 2026-09-29, whose nightly writes that name on every history file - is
# drawn as the rebalance too, never as "Add →25%".
def test_a_reset_add_in_a_v5_history_is_labelled_as_a_rebalance(tmp_path):
    store = _store(tmp_path)
    history = _history(tmp_path)
    history["policy"] = "graded-equal-weight/5"
    history["rows"][0] = {
        "date": EARLY.isoformat(),
        "grade": "A",
        "action": "add",
        "target_weight": 0.25,
        "delta_weight": 0.05,
        "rebalance": True,
    }
    out = chart.payload(store, tmp_path, "AAPL", 10, history)
    assert out["policy"] == "graded-equal-weight/5"
    assert out["decisions"][0]["label"] == "Rebalance +5% decided at the close"
    assert out["fills_at"][0]["label"] == "Rebalance +5% fills at the open"


# A fill that names its plan leg carries it and says so in its label, so
# a redeploy buy can be told from an entry; a fill without one is as before.
def test_a_redeploy_fill_carries_its_kind(tmp_path):
    store = _store(tmp_path)
    history = _history(
        tmp_path,
        fills=[
            {
                "date": MON.isoformat(),
                "side": "buy",
                "qty": 7,
                "price": 91.0,
                "kind": "redeploy",
            },
            {"date": TUE.isoformat(), "side": "buy", "qty": 3, "price": 90, "kind": 7},
        ],
    )
    out = chart.payload(store, tmp_path, "AAPL", 10, history)
    assert out["fills"][0]["kind"] == "redeploy"
    assert out["fills"][0]["label"] == "Filled buy 7 @ 91.00 (redeploy)"
    assert "kind" not in out["fills"][1]
    assert out["fills"][1]["label"] == "Filled buy 3 @ 90.00"


# When the history is not handed in, it is read from <root>/history.
def test_payload_reads_the_history_file_from_the_root(tmp_path):
    store = _store(tmp_path)
    _history(tmp_path)
    out = chart.payload(store, tmp_path, "AAPL", 10, None)
    assert [d["label"] for d in out["decisions"]] == [
        "Buy 14% decided at the close",
        "Sell decided at the close",
    ]
    assert chart.read_history(tmp_path, "MSFT") is None


# A session absent from the store is reported, and a decision whose fill
# would land on the missing session is not moved onto the session after.
def test_a_missing_session_is_reported_and_no_fill_is_moved_across_it(tmp_path):
    store = _store(tmp_path, days=(EARLY, MON, WED))
    history = _history(tmp_path)
    out = chart.payload(store, tmp_path, "AAPL", 10, history)
    assert out["sessions"] == 3
    assert out["data_status"] == "incomplete"
    assert out["missing_sessions"] == [TUE.isoformat()]
    assert "1 exchange sessions" in out["data_reason"]
    # The buy still fills Monday (adjacent); the Monday sell's fill falls on
    # the missing Tuesday and is left out rather than drawn on Wednesday.
    assert [f["label"] for f in out["fills_at"]] == ["Buy 14% fills at the open"]
    # The Tuesday fill has no bars to sit on and is left out.
    assert [f["date"] for f in out["fills"]] == [MON.isoformat()]


# An incomplete partition is not drawn: the newest complete sessions are.
def test_incomplete_sessions_are_skipped(tmp_path):
    store = _store(tmp_path, days=(MON, TUE))
    sip.write_session(store, "AAPL", WED, _bars(WED, count=9), PROVENANCE)
    out = chart.payload(store, tmp_path, "AAPL", 2, None)
    assert {b["date"] for b in out["bars"]} == {MON.isoformat(), TUE.isoformat()}


# A name with no partition at all is None, the daily chart's "no history".
def test_a_name_with_no_partitions_is_none(tmp_path):
    store = _store(tmp_path)
    assert chart.payload(store, tmp_path, "MSFT", 10, None) is None
    assert (
        chart.payload(MarketStore(tmp_path / "empty"), tmp_path, "AAPL", 10, None)
        is None
    )


# The VWAP restarts each session and weights closes by volume.
def test_session_vwap_restarts_each_session():
    a = IntradayBar(datetime(2025, 12, 1, 14, 30, tzinfo=UTC), 1, 1, 1, 10.0, 100.0)
    b = IntradayBar(datetime(2025, 12, 1, 14, 45, tzinfo=UTC), 1, 1, 1, 20.0, 300.0)
    c = IntradayBar(datetime(2025, 12, 2, 14, 30, tzinfo=UTC), 1, 1, 1, 5.0, 0.0)
    out = chart._session_vwap([(MON, [a, b], None), (TUE, [c], None)])
    assert out == [10.0, 17.5, None]


# The route answers 15m with the intraday payload, clamps `sessions`, and
# 404s a name with no partitions; the daily path is unchanged. Driven with
# asyncio.run so it needs no async pytest plugin; skipped without fastapi.
def test_chart_route_serves_15m(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from backend.api.v1 import market
    from backend.config.settings import settings
    from backend.core.auth import issue_user_token
    from backend.main import app

    _store(tmp_path)
    _history(tmp_path)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "chart_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(market, "_live_snapshot", lambda: {})
    auth = {"Authorization": f"Bearer {issue_user_token('chart_user')}"}

    # Exercise the three answers of the route over one client.
    async def drive():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=auth
        ) as client:
            good = await client.get(
                "/api/v1/market/chart_user/desk/chart/AAPL",
                params={"timeframe": "15m", "sessions": 500},
            )
            missing = await client.get(
                "/api/v1/market/chart_user/desk/chart/MSFT",
                params={"timeframe": "15m"},
            )
            bad = await client.get(
                "/api/v1/market/chart_user/desk/chart/AAPL",
                params={"timeframe": "hourly"},
            )
            return good, missing, bad

    good, missing, bad = asyncio.run(drive())
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["timeframe"] == "15m"
    assert body["sessions"] == 3
    assert body["sessions_requested"] == 60
    assert body["decisions"][0]["label"] == "Buy 14% decided at the close"
    assert body["fills"][0]["label"] == "Filled buy 63 @ 224.81"
    assert missing.status_code == 404
    assert bad.status_code == 400
    assert "15m" in bad.json()["detail"]
