"""Bounded feed retrieval and the per-run request budget it spends from."""

import asyncio
import ipaddress
import socket

import httpx

from backend.discovery.events import FeedError

# A feed is fetched whole before parsing, so the ceiling is what stops a large
# or hostile response from becoming this process's memory problem.
MAX_FEED_BYTES = 5 * 1024 * 1024
# A picture published with a listing is larger than a feed but still bounded.
# The vision provider scales it down for the model; this is what stops a
# hostile or careless host from making the fetch itself the problem.
MAX_MEDIA_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0
# Bounds one scheduled run. The free-tier claim is only checkable if the number
# of outbound requests a run may make is fixed in advance.
DEFAULT_RUN_REQUEST_BUDGET = 40
# Redirect chains are followed one hop at a time so each destination can be
# checked before it is contacted. A feed that redirects in a circle stops here.
MAX_REDIRECTS = 5


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


# Read one response within a fixed byte ceiling, returning the bytes and the
# declared content type. The body is streamed so an oversized response is
# abandoned mid-transfer instead of after it has already been held in memory.
async def fetch_bytes(
    url: str,
    budget: RequestBudget | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_FEED_BYTES,
    client: httpx.AsyncClient | None = None,
) -> tuple[bytes, str]:
    if not url.lower().startswith(("http://", "https://")):
        raise FeedError("A feed URL must be http or https.")
    if budget is not None:
        budget.spend()

    # A caller-supplied client is trusted: tests inject one to avoid the
    # network, and the caller owns what it connects to. The guard below is for
    # the URLs this process fetches on its own, which users can configure.
    if client is not None:
        return await _read(client, url, max_bytes)

    async with httpx.AsyncClient(
        timeout=timeout_seconds, follow_redirects=False
    ) as owned:
        return await _read_public(owned, url, budget, max_bytes)


# Read one feed as text. Feeds are UTF-8 in practice; replacing undecodable
# bytes keeps one bad character from discarding an otherwise readable listing.
async def fetch_feed(
    url: str,
    budget: RequestBudget | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_FEED_BYTES,
    client: httpx.AsyncClient | None = None,
) -> str:
    body, _ = await fetch_bytes(
        url,
        budget=budget,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        client=client,
    )
    return body.decode("utf-8", errors="replace")


# Follow a feed's redirects one at a time, refusing any destination that points
# back inside the machine or the local network.
#
# A source URL is user-supplied, and an unguarded fetch is a request forgery
# primitive: `http://169.254.169.254/` reaches cloud metadata, and
# `http://localhost:8000/` reaches this application's own API. Redirects are the
# reason this cannot be a one-time check at the call site.
#
# Resolution and connection are separate steps, so a DNS answer can change
# between them. This closes the ordinary case — an internal hostname or literal
# address — and is not a defence against a hostile resolver.
async def _read_public(
    client: httpx.AsyncClient,
    url: str,
    budget: RequestBudget | None,
    max_bytes: int,
) -> tuple[bytes, str]:
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        await _require_public_url(current)
        if hop > 0 and budget is not None:
            # Each redirect is another outbound request and spends the run's
            # budget like any other.
            budget.spend()
        try:
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise FeedError(f"Feed redirect has no destination: {url}")
                    current = str(response.url.join(location))
                    continue
                response.raise_for_status()
                declared = response.headers.get("content-type", "")
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
            # The URL is operator-configured, so it is safe to name; the
            # provider's own error text is not, and is deliberately not
            # propagated.
            raise FeedError(f"Could not read feed: {url}") from exc
        return b"".join(chunks), declared
    raise FeedError(f"Feed redirected more than {MAX_REDIRECTS} times: {url}")


# Refuse a URL whose host resolves to anything but a public address.
async def _require_public_url(url: str) -> None:
    try:
        parsed = httpx.URL(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except httpx.InvalidURL as exc:
        raise FeedError(f"Feed URL is not readable: {url}") from exc
    if parsed.scheme not in ("http", "https"):
        raise FeedError("A feed URL must be http or https.")
    host = parsed.host
    if not host:
        raise FeedError(f"Feed URL has no host: {url}")
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM
        )
    except (socket.gaierror, OSError) as exc:
        raise FeedError(f"Could not resolve feed host: {host}") from exc
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        if not _address_is_public(address):
            raise FeedError(f"Feed host resolves to a non-public address: {host}")


# Whether one resolved address is safe to contact. Everything that is not
# clearly public is refused: loopback, private ranges, link-local (which is
# where cloud metadata lives), multicast and reserved space.
def _address_is_public(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    # An IPv4-mapped IPv6 address reaches the IPv4 address it wraps, so it is
    # judged as that address rather than as the IPv6 form, which does not
    # report loopback or private for the mapped ranges.
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


async def _read(
    client: httpx.AsyncClient, url: str, max_bytes: int
) -> tuple[bytes, str]:
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            declared = response.headers.get("content-type", "")
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
    return b"".join(chunks), declared
