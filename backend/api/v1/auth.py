from contextlib import suppress
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from backend.config.settings import settings
from backend.core.auth import IdentityDependency, validate_browser_origin
from backend.core.auth_dependencies import LoginRateLimiterDependency
from backend.core.dependencies import DbDependency
from backend.models.auth import UserAccount
from backend.services.auth_service import (
    AuthService,
    CreatedSession,
    InvalidRegistrationInviteError,
    UsernameUnavailableError,
)
from backend.services.login_rate_limiter import (
    LoginRateLimiterUnavailableError,
    RedisLoginRateLimiter,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=1_024)

    # Remove accidental surrounding whitespace from the username only.
    @field_validator("username")
    @classmethod
    def normalize_username_input(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=12, max_length=1_024)
    invite_code: str = Field(min_length=16, max_length=512)

    # Remove accidental surrounding whitespace from public registration inputs.
    @field_validator("username", "invite_code")
    @classmethod
    def normalize_registration_input(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class SessionResponse(BaseModel):
    authentication_required: bool
    user_id: str
    expires_at: str | None
    # Whether this identity may administer the machine. The browser needs it to
    # decide what to show; the server never trusts it, and every admin route
    # re-derives the answer from the database.
    is_admin: bool = False


# Attach one opaque session using the deployment's browser-cookie policy.
def _set_session_cookie(response: Response, created: CreatedSession) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=created.token,
        max_age=settings.AUTH_SESSION_TTL_HOURS * 60 * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )


# Record a rejected public attempt or fail closed when shared protection is down.
async def _record_failed_attempt(
    rate_limiter: RedisLoginRateLimiter,
    limiter_identity: str,
    unavailable_detail: str,
) -> None:
    try:
        await rate_limiter.record_failure(limiter_identity)
    except LoginRateLimiterUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        ) from exc


# Exchange valid invite-only credentials for an HttpOnly browser session.
@router.post("/login", response_model=SessionResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbDependency,
    rate_limiter: LoginRateLimiterDependency,
) -> SessionResponse:
    validate_browser_origin(request)
    try:
        decision = await rate_limiter.before_attempt(body.username)
    except LoginRateLimiterUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login protection is temporarily unavailable",
        ) from exc
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    created = await AuthService(db).login(
        body.username,
        body.password,
        timedelta(hours=settings.AUTH_SESSION_TTL_HOURS),
    )
    if created is None:
        try:
            await rate_limiter.record_failure(body.username)
        except LoginRateLimiterUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Login protection is temporarily unavailable",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    try:
        await rate_limiter.clear_failures(body.username)
    except LoginRateLimiterUnavailableError as exc:
        await AuthService(db).revoke_session(created.token)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login protection is temporarily unavailable",
        ) from exc
    _set_session_cookie(response, created)
    account = await db.scalar(
        select(UserAccount).where(UserAccount.user_id == created.user_id)
    )
    return SessionResponse(
        authentication_required=settings.AUTH_REQUIRED,
        user_id=created.user_id,
        expires_at=created.expires_at.isoformat(),
        is_admin=bool(account and account.is_admin),
    )


# Create one invited profile and sign it in without accepting a client owner ID.
@router.post("/register", response_model=SessionResponse)
async def register(
    body: RegistrationRequest,
    request: Request,
    response: Response,
    db: DbDependency,
    rate_limiter: LoginRateLimiterDependency,
) -> SessionResponse:
    validate_browser_origin(request)
    limiter_identity = f"register:{body.username}"
    try:
        decision = await rate_limiter.before_attempt(limiter_identity)
    except LoginRateLimiterUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration protection is temporarily unavailable",
        ) from exc
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    try:
        created = await AuthService(db).register(
            body.username,
            body.password,
            body.invite_code,
            timedelta(hours=settings.AUTH_SESSION_TTL_HOURS),
        )
    except InvalidRegistrationInviteError as exc:
        await _record_failed_attempt(
            rate_limiter,
            limiter_identity,
            "Registration protection is temporarily unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite code is invalid, expired, or already used.",
        ) from exc
    except UsernameUnavailableError as exc:
        await _record_failed_attempt(
            rate_limiter,
            limiter_identity,
            "Registration protection is temporarily unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is unavailable.",
        ) from exc
    except ValueError as exc:
        await _record_failed_attempt(
            rate_limiter,
            limiter_identity,
            "Registration protection is temporarily unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    with suppress(LoginRateLimiterUnavailableError):
        await rate_limiter.clear_failures(limiter_identity)
    _set_session_cookie(response, created)
    return SessionResponse(
        authentication_required=settings.AUTH_REQUIRED,
        user_id=created.user_id,
        expires_at=created.expires_at.isoformat(),
        # An invited account is a guest. Stated rather than defaulted, so
        # the answer cannot change if the field default ever does.
        is_admin=False,
    )


# Return the server-derived identity that owns every subsequent UI request.
@router.get("/session", response_model=SessionResponse)
async def current_session(
    identity: IdentityDependency, db: DbDependency
) -> SessionResponse:
    if identity is None:
        # Trusted-local mode has no account, and is already a single-user
        # development option, so it sees the operator surface.
        return SessionResponse(
            authentication_required=False,
            user_id=settings.AUTH_LOCAL_USER_ID,
            expires_at=None,
            is_admin=True,
        )
    account = await db.scalar(
        select(UserAccount).where(UserAccount.user_id == identity.user_id)
    )
    return SessionResponse(
        authentication_required=True,
        user_id=identity.user_id,
        expires_at=datetime.fromtimestamp(identity.expires_at, tz=UTC).isoformat(),
        is_admin=bool(account and account.is_admin),
    )


# Revoke the current browser session and remove its cookie from the response.
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: DbDependency,
) -> None:
    validate_browser_origin(request)
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if token:
        await AuthService(db).revoke_session(token)
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
