"""Meter interactive web search per account, the way the sweep already is.

Ambient discovery has been budgeted since it was built, but that only ever
covered the *scheduled* sweep. Search asked for in conversation went straight to
the provider with no account attached and no counter touched, so the one metered
external dependency in this system was bounded on its quiet path and unbounded
on its loud one. A single afternoon of chatting could exhaust the key that every
guest's discovery depends on.

Identity arrives through a context variable rather than a constructor argument
because the provider is built once and cached process-wide, while the account is
per request. Threading it through every construction site would have meant
rewiring five call sites and would still have missed the ones that build the
provider outside a request.

Two deliberate choices carried over from `SearchBudget`:

- **exhaustion is visible.** A silently empty result set reads as "the internet
  had nothing", which is the failure that makes a quota impossible to diagnose.
  `SearchBudgetExceededError` says which window ran out and when it refills.
- **an unavailable counter permits the search.** Redis is a rate limiter here,
  not an authorization boundary.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.core.interfaces import SearchProvider
from backend.discovery.search_budget import SearchBudget
from backend.core.harness_identity import is_harness_id
from backend.search.types import SearchResults, frugal_search


@dataclass(frozen=True, slots=True)
class SearchIdentity:
    """Who is spending, and the operator's overrides for them."""

    user_id: str
    is_operator: bool = False
    monthly_limit: int | None = None
    daily_limit: int | None = None


# Unset outside a request. An unattributed search cannot be charged to anybody,
# so it is left unmetered rather than charged to a guessed account.
current_search_identity: ContextVar[SearchIdentity | None] = ContextVar(
    "current_search_identity", default=None
)


class SearchProviderQuotaError(Exception):
    """The provider itself refused: the key has spent its plan for the period."""


@dataclass(frozen=True, slots=True)
class SearchLimit:
    """Which allowance is used up, and when it comes back.

    `window` is "today" or "this month"; `shared` says whether it is the
    pool every account spends from (the key's own ceiling) rather than this
    account's own allowance - the reply words the two differently.
    """

    window: str
    resets_at: datetime
    shared: bool = False


# Whether this request's turn has already charged the account's own daily and
# monthly allowances. A question is answered by up to three search rounds;
# charged per round, a guest's ten queries a day were three questions
# (2026-08-26, found by sweep_journeys). The pool and the provider counters
# stay per call - they meter what the key actually spends.
account_charged_this_turn: ContextVar[bool] = ContextVar("account_charged_this_turn", default=False)


# The limit in force for the request being handled, decided before any search
# is chosen. The router reads it to withhold search_web; the reply reads it
# to say so. None means searching is possible.
current_search_limit: ContextVar[SearchLimit | None] = ContextVar(
    "current_search_limit", default=None
)


class SearchBudgetExceededError(Exception):
    """Raised when an account has spent its allowance for the current window."""

    def __init__(self, window: str, resets_at: datetime) -> None:
        self.window = window
        self.resets_at = resets_at
        super().__init__(
            f"Internet search limit reached for {window}. "
            f"It resets at {resets_at.isoformat()}."
        )


