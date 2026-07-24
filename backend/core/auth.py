import base64
import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from backend.config.settings import settings

# Least-privilege scopes. A token may be restricted to a subset so a leaked or
# narrowly-issued token cannot reach the whole account. A scope with a `parent`
# below grants its children too, so `memory` implies read and write while
# `memory:read` grants only reads.
SCOPE_CHAT = "chat"
SCOPE_MEMORY_READ = "memory:read"
SCOPE_MEMORY_WRITE = "memory:write"
SCOPE_TOOLS = "tools:invoke"
SCOPE_VISION = "vision"

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


def get_authenticated_identity(
    authorization: str | None = Header(default=None),
) -> AuthenticatedIdentity | None:
    if not settings.AUTH_REQUIRED:
        return None
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_user_token(authorization[7:])


IdentityDependency = Annotated[
    AuthenticatedIdentity | None,
    Depends(get_authenticated_identity),
]


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
