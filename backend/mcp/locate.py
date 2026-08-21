"""Find an MCP server that moved to a new address.

The iMessage bridge runs on a laptop that takes whatever address DHCP hands
it. When that address changed, the bridge was "down" for nine days while the
process ran the whole time - the configured IP simply pointed at a different
device. A server marked `discover` in its configuration is hunted when its
configured host stops answering: the /24 around the last known addresses is
scanned for the configured port, and each candidate must prove it is the
same service before it is used.

Proof is deliberately two-step so the auth token is never handed to a
stranger. An unauthenticated request goes first, and the real server refuses
it (401/403) - a host that answers anything else is not guarding this path
and never sees the token. Only a candidate that refused correctly gets the
authenticated confirmation call.

A confirmed address is cached in Redis so a scan happens once per move, not
once per session. Redis being down degrades to scanning again, never to
failing: like the search budget's counter, the cache is an optimization
here, not an authority.
"""

import asyncio
import contextlib
import ipaddress
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.config.settings import settings
from backend.mcp.types import MCPServerConfig

_PORT_TIMEOUT_SECONDS = 0.75
_VERIFY_TIMEOUT_SECONDS = 5.0
_SCAN_CONCURRENCY = 64
_CACHE_TTL_SECONDS = 30 * 24 * 3600

# One JSON-RPC request any MCP streamable-http server will answer, used only
# to see whether the endpoint responds and with what status - the body of the
# reply is never trusted for anything.
_PROBE_BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
_PROBE_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}


# Where a server's last confirmed address is remembered between processes.
def _cache_key(server_id: str) -> str:
    return f"mcp:discovered_host:{server_id}"


# Can a TCP connection be opened to this host and port quickly? This is the
# cheap test that gates everything else: a closed port disqualifies a host in
# under a second without any HTTP traffic at all.
async def _port_open(host: str, port: int) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), _PORT_TIMEOUT_SECONDS
        )
    except Exception:
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


# Is the service at `url` the one this configuration authenticates to?
#
# With auth headers configured, the unauthenticated request must be refused
# before the authenticated one is sent - the refusal is what proves a guard
# is present, and it is the only thing standing between the token and an
# unknown machine that happens to hold the old address. Without headers there
# is nothing to protect and a plain 200 is acceptance.
async def _is_this_server(url: str, headers: dict[str, str]) -> bool:
    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT_SECONDS) as client:
            bare = await client.post(url, json=_PROBE_BODY, headers=_PROBE_HEADERS)
            if not headers:
                return bare.status_code == 200
            if bare.status_code not in (401, 403):
                return False
            authed = await client.post(
                url, json=_PROBE_BODY, headers={**_PROBE_HEADERS, **headers}
            )
            return authed.status_code == 200
    except Exception:
        return False


# Every host address in the /24 around each seed IP. Hostname seeds are
# skipped: a name that stopped resolving offers no subnet to search.
def _candidate_hosts(seeds: tuple[str, ...]) -> tuple[str, ...]:
    networks = set()
    for seed in seeds:
        with contextlib.suppress(ValueError):
            networks.add(ipaddress.ip_network(f"{seed}/24", strict=False))
    return tuple(str(host) for network in networks for host in network.hosts())


# Scan the candidate subnets for a host that both listens on the port and
# proves it is this server. Port probes run concurrently; verification runs
# one at a time because more than one open port is already unusual.
async def _scan(
    seeds: tuple[str, ...], port: int, build_url, headers: dict[str, str]
) -> str | None:
    semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)

    async def probe(host: str) -> str | None:
        async with semaphore:
            return host if await _port_open(host, port) else None

    probes = [probe(host) for host in _candidate_hosts(seeds)]
    listening = [host for host in await asyncio.gather(*probes) if host]
    for host in listening:
        if await _is_this_server(build_url(host), headers):
            return host
    return None


# The URL to actually connect to: the configured one while it answers, or the
# rediscovered one when the device moved. Falls back to the configured URL
# when nothing is found, so the failure that surfaces is the ordinary
# connection error at the address the operator wrote down.
async def resolve_http_url(server: MCPServerConfig) -> str:
    if not server.discover or server.transport != "http":
        return server.url

    parts = urlsplit(server.url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)

    # Rebuild the configured URL around a different host, keeping scheme,
    # path and query exactly as written.
    def build_url(new_host: str) -> str:
        return urlunsplit(
            (parts.scheme, f"{new_host}:{port}", parts.path, parts.query, "")
        )

    if await _port_open(host, port):
        return server.url

    headers = dict(server.headers)
    cached = await _read_cache(server.server_id)
    if (
        cached
        and cached != host
        and await _port_open(cached, port)
        and await _is_this_server(build_url(cached), headers)
    ):
        return build_url(cached)

    seeds = tuple(seed for seed in (host, cached) if seed)
    found = await _scan(seeds, port, build_url, headers)
    if found is None:
        return server.url
    await _write_cache(server.server_id, found)
    return build_url(found)


# Last confirmed address, or None when the cache is empty or unreachable.
async def _read_cache(server_id: str) -> str | None:
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            return await redis.get(_cache_key(server_id))
        finally:
            await redis.aclose()
    except Exception:
        return None


# Remember a confirmed address; failure to remember is not failure to find.
async def _write_cache(server_id: str, host: str) -> None:
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await redis.set(_cache_key(server_id), host, ex=_CACHE_TTL_SECONDS)
        finally:
            await redis.aclose()
    except Exception:
        return
