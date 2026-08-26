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

The tools themselves live in `backend/tools/` (one module each) and the
person's skills in `backend/skills/`; this module only assembles the offer
and reads the decision.
"""

import asyncio
import json
import logging
from typing import Any

from backend.config.settings import settings
from backend.core.llm import LLMClient
from backend.core.prompts import load
from backend.mcp.invocation import MCPInvocationError
from backend.mcp.types import MCPTool
from backend.services.mcp_invocation_service import MCPInvocationService
from backend.services.mcp_tool_orchestration_service import (
    MCPToolOrchestrationService,
    MCPToolPlan,
)
from backend.skills.tools import parse_skill_call, skill_tool_definitions
from backend.search.budgeted import current_search_identity
from backend.tools import (
    UNATTENDED_WITHHELD,
    NOT_BUILTIN,
    SEARCH_CAPABILITY,
    SEARCH_TOOL,
    WEATHER_CAPABILITY,
    SEARCH_CREDITS_CAPABILITY,
    SEARCH_CREDITS_TOOL,
    WEATHER_TOOL,
    BuiltinTool,
    CreateDiagramAction,
    DelegateAction,
    EditImageAction,
    GenerateImageAction,
    MainAction,
    ManageSkillsAction,
    ManageTasksAction,
    RecallHistoryAction,
    SaveSkillAction,
    ScheduleTaskAction,
    SearchAction,
    ShowImageAction,
    ToolboxAction,
    UseSkillAction,
    builtin_tools,
    parse_builtin,
)

__all__ = [
    "BuiltinTool",
    "CreateDiagramAction",
    "DelegateAction",
    "EditImageAction",
    "GenerateImageAction",
    "MainAction",
    "MainActionSelector",
    "ManageSkillsAction",
    "ManageTasksAction",
    "RecallHistoryAction",
    "SaveSkillAction",
    "ScheduleTaskAction",
    "SearchAction",
    "ShowImageAction",
    "ToolboxAction",
    "UseSkillAction",
    "render_recent_history",
]

logger = logging.getLogger(__name__)

# The wording lives in `prompts/routing/select_action.md`.
_SYSTEM = load("routing/select_action")

# Recent turns given to the decision so it does not re-ask for something the
# user already said earlier in this same conversation.
_MAX_HISTORY_TURNS = 4
_MAX_HISTORY_CHARS = 1_500


# Render a short, bounded window of prior turns so routing can see what the
# user already said, without paying for or trusting the full transcript.
# Whether the request being routed belongs to an operator, from the search
# identity the auth layer binds to the request. Unknown counts as not.
def _caller_is_operator() -> bool:
    identity = current_search_identity.get()
    return bool(identity is not None and identity.is_operator)


# Whether a skill row is a shipped pack rather than one the person taught.
def _is_pack(skill: dict[str, Any]) -> bool:
    return str(skill.get("source") or "") == "pack" or str(skill.get("id") or "").startswith("pack:")


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
        if self.mcp_invocation is None or not self._search_is_available():
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
                "name": SEARCH_TOOL,
                "description": live.description[:1_000],
                "parameters": live.input_schema,
            },
        }

    # A second core tool on the search server, offered under its own name and
    # parsed through the alias path into an ordinary ToolboxAction. Weather
    # exists because web search answered "today's weather" from SEO forecast
    # pages and a monthly outlook reached a real phone as today; the model
    # deciding *which* instrument fits stays a tool-calling decision.
    async def _weather_tool_definition(
        self,
    ) -> tuple[dict[str, Any], MCPTool] | None:
        return await self._core_tool_definition(WEATHER_TOOL)

    # One more core tool on the internet server, for the operator only: the
    # search key's remaining credits. The number is about the shared key, so
    # a guest is never offered it - and "not offered" is enforced here, in
    # code, not by asking the prompt to withhold it.
    async def _credits_tool_definition(
        self,
    ) -> tuple[dict[str, Any], MCPTool] | None:
        if not _caller_is_operator():
            return None
        return await self._core_tool_definition(SEARCH_CREDITS_TOOL)

    # A tool that lives on the search server, offered under its own name with
    # the server's live schema, or None when the server does not have it.
    async def _core_tool_definition(
        self, name: str
    ) -> tuple[dict[str, Any], MCPTool] | None:
        if self.mcp_invocation is None or not self._search_is_available():
            return None
        try:
            live = await self.mcp_invocation.resolve_tool(self.search_server_id, name)
        except MCPInvocationError:
            # A server without the tool simply does not offer it this turn.
            return None
        definition = {
            "type": "function",
            "function": {
                "name": name,
                "description": live.description[:1_000],
                "parameters": live.input_schema,
            },
        }
        return definition, live

    # The built-in tools this selector offers, in the order it presents them,
    # from the registry minus the rows whose service is switched off.
    def _available_builtins(self, unattended: bool = False) -> list[BuiltinTool]:
        enabled = []
        if self.diagram_enabled:
            enabled.append("diagram")
        if self.presentation_enabled:
            enabled.append("presentation")
        # A scheduled task firing carries the person's own instruction, which
        # reads like a request to schedule; offering the automation tools to
        # it lets a reminder reschedule or cancel itself unattended.
        return builtin_tools(enabled, UNATTENDED_WITHHELD if unattended else ())

    # Report whether local policy would let this turn search, without paying
    # for a session against the search server.
    #
    # `select` resolves the live contract because it needs the real schema to
    # call with; describing the capability needs neither the schema nor the
    # server's own wording, and a second `list_tools` round-trip per turn would
    # spawn the search server again for a sentence in a prompt.
    def _search_is_available(self) -> bool:
        if self.mcp_invocation is None:
            return False
        return self.mcp_invocation.can_auto_invoke(self.search_server_id)

    # What AniOS can actually do, as the reply prompt should describe it.
    #
    # Read from the same rows `select` offers as tools rather than restated in
    # the prompt, so the wording that governs conversation and the wording that
    # governs routing are one string and cannot disagree.
    def describe_capabilities(self) -> list[dict[str, str]]:
        capabilities: list[dict[str, str]] = []
        if self._search_is_available():
            capabilities.append(dict(SEARCH_CAPABILITY))
            # Weather lives on the same server under the same policy, so its
            # availability is the same question already answered above.
            capabilities.append(dict(WEATHER_CAPABILITY))
            # The meter is the operator's; a guest is not told it exists.
            if _caller_is_operator():
                capabilities.append(dict(SEARCH_CREDITS_CAPABILITY))
        capabilities.extend(
            builtin.as_capability() for builtin in self._available_builtins()
        )
        return capabilities

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
    #
    # `skills` are the person's own routines, each offered as its own tool so
    # the model can decide by meaning that "brief me" is their morning brief;
    # a skill's own instruction is routed with `skills=[]` so it cannot pick
    # itself.
    async def select(
        self,
        user_id: str,
        query: str,
        history: list[dict[str, Any]],
        active_image_artifact_id: str | None,
        query_embedding: list[float] | None = None,
        local_now: str | None = None,
        skills: list[dict[str, Any]] | None = None,
        unattended: bool = False,
        only: frozenset[str] | None = None,
        steps_taken: list[str] | None = None,
    ) -> MainAction:
        if not query.strip():
            return None

        tools: list[dict[str, Any]] = []
        aliases: dict[str, Any] = {}
        offered_skills: list[dict[str, Any]] = []
        # A later step in the same turn is restricted to a named set, in code
        # rather than by asking the prompt nicely. Same mechanism the unattended
        # withholding already uses, and it means a second decision cannot start
        # a ninety-second image generation or spend a search credit however the
        # model happens to be prompted.
        if only is not None:
            tools.extend(
                self._builtin_definition(
                    builtin.name, builtin.description, builtin.schema
                )
                for builtin in self._available_builtins(unattended)
                if builtin.name in only
            )
        else:
            # Offered even while an allowance is used up: the router's choice
            # is what tells a turn apart from one that never wanted a search.
            # Withheld, a spent pool put "I've used up the search allowance"
            # on top of a 6pm stretch reminder (2026-08-25). A chosen search is
            # refused locally by the budget - no provider call - and the reply
            # is told which allowance and when it resets, on that turn only.
            search_tool = await self._search_tool_definition()
            if search_tool is not None:
                tools.append(search_tool)

            tools.extend(
                self._builtin_definition(builtin.name, builtin.description, builtin.schema)
                for builtin in self._available_builtins(unattended)
            )
            # A scheduled firing may name a routine the person taught ("run my
            # morning brief"); it never means a shipped pack. Offered the
            # packs, a firing "Remind me to stretch" was routed to one
            # (2026-08-26, found by exercise_search_scenarios).
            offered_skills.extend(
                skill for skill in (skills or []) if not (unattended and _is_pack(skill))
            )
            tools.extend(skill_tool_definitions(offered_skills))

            candidates: list[tuple[dict[str, Any], MCPTool]] = []
            if self.tool_orchestration is not None:
                candidates = await self.tool_orchestration.list_candidates(
                    user_id, query, query_embedding=query_embedding
                )
            aliases = {f"mcp_tool_{index}": item for index, item in enumerate(candidates)}
            tools.extend(MCPToolOrchestrationService.tool_definitions(aliases))

            # Weather rides the alias path under its own name: `_parse` builds a
            # ToolboxAction from the alias entry, so the whole execution and
            # evidence pipeline is the one every other MCP tool already uses.
            weather = await self._weather_tool_definition()
            if weather is not None:
                definition, live = weather
                tools.append(definition)
                aliases[WEATHER_TOOL] = (
                    {"schema_fingerprint": live.schema_fingerprint},
                    live,
                )
            credits = await self._credits_tool_definition()
            if credits is not None:
                definition, live = credits
                tools.append(definition)
                aliases[SEARCH_CREDITS_TOOL] = (
                    {"schema_fingerprint": live.schema_fingerprint},
                    live,
                )
        history_text = render_recent_history(history)
        visual_state = (
            "A picture is currently selected and visible to the user."
            if active_image_artifact_id
            else "No picture is currently selected in the interface."
        )
        message_text = (
            f"Recent conversation:\n{history_text}\n\nNewest message: {query}"
            if history_text
            else query
        )
        # The model cannot resolve "tomorrow", "Friday", or "today at 5"
        # without knowing when now is: left to itself it dated a task for
        # "today" two years in the past, from its training era, and the task
        # fired at once. The person's own clock, when their zone is known.
        clock = f"Current date and time: {local_now}\n\n" if local_now else ""
        user_content = (
            f"{clock}Visual interface state: {visual_state}\n\n{message_text}"
        )
        # Only ever appended, and omitted entirely when empty, so a first
        # decision is byte-for-byte the request it was before the loop
        # existed: the prompt-cache prefix and the recorded routing matrix
        # both stay valid, and step one is not a new measurement.
        if steps_taken:
            done = "\n".join(f"- {line}" for line in steps_taken)
            user_content += (
                f"\n\nAlready done this turn:\n{done}\n\n"
                "Call the next tool this message still needs, or no tool if "
                "everything it asked for has been done. Never repeat something "
                "already listed above."
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_content},
        ]
        try:
            message = await asyncio.to_thread(
                self.llm.chat_with_tools,
                messages,
                tools,
                settings.ROUTING_DECISION_MAX_TOKENS,
            )
        except Exception:
            logger.warning("Main action selection failed", exc_info=True)
            return None

        offered = {tool["function"]["name"] for tool in tools}
        return self._parse(message, query, aliases, offered, offered_skills)

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
        skills: list[dict[str, Any]] | None = None,
    ) -> MainAction:
        extracted = self._extract_call(message, offered)
        if extracted is None:
            return None
        name, arguments = extracted

        builtin = parse_builtin(name, arguments, fallback_query)
        if builtin is not NOT_BUILTIN:
            return builtin  # type: ignore[return-value]
        skill = parse_skill_call(name, skills or [])
        if skill is not None:
            return skill

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
