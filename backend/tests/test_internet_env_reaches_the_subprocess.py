"""Every setting the internet server reads is named in the sample inherit_env.

The internet MCP server is a stdio subprocess that sees only the variables
its `inherit_env` lists. Brave's four settings reached the backend container
on 2026-08-25 and not the subprocess, so the new rung silently did not exist:
the chain fell straight to a spent Tavily key. This holds the sample
MCP_SERVERS_JSON in .env.example to the server's own reads, so the next
setting added to the server fails here before it is missed in a deployment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "backend" / "mcp" / "servers" / "internet.py"
ENV_EXAMPLE = REPO / ".env.example"

# Read by the server but supplied by the process, not the operator.
NOT_OPERATOR_SETTINGS = {"GEMINI_API_KEY"}


def _server_reads() -> set[str]:
    return set(re.findall(r'os\.getenv\(\s*"([A-Z0-9_]+)"', SERVER.read_text())) - NOT_OPERATOR_SETTINGS


def _sample_inherit_env() -> set[str]:
    for line in ENV_EXAMPLE.read_text().splitlines():
        if line.startswith("MCP_SERVERS_JSON="):
            servers = json.loads(line[len("MCP_SERVERS_JSON="):])
            for server in servers:
                if server.get("server_id") == "internet":
                    return set(server.get("inherit_env") or [])
    raise AssertionError(".env.example has no active MCP_SERVERS_JSON with an internet server")


def test_every_setting_the_internet_server_reads_is_inherited() -> None:
    missing = sorted(_server_reads() - _sample_inherit_env())
    assert not missing, (
        f"the internet server reads {missing} but the sample MCP_SERVERS_JSON "
        "does not pass them to the subprocess; add them to inherit_env in "
        ".env.example (and in the deployed .env)"
    )
