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

logger = logging.getLogger(__name__)

_SEARCH_TOOL = "search_web"
_WEATHER_TOOL = "get_weather"
_GENERATE_IMAGE_TOOL = "generate_image"
_EDIT_IMAGE_TOOL = "edit_image"
_CREATE_DIAGRAM_TOOL = "create_diagram"
_DELEGATE_PRESENTATION_TOOL = "delegate_to_presentation_agent"
_SCHEDULE_TASK_TOOL = "schedule_task"
_MANAGE_TASKS_TOOL = "manage_tasks"


# Asked of the two tools that otherwise take no arguments. The point is not to
# pass it on - both of them read the request itself - but to make the model
# state what it believes it was asked to make. A tool chosen by mistake has no
# subject to state, and the caller can see that before spending the turn on it
# instead of after, when a deck is already queued.
def _subject_schema(what: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": (
                    f"What the {what} is about, in a few words, taken from the "
                    "request. Leave empty if the request does not say."
                ),
            }
        },
        "required": ["subject"],
        "additionalProperties": False,
    }


_GENERATE_IMAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "Exactly what to draw, as a self-contained subject.",
        },
        # Asked here because the model already knows it, and the alternative
        # was a word list. `mentions_a_person` matched "my", "me", "i", "her"
        # among others, so "draw me a picture of my car" was a person and got
        # skin-and-hair styling applied to a car.
        "depicts_a_person": {
            "type": "boolean",
            "description": (
                "True when the picture would show a person or people. False "
                "for objects, places, animals, food, or diagrams."
            ),
        },
    },
    "required": ["prompt", "depicts_a_person"],
    "additionalProperties": False,
}
_EDIT_IMAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instruction": {
            "type": "string",
            "description": "The single change to make to the picture in view.",
        },
        # Asked of the model because only the request says which kind of edit
        # this is, and the two need opposite instructions to the image model.
        # Every edit used to be sent with "do not add, remove, or move
        # anything", which is right for recolouring a hat and self-defeating
        # for "make it look like it came in its original packaging" - that one
        # cannot be done without adding something, so the picture came back
        # unchanged.
        "restages_the_scene": {
            "type": "boolean",
            "description": (
                "True when carrying out the edit means changing the setting or "
                "introducing things that are not in the picture yet - putting "
                "the subject in packaging or another place, changing the "
                "season, weather, or time of day, or restyling the whole "
                "image. False for a change confined to something already "
                "visible, such as recolouring, removing, or relabelling one "
                "object, where everything else must stay exactly as it is."
            ),
        },
    },
    "required": ["instruction", "restages_the_scene"],
    "additionalProperties": False,
}


# The one argument a built-in tool cannot do without, or nothing.
#
# A tool call carrying an empty required string is not a decision the model
# made, it is a tool it picked without being able to say what for. Every
# built-in treats that as no call at all rather than acting on a blank.
def _required_text(arguments: dict[str, Any], field: str) -> str | None:
    value = arguments.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


_NOT_BUILTIN = object()


# The built-in tools' calls as actions. Returns the `_NOT_BUILTIN` sentinel
# for a name that is not a built-in at all, so the caller can tell "not ours"
# from "ours, but the model left out what it needed" (None).
def _builtin_action(
    name: str, arguments: dict[str, Any], fallback_query: str
) -> "MainAction | object":
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
        prompt = _required_text(arguments, "prompt")
        if prompt is None:
            return None
        return GenerateImageAction(
            prompt=prompt,
            depicts_a_person=bool(arguments.get("depicts_a_person")),
        )
    if name == _EDIT_IMAGE_TOOL:
        return _edit_action(arguments)
    # The two below used to take no arguments, so a turn routed to either by
    # mistake reached the caller looking exactly like a real request and took
    # the whole turn. Both now state their subject, and the same rule the two
    # above already applied covers all four: no subject means no decision, so
    # the turn goes down the ordinary reply path where the assistant asks for
    # the one thing it is missing, rather than queueing a subjectless deck or
    # drawing a diagram of nothing.
    if name == _CREATE_DIAGRAM_TOOL:
        subject = _required_text(arguments, "subject")
        return None if subject is None else CreateDiagramAction(subject)
    if name == _DELEGATE_PRESENTATION_TOOL:
        subject = _required_text(arguments, "subject")
        return (
            None if subject is None else DelegateAction("presentation_agent", subject)
        )
    if name == _SCHEDULE_TASK_TOOL:
        return _schedule_task_action(arguments)
    if name == _MANAGE_TASKS_TOOL:
        return _manage_tasks_action(arguments)
    return _NOT_BUILTIN


