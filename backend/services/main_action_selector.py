"""Let the model that talks to the user choose what this turn needs, once.

Searching the internet, drawing or editing a picture, drafting a diagram, and
handing off to a specialist agent each used to be decided by a separate
deterministic gate -- a regex, a bounded YES/NO classifier, or a browser-side
keyword match -- running before the model that actually answers the user ever
saw the request. Every gate judged the question alone from its wording, so two
could fire for the same message, none of them could choose to ask a
clarifying question instead of guessing, and a request phrased in a way no
gate's author anticipated fell through all of them.

This offers every candidate as a real function-calling tool to one model in
one call, so the choice -- including the choice to do nothing and let the
reply ask what is missing -- is made holistically, by whichever model is
actually configured to talk to the user. A better main model directly makes
this routing better; a regex never does.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from backend.core.llm import LLMClient
from backend.mcp.invocation import MCPInvocationError
from backend.mcp.types import MCPTool
from backend.services.mcp_invocation_service import MCPInvocationService
from backend.services.mcp_tool_orchestration_service import (
    MCPToolOrchestrationService,
    MCPToolPlan,
)

logger = logging.getLogger(__name__)

_SEARCH_TOOL = "search_web"
_GENERATE_IMAGE_TOOL = "generate_image"
_EDIT_IMAGE_TOOL = "edit_image"
_CREATE_DIAGRAM_TOOL = "create_diagram"
_DELEGATE_PRESENTATION_TOOL = "delegate_to_presentation_agent"

_EMPTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_GENERATE_IMAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "Exactly what to draw, as a self-contained subject.",
        }
    },
    "required": ["prompt"],
    "additionalProperties": False,
}
_EDIT_IMAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instruction": {
            "type": "string",
            "description": "The single change to make to the picture in view.",
        }
    },
    "required": ["instruction"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are choosing how to handle one user message before it is answered. "
    "You may call at most one of the tools offered below. Calling none is "
    "correct and common: it means the message is answered directly as an "
    "ordinary reply.\n\n"
    "Call search_web whenever the correct answer could have changed since "
    "training and is not already known for certain -- this includes current "
    "events, prices, availability, schedules, scores, and *whoever currently "
    "holds a role, title, office, or record* (a president, prime minister, "
    "mayor, CEO, champion, or record holder can change at any time, so treat "
    "a question about who holds one today as needing a live check even when "
    "the fact feels stable). When genuinely unsure whether something could "
    "have changed, prefer calling the tool over answering from memory: a "
    "needless search costs a second, a stale confident answer costs trust. "
    "Write a specific, self-contained query, since the tool has no memory of "
    "this conversation. If the request depends on the user's location or "
    "other personal context that is not already known from this "
    "conversation, do not guess a placeholder and do not call the tool with "
    "an assumption. Call no tool instead, so the reply can ask for what is "
    "missing.\n\n"
    "Call generate_image only when the user wants a brand-new picture made "
    "for them, describing exactly what to draw.\n\n"
    "Call edit_image only when the user wants a change made to the picture "
    "currently in view, describing that one change.\n\n"
    "Call create_diagram only when the user explicitly asks for a technical "
    "diagram: a flowchart, architecture, sequence, state, class, or "
    "entity-relationship diagram.\n\n"
    "Call delegate_to_presentation_agent only when the user explicitly asks "
    "to create a slide deck or presentation.\n\n"
    "None of these apply to a question about the user's own life, memory, "
    "opinions, or anything already answerable directly -- call no tool for "
    "those, and answer normally instead."
)

# Recent turns given to the decision so it does not re-ask for something the
# user already said earlier in this same conversation.
_MAX_HISTORY_TURNS = 4
_MAX_HISTORY_CHARS = 1_500


@dataclass(frozen=True, slots=True)
class SearchAction:
    """The model decided this turn needs a live web search, with its own query."""

    query: str
    max_results: int | None = None


@dataclass(frozen=True, slots=True)
class GenerateImageAction:
    """The model decided this turn wants a brand-new picture."""

    prompt: str


@dataclass(frozen=True, slots=True)
class EditImageAction:
    """The model decided this turn wants the picture in view changed."""

    instruction: str


@dataclass(frozen=True, slots=True)
class CreateDiagramAction:
    """The model decided this turn wants a technical diagram."""


@dataclass(frozen=True, slots=True)
class DelegateAction:
    """The model decided this turn belongs to a registered specialist."""

    capability_id: str


@dataclass(frozen=True, slots=True)
class ToolboxAction:
    """The model decided this turn needs one of the user's own registered tools."""

    plan: MCPToolPlan


