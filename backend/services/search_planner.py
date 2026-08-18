"""Write the search query, and judge whether the results answered it.

Both jobs used to belong to the 4B routing model, which chose the query as one
field of its tool call and never saw what came back. Asked for the best models
to host on a single DGX Spark for chat, vision, and three kinds of image work,
it compressed four requirements into one generic query; the five results were
DGX Spark tutorials that named no models, and the reply model filled the gap
from training and answered with models that are no longer current.

Neither job needs a schema, so neither is bound to the routing role. They are
ordinary prose written from the whole conversation, which is what the reply
model is best at - and it is the model that has to use the results, so it is
the one that should say what it needs and whether it got it.
"""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_QUERY_CHARS = 400

_COMPOSE = (
    "Write one web search query that would find what this person is asking "
    "for.\n"
    "Use the words a source that answers them would use, not the words they "
    "used: names, model numbers, versions, units, and the year when the "
    "answer changes over time.\n"
    "A request with several requirements needs the one that decides the "
    "answer, not all of them at once.\n"
    "Today is {today}. When the answer changes over time, search for now, not "
    "for whenever you were trained - a year taken from your own memory is the "
    "one thing guaranteed to return what is already out of date.\n"
    "Reply with the query alone. No quotes, no explanation."
)

_REFINE = (
    "Here is a question and the search results gathered so far.\n"
    "If the results contain what is needed to answer, reply with exactly: "
    "ENOUGH\n"
    "If they do not - they are about the subject but never state the answer, "
    "or they are too general, or too old - reply with one better search "
    "query and nothing else. Name what was missing in the query itself: be "
    "more specific, use the vocabulary the missing source would use.\n"
    "Never repeat a query that has already been tried."
)


class SearchPlanner:
    """Compose search queries with the model that has to use the answers."""

    # `now` is injectable so a test can pin the date a query is written for.
    def __init__(self, llm: Any, now: datetime | None = None) -> None:
        self.llm = llm
        self.now = now

    # One query for this turn, or nothing when the model cannot improve on
    # what the router already chose.
    def compose(self, question: str, history: list[dict[str, Any]]) -> str:
        recent = [
            f"{turn.get('role', 'user')}: {str(turn.get('content') or '')[:400]}"
            for turn in history[-4:]
        ]
        context = "\n".join(recent)
        asked = f"Conversation so far:\n{context}\n\n" if context else ""
        return self._ask(
            _COMPOSE.format(today=(self.now or datetime.now(UTC)).date()),
            f"{asked}Their message: {question}",
            "compose a search query",
        )

    # A better query when the results fall short, or nothing when they do not.
    def refine(
        self,
        question: str,
        results: list[dict[str, Any]],
        already_tried: list[str],
    ) -> str:
        if not results:
            # Nothing came back at all, which the model cannot diagnose from
            # an empty list any better than the caller can.
            return ""
        found = "\n".join(
            f"- {str(item.get('title') or '')[:120]}: "
            f"{str(item.get('content') or '')[:300]}"
            for item in results[:8]
        )
        tried = ", ".join(already_tried)
        verdict = self._ask(
            _REFINE,
            f"Question: {question}\n\nAlready tried: {tried}\n\nResults:\n{found}",
            "judge search results",
        )
        if not verdict or verdict.strip().upper().startswith("ENOUGH"):
            return ""
        # A model that ignores the instruction and repeats itself would loop.
        if verdict.casefold() in {item.casefold() for item in already_tried}:
            return ""
        return verdict

    # One bounded free-text call. A failure here costs the improvement, never
    # the turn: every caller falls back to what it already had.
    def _ask(self, system: str, user: str, what: str) -> str:
        try:
            reply = self.llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                200,
            )
        except Exception:
            logger.warning("Could not %s", what, exc_info=True)
            return ""
        text = str(reply.get("content") or "").strip()
        # Models like to wrap a bare query in quotes despite being told not to.
        text = text.strip().strip('"').strip("'").strip()
        return text[:_MAX_QUERY_CHARS]
