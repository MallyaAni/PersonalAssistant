"""No decision budget may sit in the reasoning-truncation zone.

A reasoning model spends part of any token budget thinking before it answers.
A budget sized for the answer alone therefore guarantees truncation mid-thought
- and the two engines used here fail that differently, both badly. ds4-server
puts the truncated thinking into `content`, so the caller parses monologue as
an answer; vLLM returns an empty string. Measured on the reply path: at 1,024
tokens one reply in six came back empty; image intent at 16 tokens produced
"unparseable content on every upload" and was misdiagnosed as a model
capability problem.

These budgets run on the 4B today, which does not reason, so the headroom is
free: max_tokens is a ceiling, not a target, and the 4B stops when its answer
is done. What the floor buys is that moving any of these callers to a
reasoning engine - which MAIN_LLM_STRUCTURED_OUTPUT exists to do in one flip -
cannot silently re-arm the trap.
"""

from backend.config.settings import settings

# Below this a reasoning model's thinking alone can exhaust the budget. The
# reply path needed 4,096 for prose; a bounded JSON decision needs less, but
# observed thinking bursts of several hundred tokens put the floor here.
_REASONING_SAFE_FLOOR = 1_024


def test_every_decision_budget_clears_the_thinking_floor():
    budgets = {
        "IMAGE_INTENT_MAX_TOKENS": settings.IMAGE_INTENT_MAX_TOKENS,
        "MEMORY_PROPOSAL_MAX_TOKENS": settings.MEMORY_PROPOSAL_MAX_TOKENS,
        "VISION_SEARCH_DECISION_MAX_TOKENS": (
            settings.VISION_SEARCH_DECISION_MAX_TOKENS
        ),
        "ROUTING_DECISION_MAX_TOKENS": settings.ROUTING_DECISION_MAX_TOKENS,
    }

    trapped = {
        name: value for name, value in budgets.items() if value < _REASONING_SAFE_FLOOR
    }
    assert not trapped, (
        f"{trapped} sit in the reasoning-truncation zone: a reasoning model "
        "truncates mid-thought there, which ds4-server surfaces as garbage "
        "content and vLLM as an empty string"
    )


def test_the_routing_call_site_carries_no_bare_number():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "services" / "main_action_selector.py"
    ).read_text(encoding="utf-8")

    assert "settings.ROUTING_DECISION_MAX_TOKENS" in source, (
        "the routing decision budget must come from settings; a bare number "
        "at the call site is the limit-nobody-chose defect class"
    )
