"""Closed label vocabularies keep their exact wire spellings and refuse the rest."""

import hashlib
import json

import httpx
import pytest

from backend.agents.trading import current_setup
from backend.agents.trading.desk import economist, narrative
from backend.core.llm import OpenAICompatibleInferenceProvider, StrictSchema
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


# The OpenAI-compatible provider marks a strict schema's request strict and
# leaves every other caller's request byte for byte as it was.
def test_only_a_strict_schema_is_sent_strict():
    sent = []

    # Answer like vLLM and keep the request body the provider sent.
    def answer(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"x": "a"}'}}]}
        )

    provider = OpenAICompatibleInferenceProvider(
        "http://engine",
        "model",
        reasoning_effort="",
        client=httpx.Client(transport=httpx.MockTransport(answer)),
    )
    schema = {"title": "X", "type": "object"}
    messages = [{"role": "user", "content": "q"}]
    provider.chat(messages, 10, schema, 0.0)
    provider.chat(messages, 10, StrictSchema(schema), 0.0)
    assert sent[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "X", "schema": schema},
    }
    assert sent[1]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "X", "schema": schema, "strict": True},
    }


# A scripted engine for the label-returning agents: it records each request
# and answers with whatever label the test supplies, so the test can show the
# request carries the enum and the agent refuses a word outside it.
def _engine(reply):
    sent = []

    # Return the scripted JSON reply to every request.
    def answer(request):
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(
            200,
            json={
                "model": "model",
                "choices": [
                    {
                        "message": {"content": json.dumps(reply(body))},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    provider = OpenAICompatibleInferenceProvider(
        "http://engine",
        "model",
        reasoning_effort="",
        client=httpx.Client(transport=httpx.MockTransport(answer)),
    )
    return provider, sent


# The strict JSON schema the request carried, which the engine enforces.
def _strict_schema(body):
    shape = body["response_format"]
    assert shape["type"] == "json_schema"
    assert shape["json_schema"]["strict"] is True
    return shape["json_schema"]["schema"]


# The brief's stance is enumerated in a strict request; a stance outside the
# enum (which the engine would never emit) is refused as a bad shape.
def test_brief_stance_is_schema_enforced_and_other_stances_are_refused():
    brief = {
        "stance": "buy",
        "verdict": "A reason here",
        "reasoning": "Twenty or more characters of reasoning.",
        "risks": "Some risk",
        "watch": "Something to watch",
    }
    provider, sent = _engine(lambda body: brief)
    result, failure = narrative.DeskNarrator(provider).brief_outcome("Grade: A+.", "A+")
    schema = _strict_schema(sent[0])
    assert schema["properties"]["stance"]["enum"] == ["own", "wait", "avoid"]
    assert result is None
    assert failure["reason"].startswith(narrative.BAD_SHAPE)

    provider, sent = _engine(lambda body: {**brief, "stance": "own"})
    written, _ = narrative.DeskNarrator(provider)._write_brief("Grade: A+.")
    assert written.stance is labels.BriefStance.OWN


# The checker's claim verdicts are enumerated in a strict request; a verdict
# outside the enum makes that check attempt count for nothing.
def test_brief_check_verdict_is_schema_enforced_and_other_verdicts_are_refused():
    brief = narrative.DeskBrief(
        labels.BriefStance.OWN, "verdict", "reasoning text", "risks", "watch"
    )
    provider, sent = _engine(
        lambda body: {"claims": [{"claim": "c", "fact": "f", "verdict": "fine"}]}
    )
    assert narrative.DeskNarrator(provider)._check("Grade: A+.", brief) == []
    schema = _strict_schema(sent[0])
    verdict = schema["properties"]["claims"]["items"]["properties"]["verdict"]
    assert verdict["enum"] == ["consistent", "contradicts", "uncertain"]

    provider, _ = _engine(
        lambda body: {"claims": [{"claim": "c", "fact": "f", "verdict": "consistent"}]}
    )
    assert narrative.DeskNarrator(provider)._check("Grade: A+.", brief) is None


# The economist's pressure is enumerated in a strict request; another word
# falls back to the unavailable reading.
def test_economist_pressure_is_schema_enforced_and_other_words_fall_back():
    facts = [{"id": "cpi", "status": "available", "value": 1}]
    provider, sent = _engine(lambda body: {"pressure": "hot", "evidence_ids": ["cpi"]})
    result = economist.assess(facts, provider)
    assert _strict_schema(sent[0])["properties"]["pressure"]["enum"] == [
        "easing",
        "building",
        "mixed",
        "unknown",
    ]
    assert result["status"] == "unavailable"
    assert result["pressure"] == "unknown"

    reply = {"pressure": "building", "evidence_ids": ["cpi"]}
    provider, _ = _engine(lambda body: reply)
    result = economist.assess(facts, provider)
    assert result["pressure"] is labels.InflationPressure.BUILDING
    assert json.dumps(result["pressure"]) == '"building"'


# Chart judgments come back as one strict structured output whose labels are
# enumerated; a judgment outside a vocabulary fails the whole batch closed.
def test_chart_setup_labels_are_schema_enforced_and_other_labels_are_refused():
    fact = {
        "ticker": "AAA",
        "entry_permitted": True,
        "candles": [{"close": 1}],
        "levels": {"vwap": {"label": "VWAP", "price": 10}},
    }
    row = {
        "ticker": "AAA",
        "entry": "ready",
        "exit": "hold",
        "entry_priority": "high",
        "exit_priority": "low",
        "reason": "Buyers defended the level and reclaimed it cleanly.",
        "confirmation": "hold_above",
        "confirmation_ref": "vwap",
        "invalidation_ref": "vwap",
    }
    provider, sent = _engine(lambda body: {"rows": {"AAA": row}})
    assert current_setup.assess([fact], provider) == [row]
    properties = _strict_schema(sent[0])["properties"]["rows"]["properties"]["AAA"][
        "properties"
    ]
    assert properties["entry"]["enum"] == ["ready", "wait", "avoid"]
    assert properties["exit"]["enum"] == ["review", "hold"]
    assert properties["confirmation"]["enum"] == ["hold_above", "reclaim_above", "none"]
    assert "tools" not in sent[0]
    for key, word in (("entry", "buy"), ("exit", "sell"), ("exit_priority", "max")):
        bad = {"rows": {"AAA": {**row, key: word}}}
        provider, _ = _engine(lambda body, bad=bad: bad)
        assert current_setup.assess([fact], provider) == []


# `decision_view.Action` is the labels module's `Action`, not a second class
# with the same words: the view compares rows built elsewhere by identity.
def test_decision_view_action_is_the_one_action_type():
    from backend.market import decision_view

    assert decision_view.Action is labels.Action
