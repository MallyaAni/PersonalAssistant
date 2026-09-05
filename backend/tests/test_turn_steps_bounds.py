"""The step loop's bounds, each pinned by the defect it closes.

Every rule in `run_steps` exists because something got past the one before
it, and every one of these tests is that something, arranged deterministically
so no model is needed to see it. The deadline test is the isolated probe from
the 2026-09-04 review: a 20 ms budget, an 80 ms decision, and the second
action was carried out at 81 ms anyway.
"""

import asyncio
from dataclasses import dataclass

import pytest

from backend.services.turn_steps import (
    BUDGET,
    DECLINED,
    FAILED,
    NEEDS_INPUT,
    REPEATED,
    SECOND_CREATE,
    SUCCEEDED,
    UNAVAILABLE,
    UNKNOWN,
    UNKNOWN_STATUS,
    Act,
    Done,
    NeedsInput,
    Unavailable,
    as_decision,
    run_steps,
    status_of,
)

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class Reminder:
    """A stand-in for a creating action, keyed on its words."""

    words: str


# One line per step, the shape the model would read.
def _describe(action, kind, outcome) -> str:
    return f"{kind}:{action!r}:{(outcome or {}).get('kind', '')}"


# A world that applies everything and records what it was asked.
class _World:
    def __init__(self, outcome=None, delay: float = 0.0) -> None:
        self.applied: list = []
        self.outcome = outcome or {"kind": "done"}
        self.delay = delay

    async def apply(self, action):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.applied.append(action)
        return "task", dict(self.outcome)


# A decision returned after the budget is spent must not be carried out.
async def test_an_action_decided_after_the_deadline_is_not_applied():
    world = _World()

    async def decide(lines):
        await asyncio.sleep(0.08)
        return "second"

    result = await run_steps(
        "first",
        apply=world.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: False,
        max_steps=3,
        budget_seconds=0.02,
    )
    assert world.applied == ["first"], world.applied
    assert result.stopped == BUDGET


# A later step still running at the deadline is cut, recorded as unknown,
# and the loop says so rather than waiting for it or dropping it.
async def test_a_later_step_cut_at_the_deadline_is_recorded_as_unknown():
    world = _World(delay=0.3)
    decided = iter(["second", "third"])

    async def decide(lines):
        return next(decided)

    result = await run_steps(
        "first",
        apply=world.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: False,
        max_steps=3,
        budget_seconds=0.4,
    )
    assert result.stopped == UNKNOWN
    assert [step.action for step in result.steps] == ["first", "second"]
    assert result.steps[-1].status == UNKNOWN_STATUS
    assert result.unknown == (result.steps[-1],)
    assert "unknown" in result.steps[-1].line


# The first action is the turn's own request and runs to completion however
# long it takes; only what the loop adds is bounded - unless a caller that
# owns its whole clock asks for the first to be bounded too.
async def test_the_first_step_is_never_cut_unless_asked():
    slow = _World(delay=0.15)

    async def decide(lines):
        return None

    result = await run_steps(
        "first",
        apply=slow.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: False,
        max_steps=3,
        budget_seconds=0.05,
    )
    assert slow.applied == ["first"]
    assert result.steps[0].status == SUCCEEDED
    assert result.stopped == BUDGET

    bounded = _World(delay=0.15)
    result = await run_steps(
        "first",
        apply=bounded.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: False,
        max_steps=3,
        budget_seconds=0.05,
        bound_first=True,
    )
    assert result.stopped == UNKNOWN
    assert result.steps[0].status == UNKNOWN_STATUS


# Two reminders with different words are two effects; the same reminder
# worded twice is one, and the loop stops on it whatever its repr says.
async def test_repeats_are_judged_on_the_natural_key_not_the_repr():
    world = _World()
    decided = iter([Reminder("gym at 8pm"), Reminder("Call  Mum")])

    async def decide(lines):
        return next(decided)

    result = await run_steps(
        Reminder("call mum"),
        apply=world.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: True,
        max_steps=5,
        budget_seconds=5.0,
        key=lambda a: " ".join(a.words.casefold().split()),
        max_creates=5,
    )
    assert [a.words for a in world.applied] == ["call mum", "gym at 8pm"]
    assert result.stopped == REPEATED


