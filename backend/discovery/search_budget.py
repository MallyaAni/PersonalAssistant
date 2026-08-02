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

# A month is the billing period, but it is the wrong unit to protect. One account
# in a loop on the first of the month can spend a whole monthly allowance in an
# afternoon, and the month's ceiling only notices once it is gone. A daily bound
# caps the blast radius of any single bad day and refills tomorrow, so a mistake
# costs a day rather than a month.
GUEST_DAILY_QUERIES = 10
OPERATOR_DAILY_QUERIES = 40

# Tavily's free plan. This is the number that actually runs out, and every
# per-account limit above is a share of it rather than an independent budget.
FREE_TIER_MONTHLY_CREDITS = 1_000

# Counters expire on their own so nothing has to sweep them up.
_TTL_SECONDS = 40 * 24 * 60 * 60
_DAILY_TTL_SECONDS = 3 * 24 * 60 * 60


class SearchBudget:
    """Count metered search queries per account per calendar month."""

    def __init__(
        self,
        redis_url: str,
        enabled: bool = True,
        monthly_credits: int = FREE_TIER_MONTHLY_CREDITS,
    ) -> None:
        self.enabled = enabled
        # The purchased ceiling, not a preference. Per-account limits are shares
        # of this; it is what actually runs out.
        self.monthly_credits = monthly_credits
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(user_id: str, now: datetime) -> str:
        return f"anios:search:{user_id}:{now.strftime('%Y-%m')}"

    @staticmethod
    def _daily_key(user_id: str, now: datetime) -> str:
        return f"anios:search:{user_id}:day:{now.strftime('%Y-%m-%d')}"

    # The shared pool every account spends from — the actual purchased ceiling.
    #
    # Per-account limits alone cannot protect this. They bound each caller but
    # say nothing about the sum, so enough accounts within their own limits
    # still drain the key. This is the only window that is not per-user.
    @staticmethod
    def _pool_key(now: datetime) -> str:
        return f"anios:search:_pool:{now.strftime('%Y-%m')}"

    # Credits left in the shared monthly pool.
    async def pool_remaining(self, now: datetime | None = None) -> int:
        if not self.enabled:
            return self.monthly_credits
        moment = now or datetime.now(UTC)
        try:
            spent = int(await self.redis.get(self._pool_key(moment)) or 0)
        except Exception:
            return self.monthly_credits
        return max(self.monthly_credits - spent, 0)

    # What all accounts together may still spend today.
    #
    # No day may promise more than the month has left, so this is the pool's
    # remainder rather than a separate number that could drift above it.
    async def shared_daily_ceiling(self, now: datetime | None = None) -> int:
        return await self.pool_remaining(now)

    # Align the pool with what the provider says the key has actually spent.
    #
    # Only ever raises the local count. The provider is authoritative about
    # spending we did not do — another tool on the same key, or a plan that
    # counts differently — but a lower number can also mean a stale or partial
    # report, and trusting that would hand back credits that are really gone.
    # Erring toward the ceiling is the safe direction for a cost control.
    async def reconcile(self, reported_spent: int, now: datetime | None = None) -> int:
        if not self.enabled or reported_spent < 0:
            return await self.pool_remaining(now)
        moment = now or datetime.now(UTC)
        key = self._pool_key(moment)
        try:
            local = int(await self.redis.get(key) or 0)
            if reported_spent > local:
                await self.redis.set(key, reported_spent)
                await self.redis.expire(key, _TTL_SECONDS)
        except Exception:
            # Reconciliation is an improvement, not a requirement. Failing here
            # leaves the local count in charge, which is what it was anyway.
            return await self.pool_remaining(moment)
        return max(self.monthly_credits - max(local, reported_spent), 0)

    # Spend against the shared pool, and what it has already cost this month.
    async def pool_status(self, now: datetime | None = None) -> dict[str, int]:
        remaining = await self.pool_remaining(now)
        return {
            "monthly_credits": self.monthly_credits,
            "remaining": remaining,
            "spent": max(self.monthly_credits - remaining, 0),
        }

    @staticmethod
    def allowance(is_operator: bool, override: int | None = None) -> int:
        # An operator-set override replaces the default entirely, including
        # zero — which is how an account is stopped from searching without
        # removing it.
        if override is not None:
            return override
        return OPERATOR_MONTHLY_QUERIES if is_operator else GUEST_MONTHLY_QUERIES

    @staticmethod
    def daily_allowance(is_operator: bool, override: int | None = None) -> int:
        if override is not None:
            return override
        return OPERATOR_DAILY_QUERIES if is_operator else GUEST_DAILY_QUERIES

    # How many queries this account may still spend this month.
    async def remaining(
        self,
        user_id: str,
        is_operator: bool,
        now: datetime | None = None,
        override: int | None = None,
    ) -> int:
        allowance = self.allowance(is_operator, override)
        if not self.enabled:
            return allowance
        moment = now or datetime.now(UTC)
        try:
            spent = int(await self.redis.get(self._key(user_id, moment)) or 0)
        except Exception:
            return allowance
        return max(allowance - spent, 0)

    # How many queries this account may still spend today.
    async def remaining_today(
        self,
        user_id: str,
        is_operator: bool,
        now: datetime | None = None,
        override: int | None = None,
    ) -> int:
        allowance = self.daily_allowance(is_operator, override)
        if not self.enabled:
            return allowance
        moment = now or datetime.now(UTC)
        try:
            spent = int(await self.redis.get(self._daily_key(user_id, moment)) or 0)
        except Exception:
            return allowance
        return max(allowance - spent, 0)

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
        override: int | None = None,
        daily_override: int | None = None,
    ) -> int:
        if not self.enabled or wanted <= 0:
            return max(wanted, 0)
        moment = now or datetime.now(UTC)

        # Ordered loosest-last. The per-account day is checked first because it
        # is the tightest bound and the one that refills, so a rejection there
        # costs the caller the least. The shared pool is checked last: it is the
        # real ceiling, and reaching it stops everybody, so nothing should be
        # charged against it that a cheaper bound would have refused anyway.
        windows = (
            (
                self._daily_key(user_id, moment),
                self.daily_allowance(is_operator, daily_override),
                _DAILY_TTL_SECONDS,
            ),
            (
                self._key(user_id, moment),
                self.allowance(is_operator, override),
                _TTL_SECONDS,
            ),
            (self._pool_key(moment), self.monthly_credits, _TTL_SECONDS),
        )

        granted = wanted
        charged: list[tuple[str, int]] = []
        for key, allowance, ttl in windows:
            took = await self._take(key, granted, allowance, ttl)
            charged.append((key, took))
            granted = min(granted, took)
            if granted <= 0:
                break

        # A later window refusing must not leave an earlier one overcharged.
        # Without this a query the shared pool blocks would still burn the
        # caller's day and month, so exhausting the pool would quietly consume
        # everyone's personal allowance too.
        for key, took in charged:
            if took > granted:
                with suppress(Exception):
                    await self.redis.decrby(key, took - granted)
        return granted

    # Spend against one window and report how much of `wanted` it allowed.
    async def _take(self, key: str, wanted: int, allowance: int, ttl: int) -> int:
        try:
            spent = int(await self.redis.incrby(key, wanted))
            await self.redis.expire(key, ttl)
        except Exception:
            # A rate limiter, not an authorization boundary: a restarted cache
            # must not take the feature down for everyone.
            return wanted

        overshoot = spent - allowance
        if overshoot <= 0:
            return wanted
        granted = max(wanted - overshoot, 0)
        # Give back what was not granted so the window's count stays honest. A
        # failure here only overstates the spend, which errs toward the ceiling.
        with suppress(Exception):
            await self.redis.decrby(key, wanted - granted)
        return granted