MainAction = (
    SearchAction
    | GenerateImageAction
    | EditImageAction
    | CreateDiagramAction
    | DelegateAction
    | ToolboxAction
    | None
)


# Render a short, bounded window of prior turns so routing can see what the
# user already said, without paying for or trusting the full transcript.
def render_recent_history(history: list[dict[str, Any]]) -> str:
    recent = history[-_MAX_HISTORY_TURNS:]
    lines: list[str] = []
    for turn in recent:
        user_text = str(turn.get("query") or "").strip()
        assistant_text = str(turn.get("response") or "").strip()
        if user_text:
            lines.append(f"User: {user_text}")
        if assistant_text:
            lines.append(f"Assistant: {assistant_text}")
    rendered = "\n".join(lines)[-_MAX_HISTORY_CHARS:]
    return rendered


class MainActionSelector:
    """Resolve every candidate action into one native tool-calling decision."""

    # Compose the pieces needed to offer built-in and user-registered tools alike.
    def __init__(
        self,
        llm: LLMClient,
        mcp_invocation: MCPInvocationService | None,
        search_server_id: str,
        search_tool_name: str,
        tool_orchestration: MCPToolOrchestrationService | None,
        diagram_enabled: bool,
        presentation_enabled: bool,
    ) -> None:
        self.llm = llm
        self.mcp_invocation = mcp_invocation
        self.search_server_id = search_server_id
        self.search_tool_name = search_tool_name
        self.tool_orchestration = tool_orchestration
        self.diagram_enabled = diagram_enabled
        self.presentation_enabled = presentation_enabled

    # Resolve the live search_web schema, or omit the tool when it is unavailable.
    async def _search_tool_definition(self) -> dict[str, Any] | None:
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
                "Search tool could not be resolved for routing", exc_info=True
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

    @staticmethod
    def _builtin_definition(
        name: str, description: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
            },
        }

    # Choose at most one action for this turn, or None to answer normally.
    async def select(
        self,
        user_id: str,
        query: str,
        history: list[dict[str, Any]],
        active_image_artifact_id: str | None,
        query_embedding: list[float] | None = None,
    ) -> MainAction:
        if not query.strip():
            return None

        tools: list[dict[str, Any]] = []
        search_tool = await self._search_tool_definition()
        if search_tool is not None:
            tools.append(search_tool)

        tools.append(
            self._builtin_definition(
                _GENERATE_IMAGE_TOOL,
                "Create a brand-new picture from a text description.",
                _GENERATE_IMAGE_SCHEMA,
            )
        )
        # Offered unconditionally, unlike generate_image's implicit sibling: a
        # request to change "the picture" can arrive before the application's
        # own idea of what is active agrees, and the only way to find that out
        # is to let the model decide edit intent from the conversation, then
        # let the caller check whether anything is actually in view -
        # otherwise a missing selection answered as an ordinary chat turn with
        # no explanation, which read as the feature being broken rather than a
        # picture nobody had picked.
        tools.append(
            self._builtin_definition(
                _EDIT_IMAGE_TOOL,
                "Change the picture currently in view. Only for an actual "
                "photo or generated image - a generic 'edit' request about a "
                "resume, document, or plan is not this. A question that asks "
                "for an opinion, preference, or comparison about the picture "
                "- such as which of two looks already shown is better, or "
                "whether something suits it - is not this either, even when "
                "it mentions the same subject an earlier edit changed: "
                "answer that directly from what is already visible instead.",
                _EDIT_IMAGE_SCHEMA,
            )
        )
        if self.diagram_enabled:
            tools.append(
                self._builtin_definition(
                    _CREATE_DIAGRAM_TOOL,
                    "Draft a technical diagram (flowchart, architecture, "
                    "sequence, state, class, or entity-relationship).",
                    _EMPTY_SCHEMA,
                )
            )
        if self.presentation_enabled:
            tools.append(
                self._builtin_definition(
                    _DELEGATE_PRESENTATION_TOOL,
                    "Hand off to the specialist that builds slide decks.",
                    _EMPTY_SCHEMA,
                )
            )

        candidates: list[tuple[dict[str, Any], MCPTool]] = []
        if self.tool_orchestration is not None:
            candidates = await self.tool_orchestration.list_candidates(
                user_id, query, query_embedding=query_embedding
            )
        aliases = {f"mcp_tool_{index}": item for index, item in enumerate(candidates)}
        tools.extend(MCPToolOrchestrationService.tool_definitions(aliases))

        history_text = render_recent_history(history)
        user_content = (
            f"Recent conversation:\n{history_text}\n\nNewest message: {query}"
            if history_text
            else query
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_content},
        ]
        try:
            message = await asyncio.to_thread(
                self.llm.chat_with_tools, messages, tools, 300
            )
        except Exception:
            logger.warning("Main action selection failed", exc_info=True)
            return None

        offered = {tool["function"]["name"] for tool in tools}
        return self._parse(message, query, aliases, offered)

    # Extract the tool name and parsed arguments from one native tool-call
    # message, refusing a name this round never actually offered -- a
    # built-in is a fixed set of literals, so nothing stops a malformed or
    # unexpected provider response from naming one that was not on the list
    # this turn (edit_image with no active image, a disabled diagram tool);
    # the provider's own output is not trusted to have respected what it was
    # given.
    @staticmethod
    def _extract_call(
        message: dict[str, Any], offered: set[str]
    ) -> tuple[str, dict[str, Any]] | None:
        calls = message.get("tool_calls")
        if not calls or not isinstance(calls, list):
            return None
        call = calls[0]
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name not in offered:
            return None
        raw_arguments = (
            function.get("arguments") if isinstance(function, dict) else None
        )
        arguments: dict[str, Any] = {}
        if isinstance(raw_arguments, str):
            try:
                parsed = json.loads(raw_arguments)
                if isinstance(parsed, dict):
                    arguments = parsed
            except ValueError:
                arguments = {}
        return str(name), arguments

    # Convert one native tool-call message into a typed, application-owned action.
    def _parse(
        self,
        message: dict[str, Any],
        fallback_query: str,
        aliases: dict[str, tuple[dict[str, Any], MCPTool]],
        offered: set[str],
    ) -> MainAction:
        extracted = self._extract_call(message, offered)
        if extracted is None:
            return None
        name, arguments = extracted

        if name == _SEARCH_TOOL:
            model_query = arguments.get("query")
            chosen_query = (
                model_query.strip()
                if isinstance(model_query, str) and model_query.strip()
                else fallback_query
            )
            max_results = arguments.get("max_results")
            return SearchAction(
                query=chosen_query,
                max_results=max_results if isinstance(max_results, int) else None,
            )
        if name == _GENERATE_IMAGE_TOOL:
            prompt = arguments.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return GenerateImageAction(prompt=prompt.strip())
            return None
        if name == _EDIT_IMAGE_TOOL:
            instruction = arguments.get("instruction")
            if isinstance(instruction, str) and instruction.strip():
                return EditImageAction(instruction=instruction.strip())
            return None
        if name == _CREATE_DIAGRAM_TOOL:
            return CreateDiagramAction()
        if name == _DELEGATE_PRESENTATION_TOOL:
            return DelegateAction(capability_id="presentation_agent")

        selected = aliases.get(str(name))
        if selected is None:
            return None
        descriptor, live = selected
        return ToolboxAction(
            plan=MCPToolPlan(
                server_id=live.server_id,
                tool_name=live.name,
                arguments=arguments,
                expected_fingerprint=str(descriptor["schema_fingerprint"]),
            )
        )
