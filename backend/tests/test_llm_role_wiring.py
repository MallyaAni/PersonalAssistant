"""Which model each role resolves to, asserted rather than assumed.

Roles are wired independently so that changing one never silently moves
another, and this is the test that holds that claim. It exists because the
claim was false: promoting `MAIN_LLM_*` to DeepSeek quietly took the bounded
strict-JSON classifiers with it, and image recall began returning nothing
because that engine treats a supplied JSON schema as advisory. Nothing failed
loudly - `VisualMemorySelector` fails closed, so the only symptom was the
assistant no longer remembering pictures it could see moments earlier.
"""

import pytest

from backend.config.settings import settings
from backend.core.dependencies import (
    get_classifier_llm,
    get_place_suggester,
    get_routing_llm_client,
)

_MAIN = "http://main-role.invalid:9000"
_ROUTING = "http://routing-role.invalid:9001"


# Point the two roles at distinguishable endpoints for the duration of a test.
@pytest.fixture
def split_roles():
    original = {
        name: getattr(settings, name)
        for name in (
            "MAIN_LLM_BASE_URL",
            "MAIN_LLM_MODEL",
            "ROUTING_LLM_BASE_URL",
            "ROUTING_LLM_MODEL",
            "SEARCH_CLASSIFIER_MODEL",
        )
    }
    settings.MAIN_LLM_BASE_URL = _MAIN
    settings.MAIN_LLM_MODEL = "main-model"
    settings.ROUTING_LLM_BASE_URL = _ROUTING
    settings.ROUTING_LLM_MODEL = "routing-model"
    settings.SEARCH_CLASSIFIER_MODEL = ""
    get_place_suggester.cache_clear()
    yield
    for name, value in original.items():
        setattr(settings, name, value)
    get_place_suggester.cache_clear()


# The reported defect: this followed the chat model, so an engine that ignores
# the schema silently emptied image recall.
def test_the_bounded_classifier_follows_the_routing_role(split_roles):
    assert get_classifier_llm().base_url == _ROUTING
    assert get_classifier_llm().base_url == get_routing_llm_client().base_url


# Same contract, same failure: a strict-JSON shortlist that came back empty
# every time on the chat model.
def test_the_place_suggester_follows_the_routing_role(split_roles):
    assert get_place_suggester().writer.base_url == _ROUTING


# A dedicated classifier model must still be served from the routing endpoint,
# or naming a Qwen model while pointing at the chat host asks one server for a
# model it has never heard of.
def test_a_dedicated_classifier_model_is_served_from_the_routing_endpoint(
    split_roles,
):
    settings.SEARCH_CLASSIFIER_MODEL = "dedicated-classifier"

    resolved = get_classifier_llm()

    assert resolved.base_url == _ROUTING
    assert resolved.model == "dedicated-classifier"


# Configuring neither role must behave exactly as it did before the split, or
# this becomes a breaking change for every install that never set it.
def test_an_unset_routing_role_still_falls_back_to_the_chat_model(split_roles):
    settings.ROUTING_LLM_BASE_URL = ""
    settings.ROUTING_LLM_MODEL = ""

    assert get_classifier_llm().base_url == _MAIN
