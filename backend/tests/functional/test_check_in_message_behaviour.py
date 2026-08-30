"""What a check-in actually says when it fires.

The judgement deciding to arm one and the limits deciding to allow it are
both tested elsewhere and neither is visible to anyone. This is the part
that reaches a phone: a firing check-in is the stored instruction plus the
manner the runner attaches (`backend/workers/task_runner._asked`), put
through the ordinary reply path.

The ways it can be right and still be bad are what is asserted here. It can
arrive as a paragraph. It can announce itself as a scheduled task, which
turns a kindness into an automation notice. It can go and search for
National Harbor and come back with opening hours nobody asked for. It can
end by offering to do something, which is the assistant's usual reflex and
exactly wrong for a question about someone's weekend.
"""

from __future__ import annotations

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.config.settings import settings
from backend.core.dependencies import get_mcp_invocation_service, get_routing_llm_client
from backend.services.main_action_selector import MainActionSelector
from backend.workers.task_runner import _asked

pytestmark = pytest.mark.asyncio

EVENT_TASK = {
    "instruction": "Ask how the visit to National Harbor went.",
    "kind": "checkin:event",
}
WELLBEING_TASK = {
    "instruction": "Check in on how they are doing after not feeling well.",
    "kind": "checkin:wellbeing",
}


def _fires(llm, task: dict) -> str:
    asked = _asked(task)
    context = {"channel": "imessage", "query": asked}
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": asked})
    return str(llm.chat(messages, 300, None, 0.0)["content"]).strip()


async def test_a_check_in_about_an_outing_asks_about_that_outing(llm) -> None:
    said = _fires(llm, EVENT_TASK)
    print(f"\nevent check-in fired:\n{said}\n")
    assert "national harbor" in said.casefold(), said
    assert "?" in said, said


async def test_it_arrives_as_a_line_rather_than_a_paragraph(llm) -> None:
    said = _fires(llm, EVENT_TASK)
    # A message that turns up unprompted has to be short or it is an
    # intrusion. Generous, because the model varies; a paragraph fails.
    assert len(said.split()) <= 45, said


async def test_it_does_not_announce_itself_as_an_automation(llm) -> None:
    # "Your scheduled check-in:" undoes the whole point of remembering.
    said = _fires(llm, EVENT_TASK).casefold()
    for giveaway in ("scheduled", "reminder", "automation", "as requested", "task"):
        assert giveaway not in said, said


async def test_it_does_not_end_by_offering_to_do_something(llm) -> None:
    # The assistant's usual reflex, and wrong for a question about someone's
    # weekend: it turns a kind message into a prompt for more work.
    said = _fires(llm, EVENT_TASK).casefold()
    for offer in ("would you like me to", "want me to", "i can help", "let me know if you'd like me"):
        assert offer not in said, said


async def test_a_wellbeing_check_in_asks_after_the_person(llm) -> None:
    said = _fires(llm, WELLBEING_TASK)
    print(f"\nwellbeing check-in fired:\n{said}\n")
    assert "?" in said, said
    assert len(said.split()) <= 45, said
    # It must not repeat the clinical phrasing of its own instruction back
    # at them - "after not feeling well" is a note to self, not a greeting.
    assert "check in on how they are doing" not in said.casefold(), said


async def test_a_firing_check_in_does_not_go_looking_things_up(llm) -> None:
    # The router sees the firing as an ordinary turn, and "how did the visit
    # to National Harbor go" is exactly the shape of a question it would
    # normally search. A check-in that comes back with opening hours is not
    # a check-in. The manner says not to; this is whether that holds where
    # it matters, which is the router rather than the reply.
    from backend.cli.evaluate_tool_selection import tool_of
    from backend.search.budgeted import SearchIdentity, current_search_identity

    selector = MainActionSelector(
        get_routing_llm_client(),
        get_mcp_invocation_service(),
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )
    for task in (EVENT_TASK, WELLBEING_TASK):
        token = current_search_identity.set(
            SearchIdentity(user_id="check_in_behaviour", is_operator=True)
        )
        try:
            action = await selector.select(
                "check_in_behaviour", _asked(task), [], None, unattended=True
            )
        finally:
            current_search_identity.reset(token)
        chosen = tool_of(action)
        print(f"\n{task['kind']} -> {chosen}")
        assert chosen == "none", (task["kind"], chosen)


async def test_a_plain_reminder_is_not_given_the_check_in_manner(llm) -> None:
    # The bound on the runner's addition: an ordinary reminder still says
    # what it was told to say, at whatever length it needs.
    reminder = {"instruction": "Remind me to call the landlord.", "kind": "reminder"}
    assert _asked(reminder) == "Remind me to call the landlord."
