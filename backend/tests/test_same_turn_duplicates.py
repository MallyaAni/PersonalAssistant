"""Two fact candidates from one turn that say the same thing are saved once,
judged by the predicate with its subject normalised away - not by vectors,
which cannot tell "Ani is female"/"The user is female" (0.278 apart) from
"Ani is female"/"Ani is a dentist" (0.136)."""
import pytest

from backend.services.conversation_service import ConversationService, _predicate_key

pytestmark = pytest.mark.asyncio


def _service():
    return ConversationService.__new__(ConversationService)


def test_predicate_keys_drop_the_subject():
    assert _predicate_key("The user is female.") == "is female"
    assert _predicate_key("Ani is female", "Ani") == "is female"
    assert _predicate_key("Ani Mallya's dentist is Dr Lee", "Ani Mallya") == "dentist is dr lee"
    assert _predicate_key("I am allergic to peanuts") == "allergic to peanuts"
    assert _predicate_key("Ani is a dentist", "Ani") != _predicate_key("Ani is female", "Ani")


async def test_the_same_fact_phrased_twice_keeps_the_named_one():
    kept = await _service()._without_same_turn_duplicates(
        (
            {"kind": "semantic_fact", "content": "The user is female."},
            {"kind": "semantic_fact", "content": "Ani is female"},
        ),
        "Ani",
    )
    assert [c["content"] for c in kept] == ["Ani is female"]


async def test_different_facts_are_both_kept():
    kept = await _service()._without_same_turn_duplicates(
        (
            {"kind": "semantic_fact", "content": "Ani is female"},
            {"kind": "semantic_fact", "content": "Ani is a dentist"},
        ),
        "Ani",
    )
    assert len(kept) == 2


async def test_non_fact_candidates_pass_through():
    candidates = ({"kind": "preferred_name", "value": "Ani"}, {"kind": "semantic_fact", "content": "x"})
    assert await _service()._without_same_turn_duplicates(candidates) == candidates