# Lifted out of `_parse` to keep that function readable as the built-ins grew a
# second argument each; it makes no decision the caller could not.
def _edit_action(arguments: dict[str, Any]) -> "EditImageAction | None":
    instruction = _required_text(arguments, "instruction")
    if instruction is None:
        return None
    return EditImageAction(
        instruction=instruction,
        restages_the_scene=bool(arguments.get("restages_the_scene")),
    )


# A schedule_task call as an action, or nothing when the model left out what
# the task is or picked a cadence the scheduler does not have.
def _schedule_task_action(arguments: dict[str, Any]) -> "ScheduleTaskAction | None":
    instruction = _required_text(arguments, "instruction")
    cadence = arguments.get("cadence")
    if instruction is None or cadence not in ("once", "daily", "weekdays", "weekly"):
        return None
    try:
        hour = int(arguments.get("hour", 9))
        minute = int(arguments.get("minute", 0))
        weekday = int(arguments.get("weekday") or 0)
    except (TypeError, ValueError):
        return None
    on_date = arguments.get("on_date")
    return ScheduleTaskAction(
        instruction=instruction,
        cadence=str(cadence),
        hour=hour,
        minute=minute,
        weekday=weekday,
        on_date=str(on_date) if isinstance(on_date, str) and on_date else None,
    )


# A manage_tasks call as an action, or nothing for an unknown operation.
def _manage_tasks_action(arguments: dict[str, Any]) -> "ManageTasksAction | None":
    operation = arguments.get("operation")
    if operation not in ("list", "cancel", "pause", "resume"):
        return None
    which = arguments.get("which")
    return ManageTasksAction(
        operation=str(operation), which=which.strip() if isinstance(which, str) else ""
    )


@dataclass(frozen=True, slots=True)
class BuiltinTool:
    """One built-in action, written down once and read by both callers.

    The reply prompt has to tell the user what AniOS can do, and this selector
    has to tell the routing model when each tool fires. Those were two hand-
    written lists in two files saying the same thing in different words, which
    is a drift waiting to happen: the prompt's wording would govern what the
    assistant claims while the wording here governs what actually runs. One
    row carries both, so a tool cannot be added, removed, or disabled in
    routing while conversation goes on describing the old set.

    `label` is what to call the capability in conversation; `description` is
    the router's own account of what it does and when it applies, and is
    reused verbatim rather than paraphrased.
    """

    name: str
    label: str
    description: str
    schema: dict[str, Any]

    # The same row as a capability line for the reply prompt's context.
    def as_capability(self) -> dict[str, str]:
        return {"label": self.label, "description": self.description}


_GENERATE_IMAGE = BuiltinTool(
    name=_GENERATE_IMAGE_TOOL,
    label="New images",
    description=(
        "Create a brand-new picture from a text description. Only when the "
        "user actually asks for an image, picture, drawing, or artwork to be "
        "made - never for a request to write text, such as a poem, haiku, "
        "story, or description, even when its subject is visual (rain, a "
        "sunset, a mountain): that is answered as words, not illustrated, "
        "unless the user separately asks for a picture too."
    ),
    schema=_GENERATE_IMAGE_SCHEMA,
)
# Offered unconditionally, unlike generate_image's implicit sibling: a request
# to change "the picture" can arrive before the application's own idea of what
# is active agrees, and the only way to find that out is to let the model
# decide edit intent from the conversation, then let the caller check whether
# anything is actually in view - otherwise a missing selection answered as an
# ordinary chat turn with no explanation, which read as the feature being
# broken rather than a picture nobody had picked.
_EDIT_IMAGE = BuiltinTool(
    name=_EDIT_IMAGE_TOOL,
    label="Image edits",
    description=(
        "Change the picture currently in view, including adding labels or "
        "annotations to it. Never for a resume, document, "
        "email, message, plan, or schedule, including a short request to make "
        "that text more casual, formal, friendly, concise, or professional. "
        "Even when the message says 'edit' and no other "
        "tool fits that request - answer those directly instead of calling "
        "any tool. Only for a direct instruction to change the picture, never "
        "for a question, including one that names the alternative it is asking "
        "about: asking whether something would look better, which of two is "
        "preferable, or what you would recommend is asking what you think, not "
        "telling you to change anything, even when the same subject was just "
        "edited - answer "
        "it directly from what is already visible instead."
    ),
    schema=_EDIT_IMAGE_SCHEMA,
)
_CREATE_DIAGRAM = BuiltinTool(
    name=_CREATE_DIAGRAM_TOOL,
    label="Diagrams",
    description=(
        "Draft a technical diagram (flowchart, architecture diagram, sequence, "
        "state, class, or entity-relationship). What decides this is the kind "
        "of thing they asked for, not the subject they asked about: choose it "
        "when they name a diagram, chart, flowchart or one of the forms above. "
        "A technical subject does not by itself make the request a diagram - "
        "someone asking for an image or a picture of an architecture wants a "
        "picture of it, and generate_image is right even though the subject is "
        "technical. When they do ask for a diagram, this renders real text "
        "where a generated picture can only imitate writing."
    ),
    schema=_subject_schema("diagram"),
)
_DELEGATE_PRESENTATION = BuiltinTool(
    name=_DELEGATE_PRESENTATION_TOOL,
    label="Presentations",
    description="Hand off to the specialist that builds slide decks.",
    schema=_subject_schema("deck"),
)

