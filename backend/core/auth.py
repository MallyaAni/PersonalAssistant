import base64
import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.database.session import get_db
from backend.models.auth import UserAccount
from backend.search.budgeted import SearchIdentity, current_search_identity
from backend.services.auth_service import AuthService

# Least-privilege scopes. A token may be restricted to a subset so a leaked or
# narrowly-issued token cannot reach the whole account. A scope with a `parent`
# below grants its children too, so `memory` implies read and write while
# `memory:read` grants only reads.
SCOPE_CHAT = "chat"
SCOPE_MEMORY_READ = "memory:read"
SCOPE_MEMORY_WRITE = "memory:write"
SCOPE_TOOLS = "tools:invoke"
SCOPE_VISION = "vision"
SCOPE_PRESENTATIONS = "presentations"

# Coarse group scopes an operator may grant instead of the fine-grained ones.
SCOPE_MEMORY = "memory"
SCOPE_TOOLS_GROUP = "tools"

# Everything an operator may put in a token. Issuing rejects anything else, so a
# typo becomes an error at issue time rather than a silently powerless token.
GRANTABLE_SCOPES = frozenset(
    {
        SCOPE_CHAT,
        SCOPE_MEMORY_READ,
        SCOPE_MEMORY_WRITE,
        SCOPE_MEMORY,
        SCOPE_TOOLS,
        SCOPE_TOOLS_GROUP,
        SCOPE_VISION,
        SCOPE_PRESENTATIONS,
    }
)


@dataclass(frozen=True)
class AuthenticatedIdentity:
    user_id: str
    expires_at: int
    # None means unrestricted: a legacy token with no scope claim keeps full
    # access, so scopes can be adopted without invalidating existing tokens.
    scopes: frozenset[str] | None = None


def _scope_satisfied(held: frozenset[str] | None, required: str) -> bool:
    if held is None:
        return True
    if required in held:
        return True
    # A group scope (`memory`, `tools`) satisfies its `group:action` children.
    parent = required.split(":", 1)[0]
    return parent in held


def issue_user_token(
    user_id: str,
    ttl_seconds: int = 3_600,
    scopes: Sequence[str] | None = None,
) -> str:
    payload: dict[str, object] = {
        "sub": user_id,
        "exp": int(time.time()) + ttl_seconds,
        "v": 1,
    }
    if scopes is not None:
        unknown = set(scopes) - GRANTABLE_SCOPES
        if unknown:
            raise ValueError(f"unknown scopes: {sorted(unknown)}")
        # Version 2 carries an explicit scope claim; version 1 stays unrestricted.
        payload["v"] = 2
        payload["scp"] = sorted(set(scopes))
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _sign(encoded)
    return f"{encoded}.{signature}"


