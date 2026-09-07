"""Score which tool the router picks, and report what it mistakes for what.

    python -m backend.cli.evaluate_tool_selection --reps 3

The existing routing tests each ask a binary question about one tool. This
reports the full picture: accuracy per expected tool, and the matrix of what
was chosen instead. A wrong turn is only fixable once you know what it became -
a request scattering across three unrelated tools is a model with no right
answer available, while one landing on the same wrong tool every time is
usually a sentence in a prompt.

Cost is not symmetric either, so the matrix is the honest output rather than a
single accuracy number: a stray `search_web` costs a second, a stray
`edit_image` mutates an artifact and spends a ninety-second generation, and a
search that should have fired and did not returns a confident wrong answer with
nothing to signal it. Read the cells, not the total.

Use it to compare two candidate models before promoting one. The last
head-to-head scored 45/50 against 44/50 - statistically a tie - while the
failure modes underneath were opposites, which a single number cannot show.
"""

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from typing import Any

from backend.config.settings import settings
from backend.core.evaluation_log import record
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.services.main_action_selector import (
    clear_decision_cache,
    CreateDiagramAction,
    CreateDocumentAction,
    EditDocumentAction,
    DelegateAction,
    DiscussImageAction,
    EditImageAction,
    GenerateImageAction,
    MainActionSelector,
    ManageSkillsAction,
    ManageTasksAction,
    ManageCheckInsAction,
    ManageRunsAction,
    ScoutScheduleAction,
    SaveSkillAction,
    ScheduleTaskAction,
    SendEventLinksAction,
    RecallHistoryAction,
    SearchAction,
    ShowImageAction,
    ToolboxAction,
)
from backend.search.budgeted import SearchIdentity, current_search_identity
from backend.tools.search import SEARCH_CREDITS_TOOL
from backend.services.tool_selection_cases import (
    SelectionCase,
    SEARCH,
    SEARCH_CREDITS,
    ACCURACY_FLOOR,
    ARGUMENT_FLOOR,
    PER_TOOL_ACCURACY_FLOORS,
    NO_TOOL,
    SELECTION_CASES,
    TOOL_NAMES,
)

_ACTION_TOOL = {
    SearchAction: "search_web",
    GenerateImageAction: "generate_image",
    EditImageAction: "edit_image",
    ShowImageAction: "show_image",
    CreateDiagramAction: "create_diagram",
    CreateDocumentAction: "create_document",
    EditDocumentAction: "edit_document",
    DelegateAction: "delegate_to_presentation_agent",
    DiscussImageAction: "discuss_image",
    ToolboxAction: "mcp_tool",
    # Absent until 2026-08-23, so every task and skill decision - correct or
    # not - was scored as "no tool". The four newest capabilities were
    # unmeasurable, and the aggregate looked fine because their failures were
    # being counted as successes for `none`.
    ScheduleTaskAction: "schedule_task",
    ManageTasksAction: "manage_tasks",
    ManageCheckInsAction: "manage_check_ins",
    ScoutScheduleAction: "scout_schedule",
    SaveSkillAction: "save_skill",
    ManageSkillsAction: "manage_skills",
    # Absent again for search_history (2026-08-25): the tool shipped and
    # the gap-catcher caught it.
    RecallHistoryAction: "search_history",
    ManageRunsAction: "manage_runs",
    SendEventLinksAction: "send_event_links",
}


# Name the tool one decision resolved to, including the decision to use none.
def tool_of(action: object) -> str:
    # The search meter is a toolbox action by mechanism (it lives on the
    # internet MCP server) and its own tool by measurement.
    if isinstance(action, ToolboxAction) and action.plan.tool_name == SEARCH_CREDITS_TOOL:
        return SEARCH_CREDITS
    # A weather question answered by the forecast tool is the live-data
    # decision made better, not a miss - the behaviour suite already scores
    # it so; the matrix did not, and counted every weather case against it.
    if isinstance(action, ToolboxAction) and action.plan.tool_name == "get_weather":
        return SEARCH
    return _ACTION_TOOL.get(type(action), NO_TOOL)


