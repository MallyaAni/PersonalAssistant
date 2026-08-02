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
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from backend.core.auth import AdminDependency
from backend.core.dependencies import DbDependency
from backend.models.auth import RegistrationInvite, UserAccount

router = APIRouter(prefix="/admin", tags=["admin"])

# A short default. An unused invitation is a live path to creating an account on
# this machine, so it should expire sooner than someone is likely to forget it.
DEFAULT_INVITE_HOURS = 24
MAX_INVITE_HOURS = 168


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
            }
            for row in rows
        ]
    }
