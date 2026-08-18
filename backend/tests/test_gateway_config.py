"""The gateway must not cache the backend's address for the life of the process.

`proxy_pass http://backend:8000` resolves that name once, when nginx loads, and
keeps the address forever. Recreating the backend container - which any rebuild
does - moves it to a new address on the Docker network, and the gateway went on
dialling the old one. Every API call answered 502 with a completely healthy
backend running behind it, so the site looked down while nothing was actually
wrong with it, and the only cure was remembering to reload nginx by hand after
every backend deploy.

Naming the upstream through a variable is what forces a per-request lookup, so
these assert the shape that survives a redeploy rather than the comment above
it.
"""

import re
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[2] / "frontend" / "nginx.gateway.conf"


# Comments stripped first: the block explains the defect by quoting the
# directive that caused it, and a check reading that would report the fix as
# the bug.
def _api_location() -> str:
    text = "\n".join(
        line
        for line in CONFIG.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    start = text.index("location /api/")
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError("the /api/ location block is not closed")


def test_the_api_upstream_is_resolved_per_request_not_once_at_startup():
    block = _api_location()

    # A literal host:port in proxy_pass is the defect: nginx resolves it at
    # load time and never again.
    assert not re.search(r"proxy_pass\s+http://[a-zA-Z0-9_.-]+:\d+", block), (
        "proxy_pass names the upstream literally, so nginx will cache its "
        "address and 502 after the backend is recreated on a new one"
    )
    assert re.search(r"proxy_pass\s+http://\$", block), (
        "the upstream must be reached through a variable, which is what makes "
        "nginx resolve it per request"
    )


def test_a_resolver_is_configured_for_the_variable_upstream():
    block = _api_location()

    # Without a resolver, a variable upstream fails to resolve at all rather
    # than falling back to the cached address.
    assert re.search(r"\bresolver\s+127\.0\.0\.11\b", block), (
        "a variable upstream needs Docker's embedded DNS named explicitly"
    )
    valid = re.search(r"\bresolver\b[^;]*\bvalid=(\d+)s", block)
    assert valid, "the resolver must cap how long a lookup is cached"
    assert int(valid.group(1)) <= 30, (
        f"valid={valid.group(1)}s leaves the gateway pointing at a dead "
        f"address for too long after a redeploy"
    )


# Appending the URI stops being automatic once proxy_pass holds a variable,
# because nginx cannot work out at config time which prefix to replace. Losing
# it silently rewrites every API path to /.
def test_the_request_uri_is_passed_through_explicitly():
    assert "$request_uri" in _api_location()


@pytest.mark.parametrize(
    "directive",
    ["proxy_buffering off", "proxy_read_timeout", "proxy_set_header Host"],
)
def test_streaming_and_forwarding_survive_the_rewrite(directive: str):
    # Chat is server-sent events; buffering or a short read timeout truncates a
    # reply mid-stream, and these sit in the same block that was edited.
    assert directive in _api_location()
