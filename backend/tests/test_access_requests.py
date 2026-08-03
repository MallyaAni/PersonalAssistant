"""Asking for an account, and the operator deciding.

Minting a code blind means deciding who gets access before knowing who is
asking. A request carries the details first, so the decision is informed. The
asker keeps their own token throughout, so approval needs no secret to travel
back to them over some other channel.
"""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.config.settings import settings
from backend.core.auth_dependencies import get_login_rate_limiter
from backend.database.session import AsyncSessionLocal
from backend.main import app
from backend.models.auth import AccessRequest, RegistrationInvite
from backend.services.auth_service import AuthService


# Enable the boundary for this module only, restoring it afterwards, so this
# file cannot change how unrelated tests behave.
@pytest.fixture(autouse=True)
def _require_auth():
    previous = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True
    # The rate limiter holds a cached Redis pool bound to the event loop that
    # created it. Each test runs its own loop, so a reused pool raises "event
    # loop is closed" on the second test rather than on the first. Dropping the
    # cache around each test keeps the pool and the loop the same age.
    get_login_rate_limiter.cache_clear()
    # The global attempt window is shared by every caller by design, and the
    # password-auth tests deliberately exhaust it. Clearing it here keeps this
    # module independent of whatever ran before it, rather than passing alone
    # and failing in a full run.
    _clear_login_windows()
    try:
        yield
    finally:
        _clear_login_windows()
        get_login_rate_limiter.cache_clear()
        settings.AUTH_REQUIRED = previous


# Remove the shared login-attempt windows with a synchronous client, so no
# event loop outlives the test that created it.
def _clear_login_windows() -> None:
    import redis as sync_redis

    try:
        client = sync_redis.Redis.from_url(settings.REDIS_URL)
        keys = list(client.scan_iter("anios:auth:login*"))
        if keys:
            client.delete(*keys)
        client.close()
    except Exception:
        pass


# Create an operator account and return its session token.
async def _operator(username: str) -> str:
    from datetime import timedelta

    from sqlalchemy import update

    from backend.models.auth import UserAccount

    async with AsyncSessionLocal() as session:
        service = AuthService(session)
        await service.create_account(
            user_id=username, username=username, password="Str0ng-Passw0rd-Here"
        )
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
    return created.token


def _client(token: str | None = None) -> AsyncClient:
    cookies = {settings.AUTH_COOKIE_NAME: token} if token else {}
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8080",
        cookies=cookies,
        headers={"Origin": "http://localhost:8080"},
    )