# The creation allowance is a count: two distinct reminders in one turn are
# both written, and the one past the allowance is stopped by name.
async def test_the_creation_allowance_admits_distinct_creates_up_to_its_count():
    world = _World()
    decided = iter([Reminder("gym"), Reminder("bins")])

    async def decide(lines):
        return next(decided)

    result = await run_steps(
        Reminder("mum"),
        apply=world.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: True,
        max_steps=5,
        budget_seconds=5.0,
        key=lambda a: a.words,
        max_creates=2,
    )
    assert [a.words for a in world.applied] == ["mum", "gym"]
    assert result.stopped == SECOND_CREATE


# A creation that failed created nothing and does not spend the allowance.
async def test_a_failed_creation_does_not_spend_the_allowance():
    outcomes = iter([{"kind": "failed"}, {"kind": "done"}, {"kind": "done"}])
    applied: list = []

    async def apply(action):
        applied.append(action)
        return "task", dict(next(outcomes))

    decided = iter([Reminder("again"), Reminder("third")])

    async def decide(lines):
        return next(decided)

    result = await run_steps(
        Reminder("first"),
        apply=apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: True,
        max_steps=5,
        budget_seconds=5.0,
        key=lambda a: a.words,
        max_creates=1,
    )
    # The failed first create left the allowance whole, so the second was
    # written; the third is the one past the allowance.
    assert [a.words for a in applied] == ["first", "again"]
    assert result.stopped == SECOND_CREATE
    assert result.steps[0].status == FAILED


# The default allowance is one, so a caller written before it was a count
# keeps exactly the behaviour it had.
async def test_the_default_allowance_is_one():
    world = _World()

    async def decide(lines):
        return Reminder("second")

    result = await run_steps(
        Reminder("first"),
        apply=world.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: True,
        max_steps=3,
        budget_seconds=5.0,
    )
    assert [a.words for a in world.applied] == ["first"]
    assert result.stopped == SECOND_CREATE


# Four things used to be the same None. Each is now its own stop, and only
# the router's own "nothing further" is a clean one.
@pytest.mark.parametrize(
    ("decision", "stopped", "clean"),
    [
        (Done("nothing further"), DECLINED, True),
        (None, DECLINED, True),
        (NeedsInput("schedule_task", "the time"), NEEDS_INPUT, False),
        (Unavailable("the routing model did not answer"), UNAVAILABLE, False),
    ],
)
async def test_each_kind_of_non_action_is_its_own_stop(decision, stopped, clean):
    world = _World()

    async def decide(lines):
        return decision

    result = await run_steps(
        "first",
        apply=world.apply,
        decide=decide,
        describe=_describe,
        creates=lambda a: False,
        max_steps=3,
        budget_seconds=5.0,
    )
    assert result.stopped == stopped
    assert result.clean is clean
    if isinstance(decision, NeedsInput):
        assert result.detail == "schedule_task"
    if isinstance(decision, Unavailable):
        assert result.detail == decision.reason


# A bare action from a caller written before decisions were typed still acts.
async def test_a_bare_action_is_still_understood_as_a_decision():
    assert isinstance(as_decision("anything"), Act)
    assert isinstance(as_decision(None), Done)
    assert as_decision(Done()) == Done()


# The outcome vocabulary every applier writes, read one way.
@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("done", SUCCEEDED),
        ("scheduled", SUCCEEDED),
        ("found", SUCCEEDED),
        ("nothing", SUCCEEDED),
        ("failed", FAILED),
        ("not_found", FAILED),
        ("refused", FAILED),
        ("blocked", FAILED),
        ("unavailable", FAILED),
        ("needs_place", FAILED),
        ("unknown", UNKNOWN_STATUS),
    ],
)
async def test_status_reads_the_outcome_vocabulary(kind, status):
    assert status_of({"kind": kind}) == status
