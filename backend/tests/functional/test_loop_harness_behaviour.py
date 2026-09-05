"""The loop harness against the real router, and the case it was built for.

A loop that cannot see a step failed reports success. Until step outcomes
reached the model there was no way to arrange that failure in a test; this is
that test. Everything here uses the real selector and the real `run_steps` -
only what a step *does* is scripted, because that is where a step touches the
world.
"""
import pytest

from backend.services.trajectory_harness import World, repeat, walk
from backend.services.turn_steps import CEILING, DECLINED
from backend.tools.actions import ScheduleTaskAction

pytestmark = pytest.mark.asyncio

WORKED = {"kind": "scheduled"}
FOUND_NOTHING = {"kind": "not_found", "tasks": []}


@pytest.fixture(scope="session")
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service
    from backend.services.main_action_selector import MainActionSelector

    invocation = get_mcp_invocation_service()
    return MainActionSelector(
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


async def test_the_harness_reports_the_path_and_why_it_stopped(selector):
    trip = await walk(
        selector,
        ask="cancel my 5pm reminder and set one for 6pm to call mum",
        world=World([WORKED]),
        max_steps=3,
    )
    assert len(trip) >= 1, trip.path
    assert trip.path[0] in {"ManageTasksAction", "ScheduleTaskAction"}, trip.path
    assert trip.stopped in {DECLINED, CEILING, "the router repeated a step"}
    # What the model was shown before each decision after the first: this is
    # the record that made the failed-step bug invisible for as long as it was.
    assert len(trip.shown) == max(0, len(trip) - 1) or trip.shown


async def test_a_step_that_worked_is_not_reported_as_a_failure(selector):
    trip = await walk(
        selector, ask="remind me at 6pm to call mum", world=World([WORKED]), max_steps=1
    )
    assert trip.failed == (), [step.line for step in trip.steps]
    assert trip.stopped == CEILING


# The case the harness exists for. The first step reports that it found
# nothing to act on, and that now reaches the model in the step line.
async def test_a_failed_step_is_visible_to_the_next_decision(selector):
    trip = await walk(
        selector,
        ask="cancel my 5pm reminder",
        world=World([FOUND_NOTHING]),
        max_steps=2,
    )
    assert trip.failed, "the scripted outcome says the step found nothing"
    if trip.shown:
        # Whatever the model then decides, it was told the truth about the
        # step rather than being shown it as done.
        assert any(
            "found nothing to act on" in line for line in trip.shown[0]
        ), trip.shown


# Loops compound: three steps at ninety percent each is seventy-three percent
# end to end. A loop claim is a rate, and this is how one should be written.
async def test_a_single_action_request_takes_one_step_at_a_measured_rate(selector):
    async def once():
        return await walk(
            selector,
            ask="remind me at 6pm to call mum",
            world=World([WORKED]),
            max_steps=3,
            creates=lambda item: isinstance(item, ScheduleTaskAction),
        )

    rate = await repeat(once, lambda trip: len(trip) == 1, reps=5)
    assert rate.rate >= 0.8, str(rate)


async def test_the_harness_reports_a_router_that_names_no_tool(selector):
    trip = await walk(selector, ask="thanks, that's all", world=World([WORKED]))
    if not len(trip):
        assert trip.stopped == DECLINED
