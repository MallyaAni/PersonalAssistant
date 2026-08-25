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
class CreateDiagramAction:
    """The model decided this turn wants a diagram drafted."""

    subject: str


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
class ToolboxAction:
    """The model decided this turn should call one of the user's own tools."""

    plan: MCPToolPlan


MainAction = (
    SearchAction
    | GenerateImageAction
    | EditImageAction
    | ShowImageAction
    | CreateDiagramAction
    | DelegateAction
    | ScheduleTaskAction
    | ManageTasksAction
    | SaveSkillAction
    | ManageSkillsAction
    | UseSkillAction
    | ToolboxAction
    | None
)
