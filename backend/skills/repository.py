"""Storage for the skills a person taught."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.skill import UserSkill


# A stable key from a name: "Morning Brief!" and "morning brief" are one skill.
def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:80] or "skill"


def _skill_dict(skill: UserSkill) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "user_id": skill.user_id,
        "slug": skill.slug,
        "name": skill.name,
        "description": skill.instruction[:200],
        "instruction": skill.instruction,
        "enabled": skill.enabled,
        "use_count": skill.use_count,
        "last_used_at": skill.last_used_at,
        "created_at": skill.created_at,
        "source": "user",
    }


class SkillRepository:
    """User skills, on the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Save a skill, replacing one of the same name: teaching it again is how
    # a person changes what it does.
    async def save(self, user_id: str, name: str, instruction: str) -> dict[str, Any]:
        slug = slugify(name)
        skill = await self.session.scalar(
            select(UserSkill).where(
                UserSkill.user_id == user_id, UserSkill.slug == slug
            )
        )
        if skill is None:
            skill = UserSkill(user_id=user_id, slug=slug, name=name.strip())
            self.session.add(skill)
        skill.name = name.strip()[:80]
        skill.instruction = instruction.strip()
        skill.enabled = True
        await self.session.commit()
        await self.session.refresh(skill)
        return _skill_dict(skill)

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(UserSkill)
                .where(UserSkill.user_id == user_id, UserSkill.enabled.is_(True))
                .order_by(UserSkill.created_at)
            )
        ).scalars()
        return [_skill_dict(skill) for skill in rows]

    async def get_owned(self, user_id: str, skill_id: str) -> dict[str, Any] | None:
        skill = await self._owned(user_id, skill_id)
        return _skill_dict(skill) if skill else None

    async def delete_owned(self, user_id: str, skill_id: str) -> bool:
        skill = await self._owned(user_id, skill_id)
        if skill is None:
            return False
        await self.session.delete(skill)
        await self.session.commit()
        return True

    # Count a use, so the panel can show what actually gets invoked.
    async def touch_used(self, user_id: str, skill_id: str) -> None:
        skill = await self._owned(user_id, skill_id)
        if skill is None:
            return
        skill.use_count += 1
        skill.last_used_at = datetime.now(UTC)
        await self.session.commit()

    async def _owned(self, user_id: str, skill_id: str) -> UserSkill | None:
        try:
            key = uuid.UUID(str(skill_id))
        except ValueError:
            return None
        return await self.session.scalar(
            select(UserSkill).where(UserSkill.id == key, UserSkill.user_id == user_id)
        )
