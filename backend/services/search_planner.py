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
    "answer, not all of them at once. When the request is a choice under a "
    "limit - what fits, what runs on this, what stays under that - the "
    "deciding requirement is usually a number attached to each option rather "
    "than the options themselves, so search for the thing that would let you "
    "compare them.\n"
    "Today is {today}, and your own knowledge ends around {cutoff}. Everything "
    "between those two dates is precisely what you cannot know and what this "
    "search is for, so search for now rather than for the last state you "
    "remember - a year taken from your own memory is the one thing guaranteed "
    "to return what is already out of date.\n"
    "Reply with the query alone. No quotes, no explanation."
)

_REFINE = (
    "Here is a question and the search results gathered so far.\n"
    "Judge them against what answering actually requires, not against whether "
    "they are on topic.\n"
    "A choice made under a limit - what fits in this much memory, runs on this "
    "hardware, finishes in this long, costs under this much - is only "
    "answerable when the results give you both halves: which options exist, "
    "and the figure that decides between them. Naming the options is not "
    "enough. If the options are named but their sizes, requirements or prices "
    "are not, search for that figure directly, by option name and unit.\n"
    "The same applies to any question whose answer turns on a specific fact "
    "the results talk around rather than state.\n"
    "If both halves are present, reply with exactly: ENOUGH\n"
    "Otherwise reply with one better search query and nothing else - the one "
    "that would find the missing half. Use the vocabulary that source would "
    "use.\n"
    "Never repeat a query that has already been tried."
)


# Recover the query from a reply that would not stop explaining itself.
#
# Told to answer with the query alone, the model reasoned for a paragraph and
# then wrote "Search: deepseek v4 pro api pricing". Its reasoning was right -
# it had spotted that the options were named but the deciding figure was not -
# and passing the paragraph to a search engine would have thrown that away and
# returned nothing. Prose is what models do; taking the query out of it is
# cheaper and steadier than insisting they stop.
def _query_from(reply: str) -> str:
    text = reply.strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # A labelled query is the model saying which part it meant.
    for line in reversed(lines):
        lowered = line.lower()
        for label in ("search:", "query:", "better query:"):
            if lowered.startswith(label):
                return _bare(line[len(label):])
    # ENOUGH is a verdict, not a query, and may arrive with commentary.
    if any(line.upper().startswith("ENOUGH") for line in lines):
        return "ENOUGH"
    # Otherwise the last line: a preamble comes first and the answer last.
    return _bare(lines[-1])


# Strip the quotes and list markers a model wraps a bare query in.
def _bare(text: str) -> str:
    cleaned = text.strip().strip("-*").strip()
    for quote in ('"', "'", "`"):
        cleaned = cleaned.strip(quote)
    return cleaned.strip()[:_MAX_QUERY_CHARS]


class SearchPlanner:
    """Compose search queries with the model that has to use the answers."""

    # `now` is injectable so a test can pin the date a query is written for.
    def __init__(
        self,
        llm: Any,
        now: datetime | None = None,
        # Where the model's own knowledge stops. Today's date says when
        # now is; this says which of its beliefs are already stale, which
        # is the half that decides whether it searches the right period.
        cutoff: str = "",
    ) -> None:
        self.llm = llm
        self.now = now
        self.cutoff = cutoff.strip()

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
            _COMPOSE.format(
                today=(self.now or datetime.now(UTC)).date(),
                cutoff=self.cutoff or "an unstated date in the past",
            ),
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
        return _query_from(str(reply.get("content") or ""))
