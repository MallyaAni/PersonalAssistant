"""A moved LAN server is found again, and the token never courts a stranger.

The iMessage bridge was "down" for nine days while its process ran the whole
time - DHCP had moved the laptop and the configured IP pointed at a different
device. `resolve_http_url` exists so that failure heals itself. What these
tests pin is not the scanning mechanics but the promises around them: an
undiscoverable server is never hunted, a reachable configured address is
never second-guessed, a rediscovered URL keeps everything but the host, and
the auth token is only ever sent to a host that first refused an
unauthenticated request the way the real server does.
"""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import backend.mcp.locate as locate
from backend.mcp.config import parse_server_configs
from backend.mcp.types import MCPServerConfig


def _server(**overrides) -> MCPServerConfig:
    base = {
        "server_id": "bridge",
        "transport": "http",
        "url": "http://172.16.8.4:8010/mcp",
        "headers": (("x-token", "secret"),),
        "discover": True,
    }
    base.update(overrides)
    return MCPServerConfig(**base)


@pytest.mark.asyncio
async def test_a_server_not_marked_discover_is_never_probed(monkeypatch):
    async def explode(host, port):  # pragma: no cover - the assertion
        raise AssertionError("probed a server that opted out")

    monkeypatch.setattr(locate, "_port_open", explode)

    resolved = await locate.resolve_http_url(_server(discover=False))

    assert resolved == "http://172.16.8.4:8010/mcp"


@pytest.mark.asyncio
async def test_a_configured_address_that_answers_is_used_as_written(monkeypatch):
    async def port_open(host, port):
        return host == "172.16.8.4"

    monkeypatch.setattr(locate, "_port_open", port_open)

    resolved = await locate.resolve_http_url(_server())

    assert resolved == "http://172.16.8.4:8010/mcp"


@pytest.mark.asyncio
async def test_a_moved_server_is_found_and_the_url_keeps_its_path(monkeypatch):
    async def port_open(host, port):
        return host == "172.16.8.2"

    async def verified(url, headers):
        return url.startswith("http://172.16.8.2:")

    written = {}

    async def remember(server_id, host):
        written[server_id] = host

    monkeypatch.setattr(locate, "_port_open", port_open)
    monkeypatch.setattr(locate, "_is_this_server", verified)
    monkeypatch.setattr(locate, "_read_cache", lambda server_id: _none())
    monkeypatch.setattr(locate, "_write_cache", remember)

    resolved = await locate.resolve_http_url(_server())

    assert resolved == "http://172.16.8.2:8010/mcp"
    assert written == {"bridge": "172.16.8.2"}


@pytest.mark.asyncio
async def test_nothing_found_falls_back_to_the_configured_url(monkeypatch):
    async def port_closed(host, port):
        return False

    monkeypatch.setattr(locate, "_port_open", port_closed)
    monkeypatch.setattr(locate, "_read_cache", lambda server_id: _none())

    resolved = await locate.resolve_http_url(_server())

    assert resolved == "http://172.16.8.4:8010/mcp"


# The cached address is tried before any scan, so one move costs one scan.
@pytest.mark.asyncio
async def test_a_cached_address_short_circuits_the_scan(monkeypatch):
    async def port_open(host, port):
        return host == "172.16.8.9"

    async def verified(url, headers):
        return True

    async def cached(server_id):
        return "172.16.8.9"

    async def no_scan(seeds, port, build_url, headers):  # pragma: no cover
        raise AssertionError("scanned despite a working cached address")

    monkeypatch.setattr(locate, "_port_open", port_open)
    monkeypatch.setattr(locate, "_is_this_server", verified)
    monkeypatch.setattr(locate, "_read_cache", cached)
    monkeypatch.setattr(locate, "_scan", no_scan)

    resolved = await locate.resolve_http_url(_server())

    assert resolved == "http://172.16.8.9:8010/mcp"


# The two-step identity check, exercised against a stub transport. A host
# that answers 200 without credentials is not guarding the path, so it must
# be rejected before the authenticated request exists at all.
class _StubClient:
    responses: list[int] = []
    calls: list[dict] = []

    def __init__(self, timeout=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _StubClient.calls.append(dict(headers or {}))

        class _Reply:
            status_code = _StubClient.responses.pop(0)

        return _Reply()


@pytest.mark.asyncio
async def test_the_token_is_only_sent_after_a_correct_refusal(monkeypatch):
    monkeypatch.setattr(locate.httpx, "AsyncClient", _StubClient)
    _StubClient.responses, _StubClient.calls = [401, 200], []

    accepted = await locate._is_this_server("http://x/mcp", {"x-token": "secret"})

    assert accepted is True
    assert "x-token" not in _StubClient.calls[0]
    assert _StubClient.calls[1]["x-token"] == "secret"


@pytest.mark.asyncio
async def test_a_host_that_answers_without_credentials_never_sees_the_token(
    monkeypatch,
):
    monkeypatch.setattr(locate.httpx, "AsyncClient", _StubClient)
    _StubClient.responses, _StubClient.calls = [200], []

    accepted = await locate._is_this_server("http://x/mcp", {"x-token": "secret"})

    assert accepted is False
    assert len(_StubClient.calls) == 1
    assert "x-token" not in _StubClient.calls[0]


def test_discover_is_parsed_from_configuration_and_off_by_default():
    raw = (
        '[{"server_id":"a","transport":"http","url":"http://h:1/mcp",'
        '"discover":true},'
        '{"server_id":"b","transport":"http","url":"http://h:2/mcp"}]'
    )

    first, second = parse_server_configs(raw)

    assert first.discover is True
    assert second.discover is False


# A helper for patching async cache reads that return nothing.
async def _none():
    return None
