"""Synthetic funded-account acceptance; no historical strategy is rerun."""

import copy
import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.allocation_attribution import MODES, _sign, attribution
from backend.market.allocation_replay import AllocationInstruction, replay
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot

SYMBOLS = ("AAA", "BBB", "SPY", "QQQ")
DATES = np.array(
    [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
        "2024-01-09",
    ],
    dtype="datetime64[D]",
)


# Build a small complete adjusted-price panel without any provider or stored data.
def _panel(*, rows=5, closes=None, opens=None, dates=None, tickers=SYMBOLS):
    closing = (
        np.full((rows, 4), 100.0) if closes is None else np.array(closes, dtype=float)
    )
    opening = closing.copy() if opens is None else np.array(opens, dtype=float)
    return SimpleNamespace(
        dates=DATES[: len(closing)].copy() if dates is None else dates,
        tickers=tickers,
        open=opening,
        close=closing.copy(),
        adj_close=closing.copy(),
    )


# Exercise the real allocation adapter and retain only its completed journal.
def _snapshot(panel, modes=None, *, cost=10, capital=100.0, first=0, base=None):
    count = len(panel.dates) - first - 1
    modes = ["stock"] * count if modes is None else modes
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        panel.open,
        panel.adj_close,
        run_id="synthetic-attribution",
        account_id="synthetic",
        policy_id="synthetic-allocation",
        cost_bps=cost,
        provenance={"evidence_basis": "synthetic-attribution-test"},
    )
    instructions = []
    for offset, mode in enumerate(modes):
        t = first + offset
        sleeves = {
            "stock": (1, 0, 0),
            "SPY": (0, 1, 0),
            "QQQ": (0, 0, 1),
            "cash": (0, 0, 0),
            "mixed": (0.4, 0.3, 0.1),
        }[mode]
        instructions.append(
            AllocationInstruction(
                str(panel.dates[t]),
                str(panel.dates[t]),
                f"synthetic-{t}",
                *sleeves,
                stock_weights=({"AAA": 1.0} if base is None else base)
                if offset == 0
                else None,
            )
        )
    replay(
        panel,
        instructions,
        first=first,
        cost_bps=cost,
        start_equity=capital,
        journal=journal,
    )
    snapshot = journal.snapshot()
    assert verify_snapshot(snapshot)["ok"]
    return snapshot


# Supply every fixed comparison as an independently funded account on the same grid.
def _accounts(panel=None, modes=None, *, cost=10, capital=100.0, base=None):
    panel = _panel() if panel is None else panel
    count = len(panel.dates) - 1
    return {
        "candidate": _snapshot(panel, modes, cost=cost, capital=capital, base=base),
        "no_gate_adapter": _snapshot(panel, cost=cost, capital=capital),
        "SPY": _snapshot(panel, ["SPY"] * count, cost=cost, capital=capital),
        "QQQ": _snapshot(panel, ["QQQ"] * count, cost=cost, capital=capital),
    }


