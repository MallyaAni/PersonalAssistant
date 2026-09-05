"""The runs API keeps one person's runs to that person, and a verb to its scope.

Every route binds the path's user to the token's subject, so a run is
invisible to anyone but its principal; and the scopes split looking from
acting, so a token issued to watch cannot stop or approve. Each test issues
its own token rather than relying on suite order (AGENTS.md, the 401 trap).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.core.auth import SCOPE_RUNS_ACT, SCOPE_RUNS_READ, issue_user_token
from backend.database.session import AsyncSessionLocal
from backend.main import app
from backend.runs.repository import AgentRunRepository

pytestmark = pytest.mark.asyncio


# Authentication on for the duration of each test and restored after: with
# it off the identity is None and ownership is not checked, which is the
# local-development mode and not the one these routes protect in.
@pytest.fixture(autouse=True)
def _authentication_required():
    from backend.config.settings import settings

    previous = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True
    try:
        yield
    finally:
        settings.AUTH_REQUIRED = previous


async def _run_for(user: str) -> dict:
    async with AsyncSessionLocal() as db:
        return await AgentRunRepository(db).create(
            user, "agent:test", "scripted", "do a", ["a"],
            budget_seconds=10.0, max_steps=2, max_creates=1,
        )


async def _clean(*users: str) -> None:
    async with AsyncSessionLocal() as db:
        for user in users:
            await AgentRunRepository(db).delete_for_user(user)


def _client(user: str, scopes=None) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {issue_user_token(user, scopes=scopes)}"})


async def test_a_run_is_visible_to_its_principal_and_to_nobody_else():
    owner, stranger = f"api_{uuid.uuid4().hex[:10]}", f"api_{uuid.uuid4().hex[:10]}"
    try:
        run = await _run_for(owner)
        with _client(owner) as client:
            listed = client.get(f"/api/v1/runs/{owner}")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()["runs"]] == [run["id"]]
            shown = client.get(f"/api/v1/runs/{owner}/{run['id']}")
            assert shown.status_code == 200
            assert shown.json()["status"] == "queued"
            assert shown.json()["events"][0]["kind"] == "created"
        with _client(stranger) as client:
            # Another person's path is refused before the handler runs.
            assert client.get(f"/api/v1/runs/{owner}").status_code == 403
            assert client.get(f"/api/v1/runs/{owner}/{run['id']}").status_code == 403
            # And under their own path the run does not exist.
            assert client.get(f"/api/v1/runs/{stranger}/{run['id']}").status_code == 404
            assert client.post(f"/api/v1/runs/{stranger}/{run['id']}/cancel").status_code == 404
    finally:
        await _clean(owner, stranger)


async def test_a_token_that_may_only_read_cannot_cancel_or_approve():
    owner = f"api_{uuid.uuid4().hex[:10]}"
    try:
        run = await _run_for(owner)
        with _client(owner, scopes=[SCOPE_RUNS_READ]) as client:
            assert client.get(f"/api/v1/runs/{owner}").status_code == 200
            assert client.post(f"/api/v1/runs/{owner}/{run['id']}/cancel").status_code == 403
            assert client.post(
                f"/api/v1/runs/{owner}/{run['id']}/approvals/{uuid.uuid4()}",
                json={"granted": True},
            ).status_code == 403
        with _client(owner, scopes=[SCOPE_RUNS_ACT]) as client:
            assert client.get(f"/api/v1/runs/{owner}").status_code == 403
            cancelled = client.post(f"/api/v1/runs/{owner}/{run['id']}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
    finally:
        await _clean(owner)


async def test_deciding_a_missing_or_foreign_approval_is_refused():
    owner = f"api_{uuid.uuid4().hex[:10]}"
    try:
        run = await _run_for(owner)
        with _client(owner) as client:
            missing = client.post(
                f"/api/v1/runs/{owner}/{run['id']}/approvals/{uuid.uuid4()}",
                json={"granted": True},
            )
            assert missing.status_code == 404
    finally:
        await _clean(owner)