@dataclass(frozen=True, slots=True)
class Observation:
    """One pass of one case: the tool wanted, the tool taken, and whether what
    the model wrote for it carried the turn's own words through."""

    expected: str
    chosen: str
    category: str
    query: str
    arguments_held: bool | None
    written: str


# Everything the model wrote for this call, as one searchable string. The
# actions are frozen dataclasses of scalars, so their own fields are the
# arguments - no per-tool list here that a new tool could fall off.
def arguments_of(action: object) -> str:
    if action is None:
        return ""
    if isinstance(action, ToolboxAction):
        return " ".join(str(value) for value in action.plan.arguments.values())
    fields = getattr(action, "__dataclass_fields__", None)
    if not fields:
        return ""
    return " ".join(str(getattr(action, name, "")) for name in fields)


# Whether the arguments carried through what the turn already contained.
# None when the case asks nothing of them, so a case with no expectation is
# neither a pass nor a failure and cannot flatter the score.
def arguments_hold(case: SelectionCase, action: object) -> bool | None:
    if not case.carries and not case.avoids:
        return None
    # A tool that should not have been called has no argument question to
    # answer. Scoring it here counted one routing miss twice and printed the
    # empty arguments of the call that never happened as though the model had
    # written nothing into a call it made.
    if tool_of(action) != case.expected:
        return None
    written = arguments_of(action).casefold()
    if not written:
        return False
    if any(word.casefold() not in written for word in case.carries):
        return False
    return not any(word.casefold() in written for word in case.avoids)


# How many cases may be in flight against the routing model at once.
#
# The deploy gate spent 9m30s of its 19m18s here, asking the model 51
# questions strictly one after another while the model sat mostly idle.
# These are independent questions - no case reads another's answer - so
# the only reason they were serial was that the loop was written that way.
# The cap exists because the model serves a fixed number of concurrent
# requests and queueing far past that adds latency without throughput.
#
# Concurrency needs its own clients to be worth anything. `LLMClient` holds
# a mutex across the whole request - `chat` and `chat_with_tools` both take
# `_request_lock` - so every caller sharing one instance is serialised no
# matter how many tasks are waiting. Running the cases concurrently through
# a single selector changed nothing at all; the first measured improvement,
# 19m18s to 13m33s, came entirely from the gate running its five files at
# once. `make_selector` is how a caller says "build me one of these per
# slot", and each carries its own client and therefore its own lock.
SELECTION_CONCURRENCY = 6


# One labelled case against the model, as its own task so the identity it
# sets is its own. `current_search_identity` is a ContextVar, and a task
# started by `gather` runs in a copy of the context, so concurrent cases
# cannot see each other's identity. Run as bare coroutines in one task they
# would, and a case routed as the operator would decide a guest's question.
async def _observe(
    selector: MainActionSelector,
    case: SelectionCase,
    limit: asyncio.Semaphore,
) -> Observation:
    history = [
        {"query": query, "response": response} for query, response in case.history
    ]
    # Routed as the operator when the case says so: some tools are offered
    # only to them, and a case for such a tool routed as a guest measures
    # the withholding, not the choice.
    identity = SearchIdentity(user_id="tool_selection_eval", is_operator=case.operator)
    async with limit:
        token = current_search_identity.set(identity)
        try:
            action = await selector.select(
                "tool_selection_eval",
                case.query,
                history,
                "active-image-id" if case.active_image else None,
                local_now=case.local_now,
                unattended=case.unattended,
            )
        finally:
            current_search_identity.reset(token)
    return Observation(
        case.expected,
        tool_of(action),
        case.category,
        case.query,
        arguments_hold(case, action),
        arguments_of(action)[:200],
    )


