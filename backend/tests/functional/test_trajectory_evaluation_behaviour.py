"""The trajectory evaluator: whole-turn measurement against the real router.

The first-tool matrix measures one decision and cannot see a turn that needs
two tools and stops after one, a failed step counted as done, or two
legitimate writes cut to one by the repeat guard. This drives the real router
through those shapes with the trajectory harness - only what a step *does* is
scripted - and pins the corrected scoring as a pure function, so a measurement
is deterministic before any model is asked. Completion requires the required
effects to have succeeded with the right operation and arguments; a failed
reminder for the wrong task at the wrong time, or two copies of one reminder
for two requested, must not score as done.
"""
import pytest

from backend.services.trajectory_cases import (
    TRAJECTORY_CASES,
    TrajectoryCase,
    case_by_name,
)
from backend.services.trajectory_harness import (
    RequiredEffect,
    Trajectory,
    World,
    score_trajectory,
    tool_name,
    walk,
)
from backend.services.turn_steps import (
    CEILING,
    DECLINED,
    REPEATED,
    SECOND_CREATE,
    Step,
    run_steps,
)
from backend.tools.actions import (
    ManageTasksAction,
    ScheduleTaskAction,
    SearchAction,
)

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


def _observation(case, steps):
    from backend.cli.evaluate_trajectories import TrajectoryObservation

    trip = Trajectory(tuple(steps), CEILING, ())
    return TrajectoryObservation(case, trip, score_trajectory(case, trip, 1.0))


# A step that satisfies one required effect, so a case can be shown winnable
# by construction. The arguments are chosen to carry the effect's words.
def _synthetic_step(effect: RequiredEffect):
    tool = sorted(effect.allowed)[0]
    carries = " ".join(effect.carries)
    if tool == "manage_tasks":
        operation = effect.operation or "cancel"
        return _step(
            ManageTasksAction(operation=operation, which=carries or "the reminder"),
            WORKED,
        )
    if tool == "schedule_task":
        return _step(
            ScheduleTaskAction(
                instruction=carries or "call mum", cadence="once", hour=18
            ),
            {"kind": "scheduled"},
        )
    if tool in {"search_web", "search_credits", "get_weather"}:
        return _step(
            SearchAction(carries or "pottery class courthouse virginia"), WORKED
        )
    raise AssertionError(f"no synthetic action for {effect}")


# Rewrite one step's action so its arguments carry a cover word, so a case
# that demands two different creations can be satisfied by construction.
def _with_cover(step, word):
    action = step.action
    if isinstance(action, ScheduleTaskAction):
        covered = ScheduleTaskAction(
            instruction=word,
            cadence=action.cadence,
            hour=action.hour,
            minute=action.minute,
            weekday=action.weekday,
            on_date=action.on_date,
        )
        return Step(covered, step.kind, step.outcome, step.line)
    return step


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
    assert score.carried is True
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
    assert both.duplicate_effects == 0, "two different writes were allowed"


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
    clean = _score(
        case,
        [_step(_manage(which="stretch reminder", operation="reschedule"), WORKED)],
    )
    assert clean.unauthorized == ()
    assert clean.completed is True
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
    assert score.completed is True, "the failure was seen and nothing fabricated"
    assert score.duplicate_effects == 0


def test_the_search_then_remind_case_separates_the_two_tools():
    case = case_by_name("search-then-remind")
    assert case.only is None, "this case offers every tool to measure the gap"
    score = _score(
        case,
        [
            _step(_search(), WORKED),
            _step(_schedule(instruction="pottery class at 3pm"), SCHEDULED),
        ],
    )
    assert score.completed is True
    assert score.carried is True


# The four false positives the first scorer had, pinned so they cannot return:
# completion must require the successful outcome, the right operation, the
# right arguments, and - for two requests - two different creations.
def test_a_failed_reminder_for_the_wrong_task_is_not_complete():
    case = case_by_name("cancel-and-reschedule")
    score = _score(
        case,
        [
            _step(_manage(), WORKED),
            _step(
                ScheduleTaskAction(instruction="tesla update", cadence="once", hour=3),
                {"kind": "failed"},
            ),
        ],
    )
    assert score.completed is False, "a failed reminder is not a scheduled one"
    assert score.carried is False


def test_two_identical_reminders_do_not_satisfy_two_different_requests():
    case = case_by_name("two-reminders")
    score = _score(
        case,
        [
            _step(_schedule(instruction="call mum", hour=18), SCHEDULED),
            _step(_schedule(instruction="call mum", hour=18), SCHEDULED),
        ],
    )
    assert score.completed is False, "two copies of one reminder are not two writes"
    assert score.duplicate_effects == 1


