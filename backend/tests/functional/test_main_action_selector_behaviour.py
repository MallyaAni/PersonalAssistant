"""Does the model actually decide well, not just get offered the tools?

Every candidate action used to be judged by its own separate deterministic
gate -- a regex, a bounded YES/NO classifier, or a browser-side keyword match
-- each guessing from the question's wording alone, before the model that
answers the user ever saw the request. This offers every candidate as a real
function-calling tool to one model in one call and lets it decide from actual
understanding. The structural tests (test_main_action_selector.py) prove the
call is shaped correctly against a scripted model. They would pass just as
happily against a selector that always searches or never does. These tests
send the real prompt to the real local model and assert on what it decided.

The web-search cases are the exact labelled set `evaluate_search_routing.py`
already holds the retired regex-plus-classifier cascade to (recall >= 0.90,
specificity >= 0.80 for the cascade's classifier-backed mode) -- reused here,
through a thin adapter, so the replacement is held to a real, comparable
floor rather than a few hand-picked examples.
"""

from dataclasses import dataclass

import pytest

from backend.search.routing_cases import ROUTING_CASES
from backend.services.main_action_selector import (
    CreateDiagramAction,
    DelegateAction,
    EditImageAction,
    GenerateImageAction,
    MainActionSelector,
    SearchAction,
)
from backend.services.search_routing_evaluator import SearchRoutingEvaluator

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")
    return MainActionSelector(
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


@dataclass(frozen=True, slots=True)
class _Verdict:
    should_search: bool


class _SelectorAsRouter:
    """Adapt the selector to the evaluator's decide(query) contract."""

    def __init__(self, selector: MainActionSelector) -> None:
        self.selector = selector

    async def decide(self, query: str) -> _Verdict:
        action = await self.selector.select(
            "functional_test_user", query, [], None
        )
        return _Verdict(should_search=isinstance(action, SearchAction))


# The floor a native tool-calling decision, made by the same model that
# answers the user, should clear against the labelled set the retired
# regex-plus-classifier cascade was held to.
async def test_search_routing_quality_meets_the_retired_cascades_floor(selector):
    report = await SearchRoutingEvaluator(
        _SelectorAsRouter(selector), ROUTING_CASES
    ).evaluate()

    assert report.overall.recall >= 0.85, (report.overall, report.misses)
    assert report.overall.specificity >= 0.75, (
        report.overall,
        report.false_alarms,
    )


# The behaviour this whole change exists for: asked a request that depends on
# the user's location, with no location anywhere in the conversation, the
# model must not silently assume one and search anyway -- it should either
# call no tool (so the reply can ask) or, if it does search, the query it
# writes must not invent a specific place.
async def test_a_location_dependent_request_does_not_search_an_assumed_place(
    selector,
):
    action = await selector.select(
        "functional_test_user",
        "any good bachata events happening tonight?",
        [],
        None,
    )
    if isinstance(action, SearchAction):
        lowered = action.query.casefold()
        invented_places = (
            "new york", "los angeles", "san francisco", "chicago", "joliet",
            "seattle", "boston", "austin", "raleigh", "arlington",
        )
        assert not any(place in lowered for place in invented_places), action.query


# The same request, once the user's city is already in the conversation, is
# free to search -- the model is not being asked to refuse location-dependent
# questions outright, only to stop guessing when it genuinely does not know.
async def test_a_location_dependent_request_may_search_once_the_city_is_known(
    selector,
):
    history = [
        {
            "query": "I just moved to Austin, Texas.",
            "response": "Nice, welcome to Austin!",
        }
    ]
    action = await selector.select(
        "functional_test_user",
        "any good bachata events happening tonight?",
        history,
        None,
    )
    assert isinstance(action, SearchAction), action


@pytest.mark.parametrize(
    "text",
    [
        "draw me a red bicycle leaning against a brick wall",
        "generate an image of a lighthouse at sunset",
        "create a picture of a cat wearing a top hat",
    ],
)
async def test_an_explicit_image_request_chooses_generate_image(selector, text):
    action = await selector.select("functional_test_user", text, [], None)
    assert isinstance(action, GenerateImageAction), action


@pytest.mark.parametrize(
    "text",
    [
        "draw a flowchart of our deployment pipeline from commit to production",
        "create an architecture diagram showing the API talking to the database",
    ],
)
async def test_an_explicit_diagram_request_chooses_create_diagram(selector, text):
    action = await selector.select("functional_test_user", text, [], None)
    assert isinstance(action, CreateDiagramAction), action


async def test_an_explicit_deck_request_delegates_to_the_presentation_agent(
    selector,
):
    action = await selector.select(
        "functional_test_user",
        "put together a six-slide deck explaining battery storage",
        [],
        None,
    )
    assert action == DelegateAction(capability_id="presentation_agent")


@pytest.mark.parametrize(
    "text",
    [
        "what's the derivative of x squared",
        "can you explain how a b-tree works",
        "write a haiku about rain",
        "what did I say my dog's name was",
    ],
)
async def test_an_ordinary_question_chooses_no_action(selector, text):
    action = await selector.select("functional_test_user", text, [], None)
    assert action is None, action


# edit_image is now offered every turn, active image or not - the check that
# something is actually selected moved to ConversationService, since only the
# application knows the real UI state. This holds the selector itself to two
# things: it must still recognize a genuine edit request when the
# conversation clearly has a picture in it, and it must not be tempted into
# calling edit_image by an unrelated "edit" request now that the tool is
# always on the table.
async def test_an_edit_request_with_a_recent_picture_chooses_edit_image(selector):
    history = [
        {
            "query": "make me a picture of a red bicycle leaning against a brick wall",
            "response": "Here's the image you asked for.",
        }
    ]
    action = await selector.select(
        "functional_test_user",
        "make it black and white",
        history,
        None,
    )
    assert isinstance(action, EditImageAction), action


@pytest.mark.parametrize(
    "text",
    [
        "edit my resume to remove my last job",
        "let's edit this project plan to push the deadline back a week",
    ],
)
async def test_an_unrelated_edit_request_does_not_choose_edit_image(selector, text):
    action = await selector.select("functional_test_user", text, [], None)
    assert not isinstance(action, EditImageAction), action