_SCHEDULE_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instruction": {
            "type": "string",
            "description": (
                "What to do each time it runs, rewritten as a self-contained "
                "instruction in the person's own terms - "
                "'text me today's weather for Arlington', 'remind me to call "
                "mom', 'check whether the stacking cable is in stock at "
                "Rockville and tell me'. Never the words 'remind me' or "
                "'every day' themselves; the schedule is carried separately."
            ),
        },
        "cadence": {
            "type": "string",
            "enum": ["once", "daily", "weekdays", "weekly"],
            "description": (
                "once for a single time ('tomorrow at 9', 'Friday'), daily for "
                "every day, weekdays for Monday to Friday, weekly for one day "
                "each week."
            ),
        },
        "hour": {"type": "integer", "minimum": 0, "maximum": 23},
        "minute": {"type": "integer", "minimum": 0, "maximum": 59},
        "weekday": {
            "type": "integer",
            "minimum": 0,
            "maximum": 6,
            "description": "For weekly: 0 is Monday, 6 is Sunday.",
        },
        "on_date": {
            "type": "string",
            "description": (
                "For once: the calendar date as YYYY-MM-DD, resolved from "
                "today's date for words like tomorrow or Friday."
            ),
        },
    },
    "required": ["instruction", "cadence", "hour", "minute"],
    "additionalProperties": False,
}

_MANAGE_TASKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["list", "cancel", "pause", "resume"],
        },
        "which": {
            "type": "string",
            "description": (
                "Which task, in the person's words, when cancelling, pausing "
                "or resuming - 'the weather one', 'the Friday reminder'. "
                "Empty for list."
            ),
        },
    },
    "required": ["operation"],
    "additionalProperties": False,
}

_SCHEDULE_TASK = BuiltinTool(
    name=_SCHEDULE_TASK_TOOL,
    label="Scheduled tasks",
    description=(
        "Set something up to happen later or on a schedule: a reminder, a "
        "daily or weekly message, a recurring check or lookup, anything they "
        "want done at a stated time rather than now. Choose it when the "
        "request names a future time or a repetition - tomorrow, every "
        "morning, Fridays, at 7 - and the thing itself is something this "
        "assistant can do in a turn (answer, look up, search, report, "
        "remind). Resolve relative words against today's date and their "
        "local time. A question asked for right now is not a task."
    ),
    schema=_SCHEDULE_TASK_SCHEMA,
)
_MANAGE_TASKS = BuiltinTool(
    name=_MANAGE_TASKS_TOOL,
    label="Manage scheduled tasks",
    description=(
        "List, cancel, pause, or resume the tasks they already scheduled. "
        "Choose it when they ask what is scheduled, or to stop, pause, or "
        "restart one - 'cancel the weather texts', 'what do I have "
        "scheduled?'. Changing a time or what a task does is a cancel and a "
        "new schedule_task."
    ),
    schema=_MANAGE_TASKS_SCHEMA,
)


