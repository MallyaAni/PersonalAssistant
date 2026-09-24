"""Hand-calculated accounting fixtures independent of every journal producer."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from backend.market.research_journal_replay import (
    verify_archive,
    verify_payload,
    verify_snapshot,
)


# Encode fixtures independently using the public canonical JSON contract.
def _bytes(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


# Re-sign mutations so accounting tests do not stop at an unrelated hash boundary.
def _rehash(snapshot):
    snapshot["manifest"]["files"] = {
        f"{key}.json": {
            "sha256": hashlib.sha256(_bytes(snapshot[key])).hexdigest(),
            "bytes": len(_bytes(snapshot[key])),
        }
        for key in ("prices", "events")
    }
    return snapshot


# Refresh transport identities after a mutation to exercise the actual ordering guard.
def _resequence(snapshot):
    for seq, event in enumerate(snapshot["events"]):
        event.update(seq=seq, event_id=f"event-{seq:06d}")
    return _rehash(snapshot)


class Fixture:
    """Explicit expected states, not a second strategy or execution implementation."""

    # Set up a small known source grid whose expected fills are supplied by each test.
    def __init__(
        self, opens, closes=None, *, cost=0, cash=100, positions=None, opening=0
    ):
        self.prices = {
            "schema": "research-journal-prices/1",
            "open": opens,
            "close": closes if closes is not None else copy.deepcopy(opens),
            "raw": None,
        }
        self.manifest = {
            "schema": "research-journal/1",
            "run_id": "hand-calculated",
            "account_id": "research",
            "policy_id": "fixture/1",
            "sessions": [
                "2020-01-02",
                "2020-01-03",
                "2020-01-06",
                "2020-01-07",
                "2020-01-08",
            ][: len(opens)],
            "symbols": [f"TEST{i}" for i in range(len(opens[0]))],
            "cost_bps": cost,
            "price_basis": "adjusted_synthetic_units",
            "cash_yield": 0.0,
            "cash_model": "single_balance_batch_funding_not_actual_settlement",
            "historical_availability_verified": False,
            "security_identity_verified": False,
            "settlement_verified": False,
            "adoption_eligible": False,
            "status": "complete",
            "provenance": {"kind": "synthetic hand calculation"},
            "files": {},
        }
        self.events = []
        self.cash = cash
        self.positions = positions if positions is not None else [0.0] * len(opens[0])
        self.traded = 0.0
        self.add("open_account", opening, cash=cash, positions=list(self.positions))

    # Append public-schema metadata without using any production recorder helper.
    def add(self, kind, session, **fields):
        seq = len(self.events)
        event = {
            "seq": seq,
            "event_id": f"event-{seq:06d}",
            "type": kind,
            "session": self.manifest["sessions"][session],
            "session_index": session,
            **fields,
        }
        self.events.append(event)
        return event

    # Record the test's explicit closing valuation and current expected state.
    def mark(self, session, nav):
        self.add(
            "mark",
            session,
            cash=self.cash,
            positions=list(self.positions),
            nav=nav,
            traded=self.traded,
            unavailable_held_symbols=[],
            price_ref={
                "file": "prices.json",
                "field": "close",
                "session_index": session,
            },
        )

    # Declare a target whose quantities were chosen by the hand-worked test case.
    def decision(self, session, target):
        identifier = f"decision-{len(self.events):06d}"
        self.add(
            "decision",
            session,
            decision_id=identifier,
            submitted_units=target,
            desired_weights=None,
            reason="hand-calculated fixture",
            metadata={},
        )
        return identifier

    # Make an explicit split-phase instruction visible rather than silently clipping it.
    def adjust(self, identifier, session, phase, target):
        self.add(
            "adjustment",
            session,
            decision_id=identifier,
            phase=phase,
            submitted_units=target,
            reason="explicit phase leg",
        )

    # Describe an explicitly supplied fill outcome; never compute its scale or funding.
    def fill(
        self,
        identifier,
        session,
        target,
        after,
        cash,
        budget,
        scale,
        *,
        phase="open",
        recycle=False,
    ):
        prices = self.prices[phase][session]
        deltas = [new - old for new, old in zip(after, self.positions, strict=True)]
        notional = [
            abs(delta) * price if delta else 0.0
            for delta, price in zip(deltas, prices, strict=True)
        ]
        fees = [value * self.manifest["cost_bps"] / 10000 for value in notional]
        residual = [
            None if wanted is None else wanted - held
            for wanted, held in zip(target, after, strict=True)
        ]
        reasons = []
        for wanted, left, price in zip(target, residual, prices, strict=True):
            if wanted is None:
                reasons.append("submitted_units_unavailable")
            elif left == 0:
                reasons.append(None)
            elif price is None or price <= 0:
                reasons.append("price_unavailable")
            elif left > 0 and scale < 1:
                reasons.append("cash_budget_limited")
            else:
                reasons.append("not_filled_in_batch")
        self.add(
            "fill_batch",
            session,
            decision_id=identifier,
            phase=phase,
            submitted_units=target,
            prices=prices,
            positions_before=list(self.positions),
            cash_before=self.cash,
            positions_after=after,
            cash_after=cash,
            buy_budget=budget,
            scale=scale,
            recycle_sells=recycle,
            filled_units=deltas,
            notional=notional,
            fees=fees,
            gross_buys=sum(
                value
                for value, delta in zip(notional, deltas, strict=True)
                if delta > 0
            ),
            gross_sells=sum(
                value
                for value, delta in zip(notional, deltas, strict=True)
                if delta < 0
            ),
            fee_total=sum(fees),
            residual_units=residual,
            unfilled_reasons=reasons,
            price_ref={"file": "prices.json", "field": phase, "session_index": session},
        )
        self.traded += sum(notional)
        self.cash, self.positions = cash, after

    # End with actual holdings and declared queue state, never a fabricated liquidation.
    def snapshot(self, pending=None):
        self.add(
            "finish",
            len(self.manifest["sessions"]) - 1,
            cash=self.cash,
            positions=list(self.positions),
            traded=self.traded,
            pending={} if pending is None else pending,
            status=self.manifest["status"],
        )
        return _rehash(
            json.loads(
                _bytes(
                    {
                        "manifest": self.manifest,
                        "events": self.events,
                        "prices": self.prices,
                    }
                )
            )
        )


# Provide one fee-bearing round-number account reused by hostile mutation cases.
def _flat():
    fixture = Fixture([[100], [100]], cost=10, cash=101)
    fixture.mark(0, 101)
    identifier = fixture.decision(0, [1])
    fixture.fill(identifier, 1, [1], [1], 0.9, 101, 1)
    fixture.mark(1, 100.9)
    return fixture.snapshot()


# Prove every reported success is narrow accounting, never adoption readiness.
def _verified(snapshot):
    report = verify_snapshot(snapshot)
    assert report["ok"], report["errors"]
    assert report["accounting_verified"]
    assert report["integrity_verified"]
    assert report["complete"]
    for key in (
        "historical_availability_verified",
        "security_identity_verified",
        "settlement_verified",
        "adoption_eligible",
    ):
        assert report[key] is False
    return report


# Confirm a full fill charges the stated fee and leaves the final security held.
def test_flat_price_fee_and_terminal_position():
    snapshot = _flat()
    report = _verified(snapshot)
    assert report["total_fees"] == pytest.approx(0.1)
    assert report["total_traded"] == pytest.approx(100)
    assert report["terminal"]["positions"] == [1]
    assert report["terminal"]["cash"] == pytest.approx(0.9)
    assert [mark["nav"] for mark in report["marks"]] == pytest.approx([101, 100.9])
    assert verify_payload(snapshot["manifest"], snapshot["events"], snapshot["prices"])[
        "ok"
    ]


# Exercise a next-open gap that halves the previously close-sized buy.
def test_overnight_gap_cash_limited_fill():
    fixture = Fixture([[100], [200]], [[100], [180]])
    fixture.mark(0, 100)
    identifier = fixture.decision(0, [1])
    fixture.fill(identifier, 1, [1], [0.5], 0, 100, 0.5)
    fixture.mark(1, 90)
    report = _verified(fixture.snapshot())
    assert report["marks"][1]["nav"] == 90
    assert report["terminal"]["pending"] == {}


# Keep independently carried balances while conditioning a sub-ULP requested buy.
def test_negligible_buy_scale_is_checked_in_currency_and_reported():
    fixture = Fixture([[100], [150], [200]], cash=1)
    fixture.mark(0, 1)
    identifier = fixture.decision(0, [0.01])
    fixture.fill(
        identifier, 1, [0.01], [0.006666666666666666], 1.1102230246251565e-16, 1, 2 / 3
    )
    fixture.mark(1, 1)
    identifier = fixture.decision(1, [0.006666666666666667])
    fixture.fill(
        identifier,
        2,
        [0.006666666666666667],
        [0.006666666666666667],
        0,
        1.1102230246251565e-16,
        0.64,
    )
    fixture.mark(2, 1.3333333333333335)
    report = _verified(fixture.snapshot())
    conditioned = report["small_notional_scale_checks"]
    assert conditioned["count"] == 1
    assert conditioned["max_requested_spend"] == pytest.approx(1.734723475976807e-16)
    assert conditioned["max_requested_spend"] < conditioned["max_bound"]
    residual = report["max_reconciliation_residual"]
    assert 0 < residual["cash"] < 1e-12
    assert 0 < residual["units"] < 1e-12
    assert report["marks"][1]["cash"] == 0


# Never excuse an invalid scale, even when the requested buy has no monetary size.
@pytest.mark.parametrize("scale", [-0.1, 1.1])
def test_negligible_buy_does_not_allow_out_of_range_scale(scale):
    fixture = Fixture([[100], [100]], cash=0)
    fixture.mark(0, 0)
    identifier = fixture.decision(0, [0])
    fixture.fill(identifier, 1, [0], [0], 0, 0, scale)
    fixture.mark(1, 0)
    report = verify_snapshot(fixture.snapshot())
    assert not report["ok"]
    assert "scale outside" in report["errors"][0]


# Accumulating individually tiny invented cash changes must exceed the carried ledger.
def test_tiny_per_batch_cash_drift_does_not_reset_independent_state():
    fixture = Fixture([[100]] * 5, cash=0)
    fixture.mark(0, 0)
    for session in range(1, 5):
        identifier = fixture.decision(session - 1, [0])
        prior_cash = fixture.cash
        fabricated_cash = 4e-13 * session
        fixture.fill(identifier, session, [0], [0], fabricated_cash, prior_cash, 0)
        fixture.mark(session, fabricated_cash)
    report = verify_snapshot(fixture.snapshot())
    assert not report["ok"]
    assert "cash_after" in report["errors"][0]
    assert len(report["marks"]) == 3
    assert all(mark["cash"] == 0 for mark in report["marks"])


# Require competing buys to receive the same fraction of their requested quantities.
def test_competing_buys_share_one_budget_scale():
    fixture = Fixture([[60, 30], [60, 30]], cash=90)
    fixture.mark(0, 90)
    identifier = fixture.decision(0, [1, 2])
    fixture.fill(identifier, 1, [1, 2], [0.75, 1.5], 0, 90, 0.75)
    fixture.mark(1, 90)
    report = _verified(fixture.snapshot())
    assert report["terminal"]["positions"] == [0.75, 1.5]
    assert report["total_traded"] == 90


# Distinguish batch sale-funding permission from actual securities settlement.
@pytest.mark.parametrize("recycle", [False, True])
def test_rotation_recycles_sales_only_when_declared(recycle):
    fixture = Fixture([[100, 100], [100, 100]], cash=0, positions=[1, 0])
    fixture.mark(0, 100)
    identifier = fixture.decision(0, [0, 1])
    fixture.fill(
        identifier,
        1,
        [0, 1],
        [0, 1 if recycle else 0],
        0 if recycle else 100,
        100 if recycle else 0,
        1 if recycle else 0,
        recycle=recycle,
    )
    fixture.mark(1, 100)
    report = _verified(fixture.snapshot())
    assert report["total_traded"] == (200 if recycle else 100)


# Deduct sale costs before calculating recycled funds and charge the scaled buy too.
def test_recycled_budget_includes_both_sides_fees():
    fixture = Fixture([[101, 100], [101, 100]], cost=100, cash=0, positions=[1, 0])
    fixture.mark(0, 101)
    identifier = fixture.decision(0, [0, 1])
    fixture.fill(identifier, 1, [0, 1], [0, 0.99], 0, 99.99, 0.99, recycle=True)
    fixture.mark(1, 99)
    report = _verified(fixture.snapshot())
    assert report["total_fees"] == pytest.approx(2)
    assert report["total_traded"] == pytest.approx(200)


# Keep opening buys separate from closing sales and preserve the original full order.
def test_open_buy_close_sell_split_execution():
    fixture = Fixture(
        [[100, 50], [110, 50]], [[100, 50], [90, 60]], cash=50, positions=[1, 0]
    )
    fixture.mark(0, 150)
    identifier = fixture.decision(0, [0, 1])
    fixture.adjust(identifier, 1, "open", [1, 1])
    fixture.fill(identifier, 1, [1, 1], [1, 1], 0, 50, 1)
    fixture.adjust(identifier, 1, "close", [0, 1])
    fixture.fill(identifier, 1, [0, 1], [0, 1], 90, 0, 0, phase="close")
    fixture.mark(1, 150)
    report = _verified(fixture.snapshot())
    assert report["total_traded"] == 140
    assert report["terminal"]["cash"] == 90


# Require every cash-only session even when source prices are unavailable and unused.
def test_all_cash_missing_unheld_prices_and_no_trades():
    fixture = Fixture([[None], [0], [-1]])
    for session in range(3):
        fixture.mark(session, 100)
    report = _verified(fixture.snapshot())
    assert [mark["nav"] for mark in report["marks"]] == [100, 100, 100]
    assert report["total_traded"] == 0


# Preserve missing target and price cells as unfilled observations instead of trades.
@pytest.mark.parametrize(("target", "price"), [(None, 100), (1, None), (1, 0)])
def test_unavailable_instruction_or_price_has_no_fill(target, price):
    fixture = Fixture([[100], [price]], [[100], [100]])
    fixture.mark(0, 100)
    identifier = fixture.decision(0, [target])
    fixture.fill(identifier, 1, [target], [0], 100, 100, 0)
    fixture.mark(1, 100)
    assert _verified(fixture.snapshot())["total_traded"] == 0


# Replay an exit, a cash-only interval, and a later entry without terminal selling.
def test_liquidate_stay_cash_reenter_continuous_account():
    fixture = Fixture([[100], [90], [80], [50]], cash=0, positions=[1])
    fixture.mark(0, 100)
    identifier = fixture.decision(0, [0])
    fixture.fill(identifier, 1, [0], [0], 90, 0, 0)
    fixture.mark(1, 90)
    fixture.mark(2, 90)
    identifier = fixture.decision(2, [1])
    fixture.fill(identifier, 3, [1], [1], 40, 90, 1)
    fixture.mark(3, 90)
    report = _verified(fixture.snapshot())
    assert [mark["cash"] for mark in report["marks"]] == [0, 90, 90, 40]
    assert report["total_traded"] == 140
    assert report["terminal"]["positions"] == [1]


# Retain the exact declared pending evidence without inventing a queue from residuals.
def test_terminal_pending_intentions_are_preserved():
    snapshot = _flat()
    pending = {
        "decision_id": "decision-000002",
        "submitted_units": [2],
        "deferred_units": {"TEST0": 1},
        "event_state": {"baseline_units": [2], "sold_units": [1]},
        "retry": True,
    }
    snapshot["events"][-1]["pending"] = pending
    report = _verified(_rehash(snapshot))
    assert report["terminal"]["pending"] == pending
    assert report["pending_semantics_verified"] is False


# A last-close intention must not silently disappear just because execution is future.
@pytest.mark.parametrize("retained", [False, True])
def test_final_session_decision_requires_explicit_pending_state(retained):
    fixture = Fixture([[100], [100]])
    fixture.mark(0, 100)
    fixture.mark(1, 100)
    identifier = fixture.decision(1, [1])
    snapshot = fixture.snapshot(
        {"decision_id": identifier, "submitted_units": [1]} if retained else {}
    )
    report = verify_snapshot(snapshot)
    assert report["ok"] is retained
    if not retained:
        assert "missing from terminal pending" in report["errors"][0]


# Let the retained source grid precede the account without demanding fictional marks.
def test_source_grid_can_precede_opening_account():
    fixture = Fixture([[90], [95], [100]], opening=1)
    fixture.mark(1, 100)
    fixture.mark(2, 100)
    report = _verified(fixture.snapshot())
    assert [mark["session_index"] for mark in report["marks"]] == [1, 2]


# Verify raw adjustment factors without adding a second dividend or split cash credit.
def test_raw_adjustment_convention():
    snapshot = _flat()
    snapshot["prices"]["raw"] = {
        "open": [[200], [200]],
        "close": [[200], [200]],
        "adjusted_close": [[100], [100]],
    }
    _verified(_rehash(snapshot))
    snapshot["prices"]["raw"]["open"][1][0] = 201
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"]
    assert "adjusted open" in report["errors"][0]


# Corroborate an explicitly supplied adjusted-close source even without raw opens.
def test_partial_raw_source_is_checked_without_inventing_missing_fields():
    snapshot = _flat()
    snapshot["prices"]["raw"] = {"adjusted_close": [[100], [100]]}
    _verified(_rehash(snapshot))
    snapshot["prices"]["raw"]["adjusted_close"][1][0] = 99
    assert not verify_snapshot(_rehash(snapshot))["ok"]


# Reject tampered fill quantities, prices, funding, and costs after valid rehashing.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prices", [101]),
        ("prices", [100 + 1e-11]),
        ("submitted_units", [2]),
        ("positions_before", [0.1]),
        ("cash_before", 102),
        ("positions_after", [1.1]),
        ("cash_after", 1),
        ("buy_budget", 100),
        ("scale", 0.9),
        ("filled_units", [0.9]),
        ("notional", [99]),
        ("fees", [0]),
        ("gross_buys", 99),
        ("gross_sells", 1),
        ("fee_total", 0),
        ("residual_units", [1]),
        ("unfilled_reasons", ["cash_budget_limited"]),
        ("recycle_sells", 1),
        ("decision_id", "decision-999999"),
        ("phase", "auction"),
        ("price_ref", {"file": "other.json", "field": "open", "session_index": 1}),
        ("price_ref", {"file": "prices.json", "field": "close", "session_index": 1}),
        ("price_ref", {"file": "prices.json", "field": "open", "session_index": 0}),
    ],
)
def test_rehashed_fill_tampering_fails(field, value):
    snapshot = _flat()
    snapshot["events"][3][field] = value
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"], field
    assert report["integrity_verified"]
    assert not report["accounting_verified"]


# Reject hidden deposits, vanished holdings, invented liquidation, and wrong turnover.
@pytest.mark.parametrize(
    ("index", "field", "value"),
    [
        (4, "cash", 1.9),
        (4, "positions", [0]),
        (4, "nav", 101.9),
        (4, "traded", 200),
        (5, "cash", 100.9),
        (5, "positions", [0]),
        (5, "traded", 200),
        (5, "pending", {"retry": 1}),
        (5, "pending", {"decision_id": "unknown"}),
        (5, "pending", {"deferred_units": {"UNKNOWN": 1}}),
        (5, "pending", {"deferred_units": {"TEST0": -1}}),
        (5, "pending", {"event_state": {"baseline_units": [1]}}),
        (5, "pending", {"merger_cash": 100}),
    ],
)
def test_rehashed_state_and_terminal_tampering_fails(index, field, value):
    snapshot = _flat()
    snapshot["events"][index][field] = value
    assert not verify_snapshot(_rehash(snapshot))["ok"]


# Detect source changes even when event copies and the payload's new hashes look valid.
def test_rehashed_source_open_change_cannot_hide_behind_copied_fill_prices():
    snapshot = _flat()
    snapshot["prices"]["open"][1][0] = 101
    assert snapshot["events"][3]["prices"] == [100]
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"]
    assert "immutable row" in report["errors"][0]


# Refuse borrowing and short holdings even if they appear in the opening endowment.
@pytest.mark.parametrize(("field", "value"), [("cash", -1), ("positions", [-1])])
def test_negative_opening_state_fails(field, value):
    snapshot = _flat()
    snapshot["events"][0][field] = value
    assert not verify_snapshot(_rehash(snapshot))["ok"]


# Ensure no missing held price becomes a fake loss, zero value, or fabricated cash.
@pytest.mark.parametrize("price", [None, 0, -1])
def test_missing_held_close_fails(price):
    snapshot = _flat()
    snapshot["prices"]["close"][1][0] = price
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"]
    assert "held closing mark unavailable" in report["errors"][0]


# Preserve a producer's unavailable NAV evidence while explicitly refusing success.
def test_declared_unavailable_held_mark_never_verifies():
    snapshot = _flat()
    snapshot["prices"]["close"][1][0] = None
    snapshot["events"][4].update(nav=None, unavailable_held_symbols=["TEST0"])
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"]
    assert "held closing mark unavailable" in report["errors"][0]


# The missing-price declaration must agree with the immutable prices and positions.
def test_falsely_declared_unavailable_mark_fails():
    snapshot = _flat()
    snapshot["events"][4]["unavailable_held_symbols"] = ["TEST0"]
    assert not verify_snapshot(_rehash(snapshot))["ok"]


# Reject malformed transport identities independently of otherwise valid arithmetic.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seq", 9),
        ("seq", True),
        ("event_id", "event-000099"),
        ("session", "2020-01-01"),
        ("session_index", True),
        ("session_index", 2),
    ],
)
def test_event_identity_tampering_fails(field, value):
    snapshot = _flat()
    snapshot["events"][3][field] = value
    assert not verify_snapshot(_rehash(snapshot))["ok"]


# Reject incomplete runs and every omitted close rather than validating sparse history.
@pytest.mark.parametrize("removed", [1, 4, 5])
def test_missing_initial_final_mark_or_finish_fails(removed):
    snapshot = _flat()
    snapshot["events"].pop(removed)
    assert not verify_snapshot(_resequence(snapshot))["ok"]


# Detect a missing middle mark even when source, event IDs, and final NAV are valid.
def test_missing_middle_cash_mark_fails():
    fixture = Fixture([[100], [100], [100]])
    fixture.mark(0, 100)
    fixture.mark(2, 100)
    report = verify_snapshot(fixture.snapshot())
    assert not report["ok"]
    assert "missing or duplicate daily mark" in report["errors"][0]


# Require all retained post-opening source sessions rather than accepting an early end.
def test_early_finish_cannot_shorten_manifest_source_grid():
    snapshot = _flat()
    snapshot["manifest"]["sessions"].append("2020-01-06")
    snapshot["prices"]["open"].append([100])
    snapshot["prices"]["close"].append([100])
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"]
    assert "complete daily marks" in report["errors"][0]


# Reject same-session execution even when a forged sequence keeps the close first.
def test_fill_cannot_use_its_decision_session():
    snapshot = _flat()
    snapshot["events"][3].update(session="2020-01-02", session_index=0)
    snapshot["events"][3]["price_ref"]["session_index"] = 0
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"]
    assert "does not follow decision" in report["errors"][0]


# Refuse repeated execution and unsupported entitlement events after hash verification.
@pytest.mark.parametrize(
    "kind",
    ["duplicate_fill", "duplicate_mark", "duplicate_open", "conversion", "post_finish"],
)
def test_duplicate_and_unsupported_events_fail(kind):
    snapshot = _flat()
    if kind == "duplicate_fill":
        snapshot["events"].insert(4, copy.deepcopy(snapshot["events"][3]))
    elif kind == "duplicate_mark":
        snapshot["events"].insert(5, copy.deepcopy(snapshot["events"][4]))
    elif kind == "duplicate_open":
        snapshot["events"].insert(1, copy.deepcopy(snapshot["events"][0]))
    elif kind == "conversion":
        snapshot["events"][3]["type"] = "terminal_entitlement"
    else:
        snapshot["events"].append(copy.deepcopy(snapshot["events"][4]))
    assert not verify_snapshot(_resequence(snapshot))["ok"]


# A failure marker or a still-recording manifest can never produce complete success.
@pytest.mark.parametrize("status", ["failed", "recording"])
def test_failed_and_recording_histories_fail(status):
    snapshot = _flat()
    snapshot["manifest"]["status"] = status
    snapshot["events"][-1]["status"] = status
    report = verify_snapshot(_rehash(snapshot))
    assert not report["ok"]
    assert not report["complete"]


# Refuse unsupported economic claims and malformed manifest calendar or identities.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sessions", ["2020-01-03", "2020-01-02"]),
        ("sessions", ["2020-01-02", "2020-01-02"]),
        ("symbols", ["TEST0", "TEST0"]),
        ("symbols", [""]),
        ("cost_bps", True),
        ("cost_bps", -1),
        ("cost_bps", 10000),
        ("cash_yield", 0.01),
        ("price_basis", "broker_shares"),
        ("cash_model", "T+1"),
        ("adoption_eligible", True),
        ("historical_availability_verified", True),
        ("run_id", ""),
    ],
)
def test_invalid_manifest_fails(field, value):
    snapshot = _flat()
    snapshot["manifest"][field] = value
    assert not verify_snapshot(snapshot)["ok"]


# Reject malformed source matrices and nonfinite JSON rather than sanitizing evidence.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", [[100]]),
        ("close", [[100], [True]]),
        ("raw", {}),
        ("raw", {"unknown": [[100], [100]]}),
    ],
)
def test_invalid_source_fails(field, value):
    snapshot = _flat()
    snapshot["prices"][field] = value
    assert not verify_snapshot(_rehash(snapshot))["ok"]


# Invalid floating-point source cells must be explicit nulls rather than NaN literals.
def test_nonfinite_in_memory_payload_fails_without_throwing():
    snapshot = _flat()
    snapshot["prices"]["open"][1][0] = float("nan")
    assert not verify_snapshot(snapshot)["ok"]


# Hash and byte-count metadata independently bind the source and event payloads.
@pytest.mark.parametrize(
    ("name", "field", "value"),
    [
        ("prices.json", "sha256", "0" * 64),
        ("events.json", "sha256", "0" * 64),
        ("events.json", "bytes", 1),
        ("prices.json", "bytes", True),
    ],
)
def test_hash_or_byte_count_tampering_fails(name, field, value):
    snapshot = _flat()
    snapshot["manifest"]["files"][name][field] = value
    report = verify_snapshot(snapshot)
    assert not report["ok"]
    assert not report["integrity_verified"]


# Write temporary JSON fixtures without supplying executable data to the loader.
def _archive(tmp_path, snapshot):
    folder = tmp_path / "archive"
    folder.mkdir()
    for name in ("manifest", "prices", "events"):
        (folder / f"{name}.json").write_bytes(_bytes(snapshot[name]))
    return folder


# Exercise both supported archive entry points using exact known source bytes.
def test_archive_directory_and_manifest_entrypoints(tmp_path):
    folder = _archive(tmp_path, _flat())
    assert verify_archive(folder)["ok"]
    assert verify_archive(folder / "manifest.json")["ok"]


# Refuse even whitespace-only byte changes to the archived event artifact.
@pytest.mark.parametrize("name", ["prices.json", "events.json", "manifest.json"])
def test_changed_archive_bytes_fail(tmp_path, name):
    folder = _archive(tmp_path, _flat())
    path = folder / name
    path.write_bytes(path.read_bytes() + b" ")
    assert not verify_archive(folder)["ok"]


# Prevent local file references from escaping through symlinks or manifest file names.
def test_archive_symlinks_and_unexpected_file_references_fail(tmp_path):
    folder = _archive(tmp_path, _flat())
    link = tmp_path / "link"
    link.symlink_to(folder, target_is_directory=True)
    assert not verify_archive(link)["ok"]
    target = tmp_path / "external-prices.json"
    original = folder / "prices.json"
    original.rename(target)
    original.symlink_to(target)
    assert not verify_archive(folder)["ok"]


# Refuse parent traversal and arbitrary manifest file entries without opening them.
def test_archive_parent_traversal_and_extra_files_fail(tmp_path):
    folder = _archive(tmp_path, _flat())
    assert not verify_archive(folder / ".." / "archive")["ok"]
    snapshot = _flat()
    snapshot["manifest"]["files"]["../../payload.pkl"] = {
        "sha256": "0" * 64,
        "bytes": 1,
    }
    assert not verify_snapshot(snapshot)["ok"]


# Refuse duplicate JSON keys instead of silently accepting the parser's last value.
def test_duplicate_json_keys_fail(tmp_path):
    folder = _archive(tmp_path, _flat())
    path = folder / "manifest.json"
    path.write_bytes(b'{"schema":"forged",' + path.read_bytes()[1:])
    report = verify_archive(folder)
    assert not report["ok"]
    assert "duplicate JSON key" in report["errors"][0]


# Never open arbitrary paths supplied as provenance, even when accounting is valid.
def test_provenance_paths_are_inert_metadata(tmp_path):
    snapshot = _flat()
    snapshot["manifest"]["provenance"] = {
        "source": "../../nonexistent.pkl",
        "executable": "do not load",
    }
    folder = _archive(tmp_path, snapshot)
    assert verify_archive(folder)["ok"]


# Return a structured failure for absent archives or malformed public API input.
def test_bad_entrypoints_fail_without_throwing(tmp_path):
    assert not verify_archive(tmp_path / "missing")["ok"]
    assert not verify_snapshot(None)["ok"]
    assert not verify_payload({}, [], {})["ok"]
