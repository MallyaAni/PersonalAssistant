"""Compression, with truncation underneath it.

The bound shipped first and on its own, so this layer can fail without the old
unbounded growth returning. That ordering is the point: a summariser layered
onto an unbounded digest would have turned every model outage into unbounded
growth again.

So most of what is pinned here is the falling back. A bad summary is worse than
no summary - truncation drops material honestly, while a weak or broken model
invents a tidy narrative that then enters every later prompt indistinguishable
from something the user actually said.
"""

import pytest

from backend.config.settings import settings
from backend.memory.digest import summarise


class Model:
    def __init__(self, answer: str = "They are planning a trip in July."):
        self.answer = answer
        self.prompts: list[str] = []

    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        self.prompts.append(prompt)
        return self.answer


TURNS = [{"query": "I want to visit Lisbon", "response": "A fine choice."}]


@pytest.fixture
def digest_enabled():
    original = settings.MEMORY_DIGEST_MODEL_ENABLED
    settings.MEMORY_DIGEST_MODEL_ENABLED = True
    yield
    settings.MEMORY_DIGEST_MODEL_ENABLED = original


def test_a_good_answer_is_used(digest_enabled):
    assert summarise(Model(), "", TURNS) == "They are planning a trip in July."


# Every one of these must return None so the caller keeps its truncation,
# rather than raising into a turn the user has already been answered on.
def test_a_missing_client_falls_back(digest_enabled):
    assert summarise(None, "", TURNS) is None


def test_a_failing_model_falls_back(digest_enabled):
    class Broken:
        def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
            raise RuntimeError("engine unreachable")

    assert summarise(Broken(), "", TURNS) is None


# A reasoning model that spends its budget thinking returns an empty string
# rather than a short answer. That cost one reply in six earlier the same day,
# and here it must not silently become an empty digest.
def test_an_empty_answer_falls_back(digest_enabled):
    assert summarise(Model("   "), "", TURNS) is None


# Compression that did not compress means the instruction was ignored, and an
# over-long digest is the defect this replaces. Truncation is safer than trust.
def test_an_answer_that_ignored_the_length_limit_falls_back(digest_enabled):
    runaway = " ".join(["word"] * (settings.MEMORY_DIGEST_MAX_WORDS * 2 + 10))

    assert summarise(Model(runaway), "", TURNS) is None


def test_an_answer_at_the_limit_is_still_accepted(digest_enabled):
    allowed = " ".join(["word"] * settings.MEMORY_DIGEST_MAX_WORDS)

    assert summarise(Model(allowed), "", TURNS) == allowed


def test_the_switch_turns_compression_off():
    original = settings.MEMORY_DIGEST_MODEL_ENABLED
    settings.MEMORY_DIGEST_MODEL_ENABLED = False
    try:
        assert summarise(Model(), "", TURNS) is None
    finally:
        settings.MEMORY_DIGEST_MODEL_ENABLED = original


def test_nothing_to_compress_is_not_a_call(digest_enabled):
    model = Model()
    assert summarise(model, "", []) is None
    assert model.prompts == []


# The earlier notes are offered for replacement, not for appending - appending
# is exactly what grew without bound before.
def test_earlier_notes_are_offered_as_something_to_replace(digest_enabled):
    model = Model()

    summarise(model, "They live in Leeds.", TURNS)

    assert "They live in Leeds." in model.prompts[0]
    assert "replace" in model.prompts[0]


def test_the_material_reaches_the_prompt(digest_enabled):
    model = Model()

    summarise(model, "", TURNS)

    assert "I want to visit Lisbon" in model.prompts[0]


# The instruction that matters most: a digest is read later as a record, so an
# invented detail becomes indistinguishable from something that was said.
def test_the_prompt_forbids_invention(digest_enabled):
    model = Model()

    summarise(model, "", TURNS)

    assert "Do not add anything" in model.prompts[0]
