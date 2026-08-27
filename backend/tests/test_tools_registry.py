"""The tools folder: every row complete, every call parsed, every wait named."""

import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.services.mcp_tool_orchestration_service import MCPToolPlan
from backend.tools import (
    NOT_BUILTIN,
    CreateDiagramAction,
    DelegateAction,
    EditImageAction,
    GenerateImageAction,
    ManageSkillsAction,
    SaveSkillAction,
    SearchAction,
    ToolboxAction,
    UseSkillAction,
    builtin_tools,
    describe_action,
    parse_builtin,
    waiting_line,
)


# A row missing any of its parts would reach the router or the status line
# half-described; the registry must never offer one.
def test_every_builtin_row_is_complete():
    rows = builtin_tools(("diagram", "presentation"))
    names = [row.name for row in rows]
    # The order the router is offered them in. `search_history` and
    # `show_image` were added after this list was first written; a row the
    # list omits is a row this test never checked.
    assert names == [
        "generate_image",
        "edit_image",
        "show_image",
        "discuss_image",
        "create_diagram",
        "delegate_to_presentation_agent",
        "search_history",
        "schedule_task",
        "manage_tasks",
        "scout_schedule",
        "save_skill",
        "manage_skills",
    ]
    for row in rows:
        assert row.label
        assert row.description
        assert row.schema.get("type") == "object"
        assert row.waiting, row.name
        assert all(line.strip() for line in row.waiting)


def test_gated_rows_disappear_with_their_service():
    names = [row.name for row in builtin_tools(())]
    assert "create_diagram" not in names
    assert "delegate_to_presentation_agent" not in names
    assert "generate_image" in names
    assert "save_skill" in names


def test_each_tool_parses_its_own_call():
    assert parse_builtin("search_web", {"query": " spark temps "}, "x") == SearchAction(
        "spark temps"
    )
    assert parse_builtin("search_web", {}, "fallback") == SearchAction("fallback")
    assert parse_builtin(
        "generate_image", {"prompt": "a hummingbird", "depicts_a_person": False}, ""
    ) == GenerateImageAction("a hummingbird", False)
    assert parse_builtin("generate_image", {"prompt": " "}, "") is None
    assert parse_builtin(
        "edit_image", {"instruction": "make it dusk", "restages_the_scene": True}, ""
    ) == EditImageAction("make it dusk", True)
    assert parse_builtin("create_diagram", {"subject": "agile"}, "") == (
        CreateDiagramAction("agile")
    )
    assert parse_builtin("create_diagram", {"subject": ""}, "") is None
    assert parse_builtin(
        "delegate_to_presentation_agent", {"subject": "q3"}, ""
    ) == DelegateAction("presentation_agent", "q3")
    assert parse_builtin(
        "save_skill", {"name": "morning brief", "instruction": "weather then tasks"}, ""
    ) == SaveSkillAction("morning brief", "weather then tasks")
    assert parse_builtin("save_skill", {"name": "x"}, "") is None
    assert parse_builtin("manage_skills", {"operation": "list"}, "") == (
        ManageSkillsAction("list", "")
    )
    assert parse_builtin("manage_skills", {"operation": "rename"}, "") is None
    assert parse_builtin("mcp_tool_0", {}, "") is NOT_BUILTIN


def test_actions_are_described_and_given_a_waiting_line():
    assert describe_action(None) is None
    assert describe_action(SearchAction("spark temps")) == ("Web search", "spark temps")
    weather = ToolboxAction(
        MCPToolPlan(
            server_id="internet",
            tool_name="get_weather",
            arguments={},
            expected_fingerprint="f",
        )
    )
    assert describe_action(weather) == ("Weather", "")
    assert waiting_line(weather).startswith(("🌤️", "☁️", "🌡️"))
    other = ToolboxAction(
        MCPToolPlan(
            server_id="drive",
            tool_name="list_files",
            arguments={},
            expected_fingerprint="f",
        )
    )
    assert describe_action(other) == ("list_files", "drive")
    line = waiting_line(other)
    assert "list_files" in line or "toolbox" in line
    skill = UseSkillAction("s1", "morning brief", "weather then tasks")
    assert describe_action(skill) == ("Skill", "morning brief")
    assert "morning brief" in waiting_line(skill)
    assert describe_action(SaveSkillAction("wrap-up", "x")) == ("Skills", "wrap-up")
    assert waiting_line(GenerateImageAction("a cat")).strip()
    assert waiting_line(None) == ""


def test_a_firing_is_offered_neither_automation_nor_history_recall():
    from backend.tools.registry import UNATTENDED_WITHHELD

    names = {row.name for row in builtin_tools(("diagram", "presentation"), UNATTENDED_WITHHELD)}
    assert "search_history" not in names and "schedule_task" not in names
    assert "generate_image" in names and "show_image" in names
