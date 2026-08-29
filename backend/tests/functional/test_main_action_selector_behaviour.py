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
    ToolboxAction,
)
from backend.services.search_routing_evaluator import SearchRoutingEvaluator
from backend.tools import DiscussImageAction, RecallHistoryAction, ScoutScheduleAction, UseSkillAction

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
        action = await self.selector.select("functional_test_user", query, [], None)
        # The labels mean "this needs live data", not "this needs search_web
        # specifically": a weather question routed to the forecast tool is the
        # live-data decision made better, and must not read as a miss.
        went_live = isinstance(action, SearchAction) or (
            isinstance(action, ToolboxAction) and action.plan.tool_name == "get_weather"
        )
        return _Verdict(should_search=went_live)


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
            "new york",
            "los angeles",
            "san francisco",
            "chicago",
            "joliet",
            "seattle",
            "boston",
            "austin",
            "raleigh",
            "arlington",
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


# Found on a different model entirely (DeepSeek-V4-Flash, evaluated for a
# possible future role, not currently in production): "write a haiku about
# rain" called generate_image to illustrate the rain instead of just writing
# the haiku - a visual subject read as an implicit picture request. Poem and
# story prompts on the same visual subjects generalize the fix cleanly; short
# nature-themed poetry forms (haiku, limerick specifically) stayed materially
# less reliable even after two rounds of strengthening this description, so
# they are deliberately left out of this assertion rather than pinned to a
# flaky expectation - see ROADMAP.md Milestone 9 for the measured numbers.
@pytest.mark.parametrize(
    "text",
    [
        "write a poem about the ocean",
        "tell me a short story about a rainy day in autumn",
        "describe a mountain sunset in vivid detail",
    ],
)
async def test_a_request_to_write_about_a_visual_subject_does_not_generate_image(
    selector, text
):
    action = await selector.select("functional_test_user", text, [], None)
    assert not isinstance(action, GenerateImageAction), action


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
    assert isinstance(action, DelegateAction), action
    assert action.capability_id == "presentation_agent"
    # The subject is the model's own words, so only its presence is asserted:
    # a delegation that cannot say what the deck is about is a misroute, and
    # the selector drops it rather than queueing a job about nothing.
    assert action.subject.strip()


@pytest.mark.parametrize(
    "text",
    [
        "what's the derivative of x squared",
        "can you explain how a b-tree works",
        # Writing is not drawing: this chose generate_image 3/3 until the
        # tool's description said so (2026-08-28).
        "write a haiku about rain",
    ],
)
async def test_an_ordinary_question_chooses_no_action(selector, text):
    action = await selector.select("functional_test_user", text, [], None)
    assert action is None, action


# "What did I say my dog's name was" asked for nothing at all when this test
# was written; `search_history` was added on 2026-08-24 and searching the
# person's own past conversations is now the right answer - measured 3/3.
# Answering from the window alone stays acceptable: a short thread may
# already hold it.
async def test_a_question_about_what_the_user_said_recalls_or_answers(selector):
    action = await selector.select(
        "functional_test_user", "what did I say my dog's name was", [], None
    )
    assert action is None or isinstance(action, RecallHistoryAction), action


# Repeatedly replay the reported Scout confirmation so a sampled false search
# cannot hide behind one fortunate pass.
async def test_a_scout_schedule_confirmation_never_calls_an_external_tool(selector):
    history = [
        {
            "query": "what agents do i have scheduled?",
            "response": "Scout is scheduled and ready for configuration.",
        }
    ]
    decisions = [
        await selector.select(
            "functional_test_user",
            "yes id like scout for 9:40pm",
            history,
            None,
        )
        for _ in range(5)
    ]

    # scout_schedule did not exist when this was written, and the failure it
    # guards is a *search* fired at a confirmation. Setting Scout's sweep to
    # the time the person just named is the right answer now (measured 3/3);
    # reaching outside for it never is.
    for decision in decisions:
        assert not isinstance(decision, SearchAction | ToolboxAction), decisions
        assert decision is None or isinstance(decision, ScoutScheduleAction), decisions


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


