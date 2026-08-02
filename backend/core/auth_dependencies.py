from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from backend.config.settings import settings
from backend.services.login_rate_limiter import RedisLoginRateLimiter


# Reuse one Redis pool so every API process enforces the same login windows.
@lru_cache(maxsize=1)
def get_login_rate_limiter() -> RedisLoginRateLimiter:
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return RedisLoginRateLimiter(
        redis,
        max_failures=settings.AUTH_LOGIN_MAX_FAILURES,
        failure_window_seconds=settings.AUTH_LOGIN_FAILURE_WINDOW_SECONDS,
        global_max_attempts=settings.AUTH_LOGIN_GLOBAL_MAX_ATTEMPTS,
        global_window_seconds=settings.AUTH_LOGIN_GLOBAL_WINDOW_SECONDS,
    )


LoginRateLimiterDependency = Annotated[
    RedisLoginRateLimiter,
    Depends(get_login_rate_limiter),
]
