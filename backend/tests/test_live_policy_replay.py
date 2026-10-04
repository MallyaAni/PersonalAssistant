"""Chronological actual-policy journeys, not a copied account or planning engine."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import calendar, entry_timing
from backend.market.live_execution_inputs import prepare
from backend.market.live_policy_replay import (
    corporate_actions,
    instant,
    run_account,
    run_benchmark,
    valuation,
)
from backend.market.live_probability_timing import build_reader
from backend.market.panel import Panel
from backend.market.replay_broker import ReplayBroker
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


# Apply a separate share grant exactly once while the archive factor stays price-only.
def test_separated_share_split_dispatch_preserves_basis_and_idempotence():
    _, raw, _ = fixture()
    actions = dict(raw.actions)
    actions["AAA"] = (
        {"date": str(raw.dates[1]), "kind": "archive_adjustment", "value": 2},
        {"date": str(raw.dates[1]), "kind": "share_split", "value": 2},
    )
    raw = replace(raw, actions=actions)
    broker = ReplayBroker(
        1000, 0, initial_holdings={"AAA": 10}, initial_average_prices={"AAA": 60}
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {name: 100 for name in raw.tickers}, True)
    corporate_actions(broker, raw, 1, opening)
    corporate_actions(broker, raw, 1, opening)
    assert broker.ledger()["holdings"] == {"AAA": 20}
    assert broker.positions()[0].avg_entry_price == 30
    assert broker.ledger()["cash"] == 1000


# Exchange shares in the actual dispatcher while retaining issuer and rounding receipts.
def test_named_exchange_journey_grants_no_fractional_stock_or_cash():
    _, raw, _ = fixture()
    actions = dict(raw.actions)
    actions["AAA"] = (
        {
            "date": str(raw.dates[1]),
            "kind": "security_exchange",
            "numerator": 1,
            "denominator": 5,
            "old_security_id": "old-common",
            "new_security_id": "new-common",
            "fractional_policy": "floor_no_compensation",
        },
    )
    broker = ReplayBroker(
        1000, 0, initial_holdings={"AAA": 24}, initial_average_prices={"AAA": 8}
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {name: 100 for name in raw.tickers}, True)
    corporate_actions(broker, replace(raw, actions=actions), 1, opening)
    assert broker.ledger()["holdings"] == {"AAA": 4}
    assert broker.ledger()["cash"] == 1000
    assert valuation(broker, raw, 1)["nav"] == 1400
    assert broker.ledger()["security_exchanges"][0]["forfeited_fraction"] == 0.8


# An unsupported entitlement rejects the whole due batch before any share mutation.
def test_unresolved_entitlement_cannot_silently_disappear_from_execution():
    _, raw, _ = fixture()
    actions = dict(raw.actions)
    actions["AAA"] = (
        {"date": str(raw.dates[1]), "kind": "share_split", "value": 2},
        {"date": str(raw.dates[1]), "kind": "unresolved_entitlement"},
    )
    broker = ReplayBroker(
        1000, 0, initial_holdings={"AAA": 10}, initial_average_prices={"AAA": 60}
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {name: 100 for name in raw.tickers}, True)
    with pytest.raises(ValueError, match="Unsupported economic"):
        corporate_actions(broker, replace(raw, actions=actions), 1, opening)
    assert broker.ledger()["holdings"] == {"AAA": 10}


# Separate a supplied archive price factor from actual child shares in the ledger.
@pytest.mark.parametrize("quantity", [99, 100])
def test_stock_distribution_journey_preserves_parent_and_missing_cash(quantity):
    _, raw, _ = fixture()
    actions = dict(raw.actions)
    actions["AAA"] = (
        {"date": str(raw.dates[1]), "kind": "archive_adjustment", "value": 1.323},
        {
            "date": str(raw.dates[1]),
            "kind": "stock_distribution",
            "child": "SPY",
            "numerator": 1,
            "denominator": 3,
            "parent_basis_fraction": 0.75,
        },
    )
    raw = replace(raw, actions=actions)
    broker = ReplayBroker(
        1000,
        0,
        initial_holdings={"AAA": quantity},
        initial_average_prices={"AAA": 60},
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {name: 100 for name in raw.tickers}, True)
    corporate_actions(broker, raw, 1, opening)
    assert broker.ledger()["holdings"] == {"AAA": quantity, "SPY": 33}
    assert broker.ledger()["cash"] == 1000
    result = valuation(broker, raw, 1)
    if quantity == 99:
        assert result["nav"] == 14200
        assert result["status"] == "marked_raw_close"
    else:
        assert result["nav"] is None
        assert result["status"] == "unknown_distribution_cash_in_lieu"
        assert len(result["unpriced_entitlements"]) == 1
        broker.settle_distribution_cash("AAA", "SPY", opening, 7, opening)
        assert valuation(broker, raw, 1)["nav"] == 14307


# Child splits precede post-split distributions regardless of source symbol order.
def test_distribution_does_not_split_new_child_shares_again():
    _, raw, _ = fixture()
    actions = dict(raw.actions)
    actions["AAA"] = (
        {
            "date": str(raw.dates[1]),
            "kind": "stock_distribution",
            "child": "SPY",
            "numerator": 1,
            "denominator": 3,
            "parent_basis_fraction": 0.75,
        },
    )
    actions["SPY"] = (
        {
            "date": str(raw.dates[1]),
            "kind": "split",
            "value": 2,
        },
    )
    raw = replace(raw, actions=actions)
    broker = ReplayBroker(
        0,
        0,
        initial_holdings={"AAA": 99, "SPY": 2},
        initial_average_prices={"AAA": 60, "SPY": 10},
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {name: 100 for name in raw.tickers}, True)
    corporate_actions(broker, raw, 1, opening)
    assert broker.ledger()["holdings"] == {"AAA": 99, "SPY": 37}
    assert broker.ledger()["average_prices"]["SPY"] == pytest.approx(1505 / 37)


# Exercise the original study's first night through the actual historical planner.
@pytest.mark.parametrize(
    "days",
    [
        ("2018-01-31", "2018-02-01", "2018-02-02"),
        ("2018-11-21", "2018-11-23", "2018-11-26"),
    ],
)
def test_actual_policy_first_2018_night_uses_reviewed_calendar(tmp_path, days):
    panel, raw, cubes = fixture(days)
    result = run_account(panel, raw, cubes, tmp_path / "historical", 1, 2, 10)
    assert [row["session"] for row in result["sessions"]] == list(days)
    assert all(row["nightly"]["status"] == "planned" for row in result["sessions"])
    assert paper.state_path(tmp_path / "historical").is_file()


# Match whole-share ETF funding, actual fees and retained uninvested cash.
@pytest.mark.parametrize("symbol", ["SPY", "QQQ"])
def test_benchmark_matches_raw_whole_share_capital_and_cost(tmp_path, symbol):
    panel, raw, _ = fixture()
    result = run_benchmark(panel, raw, tmp_path / symbol, 1, 2, 10, symbol)
    assert result["entry"]["status"] == "filled_opening_proxy"
    assert result["fills"][0]["filled_qty"] == 999
    assert result["fills"][0]["fee"] == pytest.approx(99.9)
    assert result["broker"]["cash"] == pytest.approx(0.1)
    assert result["broker"]["holdings"] == {symbol: 999}
    assert result["sessions"][-1]["nav"] == pytest.approx(99900.1)
    assert len(result["attempts"]) == len(result["fills"]) == 1


# Preserve a dated share entitlement rather than realizing a false split loss.
def test_benchmark_retains_split_entitlement_and_basis(tmp_path):
    panel, raw, _ = fixture()
    close, opening = raw.daily_close.copy(), raw.session_open.copy()
    close[2, 1] = opening[2, 1] = 50.0
    actions = dict(raw.actions)
    actions["SPY"] = ({"date": "2026-09-03", "kind": "split", "value": 2.0},)
    changed = replace(raw, daily_close=close, session_open=opening, actions=actions)
    result = run_benchmark(panel, changed, tmp_path / "split", 1, 2, 10, "SPY")
    assert result["broker"]["holdings"] == {"SPY": 1998.0}
    assert result["broker"]["average_prices"] == {"SPY": 50.0}
    assert result["sessions"][-1]["nav"] == pytest.approx(99900.1)
    assert len(result["fills"]) == 1


# Keep unknown-payment ETF dividends as wealth without financing another purchase.
def test_benchmark_dividend_is_receivable_not_reinvested_cash(tmp_path):
    panel, raw, _ = fixture()
    actions = dict(raw.actions)
    actions["SPY"] = ({"date": "2026-09-03", "kind": "dividend", "value": 0.5},)
    result = run_benchmark(
        panel, replace(raw, actions=actions), tmp_path / "dividend", 1, 2, 10, "SPY"
    )
    assert result["sessions"][-1]["dividend_receivable"] == 499.5
    assert result["sessions"][-1]["nav"] == pytest.approx(100399.6)
    assert result["broker"]["cash"] == pytest.approx(0.1)
    assert result["broker"]["holdings"] == {"SPY": 999}
    assert len(result["fills"]) == 1


# Preserve unavailable benchmark entry and held marks without synthetic prices.
def test_benchmark_missing_entry_and_missing_held_mark_are_explicit(tmp_path):
    panel, raw, _ = fixture()
    opening = raw.session_open.copy()
    opening[1, 1] = np.nan
    missing = run_benchmark(
        panel,
        replace(raw, session_open=opening),
        tmp_path / "entry_gap",
        1,
        2,
        10,
        "SPY",
    )
    assert missing["entry"]["status"] == "opening_price_unavailable"
    assert not missing["attempts"]
    assert not missing["fills"]
    assert missing["broker"]["cash"] == 100000
    close = raw.daily_close.copy()
    close[2, 1] = np.nan
    held = run_benchmark(
        panel, replace(raw, daily_close=close), tmp_path / "held_gap", 1, 2, 10, "SPY"
    )
    assert held["sessions"][-1]["nav"] is None
    assert held["sessions"][-1]["status"] == "missing_held_close"
    assert held["broker"]["holdings"] == {"SPY": 999}


# Mark a carried benchmark at the actual early close without inventing intraday bars.
def test_benchmark_uses_actual_early_close_calendar(tmp_path):
    panel, raw, _ = fixture(dates=("2026-11-24", "2026-11-25", "2026-11-27"))
    result = run_benchmark(panel, raw, tmp_path / "early", 1, 2, 0, "SPY")
    observed = datetime.fromisoformat(result["broker"]["observed_at"])
    assert observed.astimezone(calendar.NEW_YORK).strftime("%H:%M") == "13:00"
    assert result["sessions"][-1]["nav"] == 100000


# Refuse an undeclared stock control before allocating a private account folder.
def test_benchmark_rejects_non_benchmark_symbol(tmp_path):
    panel, raw, _ = fixture()
    with pytest.raises(ValueError, match="SPY or QQQ"):
        run_benchmark(panel, raw, tmp_path / "invalid", 1, 2, 0, "AAA")
    assert not (tmp_path / "invalid").exists()


# Verify private state reuse changes neither complete observations nor saved outcomes.
def test_unchanged_state_reuse_matches_original_reader_paths(tmp_path, monkeypatch):
    panel, raw, cubes = fixture()
    started = datetime.now(UTC) - timedelta(seconds=1)
    original_reader = paper.load_state
    counts = []
    reads = 0

    # Count actual state reads while preserving the original parser and contents.
    def counted(root):
        nonlocal reads
        reads += 1
        return original_reader(root)

    monkeypatch.setattr(paper, "load_state", counted)
    old = run_account(
        panel, raw, cubes, tmp_path / "old", 1, 2, 10, reuse_unchanged_state=False
    )
    counts.append(reads)
    reads = 0
    new = run_account(panel, raw, cubes, tmp_path / "new", 1, 2, 10)
    counts.append(reads)
    ended = datetime.now(UTC)
    for result in (old, new):
        for row in result["paper_state"]["history"]:
            assert started <= datetime.fromisoformat(row.pop("written")) <= ended
    for name in (
        "sessions",
        "intents",
        "observations",
        "fills",
        "attempts",
        "broker",
        "paper_state",
    ):
        assert old[name] == new[name]
    assert counts[1] < counts[0] / 2


# Catch atomic replacements before reusing the next observation's pending rows.
def test_state_cache_invalidates_on_actual_atomic_save(tmp_path):
    from backend.market.live_policy_replay import read_private_state

    root = tmp_path / "state"
    paper.save_state(root, paper.PaperState(deferred_buys={"AAA": 3}))
    before, revision = read_private_state(root, None, None)
    assert before.deferred_buys == {"AAA": 3}
    paper.save_state(root, paper.PaperState(deferred_buys={"AAA": 7}))
    after, next_revision = read_private_state(root, before, revision)
    assert after.deferred_buys == {"AAA": 7}
    assert before.deferred_buys == {"AAA": 3}
    assert next_revision != revision


# Keep callback mutation and input errors outside the account's persistent state.
def test_session_progress_is_detached_and_invalid_callback_is_rejected(tmp_path):
    panel, raw, cubes = fixture()
    seen = []

    # Mutate the callback's copy to prove it cannot rewrite the account result.
    def progress(row):
        seen.append(row["session"])
        row["nav"] = 999999999
        row["holdings"]["invented"] = 3

    result = run_account(
        panel, raw, cubes, tmp_path / "progress", 1, 2, 10, on_session=progress
    )
    assert seen == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert result["sessions"][-1]["nav"] == 100225.25
    assert "invented" not in result["broker"]["holdings"]
    with pytest.raises(ValueError, match="callable progress"):
        run_account(
            panel,
            raw,
            cubes,
            tmp_path / "invalid_progress",
            1,
            2,
            10,
            on_session="invalid",
        )
    assert not (tmp_path / "invalid_progress").exists()


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