# Rebind deliberate semantic test mutations without pretending they preserve provenance.
def _rehash(snapshot):
    for name in ("events", "prices"):
        body = (
            json.dumps(
                snapshot[name], sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode()
        snapshot["manifest"]["files"][name + ".json"] = {
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }


# Construct valid cash accounts with explicitly absent or ambiguous decision evidence.
def _cash_snapshot(*, rows=3, decisions=0, terminal=False):
    panel = _panel(rows=rows)
    journal = ResearchJournal(
        panel.dates,
        SYMBOLS,
        panel.open,
        panel.adj_close,
        run_id="synthetic-cash",
        account_id="synthetic",
        policy_id="synthetic",
        cost_bps=10,
        provenance={"evidence_basis": "synthetic-attribution-test"},
    )
    units = [0.0] * 4
    journal.open_account(0, 100.0, units)
    pending = {}
    for t in range(rows):
        journal.mark(t, 100.0, units, 100.0, 0.0)
        if t < rows - 1:
            for _ in range(decisions):
                journal.decision(t, units, units, metadata={"no_order": True})
        elif terminal:
            identifier = journal.decision(t, units, units)
            pending = {"decision_id": identifier, "submitted_units": units}
    journal.finish(rows - 1, 100.0, units, 0.0, pending)
    snapshot = journal.snapshot()
    assert verify_snapshot(snapshot)["ok"]
    return snapshot


# A cash instruction cannot receive credit for escaping a gap before its sale fills.
def test_cash_sale_after_gap_retains_loss_and_both_exposure_marks():
    closes = np.full((4, 4), 100.0)
    closes[2:, 0] = 90
    opens = closes.copy()
    opens[2, 0] = 80
    table = attribution(
        _accounts(_panel(closes=closes, opens=opens), ["stock", "cash", "cash"]),
        cost_bps=10,
    )
    row = table["intervals"][1]
    assert row["intent"]["mode"] == "cash"
    assert row["realized_sleeve_weights"]["prior_close"]["stock"] == pytest.approx(1)
    assert row["realized_sleeve_weights"]["following_close"]["cash"] == pytest.approx(1)
    assert row["outcomes"]["candidate"]["net_return"] == pytest.approx(-0.2008)
    assert row["outcomes"]["no_gate_adapter"]["net_return"] == pytest.approx(-0.1)
    assert row["comparisons"]["no_gate_adapter"]["excess_log_growth"] < 0
    assert row["fills"]["gross_sells"] > 0
    assert row["fills"]["fees"] > 0
    assert row["fills"]["batches"][0]["session"] == row["following_session"]
    assert "pre-fill gaps" in table["definitions"]["returns"]


# Mixed risky sleeves and residual cash retain their actual target fractions.
def test_mixed_targets_do_not_normalize_stock_scale_or_cash():
    row = attribution(_accounts(modes=["mixed"] * 4, base={"AAA": 0.5}), cost_bps=10)[
        "intervals"
    ][0]
    assert row["intent"]["mode"] == "mixed"
    assert row["intent"]["declared_sleeves"]["stock_scale"] == 0.4
    assert row["intent"]["desired_sleeve_weights"] == pytest.approx(
        {"stock": 0.2, "SPY": 0.3, "QQQ": 0.1, "cash": 0.4}
    )
    assert row["realized_sleeve_weights"]["prior_close"]["cash"] == 1


# Stock selection with no investable names is distinguishable from a cash command.
def test_empty_stock_basket_has_effective_cash_target_and_retained_stock_command():
    row = attribution(_accounts(base={}), cost_bps=10)["intervals"][0]
    assert row["intent"]["mode"] == "cash"
    assert row["intent"]["declared_sleeves"]["stock_scale"] == 1
    assert row["intent"]["desired_sleeve_weights"]["cash"] == 1


# Stock targets with residual cash remain stock intent rather than full investment.
def test_underfilled_stock_target_retains_residual_cash():
    row = attribution(_accounts(base={"AAA": 0.25}), cost_bps=10)["intervals"][0]
    assert row["intent"]["mode"] == "stock"
    assert row["intent"]["desired_sleeve_weights"]["stock"] == 0.25
    assert row["intent"]["desired_sleeve_weights"]["cash"] == 0.75


# Initial capital is a boundary mark, not an extra cash-return observation.
def test_initial_cash_and_final_pending_are_separate_from_return_intervals():
    accounts = _accounts(_panel(rows=3), ["stock", "QQQ"])
    table = attribution(accounts, cost_bps=10)
    assert table["return_intervals"] == 2
    assert table["accounts"]["candidate"]["initial_mark"]["cash"] == 100
    assert table["accounts"]["candidate"]["terminal"]["pending"] == {"retry": True}
    row = table["intervals"][-1]
    assert row["intent"]["mode"] == "QQQ"
    assert row["fills"]["budget_limited_batches"] == 1
    assert "cash_budget_limited" in row["fills"]["batches"][0]["unfilled_reasons"]
    assert row["realized_sleeve_weights"]["following_close"]["cash"] > 0.99
    assert row["realized_sleeve_weights"]["following_close"]["QQQ"] < 0.01


# A final-close decision has no future interval and remains in terminal evidence.
def test_terminal_decision_is_not_scored_as_a_completed_return():
    snapshot = _cash_snapshot(terminal=True)
    table = attribution(
        {
            name: copy.deepcopy(snapshot)
            for name in ("candidate", "no_gate_adapter", "SPY", "QQQ")
        },
        cost_bps=10,
    )
    assert table["return_intervals"] == 2
    boundary = table["accounts"]["candidate"]
    assert boundary["terminal_decision_ids"] == [
        boundary["terminal"]["pending"]["decision_id"]
    ]
    assert all(not row["intent"]["decision_ids"] for row in table["intervals"])


# Unavailable or contradictory semantic metadata cannot become a confident allocation.
@pytest.mark.parametrize(
    "mutation", ["missing", "unsupported", "inconsistent", "future", "null_target"]
)
def test_unknown_instruction_preserves_interval_and_decision_id(mutation):
    accounts = _accounts()
    snapshot = accounts["candidate"]
    decision = next(
        event for event in snapshot["events"] if event["type"] == "decision"
    )
    if mutation == "missing":
        decision["metadata"].pop("instruction")
    elif mutation == "unsupported":
        decision["metadata"]["execution_policy"] = "unsupported-policy"
    elif mutation == "inconsistent":
        decision["metadata"]["instruction"]["stock_scale"] = 0
    elif mutation == "future":
        decision["metadata"]["instruction"]["information_through"] = "2099-01-01"
    else:
        decision["desired_weights"] = None
    _rehash(snapshot)
    table = attribution(accounts, cost_bps=10)
    assert table["return_intervals"] == 4
    assert table["intervals"][0]["intent"]["mode"] == "unknown"
    assert table["intervals"][0]["intent"]["decision_ids"] == [decision["decision_id"]]
    assert table["intervals"][0]["fills"]["batch_count"] == 1
    assert table["by_intent"]["unknown"]["return_intervals"] == 1
    assert table["reconciliation"]["ok"]


# Missing or multiple decisions are explicit unknowns rather than dropped observations.
@pytest.mark.parametrize(
    ("decisions", "reason"),
    [(0, "missing_instruction"), (2, "ambiguous_multiple_decisions")],
)
def test_missing_and_ambiguous_decisions_keep_all_intervals(decisions, reason):
    snapshot = _cash_snapshot(decisions=decisions)
    table = attribution(
        {
            name: copy.deepcopy(snapshot)
            for name in ("candidate", "no_gate_adapter", "SPY", "QQQ")
        },
        cost_bps=10,
    )
    assert table["by_intent"]["unknown"]["return_intervals"] == 2
    for row in table["intervals"]:
        assert row["intent"]["reason"] == reason
        assert len(row["intent"]["decision_ids"]) == decisions
    assert table["reconciliation"]["ok"]


# Every intent and comparator sign contributes exactly once to net log growth.
def test_complete_partitions_ties_and_nonunit_capital_reconcile():
    closes = np.full((6, 4), 100.0)
    closes[:, 2] = [100, 100, 110, 90, 90, 95]
    closes[:, 3] = [100, 100, 90, 90, 100, 95]
    accounts = _accounts(
        _panel(closes=closes), ["stock", "SPY", "QQQ", "cash", "mixed"], capital=173.5
    )
    accounts["extra_control"] = copy.deepcopy(accounts["no_gate_adapter"])
    table = attribution(accounts, cost_bps=10)
    assert set(table["by_intent"]) == set(MODES)
    assert table["return_intervals"] == 5
    assert table["reconciliation"]["ok"]
    assert sum(group["return_intervals"] for group in table["by_intent"].values()) == 5
    assert {row["comparisons"]["SPY"]["sign"] for row in table["intervals"]} == {
        "positive",
        "negative",
        "tie",
    }
    for name, snapshot in accounts.items():
        proof = verify_snapshot(snapshot)
        expected = math.log(proof["marks"][-1]["nav"] / 173.5)
        assert table["reconciliation"]["log_growth_by_account"][name] == pytest.approx(
            expected
        )
        assert math.fsum(
            row["outcomes"][name]["log_growth"] for row in table["intervals"]
        ) == pytest.approx(expected)
    assert not table["adoption_eligible"]
    assert not table["independent_validation"]
    assert not table["historical_availability_verified"]


# A no-order hold has no invented batch or second fee despite daily intent evidence.
def test_hold_without_fill_is_not_a_failed_or_new_trade():
    row = attribution(_accounts(), cost_bps=10)["intervals"][1]
    assert row["intent"]["mode"] == "stock"
    assert len(row["intent"]["decision_ids"]) == 1
    assert row["fills"]["batch_count"] == 0
    assert row["fills"]["fees"] == 0
    assert row["outcomes"]["candidate"]["net_return"] == 0


# A different source prefix is allowed only when actual account marks exactly match.
def test_full_manifest_prefix_does_not_replace_reconstructed_mark_calendar():
    short = _panel(rows=3)
    accounts = _accounts(short)
    longer = _panel(rows=4, dates=np.r_[np.datetime64("2023-12-29"), short.dates])
    accounts["no_gate_adapter"] = _snapshot(longer, first=1)
    table = attribution(accounts, cost_bps=10)
    assert table["first_session"] == str(short.dates[0])
    assert table["return_intervals"] == 2


# Mismatched calendars or one-way costs cannot silently change the matched sample.
@pytest.mark.parametrize("mutation", ["dates", "cost", "missing_control", "one_mark"])
def test_unmatched_or_incomplete_accounts_are_rejected(mutation):
    accounts = _accounts()
    if mutation == "dates":
        accounts["SPY"] = _snapshot(_panel(dates=DATES[1:6]))
    elif mutation == "cost":
        accounts["SPY"] = _snapshot(_panel(), cost=25)
    elif mutation == "missing_control":
        del accounts["QQQ"]
    else:
        accounts = {name: _cash_snapshot(rows=1) for name in accounts}
    with pytest.raises(
        ValueError, match="dates differ|costs differ|journals required|NAV marks"
    ):
        attribution(accounts, cost_bps=10)


# Changed retained bytes must fail before any apparently valid summary is emitted.
def test_hash_tampering_is_rejected_without_mutating_inputs():
    accounts = _accounts()
    accounts["candidate"]["events"][-1]["cash"] += 1
    before = copy.deepcopy(accounts)
    with pytest.raises(ValueError, match="verification failed"):
        attribution(accounts, cost_bps=10)
    assert accounts == before


# Reading and later changing a report cannot change any retained journal object.
def test_input_and_output_ownership_are_independent():
    accounts = _accounts(_panel(rows=3), ["stock", "QQQ"])
    before = copy.deepcopy(accounts)
    table = attribution(accounts, cost_bps=10)
    assert accounts == before
    table["accounts"]["candidate"]["terminal"]["pending"]["retry"] = False
    table["intervals"][0]["fills"]["batches"][0]["notional"][0] = -1
    assert accounts == before


# Both declared execution costs work without treating Booleans as a cost level.
@pytest.mark.parametrize("cost", [10, 25])
def test_both_supported_cost_levels_have_independent_fee_evidence(cost):
    table = attribution(_accounts(cost=cost), cost_bps=cost)
    assert table["cost_bps"] == cost
    assert table["intervals"][0]["fills"]["fees"] == pytest.approx(
        100 * cost / (10000 + cost)
    )
    assert table["reconciliation"]["ok"]


# Closing decisions belong to the following interval, never the one just completed.
def test_consecutive_close_decisions_and_fills_keep_exact_interval_bindings():
    accounts = _accounts(_panel(rows=4), ["stock", "cash", "QQQ"])
    table = attribution(accounts, cost_bps=10)
    decisions = [
        event
        for event in accounts["candidate"]["events"]
        if event["type"] == "decision"
    ]
    assert [row["intent"]["mode"] for row in table["intervals"]] == [
        "stock",
        "cash",
        "QQQ",
    ]
    for row, decision in zip(table["intervals"], decisions, strict=True):
        assert row["prior_session"] == decision["session"]
        assert row["intent"]["decision_ids"] == [decision["decision_id"]]
        assert all(
            batch["decision_id"] == decision["decision_id"]
            and batch["session"] == row["following_session"]
            for batch in row["fills"]["batches"]
        )


# The documented fixed tie band includes both endpoints and never alters log growth.
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "tie"),
        (1e-12, "tie"),
        (-1e-12, "tie"),
        (1.001e-12, "positive"),
        (-1.001e-12, "negative"),
    ],
)
def test_return_sign_uses_explicit_fixed_absolute_tolerance(value, expected):
    assert _sign(value) == expected


