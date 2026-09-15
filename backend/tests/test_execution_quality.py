"""Execution quality as a series from the paper journal.

What has to hold: a buy filled above its reference is a positive cost and
a sell filled above its reference a negative one; the aggregate is
notional-weighted; FOMC fills are told apart from rebalance fills by the
event id; a fill without a reference is left out; the series runs by
session with a cumulative dollar figure.
"""

from backend.agents.trading.desk import paper
from backend.market import execution_quality as eq


def _row(session, symbol, side, qty, fill, reference, event=None):
    return {
        "session": session,
        "symbol": symbol,
        "side": side,
        "filled_qty": qty,
        "filled_price": fill,
        "event_id": event,
        "execution": {
            "reference_price": reference,
            "reference_source": "daily panel close",
        },
    }


def _state(rows):
    state = paper.PaperState()
    state.journal = rows
    return state


def test_signs_weights_and_kinds():
    rows = eq.fill_rows(
        _state(
            [
                _row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0),  # paid up: +100 bp
                _row("2026-09-10", "AMD", "sell", 10, 101.0, 100.0),  # sold up: -100 bp
                _row("2026-09-14", "SMCI", "sell", 100, 9.9, 10.0, "fomc:2026-09-16"),
                _row("2026-09-14", "NONE", "buy", 5, 10.0, None),
            ]
        )
    )
    assert [r["symbol"] for r in rows] == ["AMD", "NVDA", "SMCI"]
    by = {r["symbol"]: r for r in rows}
    assert abs(by["NVDA"]["bps"] - 100.0) < 1e-9
    assert abs(by["NVDA"]["dollars"] - 10.0) < 1e-9
    assert abs(by["AMD"]["bps"] + 100.0) < 1e-9
    assert by["SMCI"]["kind"] == "fomc"
    assert abs(by["SMCI"]["bps"] - 100.0) < 1e-9  # sold 1% below the decision price
    agg = eq.aggregate(rows)
    assert agg["fills"] == 3
    assert abs(agg["notional"] - 3000.0) < 1e-9
    assert abs(agg["dollars"] - (10.0 - 10.0 + 10.0)) < 1e-9
    assert abs(agg["bps"] - 10.0 / 3000.0 * 1e4) < 1e-9


def test_report_series_and_kinds():
    block = eq.report(
        _state(
            [
                _row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0),
                _row("2026-09-14", "SMCI", "sell", 100, 9.9, 10.0, "fomc:2026-09-16"),
            ]
        )
    )
    assert [s["session"] for s in block["series"]] == ["2026-09-10", "2026-09-14"]
    assert abs(block["series"][-1]["cumulative_dollars"] - 20.0) < 1e-9
    assert block["by_kind"]["fomc"]["fills"] == 1
    assert block["by_kind"]["rebalance"]["fills"] == 1
    assert block["by_side"]["sell"]["fills"] == 1
    assert block["worst"][0]["symbol"] in ("NVDA", "SMCI")
    assert eq.report(_state([]))["all_time"]["bps"] is None


def test_write_and_load_round_trip(tmp_path, capsys):
    root = tmp_path
    paper.save_state(
        root, _state([_row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0)])
    )
    block = eq.write(root)
    assert block is not None
    assert "1 fills, +100.0 bp" in capsys.readouterr().out
    assert eq.load(root)["all_time"]["fills"] == 1


# Opposite-signed fills net toward zero; the absolute figure keeps their size.
def test_aggregate_keeps_the_absolute_distance_beside_the_net():
    rows = eq.fill_rows(
        _state(
            [
                _row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0),  # +100 bp
                _row("2026-09-10", "AMD", "buy", 10, 99.0, 100.0),  # -100 bp
            ]
        )
    )
    agg = eq.aggregate(rows)
    assert abs(agg["bps"]) < 1e-9
    assert abs(agg["abs_bps"] - 100.0) < 1e-9
