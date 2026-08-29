"""What a third-party MCP server is permitted to offer, and where it may go.

Adding Microsoft's Playwright MCP server (2026-08-29) is the first time this
system runs a tool catalogue somebody else controls and can change. Two
controls make that safe, and they are the subject of this file.

The first is a per-server tool allowlist. Playwright's catalogue ships
`browser_run_code_unsafe` and `browser_evaluate` beside the navigation tools;
a capability flag on their side is their decision to revisit, not ours to
depend on, so the operator names what may be used and everything else is
withheld before it is ever indexed.

The second is a host allowlist. The egress screen already asks "may these
words leave the machine". A navigating tool needs the other half - "may this
machine go there" - because its destination *is* an argument.
"""

from __future__ import annotations

import pytest

from backend.mcp.client import _permitted
from backend.mcp.config import parse_server_configs
from backend.mcp.types import MCPServerConfig, MCPTool
from backend.services.mcp_invocation_service import (
    MCPInvocationError,
    MCPInvocationService,
)


def _tool(name: str) -> MCPTool:
    return MCPTool(server_id="browser", name=name, description="does a thing", input_schema={})


CATALOGUE = [
    _tool("browser_navigate"),
    _tool("browser_snapshot"),
    _tool("browser_click"),
    _tool("browser_run_code_unsafe"),
    _tool("browser_evaluate"),
    _tool("browser_cookie_list"),
]


def _server(**overrides) -> MCPServerConfig:
    fields = {
        "server_id": "browser",
        "transport": "http",
        "url": "http://browser:8931/mcp",
        "risk_classification": "untrusted",
    }
    fields.update(overrides)
    return MCPServerConfig(**fields)


def test_only_the_named_tools_survive_the_catalogue():
    server = _server(allowed_tools=("browser_navigate", "browser_snapshot", "browser_click"))
    kept = {tool.name for tool in _permitted(server, CATALOGUE)}
    assert kept == {"browser_navigate", "browser_snapshot", "browser_click"}
    for dangerous in ("browser_run_code_unsafe", "browser_evaluate", "browser_cookie_list"):
        assert dangerous not in kept


def test_a_tool_the_server_adds_tomorrow_is_withheld_by_default():
    # The property that matters: the allowlist is a whitelist, so growth in
    # somebody else's catalogue cannot widen what this system can do.
    server = _server(allowed_tools=("browser_navigate",))
    grown = CATALOGUE + [_tool("browser_install_extension"), _tool("browser_read_disk")]
    assert {tool.name for tool in _permitted(server, grown)} == {"browser_navigate"}


def test_a_server_with_no_allowlist_is_left_alone():
    # Our own servers are written here and reviewed here; naming every tool
    # would be ceremony that goes stale.
    assert _permitted(_server(), CATALOGUE) == CATALOGUE


def test_the_allowlist_is_read_from_the_operators_json():
    parsed = parse_server_configs(
        '[{"server_id":"browser","transport":"http","url":"http://browser:8931/mcp",'
        '"risk_classification":"untrusted","allowed_tools":["browser_navigate"],'
        '"allowed_hosts":["OpenTable.com "," example.test"]}]'
    )
    assert len(parsed) == 1
    assert parsed[0].allowed_tools == ("browser_navigate",)
    # Cased and padded as a person would type them; compared as hosts.
    assert parsed[0].allowed_hosts == ("opentable.com", "example.test")


def _service(server: MCPServerConfig) -> MCPInvocationService:
    return MCPInvocationService(invoker=None, lister=None, servers=(server,))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("url", "permitted"),
    [
        ("https://opentable.com/r/somewhere", True),
        ("https://www.opentable.com/r/somewhere", True),
        ("https://booking.opentable.com/x", True),
        ("http://opentable.com:8080/x", True),
        ("https://notopentable.com/x", False),
        ("https://opentable.com.evil.test/x", False),
        ("https://evil.test/x", False),
        ("https://user:pw@evil.test/x", False),
    ],
)
def test_a_navigation_argument_may_only_name_a_permitted_host(url, permitted):
    server = _server(allowed_hosts=("opentable.com",))
    service = _service(server)
    if permitted:
        service._check_hosts(server, {"url": url})
        return
    with pytest.raises(MCPInvocationError) as raised:
        service._check_hosts(server, {"url": url})
    assert raised.value.reason == "host_not_allowed"


def test_arguments_that_are_not_addresses_are_not_treated_as_ones():
    server = _server(allowed_hosts=("opentable.com",))
    # A snapshot's element description, a typed value, a number.
    _service(server)._check_hosts(
        server, {"element": "the Book button", "text": "2 people", "index": 3}
    )


def test_a_server_with_no_host_allowlist_may_be_asked_for_any_url():
    # Search is exactly this: its job is the open web, behind a screened query.
    server = _server(server_id="internet", allowed_hosts=())
    _service(server)._check_hosts(server, {"url": "https://anywhere.test/x"})


def test_a_navigating_server_with_no_hosts_named_reaches_nothing():
    # The state the browser ships in. An empty allowlist reads as "nowhere"
    # here and as "no restriction" for search, which is why the difference is
    # declared rather than inferred.
    server = _server(navigates=True, allowed_hosts=())
    with pytest.raises(MCPInvocationError) as raised:
        _service(server)._check_hosts(server, {"url": "https://anywhere.test/x"})
    assert raised.value.reason == "host_not_allowed"


def test_the_navigates_flag_is_read_from_the_operators_json():
    parsed = parse_server_configs(
        '[{"server_id":"browser","transport":"http","url":"http://browser:8931/mcp",'
        '"risk_classification":"untrusted","navigates":true}]'
    )
    assert parsed[0].navigates is True
    assert parse_server_configs(
        '[{"server_id":"internet","command":"x","risk_classification":"read_only"}]'
    )[0].navigates is False
