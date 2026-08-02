"""Operator-only administration of invitations and accounts.

Every route here is guarded by `require_admin` rather than by ownership. The
distinction matters: ownership answers "is this your data", and an invited guest
owns their chat, memory, and agents completely. This answers "may you act on the
machine", which a guest may not — they cannot invite people, discover who else
has an account, or disable anyone.

Nothing here returns a raw invitation code except the moment one is minted. The
database stores only a digest, so a code cannot be recovered later even by the
operator; the listing shows status and never a token.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.config.settings import settings
from backend.core.auth import AdminDependency, IdentityDependency
from backend.core.dependencies import DbDependency, DependencyDiscoverySubscribers
from backend.models.auth import AccessRequest, RegistrationInvite, UserAccount

router = APIRouter(prefix="/admin", tags=["admin"])

# A short default. An unused invitation is a live path to creating an account on
# this machine, so it should expire sooner than someone is likely to forget it.
DEFAULT_INVITE_HOURS = 24
MAX_INVITE_HOURS = 168


# The account these operator-owned resources belong to. Trusted-local mode has no
# identity and is already a single-user development option, so it maps to the
# configured local owner.
def _operator_id(identity: object) -> str:
    user_id = getattr(identity, "user_id", None)
    return str(user_id) if user_id else settings.AUTH_LOCAL_USER_ID


# Describe one invitation by status rather than by its secret.
def _describe(invite: RegistrationInvite, now: datetime) -> dict[str, object]:
    if invite.consumed_at is not None:
        state = "used"
    elif invite.expires_at <= now:
        state = "expired"
    else:
        state = "open"
    return {
        "id": str(invite.id),
        "status": state,
        "expires_at": invite.expires_at.isoformat(),
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
        "consumed_at": (invite.consumed_at.isoformat() if invite.consumed_at else None),
        "consumed_by": invite.consumed_by_user_id,
    }


# List every invitation with its current state, newest first.
@router.get("/invites")
async def list_invites(
    admin: AdminDependency,
    db: DbDependency,
    include_finished: bool = Query(True),
) -> dict[str, object]:
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(RegistrationInvite).order_by(
                    RegistrationInvite.created_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    described = [_describe(row, now) for row in rows]
    if not include_finished:
        described = [item for item in described if item["status"] == "open"]
    return {
        "invites": described,
        "open": sum(1 for item in described if item["status"] == "open"),
    }


# Mint one invitation and return its code exactly once.
@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    admin: AdminDependency,
    db: DbDependency,
    ttl_hours: Annotated[int, Query(ge=1, le=MAX_INVITE_HOURS)] = DEFAULT_INVITE_HOURS,
) -> dict[str, object]:
    from backend.services.auth_service import AuthService

    invite = await AuthService(db).create_registration_invite(
        timedelta(hours=ttl_hours)
    )
    return {
        # Shown once. Only the digest is stored, so this cannot be retrieved
        # again — which is also why revoking is the only recovery from a
        # code sent to the wrong person.
        "code": invite.token,
        "expires_at": invite.expires_at.isoformat(),
    }


# Revoke an unused invitation so the code stops working.
#
# Deleting the row is the revocation: registration looks the invitation up by
# digest, so a removed row cannot be consumed. An already-used invitation is left
# alone, because it is the record of how an existing account was created.
@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    admin: AdminDependency,
    db: DbDependency,
    invite_id: UUID,
) -> None:
    invite = await db.get(RegistrationInvite, invite_id)
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found."
        )
    if invite.consumed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That invitation was already used and is now a record.",
        )
    await db.delete(invite)
    await db.commit()


# List accounts so the operator can see who has access.
@router.get("/accounts")
async def list_accounts(
    admin: AdminDependency,
    db: DbDependency,
) -> dict[str, object]:
    rows = (
        (await db.execute(select(UserAccount).order_by(UserAccount.created_at)))
        .scalars()
        .all()
    )
    return {
        "accounts": [
            {
                "user_id": row.user_id,
                "username": row.username,
                "is_active": row.is_active,
                "is_admin": row.is_admin,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_seen_at": (
                    row.last_seen_at.isoformat() if row.last_seen_at else None
                ),
                "search_monthly_limit": row.search_monthly_limit,
                "search_daily_limit": row.search_daily_limit,
            }
            for row in rows
        ]
    }


class SubscriberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["imessage", "shortcuts_pull"]
    address: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=80)
    # Consent is stated, never inferred. Without it the permission is stored
    # inactive, so the default outcome of a mistake is that nothing is sent.
    consented: bool = False


# Who this machine may message.
#
# Deliberately here rather than under a per-user path. Delivery goes through one
# Apple ID and one bridge — the operator's — so a subscriber is a property of the
# machine, not of whichever agent produced the digest. Modelling it per user
# described something only one user could ever have, which reads as a feature
# and is not one.
@router.get("/subscribers")
async def list_subscribers(
    admin: AdminDependency,
    identity: IdentityDependency,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    owner = _operator_id(identity)
    people = await subscribers.list_subscribers(owner)
    return {
        "egress_enabled": settings.DISCOVERY_EGRESS_ENABLED,
        "subscribers": [
            {
                "id": person.id,
                "channel": person.channel,
                "label": person.label,
                "active": person.active,
                "deliverable": person.deliverable,
                "delivery_count": person.delivery_count,
                "last_error": person.last_error,
                # The address is another person's contact detail; enumerating
                # recipients should not hand them out.
                "feed_path": f"/api/v1/discovery/feed/{person.token}.ics",
            }
            for person in people
        ],
    }


@router.put("/subscribers", status_code=status.HTTP_200_OK)
async def put_subscriber(
    admin: AdminDependency,
    identity: IdentityDependency,
    body: SubscriberRequest,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    owner = _operator_id(identity)
    try:
        person = await subscribers.enroll(
            owner, body.channel, body.address, body.label, body.consented
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return {
        "id": person.id,
        "channel": person.channel,
        "deliverable": person.deliverable,
        "feed_path": f"/api/v1/discovery/feed/{person.token}.ics",
    }


# Stop delivery now, and invalidate any calendar link already shared.
@router.post("/subscribers/{subscriber_id}/revoke", status_code=status.HTTP_200_OK)
async def revoke_subscriber(
    admin: AdminDependency,
    identity: IdentityDependency,
    subscriber_id: UUID,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    if not await subscribers.revoke(_operator_id(identity), subscriber_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscriber not found."
        )
    return {"id": str(subscriber_id), "revoked": True}


@router.delete("/subscribers/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscriber(
    admin: AdminDependency,
    identity: IdentityDependency,
    subscriber_id: UUID,
    subscribers: DependencyDiscoverySubscribers,
) -> None:
    if not await subscribers.delete(_operator_id(identity), subscriber_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscriber not found."
        )


# Every subscription on the machine, whoever requested it.
#
# The operator's view differs from a guest's on purpose: a guest sees only their
# own and cannot approve it, while this shows who asked for what and is the only
# place an address becomes messageable.
@router.get("/subscriptions")
async def list_subscriptions(
    admin: AdminDependency,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    rows = await subscribers.list_all()
    return {
        "egress_enabled": settings.DISCOVERY_EGRESS_ENABLED,
        "subscriptions": [
            {
                "id": person.id,
                "requested_by": owner,
                "channel": person.channel,
                "approved": person.approved,
                "deliverable": person.deliverable,
                "delivery_count": person.delivery_count,
                # The address is shown here and nowhere else: approving it is a
                # decision about who this machine messages, and that cannot be
                # made blind.
                "address": person.address,
            }
            for owner, person in rows
        ],
    }


# Permit this machine to message one address.
@router.post("/subscriptions/{subscriber_id}/approve", status_code=status.HTTP_200_OK)
async def approve_subscription(
    admin: AdminDependency,
    subscriber_id: UUID,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    person = await subscribers.approve(subscriber_id)
    if person is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found."
        )
    return {"id": person.id, "approved": person.approved}


class SearchLimitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Null restores the deployment default rather than meaning "no limit": an
    # unbounded account is exactly what this exists to prevent.
    monthly_limit: int | None = Field(default=None, ge=0, le=10_000)
    daily_limit: int | None = Field(default=None, ge=0, le=1_000)


# Requests for an account, newest first.
#
# The details are the point. Minting a code blind means deciding who gets access
# before knowing who is asking, so approving reads what they said about
# themselves.
@router.get("/access-requests")
async def list_access_requests(
    admin: AdminDependency,
    db: DbDependency,
    pending_only: bool = Query(False),
) -> dict[str, object]:
    stmt = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if pending_only:
        stmt = stmt.where(AccessRequest.status == "pending")
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "requests": [row.to_dict() for row in rows],
        "pending": sum(1 for row in rows if row.status == "pending"),
    }


# Approve one request, making the token its asker already holds usable.
#
# Nothing is sent anywhere. The asker keeps their token from the moment they
# asked, so approval needs no code to travel back to them over some other
# channel — which is one fewer secret in flight.
@router.post("/access-requests/{request_id}/approve", status_code=status.HTTP_200_OK)
async def approve_access_request(
    admin: AdminDependency,
    identity: IdentityDependency,
    db: DbDependency,
    request_id: UUID,
    ttl_hours: Annotated[int, Query(ge=1, le=MAX_INVITE_HOURS)] = DEFAULT_INVITE_HOURS,
) -> dict[str, object]:
    row = await db.get(AccessRequest, request_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found."
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That request was already {row.status}.",
        )

    from datetime import UTC, datetime

    from backend.models.auth import RegistrationInvite

    # The request's own token becomes the registration credential, so the digest
    # already on file is reused rather than a second secret being created.
    invite = RegistrationInvite(
        token_digest=row.token_digest,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    db.add(invite)
    await db.flush()
    row.status = "approved"
    row.invite_id = invite.id
    row.decided_at = datetime.now(UTC)
    row.decided_by = _operator_id(identity)
    await db.commit()
    return {"id": str(request_id), "status": "approved"}


# Decline a request. The token stops being usable for anything.
@router.post("/access-requests/{request_id}/deny", status_code=status.HTTP_200_OK)
async def deny_access_request(
    admin: AdminDependency,
    identity: IdentityDependency,
    db: DbDependency,
    request_id: UUID,
) -> dict[str, object]:
    from datetime import UTC, datetime

    row = await db.get(AccessRequest, request_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found."
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That request was already {row.status}.",
        )
    row.status = "denied"
    row.decided_at = datetime.now(UTC)
    row.decided_by = _operator_id(identity)
    await db.commit()
    return {"id": str(request_id), "status": "denied"}


# Set how much metered search one account may spend per month.
@router.put("/accounts/{user_id}/search-limit", status_code=status.HTTP_200_OK)
async def set_search_limit(
    admin: AdminDependency,
    db: DbDependency,
    user_id: str,
    body: SearchLimitRequest,
) -> dict[str, object]:
    account = await db.scalar(select(UserAccount).where(UserAccount.user_id == user_id))
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        )
    account.search_monthly_limit = body.monthly_limit
    account.search_daily_limit = body.daily_limit
    await db.commit()
    return {
        "user_id": user_id,
        "monthly_limit": account.search_monthly_limit,
        "daily_limit": account.search_daily_limit,
        "using_default": account.search_monthly_limit is None
        and account.search_daily_limit is None,
    }
