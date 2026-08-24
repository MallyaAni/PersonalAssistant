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

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, text

from backend.config.settings import settings
from backend.core.auth import AdminDependency, IdentityDependency
from backend.core.dependencies import (
    DbDependency,
    DependencyDiscoverySubscribers,
    MainActionSelectorDependency,
    get_search_budget,
    grant_recipient_on_bridge,
)
from backend.discovery.search_budget import (
    GUEST_DAILY_QUERIES,
    GUEST_MONTHLY_QUERIES,
    OPERATOR_DAILY_QUERIES,
    OPERATOR_MONTHLY_QUERIES,
)
from backend.models.auth import (
    AccessRequest,
    RegistrationInvite,
    UserAccount,
    UserSession,
)
from backend.services.welcome_service import send_welcome_if_new
from backend.search.tavily import TavilyUsageClient

logger = logging.getLogger(__name__)

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
def _describe(
    invite: RegistrationInvite,
    now: datetime,
    asker: AccessRequest | None = None,
) -> dict[str, object]:
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
        # Who this was minted for, when they asked, and what they said. A code
        # with only a timestamp tells the operator nothing about whether it
        # still belongs to anyone.
        "requested_by": asker.display_name if asker else None,
        "requested_username": asker.desired_username if asker else None,
        "requested_contact": asker.contact if asker else None,
        "requested_reason": asker.reason if asker else None,
        "requested_at": (
            asker.created_at.isoformat() if asker and asker.created_at else None
        ),
    }