# Start of the next UTC day, when the daily counter rolls over.
def _next_day(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


# Start of the next UTC month.
def _next_month(now: datetime) -> datetime:
    if now.month == 12:
        return now.replace(
            year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    return now.replace(
        month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
    )


class BudgetedSearchProvider(SearchProvider):
    """Charge one query to the calling account before delegating downstream."""

    def __init__(
        self,
        inner: SearchProvider,
        budget: SearchBudget,
        credits_per_search: int = 1,
        usage: Any = None,
        reconcile_every_seconds: float = 600.0,
        brave_monthly_limit: int = 0,
    ) -> None:
        # Brave's monthly request ceiling as the backend knows it (0 = no
        # Brave rung); the internet server enforces the same number itself.
        self.brave_monthly_limit = max(0, int(brave_monthly_limit))
        # The provider's own meter, asked at most every `reconcile_every_seconds`
        # before a search so the local pool is never further from the truth
        # than that - the key is shared with whatever else the operator points
        # at it, and a pool that only counts its own reservations found out it
        # was empty by being refused (432, 2026-08-25).
        self.usage = usage
        self.reconcile_every_seconds = reconcile_every_seconds
        # What one call costs the key. Tavily bills an `advanced` search at
        # two credits and the ceiling is in credits, so counting calls let
        # the key run out (432 from the provider) with the local counter
        # showing room to spare - 2026-08-25, at 993 of 1,000.
        self.credits_per_search = max(1, int(credits_per_search))
        self.inner = inner
        self.budget = budget

    def is_enabled(self) -> bool:
        return self.inner.is_enabled()

    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults:
        identity = current_search_identity.get()
        # Set before anything can search: a harness spends the same live
        # allowance a person does, and by 2026-09-06 the two deploy harnesses
        # were three quarters of the month's Tavily credits. They check which
        # tool ran and how the answer reads, so the cheap depth serves them.
        frugal_search.set(identity is not None and is_harness_id(identity.user_id))
        await self._reconcile_if_stale()
        if identity is None:
            # Unattributed callers are unmetered per account by design, but the
            # shared pool is the key's own ceiling: once it is spent nobody
            # searches, attributed or not - the provider would refuse anyway.
            now = datetime.now(UTC)
            if await self.limit_state(None, now) is not None:
                raise SearchBudgetExceededError("this month", _next_month(now))
            return await self._search_inner(query, max_results)

        # The pool meters Tavily's credits. With a rung ahead of Tavily that
        # still has room this month, the pool is left out of the reservation
        # and charged only if Tavily ends up serving - otherwise a spent pool
        # refused attributed callers a search Brave would have answered
        # (the operator, over iMessage, 2026-08-25), while unattributed ones
        # sailed through.
        brave_room = await self._brave_has_room()
        if account_charged_this_turn.get():
            # A later round of the same question: the account has paid for
            # the question; only the pool (Tavily's credits) is reserved.
            granted = (
                await self.budget.reserve_pool_only(self.credits_per_search)
                if not brave_room
                else self.credits_per_search
            )
        else:
            granted = await self.budget.reserve(
                identity.user_id,
                identity.is_operator,
                wanted=self.credits_per_search,
                override=identity.monthly_limit,
                daily_override=identity.daily_limit,
                include_pool=not brave_room,
            )
            if granted >= self.credits_per_search:
                account_charged_this_turn.set(True)
        if granted < self.credits_per_search:
            now = datetime.now(UTC)
            # Report the window that actually ran out. Saying "monthly" to
            # somebody who only needs to wait until midnight would send them
            # away for weeks.
            today_left = await self.budget.remaining_today(
                identity.user_id, identity.is_operator, override=identity.daily_limit
            )
            if today_left <= 0:
                raise SearchBudgetExceededError("today", _next_day(now))
            raise SearchBudgetExceededError("this month", _next_month(now))

        return await self._search_inner(query, max_results, pool_reserved=not brave_room)

    # Whether the Brave rung still has requests left this month, as the
    # backend counts them (the internet server keeps the count that stops).
    async def _brave_has_room(self, now: datetime | None = None) -> bool:
        if self.brave_monthly_limit <= 0:
            return False
        try:
            used = await self.budget.provider_used("brave", now or datetime.now(UTC))
        except Exception:
            return False
        return used < self.brave_monthly_limit

    # The provider's refusal becomes the same exhaustion the local pool
    # raises, and the pool is marked spent so the next turn knows before it
    # asks: a 432 is the provider saying the month is gone.
    async def _search_inner(
        self, query: str, max_results: int | None, pool_reserved: bool = True
    ) -> SearchResults:
        try:
            found = await self.inner.search(query, max_results=max_results)
        except SearchProviderQuotaError:
            now = datetime.now(UTC)
            try:
                await self.budget.reconcile(self.budget.monthly_credits, now)
            except Exception:
                pass
            raise SearchBudgetExceededError("this month", _next_month(now)) from None
        # The pool counts Tavily's credits. A search another rung served
        # spent none of them, so the reservation goes back; and Brave's own
        # count goes up, which is what the pre-flight reads.
        served_by = str(found.provider or "").lower()
        if "tavily" in served_by and not pool_reserved:
            try:
                await self.budget.charge_pool(self.credits_per_search)
            except Exception:
                pass
        if "tavily" not in served_by and pool_reserved:
            try:
                await self.budget.refund_pool(self.credits_per_search)
            except Exception:
                pass
        if "brave" in served_by:
            try:
                await self.budget.charge_provider("brave", 1)
            except Exception:
                pass
        return found

    # Align the local pool with the provider's meter when the last alignment
    # is older than the interval. Best effort: a failed read leaves the local
    # count in charge, which is what it was anyway.
    async def _reconcile_if_stale(self) -> None:
        if self.usage is None or not getattr(self.usage, "is_enabled", lambda: False)():
            return
        try:
            await self.budget.reconcile_if_stale(self.usage, self.reconcile_every_seconds)
        except Exception:
            return

    # Which allowance, if any, would refuse this identity's next search -
    # asked before a search is chosen, so a turn can say so instead of
    # choosing one and being refused. Order: the shared pool (what actually
    # runs out), then the account's month, then its day.
    async def limit_state(
        self, identity: SearchIdentity | None, now: datetime | None = None
    ) -> SearchLimit | None:
        moment = now or datetime.now(UTC)
        await self._reconcile_if_stale()
        try:
            # The shared pool is Tavily's; with another rung ahead of it that
            # still has room this month, a spent pool limits nothing yet.
            brave_room = await self._brave_has_room(moment)
            if (
                await self.budget.pool_remaining(moment) < self.credits_per_search
                and not brave_room
            ):
                return SearchLimit("this month", _next_month(moment), shared=True)
            if identity is None:
                return None
            monthly = await self.budget.remaining(
                identity.user_id, identity.is_operator, moment, override=identity.monthly_limit
            )
            if monthly < self.credits_per_search:
                return SearchLimit("this month", _next_month(moment), shared=False)
            daily = await self.budget.remaining_today(
                identity.user_id, identity.is_operator, moment, override=identity.daily_limit
            )
            if daily < self.credits_per_search:
                return SearchLimit("today", _next_day(moment), shared=False)
        except Exception:
            return None
        return None
