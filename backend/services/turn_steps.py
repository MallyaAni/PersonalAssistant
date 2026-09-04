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
  2. an identical repeat, compared on shape, never on meaning
  3. a second creation of anything, whatever its arguments
  4. a step ceiling
  5. a wall clock, because time is what starves the next person in the queue
     while a worker answers serially
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Step:
    """One action carried out, and whatever the doing of it recorded."""

    action: Any
    kind: str
    outcome: dict[str, Any]
    line: str


# Run the decide/act cycle to a stop, and return what actually happened.
#
# `apply` returns None for an action this loop does not carry out, which is how
# a turn that routed to something else - a search, a picture, no tool at all -
# passes through having done nothing. `decide` is handed the lines of what is
# already done and returns the next action or None.
async def run_steps(
    first: Any,
    apply: Callable[[Any], Awaitable[tuple[str, dict[str, Any]] | None]],
    decide: Callable[[list[str]], Awaitable[Any]],
    describe: Callable[[Any, str, dict[str, Any] | None], str],
    creates: Callable[[Any], bool],
    max_steps: int = 1,
    budget_seconds: float = 45.0,
) -> list[Step]:
    steps: list[Step] = []
    seen: set[str] = set()
    created = 0
    started = monotonic()
    action = first

    while action is not None:
        applied = await apply(action)
        if applied is None:
            break
        kind, outcome = applied
        steps.append(Step(action, kind, outcome, describe(action, kind, outcome)))
        seen.add(repr(action))
        if creates(action):
            created += 1

        if len(steps) >= max(1, max_steps):
            break
        if monotonic() - started >= budget_seconds:
            logger.info("Turn step budget spent after %d step(s)", len(steps))
            break

        action = await decide([step.line for step in steps])
        if action is None:
            break
        if repr(action) in seen:
            logger.info("Turn repeated an identical action; stopping")
            break
        if creates(action) and created:
            logger.info("Turn tried to create a second thing; stopping")
            break

    return steps
