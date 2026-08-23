"""The nodes of the answering graph.

One node for now. C6 splits it along the seams the body already has - measure,
enforce, assemble, generate - and each of those is a separate commit so a
regression traces to one of them rather than to "the graph landed".

The prompt-rendering helpers stay in `backend/agents/graph.py` where every
existing test imports them from. Moving 690 lines of rendering in the same
commit that changes how the graph is compiled would make both unreviewable.
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


# Measure the turn, trim it when policy allows, assemble the prompt, and stream
# the answer. Split in C6; kept whole here so this commit changes only how the
# graph is built and not what it does.
def answer(state: ReplyState) -> dict[str, Any]:
    deps = get_runtime(TurnDeps).context
    trace_id = state.get("trace_id", "")
    logger.debug("Processing conversation trace %s", trace_id)

    context_data = state.get("context") or {}
    history = state.get("history") or []
    query = state["query"]

    # Measured before assembly, so enforcement can act on the inputs and the
    # report describes the prompt that is actually sent - planned and sent are
    # the same thing by construction, not by later comparison.
    report = measure_turn(
        context_data, history, query, _build_system_prompt(context_data)
    )
    if report is not None:
        logger.info("trace=%s %s", trace_id, report.summary())
        record_context_report(report, str(trace_id or ""))
        if report.dropped_total and settings.CONTEXT_BUDGET_ENFORCE:
            named = {item.name: item for item in report.allocations}
            if named["system"].complete and named["query"].complete:
                context_data, history = _apply_report(context_data, history, report)
                logger.info(
                    "trace=%s enforced: dropped %d item(s) to fit the window",
                    trace_id,
                    report.dropped_total,
                )
            else:
                # A window too small for the system prompt and the question
                # cannot be fixed by dropping enrichment; trimming would send a
                # turn missing its own question. Send in full and say so.
                logger.warning(
                    "trace=%s window smaller than the untrimmable parts; "
                    "turn sent in full",
                    trace_id,
                )

    messages = [{"role": "system", "content": _build_system_prompt(context_data)}]
    for turn in history:
        if turn.get("query"):
            messages.append({"role": "user", "content": turn["query"]})
        if turn.get("response"):
            messages.append({"role": "assistant", "content": turn["response"]})
    # This turn's volatile material goes after the history, so the prefix above
    # it stays byte-identical between turns and the server can reuse its KV
    # blocks. Measured at 16.5x on a 34k-token conversation.
    messages.extend(turn_context_messages(context_data))
    messages.append({"role": "user", "content": query})

    chunks: list[str] = []
    # Explicit, because the signature default was 1,024 and nobody chose it. A
    # reasoning model spends part of this budget on thinking that is never
    # rendered, so too small a value returns an empty reply rather than a short
    # one.
    for chunk in deps.llm.stream_chat(messages, settings.MAIN_LLM_MAX_TOKENS):
        chunks.append(chunk)
        # The wire shape, not a private one. `emit` validates the name against
        # ChatStreamEvent, so a kind the consumer would drop raises here
        # instead of vanishing.
        emit("delta", content=chunk)

    return {
        "prompt_messages": messages,
        "reply": "".join(chunks),
        "budget_report": report,
    }
