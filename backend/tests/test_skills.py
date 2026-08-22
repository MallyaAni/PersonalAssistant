"""Skills: packs on disk, skills as router tools, and the taught-skill store."""

import os
import uuid
from pathlib import Path

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.skills.packs import load_packs
from backend.skills.repository import SkillRepository, slugify
from backend.skills.tools import parse_skill_call, skill_tool_definitions
from backend.tools import UseSkillAction


def test_slugs_are_stable_keys():
    assert slugify("Morning Brief!") == "morning-brief"
    assert slugify("  morning   brief ") == "morning-brief"
    assert slugify("???") == "skill"


# The repository's own packs folder must parse, and a pack without a body
# must not be offered.
def test_shipped_packs_load_and_a_bodyless_pack_is_skipped(tmp_path: Path):
    shipped = load_packs()
    assert "quick-brief" in shipped
    assert shipped["quick-brief"].description
    assert shipped["quick-brief"].as_skill()["source"] == "pack"

    (tmp_path / "good.md").write_text(
        "---\nname: Standup notes\ndescription: Notes for standup.\n---\nWrite them.\n",
        encoding="utf-8",
    )
    (tmp_path / "empty.md").write_text("---\nname: Nothing\n---\n\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("about packs", encoding="utf-8")
    load_packs.cache_clear()
    try:
        packs = load_packs(tmp_path)
    finally:
        load_packs.cache_clear()
    assert list(packs) == ["standup-notes"]
    assert packs["standup-notes"].instruction == "Write them."


def test_each_skill_becomes_a_tool_the_router_can_choose():
    skills = [
        {
            "id": "s1",
            "slug": "morning-brief",
            "name": "morning brief",
            "instruction": "weather for Arlington, then my tasks",
            "source": "user",
        },
        {
            "id": "pack:quick-brief",
            "slug": "quick-brief",
            "name": "Quick brief",
            "description": "three lines",
            "instruction": "...",
            "source": "pack",
        },
    ]
    definitions = skill_tool_definitions(skills)
    assert [d["function"]["name"] for d in definitions] == [
        "skill__morning-brief",
        "skill__quick-brief",
    ]
    assert "weather for Arlington" in definitions[0]["function"]["description"]
    assert definitions[0]["function"]["parameters"]["properties"] == {}

    chosen = parse_skill_call("skill__morning-brief", skills)
    assert chosen == UseSkillAction(
        "s1", "morning brief", "weather for Arlington, then my tasks", "user"
    )
    assert parse_skill_call("skill__quick-brief", skills).source == "pack"
    assert parse_skill_call("skill__unknown", skills) is None
    assert parse_skill_call("search_web", skills) is None


@pytest.mark.asyncio
async def test_taught_skills_round_trip_replace_by_name_and_stay_owned():
    from sqlalchemy import delete

    from backend.database.session import AsyncSessionLocal
    from backend.models.skill import UserSkill

    user_id = f"skill_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SkillRepository(session)
            first = await repo.save(user_id, "Morning Brief", "weather then tasks")
            assert first["slug"] == "morning-brief"
            again = await repo.save(user_id, "morning brief", "weather, tasks, a joke")
            assert again["id"] == first["id"]
            listed = await repo.list_for_user(user_id)
            assert len(listed) == 1
            assert listed[0]["instruction"] == "weather, tasks, a joke"
            await repo.touch_used(user_id, first["id"])
            assert (await repo.get_owned(user_id, first["id"]))["use_count"] == 1
            assert await repo.get_owned("intruder", first["id"]) is None
            assert await repo.delete_owned("intruder", first["id"]) is False
            assert await repo.delete_owned(user_id, first["id"]) is True
            assert await repo.list_for_user(user_id) == []
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(UserSkill).where(UserSkill.user_id == user_id))
            await session.commit()
