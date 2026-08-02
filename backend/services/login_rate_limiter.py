import hashlib
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

_INCREMENT_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class LoginRateLimiterUnavailableError(RuntimeError):
    """Raised when login protection cannot safely consult its shared state."""


@dataclass(frozen=True)
class LoginRateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class RedisLoginRateLimiter:
    # Bind one limiter to shared Redis policy without retaining raw usernames.
    def __init__(
        self,
        redis: Redis,
        *,
        max_failures: int,
        failure_window_seconds: int,
        global_max_attempts: int,
        global_window_seconds: int,
        key_prefix: str = "anios:auth:login",
    ) -> None:
        self.redis = redis
        self.max_failures = max_failures
        self.failure_window_seconds = failure_window_seconds
        self.global_max_attempts = global_max_attempts
        self.global_window_seconds = global_window_seconds
        self.key_prefix = key_prefix

    # Admit one bounded login attempt or return the time until retry is safe.
    async def before_attempt(self, username: str) -> LoginRateLimitDecision:
        try:
            global_count, global_ttl = await self._increment_window(
                f"{self.key_prefix}:global",
                self.global_window_seconds,
            )
            if global_count > self.global_max_attempts:
                return LoginRateLimitDecision(False, max(global_ttl, 1))

            failure_key = self._failure_key(username)
            failures = int(await self.redis.get(failure_key) or 0)
            if failures >= self.max_failures:
                ttl = int(await self.redis.ttl(failure_key))
                return LoginRateLimitDecision(False, max(ttl, 1))
            return LoginRateLimitDecision(True)
        except RedisError as exc:
            raise LoginRateLimiterUnavailableError from exc

    # Count one invalid credential result inside its fixed failure window.
    async def record_failure(self, username: str) -> None:
        try:
            await self._increment_window(
                self._failure_key(username),
                self.failure_window_seconds,
            )
        except RedisError as exc:
            raise LoginRateLimiterUnavailableError from exc

    # Let a successful credential check clear only that login's failures.
    async def clear_failures(self, username: str) -> None:
        try:
            await self.redis.delete(self._failure_key(username))
        except RedisError as exc:
            raise LoginRateLimiterUnavailableError from exc

    # Increment one shared fixed-window counter atomically and return its TTL.
    async def _increment_window(self, key: str, seconds: int) -> tuple[int, int]:
        result = await self.redis.eval(
            _INCREMENT_WINDOW_SCRIPT,
            1,
            key,
            seconds,
        )
        if not isinstance(result, list) or len(result) != 2:
            raise RedisError("unexpected login limiter response")
        return int(result[0]), int(result[1])

    # Hash normalized login text so Redis diagnostics never expose usernames.
    def _failure_key(self, username: str) -> str:
        normalized = username.strip().casefold().encode("utf-8")
        digest = hashlib.sha256(normalized).hexdigest()
        return f"{self.key_prefix}:failure:{digest}"
