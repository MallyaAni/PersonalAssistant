"""Chronological actual-policy journeys, not a copied account or planning engine."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import calendar, entry_timing
from backend.market.live_execution_inputs import CUBE_BASIS, prepare, prepare_passive
from backend.market.live_policy_replay import (
    account_marks,
    corporate_actions,
    due_actions,
    instant,
    passive_marks,
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


# Supply inherited assets without expanding selection or the original execution cubes.
def passive_fixture(raw):
    return prepare_passive(
        raw.dates,
        raw.tickers,
        ("CHILD",),
        np.full((len(raw.dates), 1), 20.0),
        np.full((len(raw.dates), 26, 1), 21.0),
        np.full((len(raw.dates), 1), 22.0),
        first_session=str(raw.dates[0]),
        complete_through=str(raw.dates[-1]),
        provenance={"source": "synthetic_raw_child_prices"},
        price_basis=CUBE_BASIS,
    )


# Only the completed current slot or a separately declared opening proxy is observable.
@pytest.mark.parametrize(
    ("minute", "expected"),
    [(0, 20), (1, None), (15, 21), (16, None), (390, 21), (391, 22)],
)
def test_passive_marks_follow_actual_bar_and_daily_close_clock(minute, expected):
    _, raw, _ = fixture()
    raw = replace(raw, passive=passive_fixture(raw))
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    assert passive_marks(raw, 1, opening + timedelta(minutes=minute)) == {
        "CHILD": expected
    }


# Later bar values and final daily prices cannot change an earlier observed mark.
def test_passive_mark_is_future_prefix_invariant_and_keeps_missing_slot():
    _, raw, _ = fixture()
    original = passive_fixture(raw)
    bars = original.observation_close.copy()
    closing = original.daily_close.copy()
    bars[:, 1:] = 999
    closing[:] = 888
    changed = prepare_passive(
        raw.dates,
        raw.tickers,
        original.tickers,
        original.session_open,
        bars,
        closing,
        first_session=str(raw.dates[0]),
        complete_through=str(raw.dates[-1]),
        provenance={"source": "synthetic"},
        price_basis=CUBE_BASIS,
    )
    now = instant(raw.dates[1], calendar.REGULAR_OPEN) + timedelta(minutes=15)
    assert passive_marks(replace(raw, passive=original), 1, now) == {"CHILD": 21}
    assert passive_marks(replace(raw, passive=changed), 1, now) == {"CHILD": 21}
    bars[1, 0, 0] = np.nan
    missing = prepare_passive(
        raw.dates,
        raw.tickers,
        original.tickers,
        original.session_open,
        bars,
        closing,
        first_session=str(raw.dates[0]),
        complete_through=str(raw.dates[-1]),
        provenance={"source": "synthetic"},
        price_basis=CUBE_BASIS,
    )
    assert passive_marks(replace(raw, passive=missing), 1, now) == {"CHILD": None}


# A close-only inherited asset cannot use its final price in a morning account NAV.
def test_passive_daily_valuation_waits_for_close_and_preserves_held_security():
    _, raw, _ = fixture()
    raw = replace(raw, passive=passive_fixture(raw))
    broker = ReplayBroker(
        1000,
        0,
        initial_holdings={"AAA": 10, "CHILD": 2},
        initial_average_prices={"AAA": 60, "CHILD": 10},
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, account_marks(raw, 1, opening, raw.session_open[1]), True)
    assert broker.account().equity == 2040
    assert valuation(broker, raw, 1)["nav"] is None
    now = instant(raw.dates[1], calendar.REGULAR_CLOSE) + timedelta(minutes=1)
    broker.observe(now, account_marks(raw, 1, now, raw.daily_close[1]), False)
    assert valuation(broker, raw, 1)["nav"] == 2044
    assert broker.ledger()["holdings"] == {"AAA": 10, "CHILD": 2}


# Value inherited shares through the real planner without making them buy candidates.
def test_actual_policy_journey_retains_inherited_security_without_ordering_it(tmp_path):
    panel, raw, cubes = fixture()
    actions = dict(raw.actions)
    actions["AAA"] = (
        {
            "date": str(raw.dates[2]),
            "kind": "stock_distribution",
            "child": "CHILD",
            "numerator": 1,
            "denominator": 1,
            "parent_basis_fraction": 0.75,
        },
    )
    raw = replace(raw, actions=actions, passive=passive_fixture(raw))
    result = run_account(panel, raw, cubes, tmp_path / "passive", 1, 2, 10)
    assert result["broker"]["holdings"]["CHILD"] == 250
    assert all(row["symbol"] != "CHILD" for row in result["attempts"])
    assert all(row["symbol"] != "CHILD" for row in result["intents"])
    assert result["sessions"][-1]["nav"] == pytest.approx(105725.25)
    assert result["sessions"][-1]["nightly"]["status"] == "planned"
    assert "CHILD" not in result["paper_state"]["rebalance_targets"]
    assert all(row["symbol"] != "CHILD" for row in result["fills"])
    assert result["passive_valuation_source"]["tickers"] == ["CHILD"]
    assert (
        result["passive_valuation_source"]["arrays"]["daily_close"]
        == raw.passive.provenance["arrays"]["daily_close"]
    )


# The actual planner funds the same orders with known or unallocated distribution cost.
def test_actual_policy_orders_and_wealth_do_not_depend_on_tax_basis_guess(tmp_path):
    panel, raw, cubes = fixture()
    records = []
    for allocated in (True, False):
        actions = dict(raw.actions)
        grant = {
            "date": str(raw.dates[2]),
            "kind": "stock_distribution",
            "child": "CHILD",
            "numerator": 1,
            "denominator": 1,
            "parent_basis_fraction": 0.75 if allocated else None,
        }
        if not allocated:
            grant.update(
                basis_policy="unallocated_at_effective_clock",
                effective_at="2026-09-02T17:00:00-04:00",
            )
        actions["AAA"] = (grant,)
        records.append(
            run_account(
                panel,
                replace(raw, actions=actions, passive=passive_fixture(raw)),
                cubes,
                tmp_path / ("allocated" if allocated else "unknown-basis"),
                1,
                2,
                10,
            )
        )
    known, unknown = records
    for key in ("attempts", "intents", "fills"):
        assert known[key] == unknown[key]
    assert {
        key: value for key, value in known["paper_state"].items() if key != "history"
    } == {
        key: value for key, value in unknown["paper_state"].items() if key != "history"
    }
    for historical, unallocated in zip(
        known["paper_state"]["history"], unknown["paper_state"]["history"], strict=True
    ):
        assert {
            key: value
            for key, value in historical.items()
            if key not in ("written", "positions", "actions")
        } == {
            key: value
            for key, value in unallocated.items()
            if key not in ("written", "positions", "actions")
        }
        for a, b in zip(historical["positions"], unallocated["positions"], strict=True):
            assert {
                key: value
                for key, value in a.items()
                if key not in ("avg_entry_price", "unrealized_pl")
            } == {
                key: value
                for key, value in b.items()
                if key not in ("avg_entry_price", "unrealized_pl")
            }
        for a, b in zip(historical["actions"], unallocated["actions"], strict=True):
            assert {key: value for key, value in a.items() if key != "entry_price"} == {
                key: value for key, value in b.items() if key != "entry_price"
            }
    assert known["broker"]["cash"] == unknown["broker"]["cash"]
    assert known["broker"]["holdings"] == unknown["broker"]["holdings"]
    assert unknown["broker"]["holdings"]["CHILD"] == 250
    assert unknown["broker"]["average_prices"] == {"AAA": None, "CHILD": None}
    assert [row["nav"] for row in known["sessions"]] == [
        row["nav"] for row in unknown["sessions"]
    ]
    positions = unknown["paper_state"]["history"][-1]["positions"]
    assert all(
        row["avg_entry_price"] is None and row["unrealized_pl"] is None
        for row in positions
    )
    assert all(row["symbol"] != "CHILD" for row in unknown["attempts"])


# Observe overnight entitlements before their next regular price-adjustment date.
@pytest.mark.parametrize(
    "dates",
    [
        ("2026-09-01", "2026-09-02", "2026-09-03"),
        ("2026-11-25", "2026-11-27", "2026-11-30"),
    ],
)
def test_overnight_distribution_is_observed_once_on_actual_close_clock(dates):
    _, raw, _ = fixture(dates)
    closing = raw.daily_close.copy()
    closing[1, 1] = np.nan
    raw = replace(raw, daily_close=closing)
    effective = instant(
        raw.dates[1], calendar.session_close(raw.dates[1].astype(object))
    ) + timedelta(minutes=1)
    actions = dict(raw.actions)
    actions["AAA"] = (
        {
            "date": str(raw.dates[2]),
            "kind": "stock_distribution",
            "child": "SPY",
            "numerator": 1,
            "denominator": 5,
            "parent_basis_fraction": None,
            "basis_policy": "unallocated_at_effective_clock",
            "effective_at": effective.isoformat(),
        },
    )
    raw = replace(raw, actions=actions)
    broker = ReplayBroker(
        1000, 0, initial_holdings={"AAA": 100}, initial_average_prices={"AAA": 60}
    )
    before = effective - timedelta(seconds=1)
    broker.observe(before, {"AAA": 100, "SPY": None}, False)
    corporate_actions(broker, raw, 1, before)
    assert broker.ledger()["holdings"] == {"AAA": 100}
    broker.observe(effective, {"AAA": 100, "SPY": None}, False)
    corporate_actions(broker, raw, 1, effective)
    receipt = broker.ledger()["security_distributions"][0]
    assert broker.ledger()["holdings"] == {"AAA": 100, "SPY": 20}
    assert (
        receipt["effective_at"]
        == receipt["applied_at"]
        == effective.astimezone(UTC).isoformat()
    )
    assert broker.ledger()["cash"] == 1000
    assert valuation(broker, raw, 1)["nav"] is None
    opening = instant(raw.dates[2], calendar.REGULAR_OPEN)
    broker.observe(opening, {"AAA": 100, "SPY": 20}, True)
    corporate_actions(broker, raw, 2, opening)
    assert broker.ledger()["holdings"] == {"AAA": 100, "SPY": 20}
    assert broker.ledger()["security_distributions"] == [receipt]


# A real nightly skips unpriced inherited wealth rather than inventing a funded plan.
@pytest.mark.parametrize("effective_minutes", [1, 60])
def test_nightly_sees_only_effective_grants_without_future_child_marks(
    tmp_path, effective_minutes
):
    panel, raw, cubes = fixture()
    effective = instant(raw.dates[1], calendar.REGULAR_CLOSE) + timedelta(
        minutes=effective_minutes
    )
    actions = dict(raw.actions)
    actions["AAA"] = (
        {
            "date": str(raw.dates[2]),
            "kind": "stock_distribution",
            "child": "CHILD",
            "numerator": 1,
            "denominator": 1,
            "parent_basis_fraction": None,
            "basis_policy": "unallocated_at_effective_clock",
            "effective_at": effective.isoformat(),
        },
    )
    records = []
    for price in (20.0, 999.0):
        opening = np.full((len(raw.dates), 1), np.nan)
        closing = opening.copy()
        bars = np.full((len(raw.dates), 26, 1), np.nan)
        opening[2] = closing[2] = price
        bars[2] = price
        passive = prepare_passive(
            raw.dates,
            raw.tickers,
            ("CHILD",),
            opening,
            bars,
            closing,
            first_session=str(raw.dates[2]),
            complete_through=str(raw.dates[2]),
            provenance={"source": "synthetic_future_child_marks"},
            price_basis=CUBE_BASIS,
        )
        records.append(
            run_account(
                panel,
                replace(raw, actions=actions, passive=passive),
                cubes,
                tmp_path / str(price),
                1,
                2,
                10,
            )
        )
    assert records[0]["sessions"][1] == records[1]["sessions"][1]
    for result in records:
        first_night = result["sessions"][1]
        assert first_night["holdings"]["AAA"] == 250
        receipt = result["broker"]["security_distributions"][0]
        assert receipt["parent_qty"] == receipt["whole_qty"] == 250
        assert len(result["broker"]["security_distributions"]) == 1
        assert all(row["symbol"] != "CHILD" for row in result["attempts"])
        if effective_minutes == 1:
            assert first_night["holdings"]["CHILD"] == 250
            assert first_night["nav"] is None
            assert first_night["missing_symbols"] == ["CHILD"]
            assert first_night["nightly"]["status"] == "nightly_broker_unavailable"
            assert receipt["applied_at"] == effective.astimezone(UTC).isoformat()
        else:
            assert "CHILD" not in first_night["holdings"]
            assert first_night["nav"] is not None
            assert first_night["nightly"]["status"] == "planned"
            assert (
                receipt["applied_at"]
                == instant(raw.dates[2], calendar.REGULAR_OPEN)
                .astimezone(UTC)
                .isoformat()
            )


# Re-observing the same session cannot grant a split or accrue a dividend twice.
def test_overnight_dispatch_keeps_legacy_opening_action_identity():
    _, raw, _ = fixture()
    actions = dict(raw.actions)
    actions["AAA"] = (
        {"date": str(raw.dates[1]), "kind": "split", "value": 2},
        {"date": str(raw.dates[1]), "kind": "dividend", "value": 0.5},
    )
    raw = replace(raw, actions=actions)
    broker = ReplayBroker(
        1000, 0, initial_holdings={"AAA": 10}, initial_average_prices={"AAA": 60}
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {"AAA": 100}, True)
    corporate_actions(broker, raw, 1, opening)
    before = broker.ledger()
    now = instant(raw.dates[1], calendar.REGULAR_CLOSE) + timedelta(minutes=1)
    broker.observe(now, {"AAA": 100}, False)
    corporate_actions(broker, raw, 1, now)
    after = broker.ledger()
    assert before["holdings"] == after["holdings"] == {"AAA": 20}
    assert before["cash"] == after["cash"] == 1000
    assert before["dividends"] == after["dividends"]
    assert len(after["dividends"]) == 1
    assert after["dividends"][0]["amount"] == 10


# Ambiguous or unobserved clocks cannot authorize a corporate-action mutation.
def test_action_dispatch_requires_an_aware_actual_broker_observation():
    _, raw, _ = fixture()
    now = instant(raw.dates[1], calendar.REGULAR_OPEN)
    with pytest.raises(ValueError, match="Aware same-session"):
        due_actions(raw, 1, now.replace(tzinfo=None))
    with pytest.raises(ValueError, match="Aware same-session"):
        due_actions(raw, 1, now + timedelta(days=1))
    broker = ReplayBroker(1000, 0)
    broker.observe(now, {"AAA": 100}, True)
    before = broker.ledger()
    with pytest.raises(ValueError, match="actual observed broker clock"):
        corporate_actions(broker, raw, 1, now + timedelta(minutes=1))
    assert broker.ledger() == before


# Keep an inherited security priced only through its final declared trading session.
def terminal_fixture():
    panel, raw, cubes = fixture(
        ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")
    )
    opening = np.full((4, 1), np.nan)
    bars = np.full((4, 26, 1), np.nan)
    closing = opening.copy()
    opening[2], bars[2], closing[2] = 20, 21, 22
    passive = prepare_passive(
        raw.dates,
        raw.tickers,
        ("CHILD",),
        opening,
        bars,
        closing,
        first_session="2026-09-03",
        complete_through="2026-09-03",
        provenance={"source": "synthetic_final_inherited_session"},
        price_basis=CUBE_BASIS,
    )
    actions = dict(raw.actions)
    actions["AAA"] = (
        {
            "date": "2026-09-03",
            "kind": "stock_distribution",
            "child": "CHILD",
            "numerator": 1,
            "denominator": 1,
            "parent_basis_fraction": None,
            "basis_policy": "unallocated_at_effective_clock",
            "effective_at": "2026-09-02T17:00:00-04:00",
            "effective_source": "https://example.test/distribution",
            "fractional_source": "https://example.test/distribution",
            "fractional_policy": "cash_in_lieu_unknown",
            "share_basis": "post_split_action_date_shares",
            "source_receipt": {"scope": "synthetic_declaration"},
        },
    )
    terminal = {
        "date": "2026-09-04",
        "kind": "cash_merger",
        "value": 142.5,
        "old_security_id": "synthetic-child-common",
        "election_policy": "declared_no_election_default_cash",
        "completed_before": "2026-09-04T09:30:00-04:00",
        "legal_clock_precision": "completed_before_open_not_exact",
        "terms_available_at": "2026-09-03T16:01:00-04:00",
        "completion_available_at": "2026-09-04T08:30:00-04:00",
        "terms_source": "https://example.test/cash-default-terms",
        "completion_source": "https://example.test/merger-completion",
        "source_receipt": {"scope": "synthetic_declaration_not_payment_receipt"},
    }
    supplied = prepare(
        panel,
        raw.grades,
        raw.eligible,
        cubes,
        actions,
        basis_as_of="2026-09-04",
        complete_through="2026-09-04",
        provenance={"source": "synthetic_terminal_journey"},
        passive=passive,
        inherited_actions={"CHILD": [terminal]},
    )
    return panel, supplied, cubes


# The real planner continues with a known unpaid entitlement, never stale child prices.
def test_actual_policy_terminal_merger_retains_wealth_without_inventing_funding(
    tmp_path,
):
    panel, raw, cubes = terminal_fixture()
    result = run_account(panel, raw, cubes, tmp_path / "terminal-merger", 1, 3, 10)
    ledger = result["broker"]
    assert "CHILD" not in ledger["holdings"]
    assert "CHILD" not in ledger["average_prices"]
    assert ledger["security_distributions"][0]["whole_qty"] == 250
    assert len(ledger["cash_mergers"]) == 1
    receipt = ledger["cash_mergers"][0]
    assert receipt["quantity_before"] == 250
    assert receipt["prior_total_cost"] is None
    assert receipt["amount"] == 35625
    assert receipt["paid"] is False
    assert (
        receipt["completed_before"]
        == receipt["applied_at"]
        == "2026-09-04T13:30:00+00:00"
    )
    assert all(
        session["nightly"]["status"] == "planned" for session in result["sessions"]
    )
    final = result["sessions"][-1]
    assert final["merger_receivable"] == 35625
    assert final["nav"] == final["price_nav"] + 35625
    assert final["price_nav"] == ledger["cash"] + ledger["holdings"]["AAA"] * 100
    assert ledger["cash"] == pytest.approx(
        100000
        - sum(
            row["filled_qty"] * row["price"] + row["fee"]
            for row in result["fills"]
            if row["filled_qty"]
        )
    )
    for kind in ("fills", "attempts", "intents"):
        assert all(row["symbol"] != "CHILD" for row in result[kind])
    assert "CHILD" not in result["paper_state"]["rebalance_targets"]
    assert all(
        row["symbol"] != "CHILD"
        for row in result["paper_state"]["history"][-1]["positions"]
    )
    assert raw.tickers == ("AAA", "SPY", "QQQ")
    assert not np.isfinite(raw.passive.daily_close[3]).any()
    assert raw.inherited_actions["CHILD"][0]["source_receipt"]["scope"] == (
        "synthetic_declaration_not_payment_receipt"
    )


# Cash receipt settlement changes funding while keeping total NAV constant.
def test_terminal_cash_receivable_and_paid_cash_have_distinct_valuation():
    _, raw, _ = terminal_fixture()
    broker = ReplayBroker(
        100, 0, initial_holdings={"CHILD": 20}, initial_average_prices={"CHILD": 80}
    )
    now = instant(raw.dates[3], calendar.REGULAR_OPEN)
    broker.observe(now, account_marks(raw, 3, now, raw.session_open[3]), True)
    corporate_actions(broker, raw, 3, now)
    before = valuation(broker, raw, 3)
    assert before["nav"] == 2950
    assert before["price_nav"] == 100
    assert before["merger_receivable"] == 2850
    broker.settle_merger_cash("CHILD", now, 2850, now)
    after = valuation(broker, raw, 3)
    assert after["nav"] == before["nav"]
    assert after["price_nav"] == after["cash"] == 2950
    assert after["merger_receivable"] == 0


# Premarket, another session and timezone-free clocks cannot expose passive prices.
def test_passive_marks_refuse_ambiguous_session_clocks():
    _, raw, _ = fixture()
    raw = replace(raw, passive=passive_fixture(raw))
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    assert passive_marks(raw, 1, opening - timedelta(minutes=1)) == {"CHILD": None}
    with pytest.raises(ValueError, match="same observed session"):
        passive_marks(raw, 1, opening + timedelta(days=1))
    with pytest.raises(ValueError, match="Aware passive"):
        passive_marks(raw, 1, opening.replace(tzinfo=None))


# The child daily close becomes available after the exchange's shortened session.
def test_passive_marks_follow_actual_early_close_instead_of_sixteen_hours():
    _, raw, _ = fixture(dates=("2026-11-24", "2026-11-25", "2026-11-27"))
    bars = np.full((3, 26, 1), 21.0)
    bars[2, 14:] = np.nan
    passive = prepare_passive(
        raw.dates,
        raw.tickers,
        ("CHILD",),
        np.full((3, 1), 20.0),
        bars,
        np.full((3, 1), 22.0),
        first_session=str(raw.dates[0]),
        complete_through=str(raw.dates[-1]),
        provenance={"source": "synthetic"},
        price_basis=CUBE_BASIS,
    )
    raw = replace(raw, passive=passive)
    closing = instant(raw.dates[2], calendar.session_close(raw.dates[2].astype(object)))
    assert passive_marks(raw, 2, closing) == {"CHILD": 21}
    assert passive_marks(raw, 2, closing + timedelta(minutes=1)) == {"CHILD": 22}


# Preserve unknown fractional cash even when the inherited shares have known prices.
def test_passive_prices_never_hide_unpriced_fractional_cash():
    _, raw, _ = fixture()
    raw = replace(raw, passive=passive_fixture(raw))
    broker = ReplayBroker(
        1000, 0, initial_holdings={"AAA": 100}, initial_average_prices={"AAA": 60}
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, account_marks(raw, 1, opening, raw.session_open[1]), True)
    broker.apply_stock_distribution(
        "AAA", "CHILD", 1, 3, opening, parent_basis_fraction=0.75
    )
    now = instant(raw.dates[1], calendar.REGULAR_CLOSE) + timedelta(minutes=1)
    broker.observe(now, account_marks(raw, 1, now, raw.daily_close[1]), False)
    assert valuation(broker, raw, 1)["status"] == "unknown_distribution_cash_in_lieu"
    assert valuation(broker, raw, 1)["nav"] is None


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


# Run the actual planner across a default share exchange with missing fractional cash.
def share_exchange_fixture():
    from backend.tests.test_live_execution_inputs import share_default_fixture

    panel, raw, cubes = fixture(
        ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")
    )
    terms = {
        **share_default_fixture(),
        "date": "2026-09-03",
        "terms_available_on": "2026-09-02",
        "terms_available_at": "2026-09-02T16:01:00-04:00",
        "completed_before": "2026-09-03T09:30:00-04:00",
        "completion_available_at": "2026-09-03T08:30:00-04:00",
    }
    actions = dict(raw.actions)
    actions["AAA"] = (terms,)
    supplied = prepare(
        panel,
        raw.grades,
        raw.eligible,
        cubes,
        actions,
        basis_as_of="2026-09-04",
        complete_through="2026-09-04",
        provenance={"source": "synthetic_private_share_default"},
    )
    return panel, supplied, cubes


# Missing fractional value remains visible and prevents a fabricated funded nightly.
def test_actual_nightly_share_exchange_retains_unknown_wealth_and_whole_holdings(
    tmp_path,
):
    panel, raw, cubes = share_exchange_fixture()
    result = run_account(panel, raw, cubes, tmp_path / "share-exchange", 1, 3, 10)
    ledger = result["broker"]
    receipt = ledger["security_exchanges"][0]
    assert receipt["quantity_before"] == 250
    assert receipt["quantity_after"] == 451
    assert receipt["fractional_qty"] == 0.65
    assert receipt["cash_in_lieu"] is None
    assert "forfeited_fraction" not in receipt
    assert ledger["holdings"] == {"AAA": 451}
    assert ledger["cash"] == 100000 - sum(
        row["filled_qty"] * row["price"] + row["fee"]
        for row in result["fills"]
        if row["filled_qty"]
    )
    assert result["sessions"][1]["nightly"]["status"] == "planned"
    for row in result["sessions"][2:]:
        assert row["nav"] is None
        assert row["status"] == "unknown_exchange_cash_in_lieu"
        assert row["nightly"]["status"] == "nightly_broker_unavailable"
        assert row["unpriced_entitlements"][0]["fractional_qty"] == 0.65
    assert all(row["symbol"] == "AAA" for row in result["intents"])
    assert result["adoption_eligible"] is False


# Explicit payment restores NAV without pretending the archived factor granted shares.
def test_default_share_exchange_dispatch_preserves_fraction_until_payment():
    _, raw, _ = share_exchange_fixture()
    broker = ReplayBroker(
        100, 0, initial_holdings={"AAA": 100}, initial_average_prices={"AAA": 90}
    )
    day = 2
    now = instant(raw.dates[day], calendar.REGULAR_OPEN)
    broker.observe(now, dict.fromkeys(raw.tickers, 100), True)
    before = broker.ledger()
    corporate_actions(broker, raw, day, now)
    assert broker.ledger()["holdings"] == {"AAA": 180}
    assert valuation(broker, raw, day)["nav"] is None
    broker.settle_exchange_cash("AAA", now, 30, now)
    assert valuation(broker, raw, day)["nav"] == 18130
    assert broker.ledger()["cash"] == before["cash"] + 30
    paid = broker.ledger()
    corporate_actions(broker, raw, day, now)
    assert broker.ledger() == paid


# Dispatch retains the legal clock and leaves fractional wealth missing until paid.
@pytest.mark.parametrize("quantity", [24, 25])
def test_consolidation_journey_preserves_legal_clock_and_cash_claim(quantity):
    _, raw, _ = fixture()
    actions = dict(raw.actions)
    effective = "2026-09-01T16:15:00-04:00"
    actions["AAA"] = (
        {"date": str(raw.dates[1]), "kind": "archive_adjustment", "value": 1 / 6},
        {
            "date": str(raw.dates[1]),
            "kind": "share_consolidation",
            "numerator": 1,
            "denominator": 6,
            "effective_at": effective,
            "fractional_policy": "cash_in_lieu_unknown",
        },
    )
    broker = ReplayBroker(
        1000, 0, initial_holdings={"AAA": quantity}, initial_average_prices={"AAA": 8}
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {name: 100 for name in raw.tickers}, True)
    corporate_actions(broker, replace(raw, actions=actions), 1, opening)
    before = broker.ledger()
    corporate_actions(broker, replace(raw, actions=actions), 1, opening)
    assert broker.ledger() == before
    assert before["holdings"] == {"AAA": 4}
    assert before["cash"] == 1000
    assert (
        before["share_consolidations"][0]["effective_at"] == "2026-09-01T20:15:00+00:00"
    )
    assert (
        before["share_consolidations"][0]["applied_at"] == "2026-09-02T13:30:00+00:00"
    )
    result = valuation(broker, raw, 1)
    if quantity == 24:
        assert result["nav"] == 1400
    else:
        assert result["nav"] is None
        assert result["status"] == "unknown_consolidation_cash_in_lieu"
        assert result["unpriced_entitlements"][0]["fractional_qty"] == pytest.approx(
            1 / 6
        )
        broker.settle_consolidation_cash("AAA", effective, 3, opening)
        assert valuation(broker, raw, 1)["nav"] == 1403


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


# Retain uncovered holdings and report missing value without assuming liquidation.
def test_unrepresented_held_security_is_explicit_missing_value():
    _, raw, _ = fixture()
    broker = ReplayBroker(
        1000,
        0,
        initial_holdings={"AAA": 10, "CHILD": 2},
        initial_average_prices={"AAA": 60, "CHILD": 20},
    )
    opening = instant(raw.dates[1], calendar.REGULAR_OPEN)
    broker.observe(opening, {name: 100 for name in raw.tickers}, True)
    before = broker.ledger()
    result = valuation(broker, raw, 1)
    assert result["nav"] is None
    assert result["price_nav"] is None
    assert result["status"] == "missing_held_close"
    assert result["missing_symbols"] == ["CHILD"]
    assert result["holdings"] == {"AAA": 10, "CHILD": 2}
    assert result["cash"] == 1000
    assert broker.ledger() == before


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
