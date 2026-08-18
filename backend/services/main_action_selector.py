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
        }
    },
    "required": ["instruction"],
    "additionalProperties": False,
}


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
        "for a question, even one naming a specific alternative ('do you "
        "recommend a straw hat instead?', 'which hat do you like better?', "
        "'would this look better in blue?', 'should I go with the other "
        "one?'): a question asks what you think, it does not tell you to "
        "change anything, even when the same subject was just edited - answer "
        "it directly from what is already visible instead."
    ),
    schema=_EDIT_IMAGE_SCHEMA,
)
_CREATE_DIAGRAM = BuiltinTool(
    name=_CREATE_DIAGRAM_TOOL,
    label="Diagrams",
    description=(
        "Draft a technical diagram (flowchart, architecture, sequence, state, "
        "class, or entity-relationship). Choose this over drawing a picture "
        "whenever the thing asked for is a diagram of how something works or "
        "is structured - an architecture, a pipeline, a data flow, a process, "
        "a system - however the request is worded, including \"create an "
        "image of\", \"draw\", or a setting like a whiteboard or slide. Those "
        "need readable labels, which a diagram renders as real text and a "
        "generated picture can only imitate."
    ),
    schema=_EMPTY_SCHEMA,
)
_DELEGATE_PRESENTATION = BuiltinTool(
    name=_DELEGATE_PRESENTATION_TOOL,
    label="Presentations",
    description="Hand off to the specialist that builds slide decks.",
    schema=_EMPTY_SCHEMA,
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

_SYSTEM = (
    "You are choosing how to handle one user message before it is answered. "
    "You may call at most one of the tools offered below. Calling none is "
    "correct and common: it means the message is answered directly as an "
    "ordinary reply. Interpret a short newest message as a continuation of "
    "the recent conversation before assigning it a new subject. If it answers "
    "a question the assistant just asked, supplies a date, time, quantity, or "
    "deadline for material being drafted, or asks to revise the tone or wording "
    "of an email, message, document, plan, or other text, call no tool and let "
    "the assistant continue that task. Words such as 'Saturday', 'schedule', "
    "'casual', 'formal', 'shorter', or 'friendlier' describe the current task; "
    "they do not by themselves start web research or refer to a picture.\n\n"
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
    "currently in view or to a picture explicitly established as the subject "
    "of the recent conversation, describing that one change. Never reinterpret "
    "a tone or wording revision to text as clothing, appearance, or image style. "
    "A labelled or annotated "
    "version of the picture in view is an edit, not a brand-new image.\n\n"
    # "explicitly" made the wording decide instead of the subject, so "create
    # an image of our architecture on a whiteboard" went to generate_image and
    # came back with a diffusion model's imitation of writing. What separates
    # these two is whether the result needs readable labels, not which noun the
    # user happened to use.
    "Call create_diagram when what is wanted is a diagram of how something "
    "works or is structured - an architecture, pipeline, data flow, process, "
    "system, sequence, state, class, or entity-relationship. Judge that by the "
    "subject, not the noun: \"create an image of our data pipeline\", \"draw "
    "the login flow\" and \"show me a picture of how the services connect\" "
    "are all diagrams, whatever setting they name. A diagram renders real "
    "text; a generated picture can only imitate writing, so anything needing "
    "readable labels belongs here.\n\n"
    "Call delegate_to_presentation_agent only when the user explicitly asks "
    "to create a slide deck or presentation.\n\n"
    "None of these apply to a question about the user's own life, memory, "
    "opinions, or anything already answerable directly -- call no tool for "
    "those, and answer normally instead.\n\n"
    # Measured: "can you have it scheduled everyday at 11pm EST?" reached
    # search_web, "schedule it daily at 11pm" reached search_web and the
    # presentation agent, and "can you set Scout to run every day at 11pm EST?"
    # reached edit_image. Configuring an agent is not one of the tools offered
    # here, so the model reached for whichever was nearest instead of calling
    # none -- and the reply, which is what actually records a schedule, never
    # ran.
    "Setting up, scheduling, changing or asking about the user's own agents "
    "and their settings is none of these either. A message about when "
    "something should run, how often, where results go, or what an agent "
    "currently has configured is answered directly -- call no tool for it, "
    "however it is phrased and whichever agent it names. This holds when no "
    "agent is named at all: changing the schedule to a stated time, making it "
    "weekly instead, or running it an hour later are all the user adjusting "
    "their own settings, not a topic to look up. A clock time, a day or a "
    "frequency appearing in such a message is the setting being chosen, never "
    "a fact about the world to check."
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
    # Stated by the model rather than inferred from its wording, so human style
    # detail is applied to people and not to anything whose description happens
    # to contain a pronoun.
    depicts_a_person: bool = False


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
        user_content = f"Visual interface state: {visual_state}\n\n{message_text}"
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
                return GenerateImageAction(
                    prompt=prompt.strip(),
                    depicts_a_person=bool(arguments.get("depicts_a_person")),
                )
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
