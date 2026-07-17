import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from backend.config.settings import settings


@dataclass(frozen=True)
class AuthenticatedIdentity:
    user_id: str
    expires_at: int


def issue_user_token(user_id: str, ttl_seconds: int = 3_600) -> str:
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + ttl_seconds,
        "v": 1,
    }
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
        if payload.get("v") != 1 or not isinstance(user_id, str):
            raise ValueError("invalid payload")
        if not isinstance(expires_at, int) or expires_at <= int(time.time()):
            raise ValueError("expired token")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return AuthenticatedIdentity(user_id=user_id, expires_at=expires_at)


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


def authorize_path_user(
    user_id: str,
    identity: IdentityDependency,
) -> None:
    authorize_user(user_id, identity)


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