def verify_user_token(token: str) -> AuthenticatedIdentity:
    try:
        encoded, supplied_signature = token.split(".", maxsplit=1)
        if not hmac.compare_digest(_sign(encoded), supplied_signature):
            raise ValueError("invalid signature")
        payload = json.loads(_decode(encoded))
        user_id = payload["sub"]
        expires_at = payload["exp"]
        if payload.get("v") not in (1, 2) or not isinstance(user_id, str):
            raise ValueError("invalid payload")
        if not isinstance(expires_at, int) or expires_at <= int(time.time()):
            raise ValueError("expired token")
        scopes = _parse_scopes(payload.get("scp"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return AuthenticatedIdentity(user_id=user_id, expires_at=expires_at, scopes=scopes)


def _parse_scopes(raw: object) -> frozenset[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("invalid scope claim")
    return frozenset(raw)


# Resolve either an operator bearer token or a revocable browser session.
async def get_authenticated_identity(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: str | None = Header(default=None),
) -> AuthenticatedIdentity | None:
    if not settings.AUTH_REQUIRED:
        return None
    if authorization and authorization.startswith("Bearer "):
        identity = verify_user_token(authorization[7:])
        # Bearer callers spend the same metered search as browser sessions.
        # This early return skipped the binding, so every bearer-driven turn
        # - which is every iMessage turn - searched unmetered: limits never
        # counted, never tripped, and never got communicated there.
        await _bind_search_identity(db, identity.user_id)
        return identity
    session_token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    validate_browser_origin(request)
    session = await AuthService(db).resolve_session(session_token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication session",
        )
    await _touch_last_seen(db, session.user_id)
    await _bind_search_identity(db, session.user_id)
    return AuthenticatedIdentity(
        user_id=session.user_id,
        expires_at=int(session.expires_at.timestamp()),
        scopes=None,
    )


IdentityDependency = Annotated[
    AuthenticatedIdentity | None,
    Depends(get_authenticated_identity),
]


# Attach the caller to any web search this request performs.
#
# The search provider is built once and cached process-wide, so it cannot hold a
# per-request account. Binding here means every route charges its own caller
# without each one having to remember to, including routes added later.
#
# A failure leaves the search unattributed and therefore unmetered, which is the
# right way to fail: metering is a cost control, not an authorization boundary,
# and a lookup problem must not stop somebody searching.
async def _bind_search_identity(db: AsyncSession, user_id: str) -> None:
    try:
        account = await db.scalar(
            select(UserAccount).where(UserAccount.user_id == user_id)
        )
        if account is None:
            return
        current_search_identity.set(
            SearchIdentity(
                user_id=user_id,
                is_operator=bool(account.is_admin),
                monthly_limit=account.search_monthly_limit,
                daily_limit=account.search_daily_limit,
            )
        )
    except Exception:
        return


# Record that an account was seen, at most once a minute.
#
# Written on every authenticated request, so it is throttled: a chat turn makes
# several calls and a to-the-minute answer is all the operator needs. A failure
# here must never fail the request — knowing when someone was last active is
# worth less than the request they were making.
async def _touch_last_seen(db: AsyncSession, user_id: str) -> None:
    now = datetime.now(UTC)
    try:
        await db.execute(
            update(UserAccount)
            .where(
                UserAccount.user_id == user_id,
                or_(
                    UserAccount.last_seen_at.is_(None),
                    UserAccount.last_seen_at < now - timedelta(minutes=1),
                ),
            )
            .values(last_seen_at=now)
        )
        await db.commit()
    except Exception:
        with suppress(Exception):
            await db.rollback()


def authorize_user(user_id: str, identity: IdentityDependency) -> None:
    if identity is not None and identity.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not own this resource",
        )


def authorize_scope(identity: AuthenticatedIdentity | None, required: str) -> None:
    # Auth disabled, or an unrestricted token: nothing to narrow.
    if identity is None:
        return
    if not _scope_satisfied(identity.scopes, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token is not authorized for scope '{required}'",
        )


def authorize_path_user(
    user_id: str,
    identity: IdentityDependency,
    request: Request,
) -> None:
    authorize_user(user_id, identity)
    # A read is a lesser privilege than a write, so a `memory:read` token can
    # browse memory without being able to change it.
    required = (
        SCOPE_MEMORY_READ
        if request.method in ("GET", "HEAD", "OPTIONS")
        else SCOPE_MEMORY_WRITE
    )
    authorize_scope(identity, required)


# Reject unsafe cookie-authenticated browser requests from untrusted origins.
def validate_browser_origin(request: Request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A trusted request origin is required",
        )
    trusted = {
        value.strip().rstrip("/")
        for value in settings.AUTH_TRUSTED_ORIGINS.split(",")
        if value.strip()
    }
    # Behind TLS termination the app sees plain HTTP, so the scheme it observes
    # is the proxy's hop rather than the browser's. Comparing that against an
    # Origin of "https://host" fails on the scheme alone and rejects a
    # same-origin request — which is exactly what a browser sends. Every
    # HTTPS ingress hits this: the gateway, a tunnel, anything in front.
    #
    # Only the scheme is taken from the header, and only to compare against the
    # request's own host. A forged value cannot introduce a new trusted origin,
    # because the host still has to match the one being served.
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded_proto.split(",")[0].strip() or request.url.scheme
    host = request.headers.get("host", "")
    same_origin = {f"{scheme}://{host}".rstrip("/"), f"https://{host}".rstrip("/")}
    if origin.rstrip("/") not in trusted | same_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not trusted",
        )


def _sign(encoded_payload: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(), encoded_payload.encode(), hashlib.sha256
    ).digest()
    return _encode(digest)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# Require that the caller is an administrator.
#
# Separated from ownership deliberately. `authorize_path_user` answers "is this
# your data"; this answers "may you act on the machine". A guest owns their chat,
# memory, and agents completely, and still may not invite people, enumerate other
# accounts, or change what this machine sends on the owner's behalf.
#
# Trusted-local mode has no identity, so it is treated as the operator — that
# mode is a single-user development option and already grants everything.
async def require_admin(
    identity: IdentityDependency,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if identity is None:
        if settings.AUTH_REQUIRED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required.",
            )
        return
    account = await db.scalar(
        select(UserAccount).where(UserAccount.user_id == identity.user_id)
    )
    if account is None or not account.is_admin:
        # Deliberately does not distinguish "not an admin" from "no such
        # account": the reply should not confirm who exists.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to the operator.",
        )


AdminDependency = Annotated[None, Depends(require_admin)]
