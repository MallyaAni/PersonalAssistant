"""The operator's group routes: guests refused, groups listed without their
chat address, switched off, and deleted with everything they own."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.groups.repository import ConversationGroupRepository
from backend.main import app
from backend.models.auth import UserAccount
from backend.models.discovery_subscriber import DiscoverySubscriber
from backend.tests.test_admin_boundary import _account, _cleanup
from backend.tests.test_conversation_groups import _chat
from backend.tests.test_conversation_groups import _cleanup as _cleanup_group


@pytest.fixture(autouse=True)
def _require_auth():
    previous = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True
    try:
        yield
    finally:
        settings.AUTH_REQUIRED = previous


def _client(token: str | None) -> AsyncClient:
    cookies = {settings.AUTH_COOKIE_NAME: token} if token else {}
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8080", cookies=cookies,
        headers={"Origin": "http://localhost:8080"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/admin/groups"), ("POST", "/api/v1/admin/groups/group:abc/enabled?enabled=false"), ("DELETE", "/api/v1/admin/groups/group:abc")],
)
async def test_a_guest_is_refused_the_group_routes(method: str, path: str):
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            response = await client.request(method, path)
        assert response.status_code == 403
    finally:
        await _cleanup(guest)


@pytest.mark.asyncio
async def test_the_operator_lists_silences_and_deletes_a_group():
    operator = f"op_{uuid.uuid4().hex[:10]}"
    chat = _chat()
    try:
        _, token = await _account(operator, admin=True)
        async with AsyncSessionLocal() as db:
            group = await ConversationGroupRepository(db).provision(chat, "Lunch crew", ("u-ani", "u-jen"))
        async with _client(token) as client:
            listed = await client.get("/api/v1/admin/groups")
            assert listed.status_code == 200
            (row,) = [g for g in listed.json()["groups"] if g["user_id"] == group.user_id]
            assert row == {"user_id": group.user_id, "display_name": "Lunch crew", "enabled": True, "members": ["u-ani", "u-jen"]}
            assert chat not in listed.text
            off = await client.post(f"/api/v1/admin/groups/{group.user_id}/enabled?enabled=false")
            assert off.status_code == 200 and off.json() == {"user_id": group.user_id, "enabled": False}
            assert (await client.post("/api/v1/admin/groups/group:nothere/enabled?enabled=true")).status_code == 404
            assert (await client.post(f"/api/v1/admin/groups/{operator}/enabled?enabled=false")).status_code == 404
            gone = await client.delete(f"/api/v1/admin/groups/{group.user_id}")
            assert gone.status_code == 204
            assert (await client.delete(f"/api/v1/admin/groups/{group.user_id}")).status_code == 404
        async with AsyncSessionLocal() as db:
            assert await db.get(UserAccount, group.user_id) is None
            assert await db.scalar(select(DiscoverySubscriber).where(DiscoverySubscriber.user_id == group.user_id)) is None
            assert await ConversationGroupRepository(db).by_user_id(group.user_id) is None
    finally:
        await _cleanup_group(chat)
        await _cleanup(operator)
