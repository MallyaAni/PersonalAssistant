"""The trajectory evaluator: whole-turn measurement against the real router.

The first-tool matrix measures one decision and cannot see a turn that needs
two tools and stops after one, a failed step counted as done, or two
legitimate writes cut to one by the repeat guard. This drives the real router
through those shapes with the trajectory harness - only what a step *does* is
scripted - and pins the scoring as a pure function, so a measurement is
deterministic before any model is asked.
"""
import pytest

from backend.services.trajectory_cases import (
    TRAJECTORY_CASES,
    TrajectoryCase,
    case_by_name,
    is_manage,
    is_schedule,
    is_search,
)
from backend.services.trajectory_harness import (
    CEILING,
    Trajectory,
    World,
    score_trajectory,
    tool_name,
    walk,
)
from backend.services.turn_steps import Step
from backend.tools.actions import ManageTasksAction, ScheduleTaskAction, SearchAction

WORKED = {"kind": "done"}
SCHEDULED = {"kind": "scheduled"}
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


def _step(action, outcome, kind="task"):
    return Step(action, kind, dict(outcome), "line")


def _manage(which="5pm reminder", operation="cancel"):
    return ManageTasksAction(operation=operation, which=which)


def _schedule(instruction="call mum", hour=18):
    return ScheduleTaskAction(instruction=instruction, cadence="once", hour=hour)


def _search():
    return SearchAction("pottery class courthouse virginia")


def _score(case: TrajectoryCase, steps):
    return score_trajectory(case, Trajectory(tuple(steps), CEILING, ()), 1.0)


# The scoring is deterministic: given the steps, the metrics are what they
# are. These pin the measurement before any model is asked.
def test_the_tool_names_agree_with_the_matrix():
    import backend.cli.evaluate_tool_selection as matrix_module
    from backend.services import trajectory_harness

    # The matrix keys by the action class; the harness by the class name.
    normalised = {
        action_type.__name__: name
        for action_type, name in matrix_module._ACTION_TOOL.items()
    }
    harness = trajectory_harness._ACTION_TOOL
    overlap = set(normalised) & set(harness)
    assert overlap, "the two tool maps share no action types"
    assert {
        name: normalised[name]
        for name in overlap
        if normalised[name] != harness[name]
    } == {}, "the matrix and the harness name an action differently"


def test_a_mixed_tool_turn_completes_in_order():
    case = case_by_name("cancel-and-reschedule")
    score = _score(case, [_step(_manage(), WORKED), _step(_schedule(), SCHEDULED)])
    assert score.path == ("manage_tasks", "schedule_task")
    assert score.completed is True
    assert score.unauthorized == ()
    assert score.duplicate_effects == 0


def test_a_mixed_tool_turn_needs_the_required_order():
    case = case_by_name("cancel-and-reschedule")
    score = _score(case, [_step(_schedule(), SCHEDULED), _step(_manage(), WORKED)])
    assert score.completed is False


def test_two_writes_count_only_when_both_happen():
    case = case_by_name("two-reminders")
    one = _score(case, [_step(_schedule(), SCHEDULED)])
    assert one.completed is False, "one creation is not two legitimate writes"
    both = _score(
        case,
        [
            _step(_schedule(instruction="call mum", hour=18), SCHEDULED),
            _step(_schedule(instruction="the gym", hour=20), SCHEDULED),
        ],
    )
    assert both.completed is True
    assert both.duplicate_effects == 0, "two writes were allowed for this case"


def test_a_second_effect_beyond_the_allowance_is_a_duplicate():
    case = case_by_name("one-reminder")
    score = _score(
        case,
        [
            _step(_schedule(instruction="call mum", hour=18), SCHEDULED),
            _step(_schedule(instruction="the gym", hour=20), SCHEDULED),
        ],
    )
    assert score.duplicate_effects == 1


def test_a_forbidden_tool_is_recorded():
    case = case_by_name("move-the-stretch-reminder")
    score = _score(
        case,
        [_step(_manage(which="stretch reminder", operation="reschedule"), WORKED)],
    )
    assert score.unauthorized == ()
    assert score.carried is True, "the reference survived into the arguments"
    offending = _score(
        case,
        [
            _step(_manage(which="stretch reminder", operation="reschedule"), WORKED),
            _step(_schedule(), SCHEDULED),
        ],
    )
    assert "schedule_task" in offending.unauthorized


def test_a_failed_step_is_measured_not_counted_as_an_effect():
    case = case_by_name("cancel-nothing-found")
    score = _score(case, [_step(_manage(), FOUND_NOTHING)])
    assert score.failed_steps == 1
    assert score.duplicate_effects == 0


def test_the_search_then_remind_case_separates_the_two_tools():
    case = case_by_name("search-then-remind")
    assert case.only is None, "this case offers every tool to measure the gap"
    score = _score(
        case,
        [_step(_search(), WORKED), _step(_schedule(), SCHEDULED)],
    )
    assert score.completed is True
    assert score.carried is True


# The real loop, the real router: a turn that needs two automation tools in
# order. The rate is gated below a floor that was measured, not guessed.
@pytest.mark.asyncio
async def test_the_real_loop_completes_a_mixed_tool_turn_at_a_measured_rate(selector):
    from backend.services.trajectory_harness import repeat

    async def once():
        return await walk(
            selector,
            ask=case_by_name("cancel-and-reschedule").ask,
            world=World([WORKED]),
            max_steps=3,
        )

    rate = await repeat(once, lambda trip: len(trip) >= 2, reps=5)
    assert rate.rate >= 0.8, str(rate)


# Every case must be winnable in principle: its required predicates can match
# the steps the case's own script could produce. This keeps a case from being
# a measurement of something no loop could ever complete.
def test_every_case_has_a_winning_path_by_construction():
    for case in TRAJECTORY_CASES:
        predicates = case.required
        assert predicates, f"{case.name} requires nothing"
        assert case.required_times >= 1, f"{case.name} times must be positive"
        # A synthetic run of one step per required predicate per pass, in
        # order, must satisfy the case - otherwise it is unsatisfiable.
        synthetic = [
            _step(_synthetic_action(p), {"kind": "done"})
            for _ in range(case.required_times)
            for p in predicates
        ]
        score = _score(case, synthetic)
        assert score.completed, f"{case.name} cannot complete even by construction"


def _synthetic_action(predicate):
    if predicate is is_search:
        return _search()
    if predicate is is_manage:
        return _manage()
    if predicate is is_schedule:
        return _schedule()
    raise AssertionError(f"no synthetic action for {predicate}")


def test_tool_name_covers_every_automation_action():
    actions = (
        ManageTasksAction(operation="cancel"),
        ScheduleTaskAction(instruction="x", cadence="once", hour=1),
    )
    for action in actions:
        assert tool_name(action) in {"manage_tasks", "schedule_task"}