# Unsupported numeric input cannot silently select a valid execution-cost account.
@pytest.mark.parametrize("cost", [True, "10", 0, 11, float("nan")])
def test_invalid_cost_levels_are_rejected_before_reading_accounts(cost):
    with pytest.raises(ValueError, match="cost_bps must be 10 or 25"):
        attribution({}, cost_bps=cost)


# Manifest identity changes are visible even when retained event and price bytes match.
def test_manifest_digest_binds_account_declarations():
    accounts = _accounts()
    first = attribution(accounts, cost_bps=10)
    accounts["candidate"]["manifest"]["provenance"]["note"] = "new declaration"
    second = attribution(accounts, cost_bps=10)
    assert (
        first["accounts"]["candidate"]["files"]
        == second["accounts"]["candidate"]["files"]
    )
    assert (
        first["accounts"]["candidate"]["manifest_sha256"]
        != second["accounts"]["candidate"]["manifest_sha256"]
    )


# A permuted symbol grid remains attached to actual filled and retained unit vectors.
def test_ordered_symbols_label_nondefault_fill_and_position_vectors():
    symbols = ("QQQ", "AAA", "SPY", "BBB")
    panel = _panel(closes=np.tile([200.0, 50.0, 100.0, 25.0], (3, 1)), tickers=symbols)
    accounts = _accounts(panel)
    # Controls may preserve their own different order on identical account dates.
    accounts["SPY"] = _snapshot(_panel(rows=3), ["SPY", "SPY"])
    table = attribution(accounts, cost_bps=10)
    boundary = table["accounts"]["candidate"]
    assert boundary["symbols"] == list(symbols)
    assert table["accounts"]["SPY"]["symbols"] == list(SYMBOLS)
    batch = table["intervals"][0]["fills"]["batches"][0]
    units = dict(zip(boundary["symbols"], batch["filled_units"], strict=True))
    notionals = dict(zip(boundary["symbols"], batch["notional"], strict=True))
    assert units == pytest.approx({"QQQ": 0, "AAA": 2 / 1.001, "SPY": 0, "BBB": 0})
    assert notionals["AAA"] == pytest.approx(units["AAA"] * 50)
    assert dict(
        zip(boundary["symbols"], boundary["terminal"]["positions"], strict=True)
    ) == pytest.approx(units)
    assert (
        len(batch["residual_units"]) == len(batch["unfilled_reasons"]) == len(symbols)
    )
    boundary["symbols"][0] = "changed-output"
    assert accounts["candidate"]["manifest"]["symbols"] == list(symbols)


# Valid cash accounting under an index role is reported without certifying that policy.
def test_control_role_names_do_not_certify_benchmark_construction():
    snapshot = _cash_snapshot()
    table = attribution(
        {
            name: copy.deepcopy(snapshot)
            for name in ("candidate", "no_gate_adapter", "SPY", "QQQ")
        },
        cost_bps=10,
    )
    assert all(row["outcomes"]["SPY"]["net_return"] == 0 for row in table["intervals"])
    assert "caller-attested" in table["definitions"]["control_roles"]
    assert "not a SPY or QQQ buy-and-hold" in table["definitions"]["control_roles"]
