import secrets
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from backend.config.settings import settings
from backend.core.auth import IdentityDependency, validate_browser_origin
from backend.core.auth_dependencies import LoginRateLimiterDependency
from backend.core.dependencies import DbDependency
from backend.core.phone import matching_key
from backend.discovery.types import label_digest
from backend.models.auth import AccessRequest, UserAccount
from backend.models.discovery_subscriber import DiscoverySubscriber
from backend.services.auth_service import (
    AuthService,
    CreatedSession,
    InvalidRegistrationInviteError,
    UsernameUnavailableError,
    digest_registration_invite,
    hash_password,
    normalize_user_id,
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


class AccessRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=80)

    # Cleaned at the door, not trusted deeper in. This name is placed into the
    # welcome message's prompt, and the fix for "a name might carry an
    # instruction" is structural per AGENTS.md: collapse whitespace to single
    # spaces, drop control characters and newlines, and cap the length, so no
    # amount of crafted input arrives as anything but a short line of text.
    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        collapsed = " ".join(
            "".join(ch for ch in value if ch == " " or ch.isprintable()).split()
        )
        cleaned = collapsed[:60].strip()
        if not cleaned:
            raise ValueError("A name is required.")
        return cleaned
    # Required, and not for contactability. The iMessage bridge decides who
    # is talking by matching a sender against the subscriber allowlist, so
    # this number is what makes an approved person reachable at all.
    # Collected here so approval is one decision rather than two, and the
    # operator can see the number they are admitting.
    phone: str = Field(min_length=1, max_length=32)
    contact: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)
    # Chosen here so approval creates the account outright. Same rules as
    # registration, checked now rather than after the operator has agreed —
    # being told the username is taken should not wait on a human.
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=12, max_length=1_024)

    # E.164 or nothing. A bare ten-digit number is a valid local number in
    # several countries at once and nothing in the string says which, so
    # the country code is what lets one allowlist serve people in
    # different places.
    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str) -> str:
        from backend.core.phone import InvalidPhoneNumber, to_e164

        try:
            return to_e164(value)
        except InvalidPhoneNumber as bad:
            raise ValueError(str(bad)) from bad


# Ask the operator for an account.
#
# Unauthenticated by necessity — the point is that the asker has no account yet —
# and therefore rate-limited on the same shared counter as login, because this
# sits on a public URL. Nothing here grants anything: it records a request and
# hands back a token the asker keeps. Approval makes that same token usable,
# which avoids having to send a code back over some other channel.
@router.post("/request-access", status_code=status.HTTP_201_CREATED)
async def request_access(
    request: Request,
    body: AccessRequestBody,
    db: DbDependency,
    rate_limiter: LoginRateLimiterDependency,
) -> dict[str, object]:
    fingerprint = (
        f"access-request:{request.client.host if request.client else 'unknown'}"
    )
    try:
        allowed = await rate_limiter.before_attempt(fingerprint)
    except LoginRateLimiterUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Requests are temporarily unavailable",
        ) from exc
    if not allowed.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(int(allowed.retry_after_seconds))},
        )

    desired = normalize_user_id(body.username)
    taken = await db.scalar(
        select(UserAccount.user_id).where(UserAccount.username == desired)
    )
    pending_claim = await db.scalar(
        select(AccessRequest.id).where(
            AccessRequest.desired_username == desired,
            AccessRequest.status == "pending",
        )
    )
    if taken is not None or pending_claim is not None:
        # Said plainly. This is a name collision on a public sign-up form, not a
        # credential check, so there is nothing here worth being vague about.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken. Pick another.",
        )

    # A phone number decides identity to the bridge, so it must belong to one
    # account only. Without this check the public form lets anyone submit
    # someone else's number: on approval that number would be allowlisted and
    # its owner's inbound texts routed into the claimant's account. Refuse a
    # number already spoken for by a pending/approved request or an existing
    # subscriber. Re-checked at approval, where the race between the two lands.
    phone_key = label_digest(matching_key(body.phone))
    phone_claimed = await db.scalar(
        select(AccessRequest.id).where(
            AccessRequest.phone_digest == phone_key,
            AccessRequest.status.in_(("pending", "approved")),
        )
    )
    subscriber_claimed = await db.scalar(
        select(DiscoverySubscriber.id).where(
            DiscoverySubscriber.channel == "imessage",
            DiscoverySubscriber.address_digest == phone_key,
        )
    )
    if phone_claimed is not None or subscriber_claimed is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That phone number is already registered.",
        )

    token = secrets.token_urlsafe(32)
    db.add(
        AccessRequest(
            token_digest=digest_registration_invite(token),
            display_name=body.display_name.strip(),
            contact=(body.contact or "").strip() or None,
            phone=body.phone,
            phone_digest=label_digest(matching_key(body.phone)),
            reason=(body.reason or "").strip() or None,
            desired_username=desired,
            # Hashed on arrival; the plaintext is never stored and never needed
            # again, since approval moves this hash across unchanged.
            password_hash=hash_password(body.password),
        )
    )
    await db.commit()
    # Deliberately not recorded as a failure. `before_attempt` already applies
    # the global attempt window, which is what bounds abuse here; counting a
    # successful request as a failure would mean an honest asker locks out the
    # next one, and it misuses a counter that means something else.
    return {
        # Shown once. Keep it: when the operator approves, this is what lets the
        # asker register, with no code needing to travel back to them.
        "request_token": token,
        "status": "pending",
    }


# Report whether a request has been decided, so the asker can come back and see.
@router.get("/request-access/{request_token}")
async def check_access_request(
    request_token: str,
    db: DbDependency,
) -> dict[str, object]:
    row = await db.scalar(
        select(AccessRequest).where(
            AccessRequest.token_digest == digest_registration_invite(request_token)
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found."
        )
    return {"status": row.status, "display_name": row.display_name}