# A labelled version modifies the selected pixels even though it says "generate".
async def test_a_labelled_version_of_the_selected_image_chooses_edit_image(selector):
    action = await selector.select(
        "functional_test_user",
        "can you generate a labelled image of this?",
        [],
        "selected-image-id",
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


# Replayed verbatim from a live trace (conversation 3d463775, 2026-08-13):
# after the model described a black cowboy hat and the user had it edited to
# straw, "which hat do you like better" made the selector choose edit_image -
# synthesizing a paraphrased instruction that silently redid the same hat
# swap instead of answering the comparison the user actually asked. This
# exact replay could not be forced to fail again against the unfixed
# description (12/12 passed) - a temperature-driven, low-probability slip
# rather than a deterministic gap - so this is best-effort coverage for the
# fixed wording, not proof the fix changed anything measurable.
async def test_an_opinion_question_about_a_just_edited_picture_does_not_re_edit(
    selector,
):
    history = [
        {
            "query": "do you like my style?",
            "response": (
                "Based on the photo from today (August 13, 2026), your style "
                "leans into a rugged yet modern look. You're wearing a "
                "classic **black cowboy hat** paired with a sleek **dark "
                "zip-up bomber jacket** over a simple **white crew-neck "
                "t-shirt**. This combination creates a cohesive "
                '"outfitter" or western-meets-urban vibe, balanced by the '
                "casual neatness of the all-black jacket and the relaxed "
                "tone of the white tee.\n\nSince your hands are tucked into "
                "the jacket pockets and you're leaning slightly forward, "
                "there's a cool, confident posture to your style as well."
            ),
        },
        {
            "query": "can you edit this to a straw hat?",
            "response": "Here's the edited image.",
        },
    ]
    action = await selector.select(
        "functional_test_user",
        "amazing! which hat do you like better for this outfit?",
        history,
        "existing-outfit-artifact-id",
    )
    assert not isinstance(action, EditImageAction), action


# The bug is the shape "a question about the picture, not an instruction to
# change it" - not any one wording of it. A fix aimed at the single reported
# phrase ("which hat do you like better") left this exact live follow-up,
# worded differently, still re-editing: reported after the first fix had
# already shipped. Held to every phrasing at once (not one at a time) so a
# fix narrow enough to pass on the reported words alone cannot pass here.
@pytest.mark.parametrize(
    "text",
    [
        "do you recommend a straw hat instead?",
        "should I go with the straw hat instead?",
        "what do you think, straw or cowboy?",
        "would the cowboy hat have suited me better?",
    ],
)
async def test_every_phrasing_of_an_opinion_question_avoids_re_editing(selector, text):
    history = [
        {
            "query": "do you like my style?",
            "response": (
                "You're wearing a classic **black cowboy hat** paired with a "
                "sleek **dark zip-up bomber jacket** over a simple **white "
                "crew-neck t-shirt**."
            ),
        },
        {
            "query": "can you edit this to a straw hat?",
            "response": "Here's the edited image.",
        },
    ]
    action = await selector.select(
        "functional_test_user", text, history, "existing-outfit-artifact-id"
    )
    assert not isinstance(action, EditImageAction), action


# The defect this tool exists for: "today's weather" went to web search, SEO
# forecast pages came back, and a monthly outlook reached a real phone as
# today. A weather question must route to the forecast tool with the place
# carried through; the tool's own description does the steering, so this
# gate holds whichever wording that description drifts to.
async def test_a_weather_question_routes_to_the_forecast_tool(selector):
    for query in (
        "what's the weather today in Arlington VA?",
        "will it rain this weekend in Arlington, Virginia?",
    ):
        action = await selector.select("functional_test_user", query, [], None)

        assert isinstance(action, ToolboxAction), (query, action)
        assert action.plan.tool_name == "get_weather", (query, action)
        place = str(action.plan.arguments.get("place", "")).casefold()
        assert "arlington" in place, (query, action.plan.arguments)


# "Weather here" with the person's place known routes to the forecast tool
# for that place; with no place known it routes to no tool so the reply can
# ask. The first live group turn (2026-08-28) went to Here, Somalia; the
# wording that fixed that then read as "call no tool when they say here",
# and the sweep's group weather journey routed to nothing with Arlington on
# record. Both readings are held here.
async def test_weather_here_uses_the_known_place_or_asks(selector):
    known = "Friday 2026-08-28 16:10 - they are in Arlington, Virginia (America/New_York); the coming weekend is Saturday 2026-08-29 and Sunday 2026-08-30"
    unknown = "Friday 2026-08-28 20:10 UTC (their time zone is not known); the coming weekend is Saturday 2026-08-29 and Sunday 2026-08-30"
    for query in ("Scout hows the weather here today?", "how's the weather here today?"):
        action = await selector.select("functional_test_user", query, [], None, local_now=known)
        assert isinstance(action, ToolboxAction) and action.plan.tool_name == "get_weather", (query, action)
        assert "arlington" in str(action.plan.arguments.get("place", "")).casefold(), (query, action.plan.arguments)
    # With no place known the router may still reach for the tool with a
    # non-place ("unknown", "here"); the tool refuses those before the
    # geocoder, so the reply asks either way. What must never happen is a
    # real-looking place invented for the argument.
    from backend.mcp.servers.internet import not_a_place

    action = await selector.select("functional_test_user", "how's the weather here today?", [], None, local_now=unknown)
    if isinstance(action, ToolboxAction) and action.plan.tool_name == "get_weather":
        assert not_a_place(str(action.plan.arguments.get("place", ""))), action.plan.arguments


# A live "what's on" question whose place is only in the conversation: the
# router searches, and the query it writes names the place and the dates -
# 2026-08-25, Canggu: it first offered to search, then searched without the
# place and got mini PC reviews.
async def test_a_whats_on_question_searches_for_the_place_and_the_dates(selector):
    history = [
        {
            "query": "what's on in canggu this week?",
            "response": (
                "From memory: Luigi's Hot Pizza and Miss Fish in Canggu both run "
                "weekly nights, but I can't verify this week's lineup."
            ),
        },
        {
            "query": (
                "This is too generic. Luigi's had a big party Monday, Miss Fish "
                "had a fashion thing Tuesday"
            ),
            "response": "Understood - those are the venues you mean.",
        },
    ]
    # The clock, as every production turn supplies it. Without it this test
    # demanded calendar dates from a router that had no date: it wrote them
    # 0 times in 3 without the clock and 2 in 3 with it (measured 2026-08-29),
    # which is what the rates below hold.
    now = (
        "Friday 2026-08-28 16:10 - they are in Canggu, Bali (Asia/Makassar); "
        "the coming weekend is Saturday 2026-08-29 and Sunday 2026-08-30"
    )
    dated = 0
    runs = 3
    for _ in range(runs):
        action = await selector.select(
            "functional_test_user", "what's going on Weds-Sunday?", history, None, local_now=now
        )
        assert isinstance(action, SearchAction), action
        lowered = action.query.casefold()
        assert "canggu" in lowered, action.query
        dated += any(
            mark in lowered
            for mark in ("aug", "26", "27", "28", "29", "30", "31", "weekend", "2026")
        )
    assert dated >= runs - 1, f"{dated}/{runs} queries carried the dates"


# A trip is searched from home: "to Rome and back from Amalfi" from a person
# in Arlington was searched as a Rome-to-Amalfi flight (2026-08-26) and
# answered with fares for a route that does not exist.
async def test_a_trip_is_searched_from_where_the_person_is(selector):
    action = await selector.select(
        "functional_test_user",
        "i took off work from October 2 to 16. planning one way trip to rome and "
        "then back from amalfi coast. cheapest non stop option ironically?",
        [],
        None,
        local_now=(
            "Tuesday 2026-08-25 22:58 - they are in Arlington, Virginia "
            "(America/New_York); this weekend is Sat 2026-08-29 to Sun 2026-08-30"
        ),
    )
    assert isinstance(action, SearchAction), action
    lowered = action.query.casefold()
    assert any(o in lowered for o in ("washington", "dulles", "iad", "dca", "arlington", "dc ")), action.query
    assert "rome" in lowered or "fco" in lowered, action.query
    # One query covers one leg; the return from Naples is the planner's next
    # round (test_search_compose_behaviour). What must never appear is the
    # two foreign places read as the flight.
    assert "rome to amalfi" not in lowered and "rome-amalfi" not in lowered, action.query


# A recommendation is not a listing. The shipped "What's on" skill pack is
# offered on every turn, and "where should the two of us go for dinner on
# friday? something we'd both like" was routed to it twice (a kept sweep on
# 2026-08-28 and deploy #20), which then searched "events happening this
# weekend" and answered off-subject. The pack's own description does the
# steering, so this holds whichever wording it drifts to - and the positive
# case is here so the fix cannot be "never choose the skill".
async def test_a_recommendation_does_not_become_a_whats_on_listing(selector):
    from backend.skills.packs import load_packs

    packs = [pack.as_skill() for pack in load_packs().values()]
    assert any(skill["slug"] == "what-s-on" for skill in packs), packs

    for question in (
        "where should the two of us go for dinner on friday? something we'd both like",
        "any good coffee place near me?",
    ):
        action = await selector.select("functional_test_user", question, [], None, skills=packs)
        assert not isinstance(action, UseSkillAction), (question, action)

    listing = await selector.select(
        "functional_test_user", "what's on in Arlington this weekend?", [], None, skills=packs
    )
    assert isinstance(listing, UseSkillAction) and listing.name.casefold().startswith("what"), listing


# Two defects this suite carried for at least a week (both reproduce at
# 7df424b6, before the group-chat work): "write a haiku about rain" chose
# generate_image 3/3, and "can you generate a labelled image of this?" with a
# picture selected chose nothing 3/3 - edit_image's own description refused
# anything shaped like a question, which a polite request is. Both are fixed
# in the tools' descriptions, and the controls are here so neither fix can be
# "stop offering the tool".
@pytest.mark.parametrize(
    ("message", "active_image", "expected"),
    [
        ("write a haiku about rain", None, type(None)),
        ("write me a short poem about the sunset", None, type(None)),
        ("can you generate a labelled image of this?", "selected-image-id", EditImageAction),
        ("make a picture of a mountain at sunrise", None, GenerateImageAction),
        ("which of these two hats looks better?", "selected-image-id", DiscussImageAction),
    ],
)
async def test_writing_is_not_drawing_and_a_polite_request_is_still_a_request(
    selector, message, active_image, expected
):
    action = await selector.select("functional_test_user", message, [], active_image)
    assert isinstance(action, expected) if expected is not type(None) else action is None, action
