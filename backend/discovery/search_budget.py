"""Bound how much of the operator's metered search each account may spend.

Search is the one component of this system with a hard monthly ceiling, and the
key belongs to the operator. Every guest's sweep spends from it. A guest with
several interests spends several queries a week without doing anything wrong, and
the failure is silent and late: Scout simply stops finding things, for everyone,
and nobody can tell why.

`RequestBudget` already bounds a single run. This bounds an *account across a
month*, which is the axis that multi-user introduced.

Two deliberate choices:

- **the operator is not exempt, but has a larger allowance.** An exempt operator
  makes the shared ceiling invisible again, which is the problem being solved;
- **an unavailable counter permits the sweep.** Redis is a rate limiter here, not
  an authorization boundary. Failing closed would take the whole feature down for
  everyone because a cache restarted, and overspending a free tier is a smaller
  harm than that.
"""

from contextlib import suppress
from datetime import UTC, datetime

from redis.asyncio import Redis

# A weekly sweep spends a handful of queries, so these are generous for ordinary
# use and still catch a runaway configuration.
GUEST_MONTHLY_QUERIES = 60
OPERATOR_MONTHLY_QUERIES = 400

# Counters expire on their own so nothing has to sweep them up.
_TTL_SECONDS = 40 * 24 * 60 * 60


class SearchBudget:
    """Count metered search queries per account per calendar month."""

    def __init__(self, redis_url: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(user_id: str, now: datetime) -> str:
        return f"anios:search:{user_id}:{now.strftime('%Y-%m')}"

    @staticmethod
    def allowance(is_operator: bool) -> int:
        return OPERATOR_MONTHLY_QUERIES if is_operator else GUEST_MONTHLY_QUERIES

    # How many queries this account may still spend this month.
    async def remaining(
        self, user_id: str, is_operator: bool, now: datetime | None = None
    ) -> int:
        if not self.enabled:
            return self.allowance(is_operator)
        moment = now or datetime.now(UTC)
        try:
            spent = int(await self.redis.get(self._key(user_id, moment)) or 0)
        except Exception:
            return self.allowance(is_operator)
        return max(self.allowance(is_operator) - spent, 0)

    # Reserve up to `wanted` queries and report how many were actually granted.
    #
    # Returns a number rather than a yes/no so a sweep can proceed with a smaller
    # budget instead of being refused outright — finding less is better than
    # finding nothing.
    async def reserve(
        self,
        user_id: str,
        is_operator: bool,
        wanted: int,
        now: datetime | None = None,
    ) -> int:
        if not self.enabled or wanted <= 0:
            return max(wanted, 0)
        moment = now or datetime.now(UTC)
        key = self._key(user_id, moment)
        try:
            spent = int(await self.redis.incrby(key, wanted))
            await self.redis.expire(key, _TTL_SECONDS)
        except Exception:
            # A rate limiter, not an authorization boundary: a restarted cache
            # must not take the feature down for everyone.
            return wanted

        allowance = self.allowance(is_operator)
        overshoot = spent - allowance
        if overshoot <= 0:
            return wanted
        granted = max(wanted - overshoot, 0)
        # Give back what was not granted so the month's count stays honest. A
        # failure here only overstates the spend, which errs toward the ceiling.
        with suppress(Exception):
            await self.redis.decrby(key, wanted - granted)
        return granted
