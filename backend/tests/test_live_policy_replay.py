"""Chronological actual-policy journeys, not a copied account or planning engine."""

from datetime import datetime

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import calendar, entry_timing
from backend.market.live_execution_inputs import prepare
from backend.market.live_policy_replay import run_account
from backend.market.live_probability_timing import build_reader
from backend.market.panel import Panel
from backend.market.sip_cube import SessionCube


# Supply a complete original panel and original raw cubes for actual desk paths.
def fixture(dates=("2026-09-01", "2026-09-02", "2026-09-03"), missing_fill=False):
    dates = np.array(dates, dtype="datetime64[D]")
    names = ("AAA", "SPY", "QQQ")
    prices = np.full((len(dates), 3), 100.0)
    panel = Panel(
        dates,
        names,
        prices.copy(),
        prices + 2,
        prices - 3,
        prices.copy(),
        prices.copy(),
        np.ones_like(prices),
        {},
        "SPY",
    )
    cubes = {}
    for name in names:
        cube_days = np.array(
            [
                day
                for day in dates
                if calendar.session_close(day.astype(object)) == calendar.REGULAR_CLOSE
            ]
        )
        opening = np.full((len(cube_days), 26), 100.0)
        close = opening.copy()
        if name == "AAA":
            close[:, 0] = 98.0
            opening[:, 1] = np.nan if missing_fill else 99.0
            opening[:, 25] = 101.0
        cubes[name] = SessionCube(
            name,
            cube_days,
            opening,
            np.full_like(opening, 102),
            np.full_like(opening, 97),
            close,
            np.ones_like(opening),
            np.full(len(cube_days), 100.0),
            {"early_close": len(dates) - len(cube_days)},
            np.full(len(cube_days), 100.0),
            np.ones(len(cube_days)),
        )
    grades = np.tile([3, 0, 3], (len(dates), 1)).astype(np.int16)
    eligible = np.tile([True, False, False], (len(dates), 1))
    raw = prepare(
        panel,
        grades,
        eligible,
        cubes,
        dict.fromkeys(names, ()),
        basis_as_of=str(dates[-1]),
        complete_through=str(dates[-1]),
        provenance={"origin": "synthetic_actual_path"},
    )
    return panel, raw, cubes


# Preserve explicit unavailable forecasts rather than introducing a fixed gate.
def unavailable(day, clock, stock):
    return None


# The real nightly creates a whole-share intent, sender waits for the real trigger,
# and reconciliation writes the actual proxy fill without an environment broker.
def test_rule_runs_actual_plan_sender_fill_and_reconciliation(tmp_path, monkeypatch):
    from backend.market import alpaca_trading

    # Make any accidental construction of the real broker a test failure.
    def forbidden():
        raise AssertionError("Attempted real broker")

    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    panel, raw, cubes = fixture()
    root = tmp_path / "private"
    result = run_account(panel, raw, cubes, root, 1, 1, 10)
    assert result["intents"][0]["qty"] == 250
    assert result["attempts"][0]["observed_price"] == 98
    assert result["fills"][0]["price"] == 99
    assert result["fills"][0]["filled_qty"] == 250
    assert result["fills"][0]["fee"] == pytest.approx(24.75)
    assert result["sessions"][-1]["nav"] == pytest.approx(100225.25)
    assert result["sessions"][-1]["cash"] == pytest.approx(75225.25)
    assert result["broker"]["holdings"] == {"AAA": 250}
    assert "QQQ" not in result["broker"]["holdings"]
    assert result["nightlies"][-1]["entry"]["settled"][0]["filled_price"] == 99
    assert paper.load_state(root).policy_version == "graded-equal-weight/5"
    latch = entry_timing.load(root, raw.dates[1].astype(object))
    assert latch is not None
    assert latch["symbols"]["AAA"]["buy_trigger"]["price"] == 98
    assert result["adoption_eligible"] is False


# Missing forecasts wait to the actual terminal clock while original shares persist.
def test_candidate_waits_without_one_percent_fallback_then_shared_final(tmp_path):
    panel, raw, cubes = fixture()
    result = run_account(
        panel,
        raw,
        cubes,
        tmp_path / "candidate",
        1,
        1,
        10,
        reader_builder=build_reader,
        provider=unavailable,
    )
    assert len(result["forecast_decisions"]) == 24
    assert all(row["state"] == "unavailable" for row in result["forecast_decisions"])
    assert len(result["attempts"]) == 1
    attempted = datetime.fromisoformat(result["attempts"][0]["at"]).astimezone(
        calendar.NEW_YORK
    )
    assert (attempted.hour, attempted.minute) == (15, 45)
    assert result["fills"][0]["price"] == 101
    assert result["fills"][0]["requested_qty"] == 250
    assert result["sessions"][-1]["nav"] == pytest.approx(99724.75)


# An accepted request with no next-open price remains a missed terminal attempt.
def test_missing_consecutive_open_is_not_replaced_by_close(tmp_path):
    panel, raw, cubes = fixture(missing_fill=True)
    result = run_account(panel, raw, cubes, tmp_path / "missing", 1, 1, 10)
    assert result["fills"][0]["filled_qty"] == 0
    assert result["fills"][0]["price"] is None
    assert result["fills"][0]["reason"] == "missing_execution_price"
    assert result["broker"]["holdings"] == {}
    assert result["sessions"][-1]["nav"] == 100000
    assert len(result["intents"]) >= 1


# Early-close dates remain unavailable but use their actual shortened sender clock.
def test_early_close_keeps_missing_opportunity_and_actual_clock(tmp_path):
    panel, raw, cubes = fixture(("2026-11-25", "2026-11-27", "2026-11-30"))
    result = run_account(panel, raw, cubes, tmp_path / "early", 1, 1, 10)
    assert len(result["observations"]) == 13
    assert max(row["clock"] for row in result["observations"]) == 12
    assert all(row["supported_full_session"] is False for row in result["observations"])
    assert result["broker"]["holdings"] == {}
    assert result["sessions"][-1]["nav"] == 100000
    assert result["intents"][0]["execute_on"] == "2026-11-27"


# An already populated state directory cannot be replayed or overwritten silently.
def test_reused_account_root_refused_before_writes(tmp_path):
    panel, raw, cubes = fixture()
    root = tmp_path / "old"
    root.mkdir()
    marker = root / "keep"
    marker.write_text("original")
    with pytest.raises(ValueError, match="new private account folder"):
        run_account(panel, raw, cubes, root, 1, 1, 10)
    assert marker.read_text() == "original"
    assert not paper.state_path(root).exists()


# Provider and reader must be supplied together, never an ambiguous partial override.
@pytest.mark.parametrize("builder", [None, build_reader])
def test_incomplete_forecast_contract_refused(tmp_path, builder):
    panel, raw, cubes = fixture()
    provider = unavailable if builder is None else None
    with pytest.raises(ValueError, match="Both explicit"):
        run_account(
            panel,
            raw,
            cubes,
            tmp_path / "bad",
            1,
            1,
            10,
            reader_builder=builder,
            provider=provider,
        )
    assert not (tmp_path / "bad").exists()
