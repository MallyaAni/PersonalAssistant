"""Keep deciding and acting until the request has nothing left in it.

One tool decision per turn was never a design, it was a ceiling on what a
request could express. `manage_tasks` used to say, in its own description, that
changing a reminder's time meant cancelling it and scheduling a new one - two
calls, where the selector makes one. Handed a request it had no way to carry
out, the model answered as though it had, and the row was untouched.

This is the loop that lifts the ceiling, kept apart from
`ConversationService` for two reasons. It is the piece a future agent will
want, and it is the piece that has to be tested against the real router: a
test that reimplements the loop proves the reimplementation, not the code that
runs.

**The stopping rules are the whole design.** A model asked "is that enough?"
answers yes too readily, so it is never asked - it is asked for the *next*
action, and the absence of one is the stop. That alone is not sufficient
either. Told in the prompt never to repeat what was already done, the router
scheduled one reminder three times in a row; `ScheduledTaskRepository.create`
has no dedupe key, so each pass is another reminder nobody asked for. Every
bound here exists because something got past the one before it:

  1. the router declining to name a tool - the intended stop
  2. a repeat, compared on the action's natural key when its tool declares
     one and on its whole shape otherwise, never on meaning
  3. a creation past the turn's allowance. One allowance was the first
     rule and it cut "set reminders for 6pm and 8pm" to one reminder; the
     allowance is now a count, and two copies of the same reminder are
     still stopped by rule 2, because they share a key
  4. a step ceiling
  5. a wall clock, because time is what starves the next person in the queue
     while a worker answers serially. Read before every decision and again
     before every action: a decision that arrived after the budget was spent
     used to be carried out anyway, measured at 81 ms against a 20 ms budget
     (2026-09-04), and an in-flight call is now cut at the deadline rather
     than waited for
  6. a decision that is not an action - the router needing something the
     message did not say, or the router failing outright - which used to be
     the same `None` as "nothing further" and so read as a clean stop

A step that was cut at the deadline is recorded with its outcome `unknown`,
never dropped: the call was dispatched and nothing here can say whether it
happened. Whoever reads the result reconciles it by the action's key before
doing anything that would repeat it.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)

# Why a loop stopped. Named, because there are nine separate stopping rules
# and "it stopped" is not a result: a turn that ended because the router had
# nothing left to do and a turn that ended against the wall clock look
# identical from the outside and mean opposite things. The loop says which one
# actually fired; nothing outside it should have to guess.
DECLINED = "the router named no further tool"
CEILING = "the step ceiling was reached"
REPEATED = "the router repeated a step"
UNAPPLIED = "the action was not one this loop carries out"
BUDGET = "the wall clock ran out"
SECOND_CREATE = "the turn reached its creation allowance"
NEEDS_INPUT = "the router needs something the message did not say"
UNAVAILABLE = "the router could not decide"
UNKNOWN = "a step was cut at the deadline with its outcome unknown"

# Stops that mean the request was seen through to the router's own stop.
# Everything else is a bound firing, and a caller judging completion must not
# read one as "done".
CLEAN_STOPS: frozenset[str] = frozenset({DECLINED})


# ---------------------------------------------------------------- decisions


@dataclass(frozen=True, slots=True)
class Act:
    """The router named the next action."""

    action: Any


@dataclass(frozen=True, slots=True)
class Done:
    """The router named no further tool: the intended stop."""

    reason: str = "nothing further"


@dataclass(frozen=True, slots=True)
class NeedsInput:
    """The router chose a tool but could not fill what it requires. The
    reply, not the loop, asks the person for it."""

    tool: str
    missing: str = ""


@dataclass(frozen=True, slots=True)
class Unavailable:
    """The router failed to decide at all - the model was unreachable, or
    named a tool that was never offered. Not a stop the request asked for."""

    reason: str


Decision = Act | Done | NeedsInput | Unavailable


# Read whatever a `decide` callback returned as a typed decision. A callback
# written before decisions were typed returns the action or None; both are
# still understood, so the harness and every existing caller keep working
# while they move over.
def as_decision(value: Any) -> Decision:
    if isinstance(value, Act | Done | NeedsInput | Unavailable):
        return value
    if value is None:
        return Done()
    return Act(value)


# ------------------------------------------------------------------ results

SUCCEEDED = "succeeded"
FAILED = "failed"
UNKNOWN_STATUS = "unknown"

# Outcome kinds every applier in this repository uses to say a step did not
# do what it was asked. Anything else is a success; `unknown` is neither.
FAILED_KINDS: frozenset[str] = frozenset(
    {
        "failed",
        "invalid",
        "not_found",
        "none",
        "unavailable",
        "refused",
        "blocked",
        "needs_place",
    }
)


# Whether a step's outcome says it did what it was asked, did not, or was
# cut before anyone could tell. Read off the outcome's `kind`, which is the
# vocabulary every applier here already writes.
def status_of(outcome: dict[str, Any] | None) -> str:
    kind = str((outcome or {}).get("kind") or "")
    if kind == "unknown":
        return UNKNOWN_STATUS
    if kind in FAILED_KINDS:
        return FAILED
    return SUCCEEDED


@dataclass(frozen=True, slots=True)
class Step:
    """One action carried out, and whatever the doing of it recorded."""

    action: Any
    kind: str
    outcome: dict[str, Any]
    line: str

    # Whether this step did what it was asked, did not, or cannot say.
    @property
    def status(self) -> str:
        return status_of(self.outcome)


# What a loop did and why it stopped. The steps alone cannot say why the loop
# ended - a decline, the ceiling, a repeat, a spent allowance and a spent
# budget all leave the same list - so the reason rides with them.
@dataclass(frozen=True, slots=True)
class TurnResult:
    """The steps a loop carried out, which rule stopped it, and any detail
    the stop carries - the tool that needed input, the reason the router
    could not decide."""

    steps: tuple[Step, ...]
    stopped: str
    detail: str = ""

    # Whether the loop reached the router's own stop rather than a bound.
    @property
    def clean(self) -> bool:
        return self.stopped in CLEAN_STOPS

    # Steps whose outcome is not known, to be reconciled before any retry.
    @property
    def unknown(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.status == UNKNOWN_STATUS)


@dataclass(frozen=True, slots=True)
class Resume:
    """Where a loop left off, for a run picked up after a restart: the lines
    of what was already done (so the next decision sees them), the keys of
    the effects that succeeded (so none is repeated), how many things were
    created, and how many steps were taken against the ceiling."""

    lines: tuple[str, ...] = ()
    keys: frozenset[str] = frozenset()
    created: int = 0
    steps: int = 0


# --------------------------------------------------------------------- loop


# Run the decide/act cycle to a stop, and return what actually happened.
#
# `apply` returns None for an action this loop does not carry out, which is how
# a turn that routed to something else - a picture, no tool at all - passes
# through having done nothing. `decide` is handed the lines of what is already
# done and returns the next decision (or, for a caller written before
# decisions were typed, the next action or None).
#
# `key` reads a tool's natural key off an action so a repeat is judged on what
# the call would do rather than on how the model happened to word it; an
# action with no key is judged on its whole shape. `creates` says which
# actions make a new thing, and `max_creates` how many of those the turn may
# make. The budget bounds the loop's own additions: a later decision and a
# later action each run under whatever time is left, and an action cut at the
# deadline is recorded with its outcome unknown. The first action is the
# turn's own request and runs to completion unless `bound_first` is set,
# which a run that owns its whole clock will want.
async def run_steps(
    first: Any,
    apply: Callable[[Any], Awaitable[tuple[str, dict[str, Any]] | None]],
    decide: Callable[[list[str]], Awaitable[Any]],
    describe: Callable[[Any, str, dict[str, Any] | None], str],
    creates: Callable[[Any], bool],
    max_steps: int = 1,
    budget_seconds: float = 45.0,
    *,
    key: Callable[[Any], str | None] | None = None,
    max_creates: int = 1,
    bound_first: bool = False,
    resume: Resume | None = None,
) -> TurnResult:
    steps: list[Step] = []
    # A resumed run carries what an earlier attempt already did: those steps
    # count against the ceiling and the allowance, and their keys are seen.
    taken_before = resume.steps if resume is not None else 0
    prior_lines = list(resume.lines) if resume is not None else []
    seen: set[str] = set(resume.keys) if resume is not None else set()
    created = resume.created if resume is not None else 0
    started = monotonic()

    # How much of the budget is left, negative once it is spent.
    def remaining() -> float:
        return budget_seconds - (monotonic() - started)

    # What a repeat is compared on: the tool's own key when it has one.
    def fingerprint(action: Any) -> str:
        found = key(action) if key is not None else None
        return found if found else repr(action)

    action = first
    while action is not None:
        # The key of the action as it was chosen. Read before it runs, because
        # a world may count a failed attempt into the next key: read after,
        # the retry's fresh key was already the one recorded as seen, and a
        # bounded retry read as a repeat (the reviewer, 2026-09-05).
        chosen_key = fingerprint(action)
        limit = remaining() if (steps or bound_first) else None
        if limit is not None and limit <= 0:
            logger.info("Turn step budget spent before step %d", len(steps) + 1)
            return TurnResult(tuple(steps), BUDGET)
        try:
            if limit is None:
                applied = await apply(action)
            else:
                async with asyncio.timeout(limit):
                    applied = await apply(action)
        except TimeoutError:
            outcome = {"kind": "unknown"}
            steps.append(
                Step(action, "unknown", outcome, describe(action, "unknown", outcome))
            )
            logger.warning(
                "Turn step %d was cut at the deadline; its outcome is unknown",
                len(steps),
            )
            return TurnResult(tuple(steps), UNKNOWN)
        if applied is None:
            return TurnResult(tuple(steps), UNAPPLIED)
        kind, outcome = applied
        steps.append(Step(action, kind, outcome, describe(action, kind, outcome)))
        seen.add(chosen_key)
        # A creation that failed created nothing and does not spend the
        # allowance; one whose outcome is unknown may have, and does.
        if creates(action) and status_of(outcome) != FAILED:
            created += 1

        if taken_before + len(steps) >= max(1, max_steps):
            return TurnResult(tuple(steps), CEILING)
        if remaining() <= 0:
            logger.info("Turn step budget spent after %d step(s)", len(steps))
            return TurnResult(tuple(steps), BUDGET)

        try:
            async with asyncio.timeout(remaining()):
                chosen = await decide(prior_lines + [step.line for step in steps])
        except TimeoutError:
            logger.info("Turn step budget spent while deciding step %d", len(steps) + 1)
            return TurnResult(tuple(steps), BUDGET)
        decision = as_decision(chosen)
        if isinstance(decision, Done):
            return TurnResult(tuple(steps), DECLINED, decision.reason)
        if isinstance(decision, NeedsInput):
            logger.info(
                "Turn stopped: %s needs %s", decision.tool, decision.missing or "input"
            )
            return TurnResult(tuple(steps), NEEDS_INPUT, decision.tool)
        if isinstance(decision, Unavailable):
            logger.warning(
                "Turn stopped: the router could not decide (%s)", decision.reason
            )
            return TurnResult(tuple(steps), UNAVAILABLE, decision.reason)
        action = decision.action
        if fingerprint(action) in seen:
            logger.info("Turn repeated an identical action; stopping")
            return TurnResult(tuple(steps), REPEATED)
        if creates(action) and created >= max_creates:
            logger.info(
                "Turn reached its creation allowance (%d); stopping", max_creates
            )
            return TurnResult(tuple(steps), SECOND_CREATE)

    return TurnResult(tuple(steps), DECLINED)
