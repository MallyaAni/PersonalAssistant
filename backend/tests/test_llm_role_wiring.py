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
    get_memory_proposal_llm_client,
    get_place_suggester,
    get_presentation_llm_client,
    get_reasoning_llm_client,
    get_routing_llm_client,
    get_structured_llm_client,
    get_vision_escalation_provider,
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
            "MAIN_LLM_STRUCTURED_OUTPUT",
            "MEMORY_PROPOSAL_LLM_BASE_URL",
            "MEMORY_PROPOSAL_LLM_MODEL",
            "PRESENTATION_LLM_BASE_URL",
            "PRESENTATION_LLM_MODEL",
        )
    }
    settings.MAIN_LLM_BASE_URL = _MAIN
    settings.MAIN_LLM_MODEL = "main-model"
    settings.ROUTING_LLM_BASE_URL = _ROUTING
    settings.ROUTING_LLM_MODEL = "routing-model"
    settings.SEARCH_CLASSIFIER_MODEL = ""
    settings.MAIN_LLM_STRUCTURED_OUTPUT = False
    settings.MEMORY_PROPOSAL_LLM_BASE_URL = ""
    settings.MEMORY_PROPOSAL_LLM_MODEL = ""
    settings.PRESENTATION_LLM_BASE_URL = ""
    settings.PRESENTATION_LLM_MODEL = ""
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


# Prose follows the main model unconditionally: it is the work a better main
# model makes better, and it carries no contract an engine can fail to honour.
def test_prose_reasoning_always_follows_the_main_model(split_roles):
    assert get_reasoning_llm_client().base_url == _MAIN

    settings.MAIN_LLM_STRUCTURED_OUTPUT = True
    assert get_reasoning_llm_client().base_url == _MAIN


# The capability, not the model name, decides where structured work runs. This
# is the whole point of the indirection: the same engine defect was patched at
# three separate call sites before it was expressed once.
def test_structured_work_follows_the_main_model_only_when_it_can_be_trusted(
    split_roles,
):
    assert get_structured_llm_client().base_url == _ROUTING

    settings.MAIN_LLM_STRUCTURED_OUTPUT = True
    assert get_structured_llm_client().base_url == _MAIN


# Every strict-JSON caller moves together, or the next promotion breaks
# whichever one was forgotten.
@pytest.mark.parametrize(
    "resolve",
    [
        get_structured_llm_client,
        get_memory_proposal_llm_client,
        get_presentation_llm_client,
        lambda: get_place_suggester().writer,
    ],
)
def test_every_structured_caller_moves_with_the_capability(split_roles, resolve):
    get_place_suggester.cache_clear()
    assert resolve().base_url == _ROUTING

    settings.MAIN_LLM_STRUCTURED_OUTPUT = True
    get_place_suggester.cache_clear()
    assert resolve().base_url == _MAIN


# An operator who pins a role explicitly still gets exactly that role, so the
# capability default never overrides a deliberate choice.
def test_an_explicit_pin_still_wins_over_the_capability(split_roles):
    settings.MAIN_LLM_STRUCTURED_OUTPUT = True
    settings.PRESENTATION_LLM_BASE_URL = "http://pinned.invalid:9002"
    settings.PRESENTATION_LLM_MODEL = "pinned-model"

    resolved = get_presentation_llm_client()

    assert resolved.base_url == "http://pinned.invalid:9002"
    assert resolved.model == "pinned-model"


# The recall classifier is deliberately not in the list above. It answers a
# bounded routing question and hands the model no schema to honour, so it
# belongs with routing and must not drift into following the main model when
# the structured capability is switched on.
def test_the_recall_classifier_stays_on_the_routing_role(split_roles):
    assert get_classifier_llm().base_url == _ROUTING

    settings.MAIN_LLM_STRUCTURED_OUTPUT = True
    assert get_classifier_llm().base_url == _ROUTING


# Restore the optional specialist-vision role and its cached provider after use.
@pytest.fixture
def vision_escalation_role():
    original_url = settings.VISION_ESCALATION_LLM_BASE_URL
    original_model = settings.VISION_ESCALATION_MODEL
    get_vision_escalation_provider.cache_clear()
    yield
    settings.VISION_ESCALATION_LLM_BASE_URL = original_url
    settings.VISION_ESCALATION_MODEL = original_model
    get_vision_escalation_provider.cache_clear()


# Leaving either specialist setting blank must preserve the single-VLM runtime.
def test_incomplete_vision_escalation_configuration_is_disabled(
    vision_escalation_role,
):
    settings.VISION_ESCALATION_LLM_BASE_URL = ""
    settings.VISION_ESCALATION_MODEL = "specialist-model"
    get_vision_escalation_provider.cache_clear()

    assert get_vision_escalation_provider() is None


# A complete specialist role resolves independently from the primary VLM.
def test_configured_vision_escalation_role_builds_its_own_provider(
    vision_escalation_role,
):
    settings.VISION_ESCALATION_LLM_BASE_URL = "http://vision-specialist.invalid:9003"
    settings.VISION_ESCALATION_MODEL = "specialist-model"
    get_vision_escalation_provider.cache_clear()

    resolved = get_vision_escalation_provider()

    assert resolved is not None
    assert resolved.base_url == "http://vision-specialist.invalid:9003"
    assert resolved.model == "specialist-model"
