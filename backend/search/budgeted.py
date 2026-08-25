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

from backend.core.interfaces import SearchProvider
from backend.discovery.search_budget import SearchBudget
from backend.search.types import SearchResults


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
    ) -> None:
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
        if identity is None:
            return await self.inner.search(query, max_results=max_results)

        granted = await self.budget.reserve(
            identity.user_id,
            identity.is_operator,
            wanted=self.credits_per_search,
            override=identity.monthly_limit,
            daily_override=identity.daily_limit,
        )
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

        return await self.inner.search(query, max_results=max_results)
