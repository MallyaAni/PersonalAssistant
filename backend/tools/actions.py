"""The typed decisions a turn can come out of routing with."""

from dataclasses import dataclass

from backend.services.mcp_tool_orchestration_service import MCPToolPlan


@dataclass(frozen=True, slots=True)
class SearchAction:
    """The model decided this turn needs a live web search."""

    query: str
    max_results: int | None = None


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
