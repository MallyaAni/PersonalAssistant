import asyncio
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.services.login_rate_limiter import (
    LoginRateLimiterUnavailableError,
    RedisLoginRateLimiter,
)


class _FakeRedis:
    # Keep deterministic counters and TTLs for limiter policy tests.
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False

    # Emulate the limiter's atomic increment-and-expire Lua result.
    async def eval(
        self, script: str, numkeys: int, key: str, seconds: int
    ) -> list[int]:
        if self.fail:
            raise RedisError("unavailable")
        self.values[key] = self.values.get(key, 0) + 1
        self.ttls.setdefault(key, seconds)
        return [self.values[key], self.ttls[key]]

    # Read one counter using the same nullable shape as Redis.
    async def get(self, key: str) -> str | None:
        value = self.values.get(key)
        return str(value) if value is not None else None

    # Return the remaining deterministic fixed-window lifetime.
    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    # Clear one successful login's failure counter and TTL.
    async def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)


# Build a limiter over the deterministic Redis-shaped test double.
def _limiter(redis: _FakeRedis) -> RedisLoginRateLimiter:
    return RedisLoginRateLimiter(
        cast(Redis, cast(Any, redis)),
        max_failures=2,
        failure_window_seconds=30,
        global_max_attempts=10,
        global_window_seconds=10,
        key_prefix="test:auth",
    )


# Verify invalid credentials block one hashed login until its window expires.
def test_failed_login_window_blocks_and_success_clears() -> None:
    async def scenario() -> None:
        redis = _FakeRedis()
        limiter = _limiter(redis)
        assert (await limiter.before_attempt("Friend.User")).allowed
        await limiter.record_failure("Friend.User")
        assert (await limiter.before_attempt("friend.user")).allowed
        await limiter.record_failure("friend.user")
        denied = await limiter.before_attempt("FRIEND.USER")
        assert not denied.allowed
        assert denied.retry_after_seconds == 30
        assert all("friend.user" not in key for key in redis.values)
        await limiter.clear_failures("friend.user")
        assert (await limiter.before_attempt("friend.user")).allowed

    asyncio.run(scenario())


# Verify Redis failure closes login instead of silently dropping protection.
def test_unavailable_redis_fails_closed() -> None:
    async def scenario() -> None:
        redis = _FakeRedis()
        redis.fail = True
        limiter = _limiter(redis)
        try:
            await limiter.before_attempt("friend.user")
        except LoginRateLimiterUnavailableError:
            return
        raise AssertionError("login limiter did not fail closed")

    asyncio.run(scenario())