# Remove accounts, sessions, and any request or invitation they created.
async def _cleanup(*user_ids: str, names: tuple[str, ...] = ()) -> None:
    from backend.models.auth import UserAccount, UserSession

    async with AsyncSessionLocal() as session:
        for name in names:
            rows = (
                (
                    await session.execute(
                        select(AccessRequest).where(AccessRequest.display_name == name)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                if row.invite_id:
                    await session.execute(
                        delete(RegistrationInvite).where(
                            RegistrationInvite.id == row.invite_id
                        )
                    )
                await session.delete(row)
        for user_id in user_ids:
            await session.execute(
                delete(UserSession).where(UserSession.user_id == user_id)
            )
            await session.execute(
                delete(UserAccount).where(UserAccount.user_id == user_id)
            )
        await session.commit()


@pytest.mark.asyncio
async def test_anyone_can_ask_and_asking_grants_nothing():
    name = f"Asker {uuid.uuid4().hex[:8]}"
    try:
        async with _client() as client:
            asked = await client.post(
                "/api/v1/auth/request-access",
                json={
                    "display_name": name,
                    "contact": "+15550100",
                    "username": f"u{uuid.uuid4().hex[:8]}",
                    "password": "Str0ng-Passw0rd-Here",
                },
            )
            token = asked.json()["request_token"]
            registered = await client.post(
                "/api/v1/auth/register",
                json={
                    "invite_code": token,
                    "username": f"u{uuid.uuid4().hex[:8]}",
                    "password": "Str0ng-Passw0rd-Here",
                },
            )

        assert asked.status_code == 201
        assert asked.json()["status"] == "pending"
        # The token exists and is worth nothing until somebody decides.
        assert registered.status_code == 400
    finally:
        await _cleanup(names=(name,))


@pytest.mark.asyncio
async def test_only_the_operator_sees_requests():
    name = f"Asker {uuid.uuid4().hex[:8]}"
    try:
        async with _client() as client:
            await client.post(
                "/api/v1/auth/request-access",
                json={
                    "display_name": name,
                    "username": f"u{uuid.uuid4().hex[:8]}",
                    "password": "Str0ng-Passw0rd-Here",
                },
            )
            anonymous = await client.get("/api/v1/admin/access-requests")
        assert anonymous.status_code in (401, 403)
    finally:
        await _cleanup(names=(name,))


@pytest.mark.asyncio
async def test_approval_makes_the_askers_own_token_work():
    """Approving is the moment the account exists, not a permit to register."""
    operator = f"op_{uuid.uuid4().hex[:10]}"
    guest = f"u{uuid.uuid4().hex[:8]}"
    name = f"Asker {uuid.uuid4().hex[:8]}"
    try:
        async with _client() as client:
            token = (
                await client.post(
                    "/api/v1/auth/request-access",
                    json={
                        "display_name": name,
                        "reason": "a friend",
                        "username": guest,
                        "password": "Str0ng-Passw0rd-Here",
                    },
                )
            ).json()["request_token"]

        op_token = await _operator(operator)
        async with _client(op_token) as client:
            listed = await client.get("/api/v1/admin/access-requests?pending_only=true")
            request_id = listed.json()["requests"][0]["id"]
            approved = await client.post(
                f"/api/v1/admin/access-requests/{request_id}/approve"
            )

        async with _client() as client:
            checked = await client.get(f"/api/v1/auth/request-access/{token}")
            # Nothing to redeem: approval already made the account, so the
            # credentials they chose when asking are simply their credentials.
            signed_in = await client.post(
                "/api/v1/auth/login",
                json={"username": guest, "password": "Str0ng-Passw0rd-Here"},
            )

        # The details are the point of asking first.
        assert listed.json()["requests"][0]["display_name"] == name
        assert listed.json()["requests"][0]["reason"] == "a friend"
        assert approved.status_code == 200
        assert approved.json()["account_created"] is True
        assert checked.json()["status"] == "approved"
        assert signed_in.status_code == 200
    finally:
        await _cleanup(operator, guest, names=(name,))


@pytest.mark.asyncio
async def test_a_denied_request_never_becomes_usable():
    operator = f"op_{uuid.uuid4().hex[:10]}"
    name = f"Asker {uuid.uuid4().hex[:8]}"
    try:
        async with _client() as client:
            token = (
                await client.post(
                    "/api/v1/auth/request-access",
                    json={
                        "display_name": name,
                        "username": f"u{uuid.uuid4().hex[:8]}",
                        "password": "Str0ng-Passw0rd-Here",
                    },
                )
            ).json()["request_token"]

        op_token = await _operator(operator)
        async with _client(op_token) as client:
            request_id = (
                await client.get("/api/v1/admin/access-requests?pending_only=true")
            ).json()["requests"][0]["id"]
            denied = await client.post(
                f"/api/v1/admin/access-requests/{request_id}/deny"
            )
            # A decision is final. Deciding twice is a conflict rather than a
            # silent overwrite of an earlier judgement.
            again = await client.post(
                f"/api/v1/admin/access-requests/{request_id}/approve"
            )

        async with _client() as client:
            registered = await client.post(
                "/api/v1/auth/register",
                json={
                    "invite_code": token,
                    "username": f"u{uuid.uuid4().hex[:8]}",
                    "password": "Str0ng-Passw0rd-Here",
                },
            )

        assert denied.status_code == 200
        assert again.status_code == 409
        assert registered.status_code == 400
    finally:
        await _cleanup(operator, names=(name,))


@pytest.mark.asyncio
async def test_the_operator_sees_activity_and_can_set_a_search_limit():
    operator = f"op_{uuid.uuid4().hex[:10]}"
    try:
        op_token = await _operator(operator)
        async with _client(op_token) as client:
            accounts = await client.get("/api/v1/admin/accounts")
            mine = [
                row for row in accounts.json()["accounts"] if row["user_id"] == operator
            ][0]
            set_limit = await client.put(
                f"/api/v1/admin/accounts/{operator}/search-limit",
                json={"monthly_limit": 25},
            )
            cleared = await client.put(
                f"/api/v1/admin/accounts/{operator}/search-limit",
                json={"monthly_limit": None},
            )

        # Requesting the listing is itself activity, so it must be recorded.
        assert mine["last_seen_at"] is not None
        assert set_limit.json()["monthly_limit"] == 25
        # Null restores the default rather than meaning "unlimited".
        assert cleared.json()["using_default"] is True
    finally:
        await _cleanup(operator)


@pytest.mark.asyncio
async def test_revoking_an_account_ends_its_sessions_immediately():
    # A revoked account whose browser keeps working would look revoked without
    # being revoked, so the sessions go rather than being left to expire.
    operator = f"op_{uuid.uuid4().hex[:10]}"
    guest = f"g{uuid.uuid4().hex[:9]}"
    try:
        async with AsyncSessionLocal() as session:
            await AuthService(session).create_account(
                user_id=guest, username=guest, password="Str0ng-Passw0rd-Here"
            )
        async with _client() as client:
            signed_in = await client.post(
                "/api/v1/auth/login",
                json={"username": guest, "password": "Str0ng-Passw0rd-Here"},
            )
            guest_token = signed_in.cookies.get(settings.AUTH_COOKIE_NAME)

        op_token = await _operator(operator)
        async with _client(op_token) as client:
            revoked = await client.post(
                f"/api/v1/admin/accounts/{guest}/revoke", json={"active": False}
            )

        async with _client(guest_token) as client:
            after = await client.get(f"/api/v1/memory/{guest}")

        assert revoked.status_code == 200
        assert revoked.json()["is_active"] is False
        assert after.status_code in (401, 403)
    finally:
        await _cleanup(operator, guest)


@pytest.mark.asyncio
async def test_the_operator_cannot_revoke_their_own_account():
    # Undoing it would need database access, so it is refused rather than
    # confirmed.
    operator = f"op_{uuid.uuid4().hex[:10]}"
    try:
        op_token = await _operator(operator)
        async with _client(op_token) as client:
            refused = await client.post(
                f"/api/v1/admin/accounts/{operator}/revoke", json={"active": False}
            )
            still_here = await client.get("/api/v1/admin/accounts")

        assert refused.status_code == 409
        assert still_here.status_code == 200
    finally:
        await _cleanup(operator)


@pytest.mark.asyncio
async def test_a_username_already_claimed_is_refused_when_asking():
    # Told at once rather than after the operator has agreed: a name collision
    # on a public form is not a credential check and nothing is gained by
    # being vague about it.
    name = f"Asker {uuid.uuid4().hex[:8]}"
    wanted = f"u{uuid.uuid4().hex[:8]}"
    try:
        async with _client() as client:
            first = await client.post(
                "/api/v1/auth/request-access",
                json={
                    "display_name": name,
                    "username": wanted,
                    "password": "Str0ng-Passw0rd-Here",
                },
            )
            second = await client.post(
                "/api/v1/auth/request-access",
                json={
                    "display_name": name,
                    "username": wanted,
                    "password": "Str0ng-Passw0rd-Here",
                },
            )

        assert first.status_code == 201
        assert second.status_code == 409
    finally:
        await _cleanup(names=(name,))


@pytest.mark.asyncio
async def test_deleting_an_account_clears_every_table_that_names_a_user():
    """The purge is schema-driven, so a new table cannot be forgotten.

    A hand-written list already shipped here missing eight discovery tables.
    This asserts the rule instead of the list: nothing with a user_id column
    still holds rows for the deleted account.
    """
    operator = f"op_{uuid.uuid4().hex[:10]}"
    guest = f"g{uuid.uuid4().hex[:9]}"
    try:
        async with AsyncSessionLocal() as session:
            await AuthService(session).create_account(
                user_id=guest, username=guest, password="Str0ng-Passw0rd-Here"
            )
        # Give them data in a couple of unrelated places.
        async with AsyncSessionLocal() as session:
            from backend.services.repository import SQLAlchemyConversationRepository

            repo = SQLAlchemyConversationRepository(session)
            await repo.save_turn(
                str(uuid.uuid4()),
                {"user_id": guest, "query": "mine", "response": "a"},
            )

        op_token = await _operator(operator)
        async with _client(op_token) as client:
            removed = await client.delete(f"/api/v1/admin/accounts/{guest}")

        assert removed.status_code == 200
        body = removed.json()
        assert body["tables_scanned"] > 5

        # The rule, checked against the live schema rather than a list.
        async with AsyncSessionLocal() as session:
            tables = [
                row[0]
                for row in (
                    await session.execute(
                        text(
                            "select table_name from information_schema.columns "
                            "where table_schema = 'public' "
                            "and column_name = 'user_id'"
                        )
                    )
                ).all()
            ]
            leftovers = {}
            for table in tables:
                count = await session.scalar(
                    text(f'select count(*) from "{table}" where user_id = :uid'),
                    {"uid": guest},
                )
                if count:
                    leftovers[table] = count
        assert leftovers == {}
    finally:
        await _cleanup(operator, guest)


@pytest.mark.asyncio
async def test_the_operator_cannot_delete_their_own_account():
    operator = f"op_{uuid.uuid4().hex[:10]}"
    try:
        op_token = await _operator(operator)
        async with _client(op_token) as client:
            refused = await client.delete(f"/api/v1/admin/accounts/{operator}")
        assert refused.status_code == 409
    finally:
        await _cleanup(operator)