# Run every labelled case and return the chosen tool for each observation.
#
# One rep at a time, every case within it at once. The cache is cleared
# once per rep rather than once per call, which is the same thing: a rep's
# cases are all different questions, so no case can read another's answer
# from the cache, and the clear that mattered was always the one between
# repeated passes of the *same* question. The point of a repeated pass is
# to sample the model's own variance, and the routing cache answers an
# identical question from memory - every field of its key is fixed here,
# so without the clear the second and third passes read back the first
# one's answer and every rate measured is one observation wearing three
# coats. True since the cache shipped in 82d0e9b8.
#
# Within a rep the observations are in case order whatever order the
# answers arrive in. Across reps they are grouped by rep rather than by
# case, which the original interleaved the other way; nothing reads them
# positionally - `failures` tallies by query and the gate counts matches -
# so the grouping is free to change and the counts are identical.
async def collect(
    selector: MainActionSelector,
    reps: int,
    cases: tuple[SelectionCase, ...] = SELECTION_CASES,
    concurrency: int = SELECTION_CONCURRENCY,
    make_selector: Callable[[], MainActionSelector] | None = None,
) -> list[Observation]:
    # Without a factory there is one selector, so one client, so one lock,
    # and asking more than one question at a time would only queue on it.
    pool = (
        [selector]
        if make_selector is None
        else [make_selector() for _ in range(max(1, concurrency))]
    )
    limit = asyncio.Semaphore(len(pool))
    observations: list[Observation] = []
    for _rep in range(reps):
        clear_decision_cache()
        observations.extend(
            await asyncio.gather(
                *(
                    _observe(pool[i % len(pool)], case, limit)
                    for i, case in enumerate(cases)
                )
            )
        )
    return observations


# Which cases actually failed, and how consistently.
#
# The aggregate says "none -> search_history, 6". It does not say which six
# questions, so the one thing a person needs to fix it - the wording that
# misled the router - was the one thing the report left out. A case that fails
# on every pass is a rule that is wrong; a case that fails on one of three is
# the model's own variance, and those want different work.
def failures(observations: list[Observation], reps: int) -> list[dict[str, Any]]:
    tally: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for seen in observations:
        tally[(seen.query, seen.expected, seen.category)][seen.chosen] += 1
    found = []
    for (query, expected, category), chosen in tally.items():
        missed = sum(count for name, count in chosen.items() if name != expected)
        if not missed:
            continue
        found.append(
            {
                "query": query,
                "expected": expected,
                "category": category,
                "missed": missed,
                "of": sum(chosen.values()),
                "chose": dict(sorted(chosen.items(), key=lambda kv: -kv[1])),
            }
        )
    return sorted(found, key=lambda row: (-row["missed"], row["category"], row["query"]))


