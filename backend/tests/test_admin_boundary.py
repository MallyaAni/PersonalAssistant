"""An invited guest owns their data and may not act on the machine.

Ownership and administration are different questions, and this file exists to
keep them apart. A guest's chat, memory, and agents are entirely theirs. Inviting
someone else, discovering who else has an account, or changing what this machine
does on the operator's behalf are not.
"""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.main import app
from backend.services.auth_service import AuthService


# Enable the authentication boundary for this module only.
#
# Setting AUTH_REQUIRED through the environment at import time would leak into
# every other test in the same process — which it did, breaking four unrelated
# tests — so it is toggled per test and restored afterwards.
@pytest.fixture(autouse=True)
def _require_auth():
    previous = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True
    try:
        yield
    finally:
        settings.AUTH_REQUIRED = previous


_ADMIN_ROUTES = (
    ("GET", "/api/v1/admin/invites"),
    ("POST", "/api/v1/admin/invites"),
    ("GET", "/api/v1/admin/accounts"),
    ("GET", "/api/v1/admin/subscribers"),
    ("GET", "/api/v1/admin/subscriptions"),
)


# Create one account and return its session cookie value.
async def _account(username: str, admin: bool) -> tuple[str, str]:
    from datetime import timedelta

    from sqlalchemy import update

    from backend.models.auth import UserAccount

    async with AsyncSessionLocal() as session:
        service = AuthService(session)
        await service.create_account(
            user_id=username, username=username, password="Str0ng-Passw0rd-Here"
        )
        if admin:
            await session.execute(
                update(UserAccount)
                .where(UserAccount.user_id == username)
                .values(is_admin=True)
            )
            await session.commit()
        created = await service.login(
            username=username,
            password="Str0ng-Passw0rd-Here",
            ttl=timedelta(hours=1),
        )
        assert created is not None
    return username, created.token


async def _cleanup(*user_ids: str) -> None:
    from sqlalchemy import delete

    from backend.models.auth import RegistrationInvite, UserAccount, UserSession
    from backend.models.discovery_subscriber import DiscoverySubscriber

    async with AsyncSessionLocal() as session:
        for user_id in user_ids:
            await session.execute(
                delete(UserSession).where(UserSession.user_id == user_id)
            )
            await session.execute(
                delete(RegistrationInvite).where(
                    RegistrationInvite.consumed_by_user_id == user_id
                )
            )
            await session.execute(
                delete(DiscoverySubscriber).where(
                    DiscoverySubscriber.user_id == user_id
                )
            )
            await session.execute(
                delete(UserAccount).where(UserAccount.user_id == user_id)
            )
        await session.commit()


def _client(token: str | None) -> AsyncClient:
    cookies = {settings.AUTH_COOKIE_NAME: token} if token else {}
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8080",
        cookies=cookies,
        headers={"Origin": "http://localhost:8080"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _ADMIN_ROUTES)
async def test_a_guest_is_refused_every_admin_route(method: str, path: str):
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            response = await client.request(method, path)
        assert response.status_code == 403
    finally:
        await _cleanup(guest)


@pytest.mark.asyncio
async def test_the_refusal_does_not_confirm_who_exists():
    # A guest learning "you are not an admin" is fine; learning which accounts
    # exist is not, so the message says neither.
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            response = await client.get("/api/v1/admin/accounts")
        body = response.text.lower()
        assert "admin" not in body or "restricted" in body
        assert guest not in body
    finally:
        await _cleanup(guest)


@pytest.mark.asyncio
async def test_an_anonymous_caller_is_refused():
    async with _client(None) as client:
        response = await client.get("/api/v1/admin/invites")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_an_admin_can_mint_list_and_revoke_an_invitation():
    operator = f"op_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(operator, admin=True)
        async with _client(token) as client:
            created = await client.post("/api/v1/admin/invites?ttl_hours=1")
            assert created.status_code == 201
            # Shown exactly once, because only a digest is stored.
            assert created.json()["code"]

            listed = await client.get("/api/v1/admin/invites")
            assert listed.status_code == 200
            invites = listed.json()["invites"]
            mine = [item for item in invites if item["status"] == "open"]
            assert mine, "the freshly minted invitation should be open"

            revoked = await client.delete(f"/api/v1/admin/invites/{mine[0]['id']}")
            assert revoked.status_code == 204

            after = await client.get("/api/v1/admin/invites")
            remaining = {item["id"] for item in after.json()["invites"]}
            assert mine[0]["id"] not in remaining
    finally:
        await _cleanup(operator)


@pytest.mark.asyncio
async def test_a_listing_never_returns_an_invitation_code():
    # The database holds only a digest, so a listing that appeared to show a
    # code would mean something had gone badly wrong.
    operator = f"op_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(operator, admin=True)
        async with _client(token) as client:
            created = await client.post("/api/v1/admin/invites?ttl_hours=1")
            code = created.json()["code"]
            listed = await client.get("/api/v1/admin/invites")

        assert code not in listed.text
        for item in listed.json()["invites"]:
            assert "code" not in item
            assert "token" not in item
    finally:
        await _cleanup(operator)