def test_listing_tasks_is_not_rescheduling_the_stretch_reminder():
    case = case_by_name("move-the-stretch-reminder")
    score = _score(
        case,
        [_step(_manage(which="stretch reminder", operation="list"), WORKED)],
    )
    assert score.completed is False, "listing is not rescheduling"


def test_unauthorized_and_duplicates_fail_the_gate():
    from backend.cli.evaluate_trajectories import acceptance

    reference = case_by_name("move-the-stretch-reminder")
    forbidden = _observation(
        reference,
        [
            _step(_manage(which="stretch reminder", operation="reschedule"), WORKED),
            _step(_schedule(), SCHEDULED),
        ],
    )
    assert acceptance([forbidden]), "a forbidden tool must breach the gate"

    single = case_by_name("one-reminder")
    doubled = _observation(
        single,
        [
            _step(_schedule(), SCHEDULED),
            _step(_schedule(instruction="the gym", hour=20), SCHEDULED),
        ],
    )
    assert acceptance([doubled]), "a duplicate effect must breach the gate"

    clean = _observation(single, [_step(_schedule(), SCHEDULED)])
    assert acceptance([clean]) == [], "a clean one-reminder must pass"


# The stop the loop names is the stop that actually fired, never an inference.
@pytest.mark.asyncio
async def test_the_loop_names_the_second_creation_as_its_stop():
    stage = World([{"kind": "scheduled"}])

    async def decide(lines):
        return ScheduleTaskAction(instruction="the gym", cadence="once", hour=20)

    first = ScheduleTaskAction(instruction="call mum", cadence="once", hour=18)
    result = await run_steps(
        first,
        apply=stage.apply,
        decide=decide,
        describe=lambda action, kind, outcome: "scheduled",
        creates=lambda item: isinstance(item, ScheduleTaskAction),
        max_steps=3,
    )
    assert result.stopped == SECOND_CREATE
    assert len(result.steps) == 1


# Every case must be winnable in principle: a synthetic run that satisfies
# each required effect, `required_times` over, must complete it (cover words
# included). This keeps a case from measuring something no loop could ever do.
def test_every_case_has_a_winning_path_by_construction():
    for case in TRAJECTORY_CASES:
        assert case.required, f"{case.name} requires nothing"
        if case.honest_failure:
            continue  # a case with an unreachable goal is not winnable
        steps = []
        for i in range(case.required_times):
            for effect in case.required:
                step = _synthetic_step(effect)
                if i < len(case.covers):
                    step = _with_cover(step, case.covers[i])
                steps.append(step)
        score = _score(case, steps)
        assert score.completed, f"{case.name} cannot complete even by construction"
        assert score.duplicate_effects == 0, f"{case.name} duplicates its own path"


def test_tool_name_covers_every_automation_action():
    actions = (
        ManageTasksAction(operation="cancel"),
        ScheduleTaskAction(instruction="x", cadence="once", hour=1),
    )
    for action in actions:
        assert tool_name(action) in {"manage_tasks", "schedule_task"}


# The real loop, the real router. The corrected scorer must never report a
# trajectory complete unless its path actually holds the required successful
# effects - the false positive this gate used to reward with `len(trip) >= 2`.
@pytest.mark.asyncio
async def test_the_real_loop_is_never_scored_complete_without_its_effects(selector):
    case = case_by_name("cancel-and-reschedule")
    for _ in range(3):
        trip = await walk(
            selector, ask=case.ask, world=World([WORKED]), max_steps=3
        )
        score = score_trajectory(case, trip, 1.0)
        if score.completed:
            # Either accepted path: cancel then set, or the one reschedule that
            # moves the 5pm reminder to 18:00 with its words.
            assert "manage_tasks" in score.path, score
            assert score.carried is True, score


# Two reminders requested are two reminders written, distinct and without a
# duplicate - the Phase 2 repair, measured 3/3 on 2026-09-05 once the step
# line carried the instruction. Held as a rate: loops compound.
@pytest.mark.asyncio
async def test_two_reminders_are_both_written(selector):
    case = case_by_name("two-reminders")
    held = 0
    seen = []
    for _ in range(3):
        trip = await walk(selector, ask=case.ask, world=World([SCHEDULED]), max_steps=3)
        score = score_trajectory(case, trip, 1.0)
        seen.append((score.path, trip.stopped, score.completed, score.duplicate_effects))
        assert score.duplicate_effects == 0, seen
        assert trip.stopped in {SECOND_CREATE, REPEATED, DECLINED, CEILING}, trip.stopped
        if score.completed:
            held += 1
    assert held >= 2, seen
