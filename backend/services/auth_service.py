import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.auth import RegistrationInvite, UserAccount, UserSession

_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,49}$")
_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)
# This public dummy value equalizes the expensive verification path for an
# unknown username without granting access to any account.
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "O0d1YXV0aC1kdW1teS1zYWx0IQ$"
    "iBgckL2m3cRwDByrAHJXw4Ab0Z4dMn+XG0eu8Z4/1lw"
)


@dataclass(frozen=True)
class CreatedSession:
    user_id: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class CreatedRegistrationInvite:
    token: str
    expires_at: datetime


class InvalidRegistrationInviteError(ValueError):
    pass


class UsernameUnavailableError(ValueError):
    pass


# Normalize either login or owner identifiers under one bounded syntax.
def normalize_user_id(user_id: str) -> str:
    normalized = user_id.strip().casefold()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "username must use 1-50 lowercase letters, numbers, dots, "
            "dashes, or underscores"
        )
    return normalized


# Hash a password with the configured Argon2id cost before persistence.
def hash_password(password: str) -> str:
    _validate_password(password)
    return _PASSWORD_HASHER.hash(password)


# Check a password without exposing whether the account exists.
def verify_password(password_hash: str | None, password: str) -> bool:
    candidate_hash = password_hash or _DUMMY_PASSWORD_HASH
    try:
        return cast(bool, _PASSWORD_HASHER.verify(candidate_hash, password))
    except (InvalidHashError, VerifyMismatchError):
        return False


# Enforce a bounded password contract before expensive hashing work.
def _validate_password(password: str) -> None:
    if not 12 <= len(password) <= 1_024:
        raise ValueError("password must contain 12 to 1024 characters")


