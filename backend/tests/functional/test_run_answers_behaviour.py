"""Answering a background run from chat, against the real models.

The router must send a yes or a no to `manage_runs` when the conversation
shows a run waiting for the person's permission, send "what's running" to
its status, and leave a yes that answers the assistant's own question alone.
Then the reply side: told a run was approved, the model says it will go
ahead and does not say it is done; told which run was not settled, it asks.
Structural tests prove the plumbing; these send the real prompts.

pinned prompt: reply/run_outcome.
"""

import pytest

from backend.agents.graph import _build_system_prompt, _build_turn_context
from backend.services.main_action_selector import MainActionSelector
from backend.tests.functional.semantic import states
from backend.tools.actions import ManageRunsAction

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_WAITING_LINE = (
    "One thing: a background run is waiting for your yes - it wants to send "
    "the ramen summary to mum by text. Say yes or no when you're ready."
)


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


def _history(assistant_said: str) -> list[dict]:
    return [
        {"role": "user", "content": "find me a good ramen place near Davis Square"},
        {"role": "assistant", "content": "Yume Wo Katare is the one near Davis Square. " + assistant_said},
    ]


@pytest.mark.parametrize(
    ("asked", "mode"),
    [
        ("yes, go ahead and send it", "approve"),
        ("no, don't send that", "deny"),
    ],
)
async def test_an_answer_to_a_waiting_run_reaches_the_tool_with_the_mode_the_words_mean(selector, asked, mode):
    held = 0
    seen = []
    for _ in range(3):
        action = await selector.select("run_answers_eval", asked, _history(_WAITING_LINE), None)
        seen.append(action)
        if isinstance(action, ManageRunsAction) and action.mode == mode:
            held += 1
    assert held >= 2, seen


async def test_asking_what_is_running_is_the_tools_status(selector):
    held = 0
    seen = []
    for _ in range(3):
        action = await selector.select("run_answers_eval", "what's running in the background for me right now?", [], None)
        seen.append(action)
        if isinstance(action, ManageRunsAction) and action.mode == "status":
            held += 1
    assert held >= 2, seen


async def test_a_yes_to_the_assistants_own_question_is_not_a_run_answer(selector):
    held = 0
    seen = []
    for _ in range(3):
        action = await selector.select(
            "run_answers_eval", "yes please", _history("Want me to look for a few more places nearby?"), None
        )
        seen.append(action)
        if not isinstance(action, ManageRunsAction):
            held += 1
    assert held >= 2, seen


def _reply(llm, context: dict, asked: str) -> str:
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{turn_context}\n\n{asked}"},
        ],
        300,
        None,
        0.0,
    )
    return str(result["content"])


async def test_an_approved_run_is_said_to_go_ahead_not_to_be_done(llm):
    context = {
        "channel": "web",
        "run_outcomes": [{"kind": "run_approved", "chosen": {"approval_id": "a1", "kind": "chat continuation", "summary": "send the ramen summary to mum by text"}}],
        "runs_waiting": [{"number": 1, "approval_id": "a1", "kind": "chat continuation", "summary": "send the ramen summary to mum by text", "objective": "ramen"}],
    }
    held = 0
    replies = []
    for _ in range(3):
        text = _reply(llm, context, "yes, go ahead and send it")
        replies.append(text)
        goes_ahead = states(text, "the reply says the message to mum will be sent, is going ahead, or has been allowed to proceed")
        not_done = states(text, "the reply does NOT say the message has already been sent or delivered")
        if goes_ahead and not_done:
            held += 1
    assert held >= 2, replies


async def test_an_unsettled_choice_asks_which_run(llm):
    waiting = [
        {"number": 1, "approval_id": "a1", "kind": "chat continuation", "summary": "send the ramen summary to mum by text", "objective": "ramen"},
        {"number": 2, "approval_id": "a2", "kind": "chat continuation", "summary": "book a table for two at Yume Wo Katare", "objective": "dinner"},
    ]
    context = {"channel": "web", "run_outcomes": [{"kind": "runs_which", "waiting": waiting}], "runs_waiting": waiting}
    text = _reply(llm, context, "yes go ahead")
    assert states(text, "the reply asks the person which of two things they mean, mentioning both the text to mum and the table booking, and does not say either has been approved or done"), text
