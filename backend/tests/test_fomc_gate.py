"""The FOMC gate: the overlay priced against the book that never traded it.

What has to hold: a sale before a rise costs the overlay exactly the shares
times the move, and a sale before a fall earns it; restoration buys close
the difference into a realised round trip; the cost column charges the
traded notional; fewer completed meetings than required leaves the gate
waiting; the verdict follows the pre-registered rule.
"""

from backend.agents.trading.desk import paper
from backend.market import fomc_gate as fg


def _close(marks: dict[str, dict[str, float]]):
    return lambda symbol, session: marks.get(symbol, {}).get(session)


def _fill(
    session, symbol, side, qty, price, event="fomc-3-session-weakness/2:2026-09-16"
):
    return {
        "session": session,
        "symbol": symbol,
        "side": side,
        "filled_qty": qty,
        "filled_price": price,
        "event_id": event,
    }


def _state(fills, active_id=None, history=None):
    state = paper.PaperState()
    state.journal = list(fills)
    state.event_cycle = {"id": active_id} if active_id else {}
    state.history = history or []
    return state


def test_a_sale_before_a_rise_costs_the_overlay_the_move():
    fills = [_fill("2026-09-14", "NVDA", "sell", 10, 200.0)]
    marks = {"NVDA": {"2026-09-14": 200.0, "2026-09-15": 210.0}}
    assert fg.overlay_difference(fills, "2026-09-14", _close(marks)) == 0.0
    assert fg.overlay_difference(fills, "2026-09-15", _close(marks)) == -100.0
    falling = {"NVDA": {"2026-09-15": 180.0}}
    assert fg.overlay_difference(fills, "2026-09-15", _close(falling)) == 200.0


def test_restoration_closes_the_difference_into_a_round_trip():
    fills = [
        _fill("2026-09-14", "NVDA", "sell", 10, 200.0),
        _fill("2026-09-17", "NVDA", "buy", 10, 210.0),
    ]
    marks = {"NVDA": {"2026-09-17": 215.0, "2026-09-18": 230.0}}
    # Sold at 200, bought back at 210: the overlay lost 100 whatever happens later.
    assert fg.overlay_difference(fills, "2026-09-17", _close(marks)) == -100.0
    assert fg.overlay_difference(fills, "2026-09-18", _close(marks)) == -100.0


def test_meeting_row_reports_effect_costs_and_drawdowns():
    fills = [
        _fill("2026-09-14", "NVDA", "sell", 10, 200.0),
        _fill("2026-09-17", "NVDA", "buy", 10, 180.0),
    ]
    history = [
        {"session": "2026-09-11", "equity": 100_000.0},
        {"session": "2026-09-14", "equity": 100_000.0},
        {"session": "2026-09-15", "equity": 99_000.0},
        {"session": "2026-09-16", "equity": 98_500.0},
        {"session": "2026-09-17", "equity": 99_200.0},
    ]
    marks = {
        "NVDA": {
            "2026-09-11": 200.0,
            "2026-09-14": 200.0,
            "2026-09-15": 190.0,
            "2026-09-16": 185.0,
            "2026-09-17": 180.0,
        }
    }
    cycle = fg.cycles(_state(fills))[0]
    row = fg.meeting_row(cycle, history, _close(marks))
    assert row["complete"]
    assert row["status"] == "restored"
    assert row["window"] == ["2026-09-11", "2026-09-17"]
    assert row["effect"] == 200.0  # sold 10 at 200, bought back at 180
    assert row["traded_notional"] == 10 * 200.0 + 10 * 180.0
    assert abs(row["effect_after_costs"] - (200.0 - 3800.0 * 25 / 10_000)) < 1e-9
    # Without the overlay the book fell further on the way down.
    assert row["drawdown_without"] < row["drawdown_live"]


def test_the_gate_waits_for_enough_meetings_then_applies_its_rule():
    complete = {
        "complete": True,
        "effect_after_costs": 50.0,
        "effect_after_costs_pct": 0.0005,
        "drawdown_live": -0.02,
        "drawdown_without": -0.03,
    }
    assert fg.verdict([complete] * 5)["standing"] == "waiting"
    assert fg.verdict([complete] * 6)["standing"] == "keep"
    losing = {**complete, "effect_after_costs": -50.0}
    assert fg.verdict([losing] * 6)["standing"] == "retire"
    deeper = {**complete, "drawdown_live": -0.05, "drawdown_without": -0.01}
    assert fg.verdict([deeper] * 4 + [complete] * 2)["standing"] == "retire"
    assert fg.verdict([{"complete": False}] * 8)["standing"] == "waiting"


def test_cycles_before_the_first_meeting_are_ignored_and_the_active_one_is_marked():
    fills = [
        _fill(
            "2026-07-24",
            "AMD",
            "sell",
            1,
            100.0,
            "fomc-3-session-weakness/2:2026-07-29",
        ),
        _fill("2026-09-14", "AMD", "sell", 1, 100.0),
    ]
    found = fg.cycles(_state(fills, active_id="fomc-3-session-weakness/2:2026-09-16"))
    assert [c["decision_date"] for c in found] == ["2026-09-16"]
    assert found[0]["active"] is True


# A cycle that ended with shares unbought is shown but never counted: its
# effect would keep moving with those shares, so it cannot close a meeting.
def test_a_cycle_ended_unrestored_is_reported_but_not_complete():
    fills = [
        _fill("2026-09-14", "NVDA", "sell", 10, 200.0),
        _fill("2026-09-17", "NVDA", "buy", 4, 190.0),
    ]
    history = [
        {"session": "2026-09-11", "equity": 100_000.0},
        {"session": "2026-09-14", "equity": 100_000.0},
        {"session": "2026-09-17", "equity": 99_500.0},
    ]
    marks = {"NVDA": {"2026-09-11": 200.0, "2026-09-14": 200.0, "2026-09-17": 190.0}}
    cycle = fg.cycles(_state(fills))[0]  # no active cycle: the policy released it
    row = fg.meeting_row(cycle, history, _close(marks))
    assert row["complete"] is False
    assert row["status"] == "ended unrestored: NVDA 6"
    assert row["unrestored"] == {"NVDA": 6}
    assert fg.verdict([row] * 6)["completed_meetings"] == 0
    assert fg.unrestored(fills) == {"NVDA": 6}
    assert fg.unrestored(fills + [_fill("2026-09-18", "NVDA", "buy", 6, 195.0)]) == {}