# Search is the one action whose tool description is not AniOS's to write: the
# schema and wording offered to the router come from the live MCP contract
# ("Research a minimized public query with bounded free-provider policy"),
# which describes the server's interface rather than the product's capability,
# and reading it costs a session against that server. Its routing rule lives in
# _SYSTEM below instead, and this is the matching sentence for conversation.
_SEARCH_CAPABILITY: dict[str, str] = {
    "label": "Web search",
    "description": (
        "Look up current information on the web when the answer could have "
        "changed since training - news, prices, availability, schedules, or "
        "whoever currently holds a role, title, office, or record."
    ),
}

_WEATHER_CAPABILITY: dict[str, str] = {
    "label": "Weather",
    "description": (
        "Check the current conditions and forecast for a place from live "
        "forecast data, for any question about weather now or in the coming "
        "days."
    ),
}

# The wording lives in `prompts/routing/select_action.md`.
_SYSTEM = load("routing/select_action")

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
    # Stated by the model rather than inferred from its wording, so human style
    # detail is applied to people and not to anything whose description happens
    # to contain a pronoun.
    depicts_a_person: bool = False


@dataclass(frozen=True, slots=True)
class EditImageAction:
    """The model decided this turn wants the picture in view changed."""

    instruction: str
    # Whether carrying out the edit requires changing the scene rather than
    # adjusting something already in it. The preservation wording sent to the
    # image model is the opposite in each case.
    restages_the_scene: bool = False


@dataclass(frozen=True, slots=True)
class CreateDiagramAction:
    """The model decided this turn wants a technical diagram."""

    # What the model believes it was asked to draw. Empty means it could not
    # say, which is how a misroute looks from here.
    subject: str = ""


@dataclass(frozen=True, slots=True)
class DelegateAction:
    """The model decided this turn belongs to a registered specialist."""

    capability_id: str
    subject: str = ""


@dataclass(frozen=True, slots=True)
class ScheduleTaskAction:
    """The model decided this turn sets something up to happen later."""

    instruction: str
    cadence: str
    hour: int
    minute: int = 0
    weekday: int = 0
    on_date: str | None = None


@dataclass(frozen=True, slots=True)
class ManageTasksAction:
    """The model decided this turn is about tasks already scheduled."""

    operation: str
    which: str = ""


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
    | ScheduleTaskAction
    | ManageTasksAction
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
                "name": _SEARCH_TOOL,
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
        if self.mcp_invocation is None or not self._search_is_available():
            return None
        try:
            live = await self.mcp_invocation.resolve_tool(
                self.search_server_id, _WEATHER_TOOL
            )
        except MCPInvocationError:
            # A server without the tool simply does not offer it this turn.
            return None
        definition = {
            "type": "function",
            "function": {
                "name": _WEATHER_TOOL,
                "description": live.description[:1_000],
                "parameters": live.input_schema,
            },
        }
        return definition, live

    # The built-in tools this selector offers, in the order it presents them.
    #
    # One list read by both the routing call and the capability description, so
    # a disabled diagram or presentation agent disappears from what the
    # assistant says it can do at the same moment it stops being callable.
    def _available_builtins(self) -> list[BuiltinTool]:
        builtins = [_GENERATE_IMAGE, _EDIT_IMAGE]
        if self.diagram_enabled:
            builtins.append(_CREATE_DIAGRAM)
        if self.presentation_enabled:
            builtins.append(_DELEGATE_PRESENTATION)
        builtins.extend((_SCHEDULE_TASK, _MANAGE_TASKS))
        return builtins

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
            capabilities.append(dict(_SEARCH_CAPABILITY))
            # Weather lives on the same server under the same policy, so its
            # availability is the same question already answered above.
            capabilities.append(dict(_WEATHER_CAPABILITY))
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
    async def select(
        self,
        user_id: str,
        query: str,
        history: list[dict[str, Any]],
        active_image_artifact_id: str | None,
        query_embedding: list[float] | None = None,
        local_now: str | None = None,
    ) -> MainAction:
        if not query.strip():
            return None

        tools: list[dict[str, Any]] = []
        search_tool = await self._search_tool_definition()
        if search_tool is not None:
            tools.append(search_tool)

        tools.extend(
            self._builtin_definition(builtin.name, builtin.description, builtin.schema)
            for builtin in self._available_builtins()
        )

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
            aliases[_WEATHER_TOOL] = (
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

        builtin = _builtin_action(name, arguments, fallback_query)
        if builtin is not _NOT_BUILTIN:
            return builtin

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
