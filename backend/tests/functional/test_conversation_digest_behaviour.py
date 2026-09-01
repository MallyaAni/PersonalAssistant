"""Does the rolling conversation digest preserve meaning without inventing it?

The deterministic digest tests prove bounds and fallback wiring with a fake
model. They cannot prove that the real prompt keeps the details later turns
depend on. These cases exercise the actual reasoning model and assert on the
record it writes, because a plausible but false digest is worse than truncation.
"""

from backend.config.settings import settings
from backend.memory.digest import summarise


# Unique decisions and constraints must survive compression exactly enough to use.
def test_digest_preserves_the_details_a_later_turn_needs(llm, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_DIGEST_MODEL_ENABLED", True)
    turns = [
        {
            "query": "Use project code CITRINE-482 for the Lisbon plan.",
            "response": "Understood.",
        },
        {
            "query": (
                "We decided to travel by train and keep the budget under 417 euros."
            ),
            "response": "I'll use those constraints.",
        },
    ]

    result = summarise(llm, "", turns)

    assert result is not None
    lowered = result.casefold()
    assert "citrine-482" in lowered, result
    assert "lisbon" in lowered, result
    assert "train" in lowered, result
    assert "417" in result, result


# Unresolved conflicting statements must remain visible instead of being reconciled.
def test_digest_preserves_an_unresolved_conflict(llm, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_DIGEST_MODEL_ENABLED", True)
    turns = [
        {
            "query": "The launch window is marker ORCHID-17.",
            "response": "Noted.",
        },
        {
            "query": (
                "The launch window is marker TOPAZ-93 instead, but do not choose "
                "between those yet because the team has not resolved the conflict."
            ),
            "response": "The conflict is still open.",
        },
    ]

    result = summarise(llm, "", turns)

    assert result is not None
    lowered = result.casefold()
    assert "orchid-17" in lowered, result
    assert "topaz-93" in lowered, result
    assert any(
        word in lowered for word in ("conflict", "unresolved", "unclear")
    ), result


# A working thread names its artifact once and then works on it across many
# turns that never restate it; the digest must carry the artifact and what was
# decided about it, not just the surrounding chatter.
def test_digest_keeps_the_artifact_and_the_decision_about_it(llm, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_DIGEST_MODEL_ENABLED", True)
    turns = [
        {
            "query": "Let's refactor the retry loop in backend/services/poller.py so it stops double-counting.",
            "response": "I'll look at poller.py's retry loop.",
        },
        {
            "query": "Use exponential backoff capped at 8 seconds, and keep the counter in the worker, not the job.",
            "response": "Got it - exponential backoff, cap 8s, counter in the worker.",
        },
    ]

    result = summarise(llm, "", turns)

    assert result is not None
    lowered = result.casefold()
    assert "poller.py" in lowered, result
    assert "backoff" in lowered, result
    assert "8" in result, result
    assert "worker" in lowered, result
