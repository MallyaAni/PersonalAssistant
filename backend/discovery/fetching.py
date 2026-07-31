"""Bounded feed retrieval and the per-run request budget it spends from."""

import httpx

from backend.discovery.events import FeedError

# A feed is fetched whole before parsing, so the ceiling is what stops a large
# or hostile response from becoming this process's memory problem.
MAX_FEED_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0
# Bounds one scheduled run. The free-tier claim is only checkable if the number
# of outbound requests a run may make is fixed in advance.
DEFAULT_RUN_REQUEST_BUDGET = 40


class RequestBudgetExceededError(FeedError):
    """Raised when a run has spent its allotted outbound requests."""


class RequestBudget:
    """Count outbound feed requests so one run cannot spend without limit."""

    def __init__(self, limit: int = DEFAULT_RUN_REQUEST_BUDGET) -> None:
        if limit < 1:
            raise ValueError("A request budget must allow at least one request.")
        self.limit = limit
        self.spent = 0

    # Reserve one request, refusing rather than allowing an unbounded run.
    def spend(self) -> None:
        if self.spent >= self.limit:
            raise RequestBudgetExceededError(
                f"This run already made its {self.limit} allotted requests."
            )
        self.spent += 1

    @property
    def remaining(self) -> int:
        return max(self.limit - self.spent, 0)


# Read one feed within a fixed byte ceiling. The body is streamed so an
# oversized response is abandoned mid-transfer instead of after it has already
# been held in memory.
async def fetch_feed(
    url: str,
    budget: RequestBudget | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_FEED_BYTES,
    client: httpx.AsyncClient | None = None,
) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise FeedError("A feed URL must be http or https.")
    if budget is not None:
        budget.spend()

    if client is not None:
        return await _read(client, url, max_bytes)
    async with httpx.AsyncClient(
        timeout=timeout_seconds, follow_redirects=True
    ) as owned:
        return await _read(owned, url, max_bytes)


async def _read(client: httpx.AsyncClient, url: str, max_bytes: int) -> str:
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise FeedError(f"Feed exceeded {max_bytes} bytes: {url}")
                chunks.append(chunk)
    except FeedError:
        raise
    except Exception as exc:
        # The URL is operator-configured, so it is safe to name; the provider's
        # own error text is not, and is deliberately not propagated.
        raise FeedError(f"Could not read feed: {url}") from exc
    return b"".join(chunks).decode("utf-8", errors="replace")
