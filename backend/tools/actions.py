"""The typed decisions a turn can come out of routing with."""

from dataclasses import dataclass

from backend.services.mcp_tool_orchestration_service import MCPToolPlan


@dataclass(frozen=True, slots=True)
class SearchAction:
    """The model decided this turn needs a live web search."""

    query: str
    max_results: int | None = None


@dataclass(frozen=True, slots=True)
class RecallHistoryAction:
    """The model decided this turn refers to something said in the past.

    Passive recall injects the top few similar past remarks before every
    answer; this is the active form, chosen when the person points at
    something that is not in view - "that restaurant I mentioned", "when did
    we talk about X" - and the transcript store has to be searched for it.

    Time bounds are the model's to state, never parsed from prose in code:
    "last week" reaches the search as ISO dates the model resolved against
    its clock, and absent bounds mean all of history.
    """

    query: str
    since: str | None = None
    until: str | None = None


@dataclass(frozen=True, slots=True)
class GenerateImageAction:
    """The model decided this turn wants a brand-new picture made."""

    prompt: str
    # Whether the picture shows a person, stated by the model; decides the
    # styling the image provider applies.
    depicts_a_person: bool = False


@dataclass(frozen=True, slots=True)
class EditImageAction:
    """The model decided this turn wants the picture in view changed."""

    instruction: str
    # Whether the edit means changing the setting or adding what is not
    # there yet, as opposed to a change confined to something visible.
    restages_the_scene: bool = False


@dataclass(frozen=True, slots=True)
class ShowImageAction:
    """The model decided this turn wants a picture they already have shown again."""

    # Which picture, in the user's words; resolved against what they own.
    which: str


@dataclass(frozen=True, slots=True)
class DiscussImageAction:
    """The model decided this turn talks about the picture in view - an
    opinion, a comparison, a question about it - and changes nothing.

    Its own row because, offered only "edit" and "show", the router read
    every sentence about the picture as one of them: opinions went to edit
    (0/9, 2026-08-26) and, once a resolver said "this is about the picture",
    to show (0/9, 2026-08-27). Nothing runs for this action; the reply
    answers from the picture's description already in its context.
    """

    about: str = ""


@dataclass(frozen=True, slots=True)
class CreateDiagramAction:
    """The model decided this turn wants a diagram drafted."""

    subject: str


@dataclass(frozen=True, slots=True)
class CreateDocumentAction:
    """Write the assistant's words to a file the person can keep and share.

    `body_markdown` empty means "what you just wrote": the previous reply in
    the conversation is the document, which is the commonest case - a plan
    or itinerary composed in chat, then asked for as a PDF.
    """

    title: str
    format: str
    body_markdown: str = ""


@dataclass(frozen=True, slots=True)
class EditDocumentAction:
    """Rewrite the Word file the person shared with revised text, its look kept.

    `body_markdown` empty means the previous reply is the revised text. The
    file is the pinned document, else the newest one shared in the
    conversation; when only a PDF was shared a new document is written
    instead and the reply says why.
    """

    title: str
    format: str
    body_markdown: str = ""


@dataclass(frozen=True, slots=True)
class DelegateAction:
    """The model decided this turn belongs to a specialist agent."""

    capability_id: str
    subject: str


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
    # Reschedule only, and named exactly as ScheduleTaskAction names them so
    # the one date resolver reads either without knowing which it has.
    instruction: str | None = None
    # None means "leave this as the task already has it". Defaulting cadence to
    # "once" would turn "move the stretch reminder to 7pm" - a weekdays task -
    # into a single firing, and nothing in the reply would say so.
    cadence: str | None = None
    hour: int = 0
    minute: int = 0
    weekday: int | None = None
    on_date: str | None = None


@dataclass(frozen=True, slots=True)
class SendEventLinksAction:
    """The model decided this turn wants links for events it already listed.

    The listing now ends by offering the map, the calendar link or the event
    page rather than printing them, and this is the follow-up that delivers:
    `which` names the events the person means, resolved by the picker against
    the last listing this conversation showed, and the links are built by
    code from the typed records so nothing is invented.
    """

    which: str


@dataclass(frozen=True, slots=True)
class ScoutScheduleAction:
    """The model decided this turn sets when Scout's own sweep runs.

    Its own action, not a `manage_tasks` reschedule: the sweep is agent
    configuration, and a router offered only "reschedule a task" read
    "change the schedule to 9:25pm" after talk of Scout as that (measured
    2026-08-23, backend/tools/manage_tasks.py). Two named things to choose
    between is the structural fix that note asked for (2026-08-26).
    """

    cadence: str
    hour: int
    minute: int = 0
    weekday: int = 0
    # "set" changes the sweep's schedule; "show" only reports it - "when does
    # scout run?" was a task list before it had a named target (2026-08-27).
    operation: str = "set"


@dataclass(frozen=True, slots=True)
class SaveSkillAction:
    """The model decided this turn teaches a skill: a name and what it does."""

    name: str
    instruction: str


@dataclass(frozen=True, slots=True)
class ManageSkillsAction:
    """The model decided this turn is about skills already saved."""

    operation: str
    which: str = ""


@dataclass(frozen=True, slots=True)
class UseSkillAction:
    """The model decided this turn invokes one of the person's skills."""

    skill_id: str
    name: str
    instruction: str
    # "user" for one they taught in conversation, "pack" for one shipped in
    # the repository's skills folder.
    source: str = "user"


@dataclass(frozen=True, slots=True)
class ManageRunsAction:
    """The model decided this turn answers a background run waiting on the
    person - a yes or a no to the step it asked about - or asks what is
    running or waiting for them."""

    mode: str  # approve, deny, status
    which: str = ""


@dataclass(frozen=True, slots=True)
class ToolboxAction:
    """The model decided this turn should call one of the user's own tools."""

    plan: MCPToolPlan


MainAction = (
    SearchAction
    | GenerateImageAction
    | EditImageAction
    | ShowImageAction
    | DiscussImageAction
    | CreateDiagramAction
    | CreateDocumentAction
    | EditDocumentAction
    | DelegateAction
    | ScheduleTaskAction
    | ManageTasksAction
    | ScoutScheduleAction
    | SaveSkillAction
    | ManageSkillsAction
    | UseSkillAction
    | ToolboxAction
    | ManageRunsAction
    | None
)


@dataclass(frozen=True, slots=True)
class ManageCheckInsAction:
    """The model decided this turn is about check-ins: the person asking to be
    asked later how something went, to have that habit on or off, or to hear
    what is waiting. Off for everyone until asked (the operator's rule,
    2026-09-02: people did not like being checked on unasked)."""

    mode: str  # on, off, once, status
    subject: str = ""
    question: str = ""
    after_days: int | None = None
    hour: int | None = None
    kind: str = "following_up"