# Store only a one-way digest of each opaque session token.
def digest_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Store registration invitations with the same one-way token protection as sessions.
def digest_registration_invite(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    # Bind authentication operations to one database transaction scope.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Create one invite-only account without changing any existing owned data.
    # Create an account from a hash computed earlier, without ever seeing the
    # password.
    #
    # An access request hashes on arrival, so approval has a hash and no
    # plaintext. Re-hashing is impossible and inventing a placeholder password
    # would be worse than either, so the hash moves across unchanged.
    async def create_account_with_hash(
        self,
        user_id: str,
        password_hash: str,
        username: str | None = None,
    ) -> UserAccount:
        normalized = normalize_user_id(user_id)
        normalized_username = normalize_user_id(username or user_id)
        if await self.session.get(UserAccount, normalized) is not None:
            raise ValueError("account already exists")
        existing_username = await self.session.scalar(
            select(UserAccount.user_id).where(
                UserAccount.username == normalized_username
            )
        )
        if existing_username is not None:
            raise ValueError("username already exists")
        account = UserAccount(
            user_id=normalized,
            username=normalized_username,
            password_hash=password_hash,
            is_active=True,
        )
        self.session.add(account)
        await self.session.flush()
        return account

    async def create_account(
        self,
        user_id: str,
        password: str,
        username: str | None = None,
    ) -> UserAccount:
        normalized = normalize_user_id(user_id)
        normalized_username = normalize_user_id(username or user_id)
        if await self.session.get(UserAccount, normalized) is not None:
            raise ValueError("account already exists")
        existing_username = await self.session.scalar(
            select(UserAccount.user_id).where(
                UserAccount.username == normalized_username
            )
        )
        if existing_username is not None:
            raise ValueError("username already exists")
        account = UserAccount(
            user_id=normalized,
            username=normalized_username,
            password_hash=hash_password(password),
            is_active=True,
        )
        self.session.add(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    # Create one expiring registration code while storing only its digest.
    async def create_registration_invite(
        self,
        ttl: timedelta,
    ) -> CreatedRegistrationInvite:
        if ttl <= timedelta(0):
            raise ValueError("invite lifetime must be positive")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + ttl
        self.session.add(
            RegistrationInvite(
                token_digest=digest_registration_invite(token),
                expires_at=expires_at,
            )
        )
        await self.session.commit()
        return CreatedRegistrationInvite(token=token, expires_at=expires_at)

    # Consume one valid invitation and create its account and first session atomically.
    async def register(
        self,
        username: str,
        password: str,
        invite_token: str,
        session_ttl: timedelta,
    ) -> CreatedSession:
        normalized = normalize_user_id(username)
        password_hash = hash_password(password)
        now = datetime.now(UTC)
        invite = await self.session.scalar(
            select(RegistrationInvite)
            .where(
                RegistrationInvite.token_digest
                == digest_registration_invite(invite_token),
                RegistrationInvite.consumed_at.is_(None),
                RegistrationInvite.expires_at > now,
            )
            .with_for_update()
        )
        if invite is None:
            raise InvalidRegistrationInviteError("invite is invalid or expired")
        existing = await self.session.scalar(
            select(UserAccount.user_id).where(
                (UserAccount.user_id == normalized)
                | (UserAccount.username == normalized)
            )
        )
        if existing is not None:
            raise UsernameUnavailableError("username is unavailable")
        token = secrets.token_urlsafe(32)
        expires_at = now + session_ttl
        account = UserAccount(
            user_id=normalized,
            username=normalized,
            password_hash=password_hash,
            is_active=True,
        )
        self.session.add(account)
        try:
            await self.session.flush()
            invite.consumed_at = now
            invite.consumed_by_user_id = normalized
            self.session.add(
                UserSession(
                    user_id=normalized,
                    token_digest=digest_session_token(token),
                    expires_at=expires_at,
                )
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise UsernameUnavailableError("username is unavailable") from exc
        return CreatedSession(normalized, token, expires_at)

    # Validate credentials and issue one revocable opaque browser session.
    async def login(
        self,
        username: str,
        password: str,
        ttl: timedelta,
    ) -> CreatedSession | None:
        try:
            normalized = normalize_user_id(username)
        except ValueError:
            normalized = ""
        account = (
            await self.session.scalar(
                select(UserAccount).where(UserAccount.username == normalized)
            )
            if normalized
            else None
        )
        valid_password = verify_password(
            account.password_hash if account is not None else None,
            password,
        )
        if account is None or not account.is_active or not valid_password:
            return None
        if _PASSWORD_HASHER.check_needs_rehash(account.password_hash):
            account.password_hash = hash_password(password)
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + ttl
        self.session.add(
            UserSession(
                user_id=account.user_id,
                token_digest=digest_session_token(token),
                expires_at=expires_at,
            )
        )
        await self.session.commit()
        return CreatedSession(account.user_id, token, expires_at)

    # Resolve an unexpired, unrevoked session to its active account owner.
    async def resolve_session(self, token: str) -> UserSession | None:
        result = await self.session.execute(
            select(UserSession)
            .join(UserAccount, UserAccount.user_id == UserSession.user_id)
            .where(
                UserSession.token_digest == digest_session_token(token),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(UTC),
                UserAccount.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    # Revoke exactly the supplied browser session without touching user data.
    async def revoke_session(self, token: str) -> bool:
        result = await self.session.execute(
            select(UserSession).where(
                UserSession.token_digest == digest_session_token(token),
                UserSession.revoked_at.is_(None),
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False
        session.revoked_at = datetime.now(UTC)
        await self.session.commit()
        return True

    # Replace an account password and revoke every prior browser session.
    async def set_password(self, user_id: str, password: str) -> None:
        normalized = normalize_user_id(user_id)
        account = await self.session.get(UserAccount, normalized)
        if account is None:
            raise ValueError("account does not exist")
        account.password_hash = hash_password(password)
        await self.session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == normalized,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.commit()

    # Enable or disable login and revoke sessions when access is disabled.
    async def set_active(self, user_id: str, active: bool) -> None:
        normalized = normalize_user_id(user_id)
        account = await self.session.get(UserAccount, normalized)
        if account is None:
            raise ValueError("account does not exist")
        account.is_active = active
        if not active:
            await self.session.execute(
                update(UserSession)
                .where(
                    UserSession.user_id == normalized,
                    UserSession.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
        await self.session.commit()