# Print accuracy, the confusion matrix, and the individual cases that failed.
def report(observations: list[Observation], reps: int) -> bool:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for seen in observations:
        matrix[seen.expected][seen.chosen] += 1

    correct = sum(1 for seen in observations if seen.expected == seen.chosen)
    total = len(observations)
    accuracy = correct / total if total else 0.0

    print(f"cases {len(SELECTION_CASES)}  reps {reps}  observations {total}")
    print(f"accuracy {accuracy:.4f}  [{correct}/{total}]  floor {ACCURACY_FLOOR}\n")

    print("per expected tool:")
    for expected in TOOL_NAMES:
        row = matrix.get(expected)
        if not row:
            continue
        seen = sum(row.values())
        hit = row.get(expected, 0)
        print(f"  {expected:32s} {hit}/{seen}")

    print("\nconfusion (expected -> chosen, wrong cells only):")
    any_wrong = False
    for expected in TOOL_NAMES:
        for chosen, count in sorted(
            matrix.get(expected, {}).items(), key=lambda kv: -kv[1]
        ):
            if chosen != expected and count:
                any_wrong = True
                print(f"  {expected:32s} -> {chosen:32s} {count}")
    if not any_wrong:
        print("  (none)")

    by_category: dict[str, list[int]] = defaultdict(list)
    for seen in observations:
        by_category[seen.category].append(int(seen.expected == seen.chosen))
    print("\nby category:")
    for category, hits in sorted(by_category.items()):
        print(f"  {category:24s} {sum(hits)}/{len(hits)}")

    # The per-tool floors were written with measured comments beside each one
    # and never checked: report() compared the aggregate and nothing else. So
    # the mechanism built to stop one capability's collapse hiding behind a
    # good average has been dead since it was added, which is how a run whose
    # no-tool cases score 55/75 - six of them wrong on every single pass -
    # reported PASS. An average over eighteen tools cannot fail for one.
    print("\nper-tool floors:")
    breached: list[str] = []
    for expected in TOOL_NAMES:
        row = matrix.get(expected)
        floor = PER_TOOL_ACCURACY_FLOORS.get(expected)
        if not row or floor is None:
            continue
        seen = sum(row.values())
        rate = row.get(expected, 0) / seen if seen else 0.0
        held = rate >= floor
        if not held:
            breached.append(f"{expected} {rate:.2f} < {floor:.2f}")
        print(f"  {expected:32s} {rate:.2f}  floor {floor:.2f}  {'ok' if held else 'BREACH'}")
    if breached:
        print("\nfloors breached: " + "; ".join(breached))

    # Right tool, wrong arguments. This is the whole of the gap between a
    # matrix that says 91% and a person saying the answer was useless: the
    # cell is correct and what was written into it is not. Scored only where
    # a case states an expectation, so silence never flatters the number.
    judged = [seen for seen in observations if seen.arguments_held is not None]
    held = [seen for seen in judged if seen.arguments_held]
    if judged:
        rate = len(held) / len(judged)
        print(
            f"\narguments: {len(held)}/{len(judged)} carried the turn's own words"
            f"  floor {ARGUMENT_FLOOR:.2f}  {'ok' if rate >= ARGUMENT_FLOOR else 'BREACH'}"
        )
        for seen in judged:
            if not seen.arguments_held:
                print(f"  {seen.category}: {seen.query[:70]}")
                print(f"      wrote: {seen.written[:110]}")
    else:
        print("\narguments: no case states what its arguments must carry")
    arguments_ok = (not judged) or (len(held) / len(judged)) >= ARGUMENT_FLOOR

    missed = failures(observations, reps)
    print(f"\ncases that failed ({len(missed)}):")
    for row in missed or []:
        chose = ", ".join(f"{name} x{count}" for name, count in row["chose"].items())
        print(f"  [{row['missed']}/{row['of']}] {row['category']}: {row['query'][:88]}")
        print(f"      wanted {row['expected']}, chose {chose}")
    if not missed:
        print("  (none)")

    record(
        "tool-selection",
        correct,
        total,
        reps=reps,
        floor=ACCURACY_FLOOR,
        scores={
            category: (sum(hits), len(hits)) for category, hits in by_category.items()
        },
        notes=f"{len(SELECTION_CASES)} labelled cases, {len(missed)} failing",
        extra={
            "failures": missed,
            "floors_breached": breached,
            "arguments": {
                "held": len(held),
                "judged": len(judged),
                "floor": ARGUMENT_FLOOR,
                "missed": [
                    {"query": seen.query, "wrote": seen.written}
                    for seen in judged
                    if not seen.arguments_held
                ],
            },
        },
    )
    return accuracy >= ACCURACY_FLOOR and not breached and arguments_ok


# Build the selector against the configured routing model and score the set.
async def evaluate(reps: int, expected: str = "") -> int:
    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        print("Search server is not auto-invocable; the matrix would be incomplete.")
        return 2
    llm = get_routing_llm_client()
    print(f"model: {llm.base_url} {llm.model}\n")
    selector = MainActionSelector(
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )
    chosen = (
        tuple(case for case in SELECTION_CASES if case.expected == expected)
        if expected
        else SELECTION_CASES
    )
    if expected and not chosen:
        print(f"no cases are labelled {expected}")
        return 2
    if expected:
        print(f"only the {len(chosen)} cases labelled {expected}\n")
    observations = await collect(selector, reps, chosen)
    passed = report(observations, reps)
    print(f"\n{'PASS' if passed else 'FAIL'} against the recorded floor")
    return 0 if passed else 1


# Parse arguments and run one evaluation pass.
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reps",
        type=int,
        default=3,
        help="passes per case; 3 or more to separate a bias from noise",
    )
    parser.add_argument(
        "--expected",
        default="",
        help="only cases labelled with this tool, for re-measuring one weakness",
    )
    arguments = parser.parse_args()
    return asyncio.run(evaluate(max(1, arguments.reps), arguments.expected.strip()))


if __name__ == "__main__":
    raise SystemExit(main())