# List every invitation with its current state, newest first.
@router.get("/invites")
async def list_invites(
    admin: AdminDependency,
    db: DbDependency,
    include_finished: bool = Query(True),
    include_expired: bool = Query(False),
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
    # One lookup for every invitation that came from a request, so each code
    # can name the person it was minted for.
    askers = {
        request.invite_id: request
        for request in (
            (
                await db.execute(
                    select(AccessRequest).where(AccessRequest.invite_id.is_not(None))
                )
            )
            .scalars()
            .all()
        )
    }
    described = [_describe(row, now, askers.get(row.id)) for row in rows]
    # An expired code cannot be used and cannot be revoked into anything, so it
    # is history rather than something to act on. Kept behind a flag rather than
    # deleted, because "was one ever issued" is still a real question.
    if not include_expired:
        described = [item for item in described if item["status"] != "expired"]
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
    # Carry the same decision to the machine that actually sends.
    #
    # Approving here and listing the number on the Mac were two records of one
    # choice, kept by hand, and they drifted: a subscriber was approved, her
    # digest was built on time, and the bridge refused it at the last hop with
    # nothing in the run to say why. The operator had done everything the UI
    # asked for.
    granted = await grant_recipient_on_bridge(person.channel, person.address)
    return {"id": person.id, "approved": person.approved, "bridge": granted}


# Refuse a request to be messaged by this machine.
#
# Approving had no counterpart, so the only way to decline was to leave the
# request sitting in the list forever — which reads exactly like one nobody has
# looked at yet.
@router.post("/subscriptions/{subscriber_id}/deny", status_code=status.HTTP_200_OK)
async def deny_subscription(
    admin: AdminDependency,
    subscriber_id: UUID,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    if not await subscribers.deny(subscriber_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found."
        )
    return {"id": str(subscriber_id), "denied": True}


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
    # Injected only so the welcome can be written from the same capability list
    # the turn router offers, rather than from a paragraph that goes stale.
    selector: MainActionSelectorDependency,
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
    from backend.services.auth_service import AuthService

    row.status = "approved"
    row.decided_at = datetime.now(UTC)
    row.decided_by = _operator_id(identity)

    # Requests made since credentials were collected become accounts here.
    # Approving is the decision, so it should also be the moment the account
    # exists — an approved request that still needs redeeming leaves the
    # operator unable to tell who actually signed up.
    if row.desired_username and row.password_hash:
        try:
            account = await AuthService(db).create_account_with_hash(
                user_id=row.desired_username,
                username=row.desired_username,
                password_hash=row.password_hash,
            )
        except ValueError as clash:
            # The name was free when they asked and is not now. The request
            # stays pending so it can be approved once they pick another.
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That username was taken since the request was made.",
            ) from clash
        # The hash now lives on the account; there is no reason to keep a second
        # copy on a decided request.
        row.password_hash = None

        # Make the account durable before any side effect. `enroll` below
        # commits the session, and reaching the bridge or the model can fail;
        # committing here means existing is settled first, and a later failure
        # rolls back only the side effect, never the account. Capture what the
        # side effects need into locals, because commit expires the ORM rows.
        user_id = account.user_id
        phone = row.phone
        display_name = row.display_name or account.user_id
        await db.commit()

        # Approving is also the moment they become reachable. The iMessage
        # bridge identifies a sender by matching against the subscriber
        # allowlist, so without this an approved person can sign in on the web
        # and still be a stranger to the bridge - their texts ignored, with
        # nothing anywhere saying why.
        #
        # Enrolled as consented because the number was given for exactly this
        # purpose, by the person themselves, in the request the operator is
        # approving. A failure here must not undo the account: being reachable
        # is a smaller thing than existing, and the operator can enrol the
        # number by hand.
        #
        # The words are distinct on purpose: "not_applicable" means no number
        # was given, "conflict" means the number already belongs to someone
        # else (the sign-up guard should have caught it, but the window between
        # sign-up and approval is real), "not_enrolled" means the enrol itself
        # failed. Collapsing these into one hid the case a hand-enrol is needed.
        bridge = "not_applicable"
        if phone:
            from backend.core.phone import matching_key
            from backend.discovery.subscribers import SubscriberRepository
            from backend.discovery.types import label_digest
            from backend.models.discovery_subscriber import DiscoverySubscriber

            phone_key = label_digest(matching_key(phone))
            conflict = await db.scalar(
                select(DiscoverySubscriber.id).where(
                    DiscoverySubscriber.channel == "imessage",
                    DiscoverySubscriber.address_digest == phone_key,
                    DiscoverySubscriber.user_id != user_id,
                )
            )
            if conflict is not None:
                bridge = "conflict"
                logger.warning(
                    "Approved %s but their number already belongs to another "
                    "account; not enrolling or granting it",
                    user_id,
                )
            else:
                bridge = "not_enrolled"
                try:
                    await SubscriberRepository(db).enroll(
                        user_id=user_id,
                        channel="imessage",
                        address=phone,
                        label="Given at sign-up",
                        consented=True,
                    )
                except Exception:
                    await db.rollback()
                    logger.warning(
                        "Approved %s but could not enrol their number for "
                        "iMessage; they will need enrolling by hand",
                        user_id,
                        exc_info=True,
                    )
                else:
                    # Two allowlists, one decision. Enrolling above only teaches
                    # AniOS whose account a sender belongs to; the Mac keeps its
                    # own list and is the last hop before a message reaches a
                    # real person. Approving here and listing the number there
                    # were kept by hand once and drifted - a subscriber
                    # approved, her digest built on time, and the bridge
                    # refusing it at the last hop with nothing to say why.
                    #
                    # Returned rather than raised: the account exists and the
                    # person can use the web either way, and "granted" vs
                    # "unreachable" is something the operator should see rather
                    # than something that should undo an approval.
                    bridge = await grant_recipient_on_bridge("imessage", phone)

        # Being reachable and knowing it are different things. Until now an
        # approved person got an account and silence: nothing said anything was
        # listening, what it could do, or that they could simply write to it.
        #
        # After the grant, deliberately - the Mac refuses a number it has not
        # been told about, so introducing someone before that is introducing
        # them to a message that bounces. Never fatal, and never retried here:
        # an approval undone because an introduction failed would be a far
        # worse outcome than an approval with no introduction. The word comes
        # back in the response so the operator can see which happened.
        welcome = await send_welcome_if_new(
            db,
            user_id=user_id,
            display_name=display_name,
            selector=selector,
        )

        await db.commit()
        return {
            "id": str(request_id),
            "status": "approved",
            "user_id": user_id,
            "account_created": True,
            # So the operator can see whether they are actually reachable, not
            # only that the account exists.
            "bridge": bridge,
            # And whether they were actually introduced: "sent", or a word
            # saying why not, so a silent approval is visible rather than
            # assumed.
            "welcome": welcome,
        }

    # Older requests carry no credentials, so they keep the token path they were
    # created under: their own token becomes the registration credential, and
    # the digest already on file is reused rather than minting a second secret.
    invite = RegistrationInvite(
        token_digest=row.token_digest,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    db.add(invite)
    await db.flush()
    row.invite_id = invite.id
    await db.commit()
    return {"id": str(request_id), "status": "approved", "account_created": False}


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
    # A denied applicant is not a user, so nothing here should keep their
    # credentials or contact details. Clear the phone (and its digest) and the
    # password hash they chose, the same way approval nulls the hash once it
    # moves onto the account. The row survives as an audit record of the
    # decision, carrying no secret.
    row.phone = None
    row.phone_digest = None
    row.password_hash = None
    await db.commit()
    return {"id": str(request_id), "status": "denied"}


# What the shared search pool has left, and whether the per-account limits
# promise more than it can pay for.
#
# The overcommitment figure is reported rather than enforced: the pool refuses
# spending past its ceiling regardless, so a warning here lets the operator
# rebalance limits deliberately instead of discovering it when a guest is cut
# off mid-sweep.
@router.get("/search-credits", status_code=status.HTTP_200_OK)
async def read_search_credits(
    admin: AdminDependency,
    db: DbDependency,
) -> dict[str, object]:
    budget = get_search_budget()
    # Ask the provider what the key has really spent before reporting a balance.
    # The local count only knows about reservations this system made, so without
    # this the operator is shown a number that drifts further from the truth
    # every time anything else touches the key.
    usage = TavilyUsageClient(
        base_url=settings.SEARCH_BASE_URL,
        api_key=settings.SEARCH_API_KEY,
    )
    reported = await usage.spent() if usage.is_enabled() else None
    if reported is not None:
        await budget.reconcile(reported)
    status_now = await budget.pool_status()
    accounts = (await db.execute(select(UserAccount))).scalars().all()
    committed_daily = sum(
        budget.daily_allowance(bool(row.is_admin), row.search_daily_limit)
        for row in accounts
        if row.is_active
    )
    return {
        **status_now,
        # No day may promise more than the month has left.
        "daily_ceiling": status_now["remaining"],
        "committed_daily": committed_daily,
        "overcommitted": committed_daily > status_now["remaining"],
        # Null means the provider could not be asked, so the figures above are
        # this system's own count. Said plainly rather than implied, because a
        # balance nobody has checked should not look like one that was.
        "provider_reported_spent": reported,
        # So the operator can see what "default" actually means rather than
        # having to guess the number an empty field stands for.
        "defaults": {
            "guest_daily": GUEST_DAILY_QUERIES,
            "guest_monthly": GUEST_MONTHLY_QUERIES,
            "operator_daily": OPERATOR_DAILY_QUERIES,
            "operator_monthly": OPERATOR_MONTHLY_QUERIES,
        },
    }


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # False restores access. Revoking is reversible on purpose: the account and
    # everything it owns stay put, so this is "locked out", not "deleted".
    active: bool = False


# Suspend or restore an account.
#
# Sessions are destroyed rather than left to expire, because an already
# signed-in browser would otherwise keep working for as long as its cookie
# lasts — which would make revoking look like it had worked while it had not.
@router.post("/accounts/{user_id}/revoke", status_code=status.HTTP_200_OK)
async def set_account_active(
    admin: AdminDependency,
    identity: IdentityDependency,
    db: DbDependency,
    user_id: str,
    body: RevokeRequest,
) -> dict[str, object]:
    account = await db.scalar(select(UserAccount).where(UserAccount.user_id == user_id))
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        )
    # Locking yourself out of the only account that can unlock anything would
    # need database access to undo.
    if not body.active and account.user_id == _operator_id(identity):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot revoke your own operator account.",
        )
    account.is_active = body.active
    if not body.active:
        await db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    await db.commit()
    return {"user_id": user_id, "is_active": account.is_active}


