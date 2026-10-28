"""Closed label vocabularies keep their exact wire spellings and refuse the rest."""

import hashlib
import json

import pytest

from backend.market import labels
from backend.market.labels import as_member, parse, values

# Every vocabulary with the exact strings its field has always carried on disk,
# in receipts, in hashes and over the API. Casing differs by field on purpose.
WIRE = {
    labels.OrderSide: ["buy", "sell"],
    labels.Action: ["Buy", "Sell", "Hold"],
    labels.DeskAction: ["buy", "add", "hold", "trim", "sell", "blocked", "uncovered"],
    labels.GradeSignal: ["buy", "hold", "sell", "avoid", "unavailable"],
    labels.TradeAction: ["BUY", "ADD", "TRIM", "SELL"],
    labels.AllocationAction: ["BUY", "HOLD", "SELL"],
    labels.TimingState: ["execute", "wait", "unavailable", "no_trade"],
    labels.Grade: ["A+", "A", "B", "C"],
    labels.ExecutionTiming: ["next_open", "dip_or_close", "decision_close"],
    labels.BoardTiming: [
        "dip_or_close",
        "next_open",
        "decision_close",
        "event",
        "close",
    ],
    labels.OrderLeg: [
        "reset",
        "reset-exit",
        "exit",
        "reinvest",
        "entry",
        "deferred",
        "redeploy",
        "event",
        "plan",
    ],
    labels.EntryTimingState: ["pre-open", "waiting", "triggered", "close", "closed"],
    labels.PlanDay: [
        "rebalance",
        "hold",
        "entries",
        "exits",
        "deferred buys",
        "redeploy",
    ],
    labels.TimingEntryRule: ["first_open", "trend_pullback", "breakout_retest"],
    labels.TimingExitRule: ["hold", "structure", "band_trim_then_structure"],
    labels.BacktestPending: ["enter", "stop", "grade"],
    labels.EntryState: ["dip", "breakout", "wait"],
    labels.Verdict: ["buy", "sell", "nothing"],
    labels.VerdictReason: [
        "execute_now",
        "waiting_better_price",
        "at_target",
        "no_allocation",
        "grade_below_a",
        "awaiting_candle",
        "publication_expired",
        "quote_stale",
        "price_unavailable",
        "entry_pending",
    ],
    labels.ExecutionIntent: ["entry", "trim", "exit"],
    labels.ShadowForecastState: ["unavailable", "terminal_attempt", "wait", "execute"],
    labels.IntradayEntryState: [
        "unavailable",
        "wait",
        "setup",
        "entry_ready",
        "invalidated",
        "ambiguous",
        "historical",
        "expired",
    ],
    labels.BriefStance: ["own", "wait", "avoid"],
    labels.ClaimVerdict: ["consistent", "contradicts", "uncertain"],
    labels.InflationPressure: ["easing", "building", "mixed", "unknown"],
    labels.ChartEntry: ["ready", "wait", "avoid", "unavailable"],
    labels.ChartExit: ["review", "hold"],
    labels.ChartPriority: ["high", "medium", "low"],
    labels.ChartConfirmation: ["hold_above", "reclaim_above", "none"],
    labels.GuidanceChange: [
        "raised",
        "lowered",
        "unchanged",
        "not_comparable",
        "not_stated",
    ],
    labels.DemandTrend: ["strengthening", "weakening", "stable", "not_stated"],
    labels.FinancingRisk: ["increasing", "decreasing", "stable", "not_stated"],
    labels.FundingPreviewMode: ["evening", "intraday_research"],
    labels.ExchangePhase: ["pre-market", "open", "post-market", "closed", "unknown"],
    labels.MarketPhase: [
        "pre_market",
        "regular",
        "after_hours",
        "overnight",
        "closed",
        "unknown",
    ],
    labels.QuoteSession: [
        "regular",
        "pre-market",
        "post-market",
        "overnight",
        "closed",
        "unknown",
    ],
    labels.QuoteFeed: ["sip", "iex", "boats", "overnight"],
}