@pytest.mark.asyncio
async def test_a_used_invitation_is_kept_as_a_record_rather_than_revoked():
    operator = f"op_{uuid.uuid4().hex[:10]}"
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(operator, admin=True)
        async with _client(token) as client:
            code = (await client.post("/api/v1/admin/invites?ttl_hours=1")).json()[
                "code"
            ]
            registered = await client.post(
                "/api/v1/auth/register",
                json={
                    "invite_code": code,
                    "username": guest,
                    "password": "Str0ng-Passw0rd-Here",
                },
            )
            assert registered.status_code == 200

            listed = (await client.get("/api/v1/admin/invites")).json()["invites"]
            used = [item for item in listed if item["status"] == "used"]
            assert used, "the consumed invitation should be listed as used"
            assert used[0]["consumed_by"] == guest

            # Revoking it would destroy the record of how that account exists.
            refused = await client.delete(f"/api/v1/admin/invites/{used[0]['id']}")
            assert refused.status_code == 409
    finally:
        await _cleanup(operator, guest)


@pytest.mark.asyncio
async def test_a_guest_cannot_configure_who_this_machine_messages():
    """The iMessage bridge sends from the operator's own Apple ID.

    A guest managing their own subscribers would cause messages to be sent as
    the operator, to numbers the operator never chose. Ownership is the wrong
    boundary for that, so these routes are the operator's.
    """
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            listed = await client.get("/api/v1/admin/subscribers")
            added = await client.put(
                "/api/v1/admin/subscribers",
                json={
                    "channel": "imessage",
                    "address": "+15550100",
                    "consented": True,
                },
            )
            # The per-user route is gone entirely. It modelled a resource only
            # one account could ever have, which reads as a feature and is not
            # one: there is one Apple ID and one bridge.
            old_path = await client.get(f"/api/v1/discovery/{guest}/subscribers")

        assert listed.status_code == 403
        assert added.status_code == 403
        assert old_path.status_code == 404
    finally:
        await _cleanup(guest)


@pytest.mark.asyncio
async def test_a_guest_keeps_the_rest_of_their_own_agent():
    # Restricting egress must not take away the parts that are genuinely theirs:
    # their interests, their place, their feeds.
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            profile = await client.get(f"/api/v1/discovery/{guest}")
            interest = await client.put(
                f"/api/v1/discovery/{guest}/interests",
                json={"label": "hiking", "strength": 2},
            )

        assert profile.status_code == 200
        assert interest.status_code == 200
    finally:
        from sqlalchemy import delete

        from backend.models.discovery import DiscoveryInterest

        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoveryInterest).where(DiscoveryInterest.user_id == guest)
            )
            await session.commit()
        await _cleanup(guest)


@pytest.mark.asyncio
async def test_a_guest_subscribes_themselves_but_cannot_make_it_live():
    """The split the design turns on.

    Where a guest's own digest goes is theirs to choose. Whether this machine
    messages that address is not, because the bridge sends from the operator's
    Apple ID — so an unapproved subscription would let any account make the
    operator message a stranger.
    """
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            asked = await client.put(
                f"/api/v1/discovery/{guest}/subscription",
                json={"channel": "imessage", "address": "+15550142"},
            )
            mine = await client.get(f"/api/v1/discovery/{guest}/subscription")
            # Approving is the operator's, and so is seeing everyone's.
            approve = await client.post(
                f"/api/v1/admin/subscriptions/{asked.json()['id']}/approve"
            )
            everyone = await client.get("/api/v1/admin/subscriptions")

        assert asked.status_code == 200
        assert asked.json()["approved"] is False
        assert asked.json()["deliverable"] is False
        assert mine.json()["subscription"]["approved"] is False
        assert approve.status_code == 403
        assert everyone.status_code == 403
    finally:
        await _cleanup(guest)


@pytest.mark.asyncio
async def test_the_operator_approves_and_only_then_is_it_deliverable():
    operator = f"op_{uuid.uuid4().hex[:10]}"
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, guest_token = await _account(guest, admin=False)
        _, op_token = await _account(operator, admin=True)

        async with _client(guest_token) as client:
            asked = await client.put(
                f"/api/v1/discovery/{guest}/subscription",
                json={"channel": "imessage", "address": "+15550143"},
            )
        subscriber_id = asked.json()["id"]

        async with _client(op_token) as client:
            listed = await client.get("/api/v1/admin/subscriptions")
            approved = await client.post(
                f"/api/v1/admin/subscriptions/{subscriber_id}/approve"
            )

        async with _client(guest_token) as client:
            after = await client.get(f"/api/v1/discovery/{guest}/subscription")

        rows = listed.json()["subscriptions"]
        assert any(row["requested_by"] == guest for row in rows)
        assert approved.status_code == 200
        assert after.json()["subscription"]["approved"] is True
        assert after.json()["subscription"]["deliverable"] is True
    finally:
        await _cleanup(operator, guest)


@pytest.mark.asyncio
async def test_an_account_may_hold_one_subscription():
    # A guest choosing where their own digest goes is reasonable; a guest
    # accumulating destinations is a way to make the operator message several
    # people.
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            first = await client.put(
                f"/api/v1/discovery/{guest}/subscription",
                json={"channel": "imessage", "address": "+15550144"},
            )
            second = await client.put(
                f"/api/v1/discovery/{guest}/subscription",
                json={"channel": "imessage", "address": "+15550145"},
            )
        assert first.status_code == 200
        assert second.status_code == 409
    finally:
        await _cleanup(guest)


@pytest.mark.asyncio
async def test_a_pull_subscription_needs_no_approval():
    # Nothing is sent: the recipient's own device fetches, so there is no
    # decision for the operator to make.
    guest = f"guest_{uuid.uuid4().hex[:10]}"
    try:
        _, token = await _account(guest, admin=False)
        async with _client(token) as client:
            asked = await client.put(
                f"/api/v1/discovery/{guest}/subscription",
                json={"channel": "shortcuts_pull", "address": "this-device"},
            )
        assert asked.json()["approved"] is True
        assert asked.json()["deliverable"] is True
    finally:
        await _cleanup(guest)