# Erase an account and everything in the database belonging to it.
#
# Tables are discovered from the schema rather than listed here. A hand-written
# list is how this codebase already shipped a purge that missed eight discovery
# tables: the list and the schema drift apart silently, and the failure is
# invisible because deletion reports success either way. Anything with a user_id
# column is data about a user, so that is the rule.
#
# Deletion is retried while it makes progress, so foreign keys between user-owned
# tables resolve themselves without hardcoding an order that would also drift.
@router.delete("/accounts/{user_id}", status_code=status.HTTP_200_OK)
async def delete_account(
    admin: AdminDependency,
    identity: IdentityDependency,
    db: DbDependency,
    user_id: str,
) -> dict[str, object]:
    account = await db.scalar(select(UserAccount).where(UserAccount.user_id == user_id))
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        )
    # Deleting the only account that can undo it needs database access to fix.
    if account.user_id == _operator_id(identity):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot delete your own operator account.",
        )

    tables = [
        row[0]
        for row in (
            await db.execute(
                text(
                    "select table_name from information_schema.columns "
                    "where table_schema = 'public' and column_name = 'user_id'"
                )
            )
        ).all()
    ]
    removed: dict[str, int] = {}
    pending = set(tables)
    while pending:
        progressed = False
        for table in sorted(pending):
            try:
                result = await db.execute(
                    text(f'delete from "{table}" where user_id = :uid'),
                    {"uid": user_id},
                )
            except Exception:
                # Probably still referenced by a table not yet cleared. Roll
                # back only this statement and try again next pass.
                await db.rollback()
                continue
            removed[table] = int(getattr(result, "rowcount", 0) or 0)
            pending.discard(table)
            progressed = True
        if not progressed:
            # A cycle, or a reference from something not owned by this user.
            # Refusing beats leaving an account half-erased and unusable.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Could not clear: {', '.join(sorted(pending))}.",
            )
    # `access_requests` has no user_id column, so the schema sweep above never
    # reaches it - and it holds the person's phone number and the Argon2 hash of
    # the password they chose. It links to the account by desired_username, which
    # equals user_id at approval, so clear it here explicitly. Deleted outright:
    # the account it produced is being erased, so its origin record has nothing
    # left to audit and no reason to keep the PII.
    access = await db.execute(
        delete(AccessRequest).where(AccessRequest.desired_username == user_id)
    )
    removed["access_requests"] = int(getattr(access, "rowcount", 0) or 0)
    await db.commit()
    return {
        "user_id": user_id,
        "deleted": {name: count for name, count in removed.items() if count},
        "tables_scanned": len(tables),
    }


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
