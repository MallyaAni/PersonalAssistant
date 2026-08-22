"""Skills as router tools: one function per skill, chosen by meaning."""

from typing import Any

from backend.tools.actions import UseSkillAction

SKILL_PREFIX = "skill__"


# One tool definition per skill. The description is the skill's own, so the
# router decides from what the skill does, not from its name alone: "brief
# me" reaches "morning brief" because the description says what a brief is.
def skill_tool_definitions(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    for skill in skills:
        slug = str(skill.get("slug") or "")
        if not slug:
            continue
        description = (
            f"The person's skill '{skill.get('name', slug)}': "
            f"{str(skill.get('description') or skill.get('instruction') or '')[:400]}"
            " Choose it whenever the message says this skill's name, or asks "
            "for what it does in other words - a skill the person set up is "
            "how they want that handled, so prefer it over answering directly. "
            "Not for teaching or changing it."
        )
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": f"{SKILL_PREFIX}{slug}"[:64],
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        )
    return definitions


# A skill tool call as its action, or None for a name no offered skill has.
def parse_skill_call(name: str, skills: list[dict[str, Any]]) -> UseSkillAction | None:
    if not name.startswith(SKILL_PREFIX):
        return None
    for skill in skills:
        slug = str(skill.get("slug") or "")
        if slug and f"{SKILL_PREFIX}{slug}"[:64] == name:
            return UseSkillAction(
                skill_id=str(skill.get("id") or slug),
                name=str(skill.get("name") or slug),
                instruction=str(skill.get("instruction") or ""),
                source=str(skill.get("source") or "user"),
            )
    return None
