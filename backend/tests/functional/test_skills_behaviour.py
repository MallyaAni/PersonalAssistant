"""Does the model teach, invoke, and carry out skills from plain words?

"When I say morning brief, give me the weather and my tasks" must become a
save_skill decision with the name and the routine; "morning brief" or
"brief me" afterwards must choose that skill by meaning; and the reply
block for a firing skill must carry the instruction out rather than
explain it. Structural tests prove the plumbing; these send the real
prompts to the real models.
"""

import pytest

from backend.agents.graph import _build_system_prompt, _build_turn_context
from backend.services.main_action_selector import (
    MainActionSelector,
    ManageSkillsAction,
    SaveSkillAction,
    UseSkillAction,
)
from backend.tests.functional.semantic import states

pytestmark = pytest.mark.asyncio

_SKILLS = [
    {
        "id": "s1",
        "slug": "morning-brief",
        "name": "morning brief",
        "description": (
            "The weather for Arlington, then what is on the schedule today, "
            "then one encouraging line."
        ),
        "instruction": (
            "Give the weather for Arlington VA today, then list what is "
            "scheduled today, then end with one encouraging line."
        ),
        "source": "user",
    },
    {
        "id": "pack:quick-brief",
        "slug": "quick-brief",
        "name": "Quick brief",
        "description": (
            "A quick three-line brief on a topic the person names - what it "
            "is, why it matters right now, and one thing to watch."
        ),
        "instruction": "Give a three-line brief on the named topic.",
        "source": "pack",
    },
    {
        "id": "pack:what-s-on",
        "slug": "what-s-on",
        "name": "What's on",
        "description": (
            "Events, nightlife and what's happening somewhere - tonight, this "
            "weekend, a date range - found live and presented as a list people "
            "can act on, with venue, map link, day and time, price, a line on "
            "the music or what it is, and links to hear the artist and see "
            "the event posting."
        ),
        "instruction": "Find what is on, live, and present each event in the agreed format.",
        "source": "pack",
    },
]


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


async def test_teaching_a_routine_becomes_a_save_skill_decision(selector):
    action = await selector.select(
        "functional_test_user",
        "when I say morning brief, give me the weather for Arlington and "
        "then my tasks for the day",
        [],
        None,
    )
    assert isinstance(action, SaveSkillAction), action
    assert "morning brief" in action.name.lower(), action
    assert "arlington" in action.instruction.lower(), action
    assert "task" in action.instruction.lower(), action


async def test_a_skill_is_invoked_by_name_and_by_meaning(selector):
    for query in (
        "morning brief",
        "do my morning brief please",
        "brief me for the day",
    ):
        action = await selector.select(
            "functional_test_user", query, [], None, skills=_SKILLS
        )
        assert isinstance(action, UseSkillAction), (query, action)
        assert action.name == "morning brief", (query, action)


async def test_a_shipped_pack_is_chosen_for_what_it_does(selector):
    action = await selector.select(
        "functional_test_user",
        "give me a quick brief on the DGX Spark",
        [],
        None,
        skills=_SKILLS,
    )
    assert isinstance(action, UseSkillAction), action
    assert action.name == "Quick brief", action


async def test_asking_what_skills_exist_is_a_list_not_an_invocation(selector):
    action = await selector.select(
        "functional_test_user",
        "what skills have I taught you?",
        [],
        None,
        skills=_SKILLS,
    )
    assert isinstance(action, ManageSkillsAction), action
    assert action.operation == "list", action


# A skill offered must not swallow ordinary questions near its subject.
async def test_an_ordinary_question_is_not_a_skill(selector):
    action = await selector.select(
        "functional_test_user",
        "what's the weather today in Arlington VA?",
        [],
        None,
        skills=_SKILLS,
    )
    assert not isinstance(action, UseSkillAction | SaveSkillAction), action


# The reply for an invoked skill carries the instruction out rather than
# describing or confirming it.
async def test_an_invoked_skill_is_carried_out_not_described(llm):
    context = {
        "channel": "imessage",
        "skill": {
            "id": "s2",
            "name": "pep talk",
            "instruction": (
                "Write two sentences of genuine encouragement for a hard day "
                "of debugging, then one short practical tip for staying focused."
            ),
        },
    }
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{turn_context}\n\npep talk"},
        ],
        300,
        None,
        0.0,
    )
    text = str(result["content"])
    assert states(text, "the reply encourages the reader and gives a focus tip"), text
    assert not states(
        text,
        "the reply explains what the skill is or asks whether to run it "
        "instead of doing it",
    ), text


async def test_a_saved_skill_is_confirmed_not_run(llm):
    context = {
        "channel": "imessage",
        "skill_outcome": {
            "kind": "saved",
            "skill": {
                "name": "morning brief",
                "instruction": (
                    "Give the weather for Arlington VA, then list what is "
                    "scheduled today."
                ),
            },
        },
    }
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"{turn_context}\n\nwhen I say morning brief, give me the "
                    "weather for Arlington and my tasks for the day"
                ),
            },
        ],
        300,
        None,
        0.0,
    )
    text = str(result["content"])
    assert states(text, "the reply confirms a skill called morning brief is saved"), (
        text
    )
    assert not states(
        text, "the reply reports actual weather conditions or a temperature"
    ), text


# Arsalon's format, shipped for everyone (2026-08-25): a what's-on question
# is the pack's, from a newcomer as much as from him.
async def test_a_whats_on_question_is_the_shipped_pack(selector):
    action = await selector.select(
        "functional_test_user",
        "what's on in Canggu this weekend?",
        [],
        None,
        skills=_SKILLS,
    )
    assert isinstance(action, UseSkillAction), action
    assert action.name == "What's on", action


# A firing reminder is not a routine: with two packs on the menu, the router
# once turned "Remind me to stretch" into a Quick brief about stretching.
@pytest.mark.parametrize(
    "text",
    ["Remind me to stretch", "time to call mom", "what's the capital of Peru?"],
)
async def test_a_reminder_or_a_plain_question_is_never_a_skill(selector, text):
    action = await selector.select(
        "functional_test_user", text, [], None, skills=_SKILLS, unattended=True
    )
    assert not isinstance(action, UseSkillAction), (text, action)
