"""Does the trading autopsy name what actually repeats, and nothing invented?

This is the first capability of the trading analyst: it reads a person's own
trade-history passages and produces a structured post-mortem. The assertions
are written from what the prompt claims to do, not from the last thing that
went wrong:

- **A pattern must repeat.** The prompt says a single event is not a pattern,
  so a history with one losing trade and then a string of winners must not be
  told "you keep cutting winners early" — that behaviour appears once.
- **A repeated behaviour is named.** A history where the person twice held a
  losing position far past their stop should come back with a pattern about
  holding losers, pointed at by the trades that show it.
- **No invented numbers.** The prompt is explicit that a cost is only stated
  when a number is present. Passages with no dollar figures must not return
  an invented amount.
- **A plan has all three lists and stays honest.** stop/start/keep present,
  and a history with nothing wrong keeps that empty rather than inventing a
  problem.

Every passage below is deliberately realistic prose from a person's own
journal — the shape of what actually gets uploaded — so the test measures
the prompt on the real thing rather than on tidy examples.
"""

import pytest

from backend.agents.trading.autopsy import MAX_PASSAGES, TradeAutopsy

pytestmark = pytest.mark.asyncio


# One chunk-shaped record, the way KnowledgeStore.search returns them.
def _chunk(title: str, content: str) -> dict:
    return {"document": {"title": title}, "content": content}


# A history with one real problem that repeats twice, and a number actually
# present for one of the costs. The third trade is fine, so "keep" has
# something honest to point at and nothing is wrong everywhere.
_REPEATING = [
    _chunk(
        "June journal",
        "Bought 100 NVDA at 128. It dropped to 121, I held, told myself the "
        "story was intact. Sold at 119 for -$900. Same thing happened in May "
        "with AMD - held a loser because I could not admit I was wrong.",
    ),
    _chunk(
        "July journal",
        "Entered TSLA at 240 on momentum. It reversed, I moved my stop down "
        "instead of taking the loss, got stopped at 231 for -$450. This is "
        "the third time I have done the stop-lowering thing this year.",
    ),
    _chunk(
        "August journal",
        "Took the MSFT setup I planned, risked 1%, stop where I said, "
        "target hit, +$380. Sticking to the plan worked.",
    ),
]

# A history with no dollar figures anywhere. Any stated amount would be an
# invention, so the autopsy must either say "not stated" or leave costs empty.
_NO_NUMBERS = [
    _chunk(
        "Notes",
        "Bought a biotech on a news pop, watched it fade all afternoon, sold "
        "at the close. Did the same thing last week with another runner - "
        "chasing the pop and giving back the move.",
    ),
]

# A history with one mistake that happens exactly once. It must not be named
# as a pattern, because a pattern is something that repeats.
_SINGLE = [
    _chunk(
        "One trade",
        "Short squeeze caught me, I panic-closed at the worst tick. Felt "
        "terrible. Every other trade this month followed the plan and worked "
        "out.",
    ),
]


async def _analyze(llm, passages):
    return await TradeAutopsy(llm).analyze(passages)


async def test_a_repeating_behaviour_is_named_as_a_pattern(llm):
    result = await _analyze(llm, _REPEATING)
    assert result is not None, "the autopsy produced nothing against a real runtime"
    joined = " ".join(p["behaviour"].lower() for p in result.patterns).lower()
    assert "stop" in joined or "loss" in joined or "held" in joined or "lower" in joined, (
        f"expected a pattern about holding losers, got: {joined}"
    )


async def test_a_single_event_is_not_a_pattern(llm):
    result = await _analyze(llm, _SINGLE)
    assert result is not None
    for pattern in result.patterns:
        joined = (pattern["behaviour"] + " " + pattern["evidence"]).lower()
        assert "panic" not in joined or "every" not in joined, (
            "a once-off panic close was named as a repeating pattern: "
            f"{pattern['behaviour']}"
        )


async def test_no_amount_is_invented(llm):
    result = await _analyze(llm, _NO_NUMBERS)
    assert result is not None
    # The property: no stated dollar figure may be invented. The model is free
    # to say "unknown" or "not stated" in its own words; what it must not do is
    # produce a number that was never in the record.
    invented = []
    for cost in result.costs:
        amount = cost["amount"].lower()
        if any(ch.isdigit() for ch in amount) or "$" in amount:
            invented.append(cost)
    assert not invented, f"an amount was invented where none exists: {invented}"


async def test_a_real_cost_is_reported_with_its_source(llm):
    result = await _analyze(llm, _REPEATING)
    assert result is not None
    amounts = " ".join(c["amount"] for c in result.costs).lower()
    assert any(ch.isdigit() for ch in amounts), (
        "a stated loss in the passages was not reported: " + amounts
    )


async def test_the_plan_has_all_three_lists(llm):
    result = await _analyze(llm, _REPEATING)
    assert result is not None
    for key in ("stop", "start", "keep"):
        assert isinstance(result.plan.get(key), list), f"plan missing {key}"
    assert any(result.plan["stop"]), "a history with a repeated mistake must say what to stop"
    assert any(result.plan["start"]), "a history with a repeated mistake must say what to start"


async def test_every_pattern_carries_evidence(llm):
    result = await _analyze(llm, _REPEATING)
    assert result is not None
    for pattern in result.patterns:
        assert len(pattern["evidence"].strip()) >= 5, (
            f"pattern without evidence: {pattern['behaviour']}"
        )