# The table above covers every vocabulary the module defines, so a new one
# cannot be added without stating its wire strings here.
def test_every_vocabulary_is_pinned_to_its_wire_strings():
    defined = {
        value
        for value in vars(labels).values()
        if isinstance(value, type)
        and issubclass(value, labels.StrEnum)
        and value is not labels.StrEnum
    }
    assert defined == set(WIRE)
    for kind, wire in WIRE.items():
        assert values(kind) == wire, kind


# A stored string reads back as its member, and the member writes the same bytes.
@pytest.mark.parametrize("kind", list(WIRE), ids=lambda kind: kind.__name__)
def test_members_round_trip_the_exact_stored_strings(kind):
    for raw in WIRE[kind]:
        member = kind(raw)
        assert member is parse(kind, raw) is as_member(kind, raw) is kind(member)
        assert member == raw
        assert hash(member) == hash(raw)
        assert type(member.value) is str
        assert member.value == raw
        assert str(member) == f"{member}" == f"{member:>0}" == raw
        assert json.dumps({member: [member]}) == json.dumps({raw: [raw]})
        assert (
            hashlib.sha256(json.dumps(member, sort_keys=True).encode()).hexdigest()
            == hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        )
        # A dict keyed by wire strings is read with members, and the reverse.
        assert {raw: 1}[member] == 1
        assert {member: 1}[raw] == 1


# Anything outside a vocabulary fails loudly; casing is part of the spelling.
@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        (labels.OrderSide, "BUY"),
        (labels.OrderSide, "Buy"),
        (labels.OrderSide, "sell_short"),
        (labels.Action, "buy"),
        (labels.Action, "Trim"),
        (labels.TradeAction, "buy"),
        (labels.TradeAction, "HOLD"),
        (labels.DeskAction, "Hold"),
        (labels.GradeSignal, "exit"),
        (labels.TimingState, "executed"),
        (labels.Grade, "a"),
        (labels.Grade, "A-"),
        (labels.BriefStance, "buy"),
        (labels.ChartEntry, "Ready"),
        (labels.OrderSide, None),
        (labels.OrderSide, ""),
        (labels.OrderSide, 1),
        (labels.OrderSide, ["buy"]),
    ],
)
def test_unknown_labels_fail(kind, raw):
    with pytest.raises(ValueError, match="is not a valid"):
        kind(raw)
    with pytest.raises(ValueError, match="is not a valid"):
        parse(kind, raw)
    with pytest.raises(ValueError, match="^side or action wrong$"):
        parse(kind, raw, "side or action wrong")
    assert as_member(kind, raw) is None
    assert raw not in kind


# Three vocabularies are written by source-bound modules this repository does
# not edit for labels (`intraday_orders`, `entry_timing`): their enums must
# keep naming exactly the words those producers write.
def test_enums_of_source_bound_producers_match_their_words():
    from backend.agents.trading.desk import intraday_orders
    from backend.market import entry_timing

    legs = {leg for _, leg, _ in intraday_orders._LEGS} | {"event", "plan"}
    assert legs == set(values(labels.OrderLeg))
    rows = [
        {"execution_timing": intraday_orders.INTRADAY_TIMING},
        {"event_id": "fomc-1"},
        {"priority": True},
        {"execution_timing": "next_open"},
        {"side": "buy"},
        {"side": "sell"},
        {"execution_timing": "decision_close", "event_id": "fomc-1"},
    ]
    assert {intraday_orders.timing_of(row) for row in rows} <= set(
        values(labels.BoardTiming)
    )
    assert labels.ExecutionTiming(intraday_orders.INTRADAY_TIMING)
    states = (
        entry_timing.PRE_OPEN,
        entry_timing.WAITING,
        entry_timing.TRIGGERED,
        entry_timing.CLOSE,
        entry_timing.CLOSED,
    )
    assert list(states) == values(labels.EntryTimingState)
