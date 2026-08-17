"""Decide whether an image question needs the web, and fetch it if so.

The models can describe an object accurately and still not know what it is. A
small VLM has little product knowledge, and the main model's knowledge is both
dated and, for niche or recent hardware, confidently wrong - asked what an
NVIDIA DGX Spark looks like it described a rack-mounted server, which is not the
machine. Neither failure is fixable by prompting, because the model has no way
to know that what it recalls is wrong.

So identification is grounded in a real search instead. The decision to search
is the model's own native tool call, not a keyword test against phrases like
"I cannot tell" - a rule this repository holds to deliberately, because a
regex over an answer is exactly the kind of brittle routing this project keeps
having to remove.
"""

import asyncio
import json
import logging
from typing import Any

from backend.mcp.invocation import MCPInvocationError
from backend.services.mcp_invocation_service import MCPInvocationService

logger = logging.getLogger(__name__)

_SEARCH_TOOL = "search_web"

_DECISION_PROMPT = """
Below is a description of an image somebody uploaded, and the question they
asked about it. Decide whether answering that question well needs a web search.

Search when the question turns on identifying a specific product, model, brand,
place, person, plant, animal, or text whose meaning you would have to look up -
anything where being out of date or mistaken about a real-world fact would make
the answer wrong. Naming something confidently from memory is exactly the
failure a search prevents.

A question asking you to judge, advise, warn, or recommend still needs the
search whenever that judgement depends on knowing what the thing actually is -
whether a mushroom is safe to eat, whether a snake is venomous, whether a
vintage is good, whether a part will fit. Identify first, then judge. The test
is simple: if learning the object's real name could change your answer, look it
up rather than reasoning from appearance.

Do not search when the description already contains everything the question
needs - counting, comparing, reading values, judging colour or composition,
giving an opinion about what is visible, or any question answerable from the
description alone. A question is pure opinion only when it is about what is
visible - colour, arrangement, mood, style, composition - and its answer would
not change if you learned what the object was called.

When you search, write the query from the distinctive visible details, not from
a guess at the answer: describe the object's form, markings, colour, and any
readable text, so the search can identify it rather than confirm a hunch.
""".strip()


class VisualSearchGrounding:
    # Wire one search-backed identification step for image questions.
    def __init__(
        self,
        llm: Any,
        mcp_invocation: MCPInvocationService | None,
        search_server_id: str,
        search_tool_name: str,
        decision_max_tokens: int = 300,
        max_result_chars: int = 4_000,
    ) -> None:
        self.llm = llm
        self.mcp_invocation = mcp_invocation
        self.search_server_id = search_server_id
        self.search_tool_name = search_tool_name
        self.decision_max_tokens = decision_max_tokens
        self.max_result_chars = max_result_chars

    # Resolve the live search tool, or None when search is unavailable.
    async def _tool_definition(self) -> dict[str, Any] | None:
        if self.mcp_invocation is None:
            return None
        if not self.mcp_invocation.can_auto_invoke(self.search_server_id):
            return None
        try:
            live = await self.mcp_invocation.resolve_tool(
                self.search_server_id, self.search_tool_name
            )
        except MCPInvocationError:
            logger.warning(
                "Search tool could not be resolved for visual grounding",
                exc_info=True,
            )
            return None
        return {
            "type": "function",
            "function": {
                "name": _SEARCH_TOOL,
                "description": live.description[:1_000],
                "parameters": live.input_schema,
            },
        }

    # Decide whether this question needs the web, returning the arguments the
    # model wrote for the search, or None to answer without one.
    #
    # Separated from `ground` so the judgement can be measured on its own. The
    # decision is the half that goes wrong -- it was found answering identify-
    # this-product questions from memory 5 times in 9 -- and an evaluation that
    # has to spend live search quota per case is one nobody runs often enough
    # to catch that.
    async def decide(
        self,
        question: str,
        observation: str,
        tool: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not question.strip() or self.llm is None:
            return None
        resolved = tool if tool is not None else await self._tool_definition()
        if resolved is None:
            return None

        messages = [
            {"role": "system", "content": _DECISION_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Description of the image:\n{observation.strip()}\n\n"
                    f"The question asked:\n{question.strip()}"
                ),
            },
        ]
        try:
            decision = await asyncio.to_thread(
                self.llm.chat_with_tools,
                messages,
                [resolved],
                self.decision_max_tokens,
            )
        except Exception:
            logger.warning("Visual search decision failed", exc_info=True)
            return None
        return _first_search_call(decision)

    # Return web evidence for this question, or None to answer without it.
    #
    # Every failure answers None. This sits in front of an answer the user is
    # waiting on and the reasoning step works without it, so an unreachable
    # search must degrade to an ungrounded answer rather than fail the request.
    async def ground(self, question: str, observation: str) -> str | None:
        if not question.strip() or self.llm is None:
            return None
        tool = await self._tool_definition()
        if tool is None:
            return None

        arguments = await self.decide(question, observation, tool)
        if arguments is None:
            return None

        return await self._invoke(arguments)

    # Search a query already selected by the pixel-facing structured decision.
    async def ground_query(self, query: str) -> str | None:
        if not query.strip() or self.mcp_invocation is None:
            return None
        tool = await self._tool_definition()
        if tool is None:
            return None
        return await self._invoke({"query": query.strip(), "max_results": 5})

    # Invoke the owned search boundary and retain only useful bounded evidence.
    async def _invoke(self, arguments: dict[str, Any]) -> str | None:
        invocation = self.mcp_invocation
        if invocation is None:
            return None
        try:
            result = await invocation.invoke(
                self.search_server_id,
                self.search_tool_name,
                arguments,
            )
        except Exception:
            logger.warning("Visual grounding search failed", exc_info=True)
            return None
        if result.is_error or not result.content.strip():
            return None
        # A search that matched nothing still returns a well-formed envelope
        # ({"provider": ..., "results": []}), which is not empty and would be
        # handed to the reasoning step as if it were evidence. Passing that on
        # is worse than passing nothing: it spends the model's attention on a
        # section that says only that the web was consulted.
        if _has_no_results(result.content):
            return None
        return result.content[: self.max_result_chars]


# Report whether a search envelope carried no findings at all.
#
# Tolerant by design: a payload this cannot parse is treated as having results,
# because dropping real evidence over an unrecognised shape is the worse error.
def _has_no_results(content: str) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return not results
    return False


# Pull the first search_web call's arguments out of a provider message.
#
# Tolerates the arguments arriving as a JSON string or an already-decoded
# object, because providers differ on that and a grounding step must not fail
# the answer over a serialisation detail.
def _first_search_call(message: dict[str, Any]) -> dict[str, Any] | None:
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        if function.get("name") != _SEARCH_TOOL:
            continue
        raw = function.get("arguments")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Search arguments were not valid JSON")
                return None
            if isinstance(parsed, dict):
                return parsed
    return None
