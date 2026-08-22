"""Automations: the person's skills and scheduled tasks, for the workspace.

Both are created in conversation; this is where they are seen and removed.
Every route checks the session identity owns `user_id`, and the
repositories only ever read or delete rows with that owner.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.auth import IdentityDependency, authorize_user
from backend.core.dependencies import DependencyScheduledTasks, DependencySkills
from backend.skills.packs import load_packs
from backend.tasks.describe import next_run_phrase, schedule_phrase

router = APIRouter(prefix="/automations/{user_id}", tags=["automations"])


class TaskToggle(BaseModel):
    enabled: bool


# A task row as the panel shows it: the stored columns plus the phrases the
# conversation uses, so the two never disagree about when a task fires.
def _task_view(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "instruction": task["instruction"],
        "cadence": task["cadence"],
        "schedule": schedule_phrase(task),
        "next_run": next_run_phrase(task),
        "timezone": task["timezone"],
        "channel": task["channel"],
        "enabled": task["enabled"],
        "last_run_at": task["last_run_at"].isoformat() if task["last_run_at"] else None,
        "last_status": task["last_status"],
    }


def _skill_view(skill: dict[str, Any]) -> dict[str, Any]:
    last = skill.get("last_used_at")
    return {
        "id": skill["id"],
        "name": skill["name"],
        "instruction": skill["instruction"],
        "source": skill.get("source", "user"),
        "use_count": int(skill.get("use_count") or 0),
        "last_used_at": last.isoformat() if last else None,
    }


# Everything automated for this person: their skills (taught and shipped)
# and their tasks, enabled or paused.
@router.get("")
async def list_automations(
    user_id: str,
    identity: IdentityDependency,
    skills: DependencySkills,
    tasks: DependencyScheduledTasks,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    taught = await skills.list_for_user(user_id)
    taught_slugs = {skill["slug"] for skill in taught}
    shipped = [
        pack.as_skill()
        for slug, pack in load_packs().items()
        if slug not in taught_slugs
    ]
    return {
        "skills": [_skill_view(skill) for skill in taught + shipped],
        "tasks": [
            _task_view(task)
            for task in await tasks.list_for_user(user_id, enabled_only=False)
        ],
    }


@router.delete("/skills/{skill_id}")
async def delete_skill(
    user_id: str,
    skill_id: str,
    identity: IdentityDependency,
    skills: DependencySkills,
) -> dict[str, str]:
    authorize_user(user_id, identity)
    if not await skills.delete_owned(user_id, skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "deleted", "id": skill_id}


@router.delete("/tasks/{task_id}")
async def delete_task(
    user_id: str,
    task_id: str,
    identity: IdentityDependency,
    tasks: DependencyScheduledTasks,
) -> dict[str, str]:
    authorize_user(user_id, identity)
    if not await tasks.delete_owned(user_id, task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted", "id": task_id}


# Pause or resume one task; resuming re-arms its next slot from now.
@router.patch("/tasks/{task_id}")
async def toggle_task(
    user_id: str,
    task_id: str,
    body: TaskToggle,
    identity: IdentityDependency,
    tasks: DependencyScheduledTasks,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    if not await tasks.set_enabled(user_id, task_id, body.enabled):
        raise HTTPException(status_code=404, detail="Task not found")
    task = await tasks.get_owned(user_id, task_id)
    return _task_view(task) if task else {"id": task_id, "enabled": body.enabled}
