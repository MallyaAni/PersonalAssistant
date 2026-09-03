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

from backend.config.settings import settings
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.services.main_action_selector import (
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
    ScoutScheduleAction,
    SaveSkillAction,
    ScheduleTaskAction,
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


# Run every labelled case and return the chosen tool for each observation.
async def collect(
    selector: MainActionSelector,
    reps: int,
    cases: tuple[SelectionCase, ...] = SELECTION_CASES,
) -> list[tuple[str, str, str]]:
    observations: list[tuple[str, str, str]] = []
    for case in cases:
        history = [
            {"query": query, "response": response} for query, response in case.history
        ]
        # Routed as the operator when the case says so: some tools are offered
        # only to them, and a case for such a tool routed as a guest measures
        # the withholding, not the choice.
        identity = SearchIdentity(user_id="tool_selection_eval", is_operator=case.operator)
        for _ in range(reps):
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
            observations.append((case.expected, tool_of(action), case.category))
    return observations


# Print accuracy, the confusion matrix, and the worst individual cases.
def report(observations: list[tuple[str, str, str]], reps: int) -> bool:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for expected, chosen, _ in observations:
        matrix[expected][chosen] += 1

    correct = sum(1 for e, c, _ in observations if e == c)
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
    for expected, chosen, category in observations:
        by_category[category].append(int(expected == chosen))
    print("\nby category:")
    for category, hits in sorted(by_category.items()):
        print(f"  {category:24s} {sum(hits)}/{len(hits)}")

    return accuracy >= ACCURACY_FLOOR


# Build the selector against the configured routing model and score the set.
async def evaluate(reps: int) -> int:
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
    observations = await collect(selector, reps)
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
    arguments = parser.parse_args()
    return asyncio.run(evaluate(max(1, arguments.reps)))


if __name__ == "__main__":
    raise SystemExit(main())
