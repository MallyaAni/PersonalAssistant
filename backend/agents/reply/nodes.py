"""The nodes of the answering graph.

Four, along the seams the single node already had: measure what the turn costs,
trim it when policy allows, assemble the prompt, stream the answer.

Splitting them buys two things that could not be had while they were one body.
The system prompt is rendered **once** and carried in state, where it used to
be rendered twice - once to measure and once to assemble - from two separate
`datetime.now()` reads, so a turn crossing midnight measured one date and
answered with another, and the report described a prompt that was never sent.
And `enforce` becomes a node the graph reaches or skips by a predicate, rather
than a branch buried in a function, so "was this turn trimmed" is visible in
the graph rather than only in a log line.

The prompt-rendering helpers stay in `backend/agents/graph.py`, where the
existing tests import them from. Moving 690 lines of rendering in the same
commit that changes the graph's shape would make both unreviewable.
"""

import logging
from typing import Any

from langgraph.runtime import get_runtime

from backend.agents.graph import (
    _apply_report,
    _build_system_prompt,
    measure_turn,
    turn_context_messages,
)
from backend.agents.reply.emit import emit
from backend.agents.reply.state import ReplyState, TurnDeps
from backend.config.settings import settings
from backend.core.observability import record_context_report

logger = logging.getLogger(__name__)


# Render the system prompt once and measure what this turn will cost.
#
# The render is kept in state rather than repeated later. Measuring one string
# and sending another is the drift this removes: the two renders were separate
# calls, so any per-render nondeterminism - the clock, most of all - made the
# report a description of a prompt that never existed.
def measure(state: ReplyState) -> dict[str, Any]:
    trace_id = state.get("trace_id", "")
    context = state.get("context") or {}
    history = state.get("history") or []
    system_prompt = _build_system_prompt(context)

    report = measure_turn(context, history, state["query"], system_prompt)
    if report is not None:
        logger.info("trace=%s %s", trace_id, report.summary())
        record_context_report(report, str(trace_id or ""))

    return {"system_prompt": system_prompt, "budget_report": report}


# Whether the measured plan is applied.
#
# Off by default (`CONTEXT_BUDGET_ENFORCE`): trimming changes what the model
# sees, and no section priority here has been argued against real turn sizes.
# A window too small for the system prompt and the question cannot be fixed by
# dropping enrichment - trimming would send a turn missing its own question -
# so that case skips enforcement and is logged loudly by `enforce`'s absence.
def after_measure(state: ReplyState) -> str:
    report = state.get("budget_report")
    if report is None or not report.dropped_total:
        return "assemble"
    if not settings.CONTEXT_BUDGET_ENFORCE:
        return "assemble"
    named = {item.name: item for item in report.allocations}
    if not all(
        named[section].complete for section in ("system", "query", "turn_context")
    ):
        logger.warning(
            "trace=%s window smaller than the untrimmable parts; turn sent in full",
            state.get("trace_id", ""),
        )
        return "assemble"
    return "enforce"


# Drop what the plan said to drop, and re-render the system prompt against the
# trimmed context so the prompt and the report still describe the same turn.
def enforce(state: ReplyState) -> dict[str, Any]:
    report = state["budget_report"]
    context, history = _apply_report(
        state.get("context") or {}, state.get("history") or [], report
    )
    logger.info(
        "trace=%s enforced: dropped %d item(s) to fit the window",
        state.get("trace_id", ""),
        report.dropped_total,
    )
    # Re-rendered, not reused: the whole point of trimming is that the context
    # changed, so the prompt built from it must change with it.
    return {
        "context": context,
        "history": history,
        "system_prompt": _build_system_prompt(context),
    }


# Build the exact message list the model is sent.
#
# Separate from `generate` so a test can assert on the prompt without reaching
# into a model call, which is what makes it safe to keep moving this code.
def assemble(state: ReplyState) -> dict[str, Any]:
    context = state.get("context") or {}
    messages = [{"role": "system", "content": state["system_prompt"]}]
    for turn in state.get("history") or []:
        if turn.get("query"):
            messages.append({"role": "user", "content": turn["query"]})
        if turn.get("response"):
            messages.append({"role": "assistant", "content": turn["response"]})
    # This turn's volatile material goes after the history, so the prefix above
    # it stays byte-identical between turns and the server can reuse its KV
    # blocks. Measured at 16.5x on a 34k-token conversation.
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": state["query"]})
    return {"prompt_messages": messages}


# Stream the answer.
#
# Synchronous on purpose. `llm.stream_chat` is a blocking generator behind a
# threading.Lock, and LangGraph runs a sync node on a worker thread, so the
# event loop stays free. Written `async def`, this would hold the loop for the
# whole generation and stall every concurrent turn - and the iMessage bridge,
# which answers serially, with it.
def generate(state: ReplyState) -> dict[str, Any]:
    deps = get_runtime(TurnDeps).context
    chunks: list[str] = []
    # Explicit, because the signature default was 1,024 and nobody chose it. A
    # reasoning model spends part of this budget on thinking that is never
    # rendered, so too small a value returns an empty reply rather than a short
    # one.
    for chunk in deps.llm.stream_chat(
        state["prompt_messages"], settings.MAIN_LLM_MAX_TOKENS
    ):
        chunks.append(chunk)
        # The wire shape, not a private one. `emit` validates the name against
        # ChatStreamEvent, so a kind the consumer would drop raises here
        # instead of vanishing.
        emit("delta", content=chunk)
    return {"reply": "".join(chunks)}
