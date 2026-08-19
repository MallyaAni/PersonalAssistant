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
    "When the request is a choice - what to use, run, host, buy, or pick - "
    "search first for which options exist right now, by category and year. "
    "That is the half your memory is stale about and the half a search can "
    "actually replace; the hardware, budget or limit they named is fixed and "
    "can be looked up afterwards. Do not spend this query on the constraint "
    "and then name the options from memory.\n"
    "Today is {today}, and your own knowledge ends around {cutoff}. Everything "
    "between those two dates is precisely what you cannot know and what this "
    "search is for, so search for now rather than for the last state you "
    "remember - a year taken from your own memory is the one thing guaranteed "
    "to return what is already out of date.\n"
    "Searching for the options means searching the category, not their "
    "hardware: a query naming the box returns reviews of the box.\n"
    "At most 12 words. Reply with the query alone, no quotes, no "
    "explanation, and never a sentence describing what to search for."
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
    "Reply ENOUGH only if you could write the final answer, with its specific "
    "names and numbers, using nothing but the text of these results. If you "
    "would have to supply any figure, version, date or name from your own "
    "memory to complete it, that is not enough - your memory is what is out of "
    "date, and it is the reason this search is running. Feeling able to answer "
    "is not the test; being able to point at where each specific came from "
    "is.\n"
    "Otherwise reply with one better search query and nothing else - the one "
    "that would find the missing half. Use the vocabulary that source would "
    "use.\n"
    "Never repeat a query that has already been tried.\n"
    "\n"
    "Worked example. Question: 'why not the latest model? I have one 128GB "
    "box'. Results say only 'Vendor released Pro and Flash; both are strong.' "
    "That is NOT enough: it names the options and gives no size for either, so "
    "nothing in it says which one fits 128GB. The right reply is a query for "
    "the missing figure, such as: Vendor Pro Flash parameter count memory "
    "requirement GB\n"
    "Now judge the results below the same way."
)


_ANOTHER = (
    "Here is a question and the search results gathered so far.\n"
    "Give one more search query, on a different angle from the ones already "
    "tried, that would make the answer more specific.\n"
    "Prefer the figures an answer has to cite and the results do not yet "
    "contain: sizes, requirements, prices, versions, dates.\n"
    "First check what is missing. If the results so far describe the "
    "constraint - the hardware, the budget, the limit - but name no current "
    "options to apply it to, the missing half is the options: search for what "
    "exists now, by category and year. If the options are named but their "
    "sizes or requirements are not, search for those figures by name and "
    "unit. Naming options from your own memory instead of searching for them "
    "is the failure this exists to prevent.\n"
    "Reply with the query alone."
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
    # A labelled query is the model saying which part it meant. The label is
    # whatever short phrase it chose - "Search:", "Better search query:" - so
    # matching a fixed list missed the ones it invented and sent the label
    # along with the query.
    for line in reversed(lines):
        head, sep, rest = line.partition(":")
        if sep and rest.strip() and len(head) <= 28 and _looks_like_a_label(head):
            return _bare(rest)
    for line in lines:
        verdict = line.upper()
        # "NOT ENOUGH" is the opposite verdict and was being searched for
        # verbatim. Without an accompanying query there is nothing to run.
        if verdict.startswith(("NOT ENOUGH", "NOT_ENOUGH")):
            return ""
        if verdict.startswith("ENOUGH"):
            return "ENOUGH"
    # Otherwise the last line: a preamble comes first and the answer last.
    return _bare(lines[-1])


# A label is a short run of words, not a sentence and not a query itself.
def _looks_like_a_label(head: str) -> bool:
    words = head.strip().strip("*_-# ").split()
    return 0 < len(words) <= 4 and all(word.isalpha() for word in words)


# A query is a handful of words. Told to reply with one, the model sometimes
# restates the instruction instead - "Given the results so far mention the
# hardware but don't name current options, search for what exists now" - and
# that goes to the search engine verbatim and returns nothing. Length is the
# one property that separates the two reliably, so an over-long reply is
# treated as no proposal at all.
_MAX_QUERY_WORDS = 16


def _is_prose(text: str) -> bool:
    return len(text.split()) > _MAX_QUERY_WORDS


# Strip the quotes and list markers a model wraps a bare query in.
def _bare(text: str) -> str:
    cleaned = text.strip().strip("-*").strip()
    for quote in ('"', "'", "`"):
        cleaned = cleaned.strip(quote)
    cleaned = cleaned.strip()[:_MAX_QUERY_CHARS]
    return "" if _is_prose(cleaned) else cleaned


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

    # One more angle, asked for rather than negotiated.
    #
    # `refine` puts a yes/no in front of the model and it takes the answer
    # that ends the work: shown results naming two options and no figure for
    # either, it replied ENOUGH in 8 runs out of 8, and across four wordings
    # of the question the rate moved between 0/8 and 3/5 with no trend. That
    # is not a prompt that needs improving, it is a judgement this model does
    # not make reliably. Asking for the next angle has no cheap answer: the
    # reply is a query or it is nothing.
    def another_angle(
        self,
        question: str,
        results: list[dict[str, Any]],
        already_tried: list[str],
    ) -> str:
        found = "\n".join(
            f"- {str(item.get('title') or '')[:120]}" for item in results[:8]
        )
        tried = ", ".join(already_tried)
        proposed = self._ask(
            _ANOTHER,
            f"Question: {question}\n\nAlready tried: {tried}\n\n"
            f"Found so far:\n{found}",
            "propose another search angle",
        )
        if not proposed or proposed.upper().startswith("ENOUGH"):
            return ""
        if proposed.casefold() in {item.casefold() for item in already_tried}:
            return ""
        return proposed

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
