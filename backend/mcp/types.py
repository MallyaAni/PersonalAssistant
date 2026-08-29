import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """One configured MCP server and the trust the operator assigns it.

    Trust is declared locally, never taken from the server, because a server
    describing itself is untrusted input like any other.

    Two transports are supported. `stdio` launches the server as a local
    subprocess, which is how most servers are distributed today and how local
    development runs. `http` connects to an already-running server over
    streamable HTTP, which is what a deployed sibling service or a remote
    vendor offers, and needs no language runtime inside this image.
    """

    server_id: str
    transport: str = "stdio"
    # stdio transport
    command: str = ""
    args: tuple[str, ...] = ()
    # Names of process variables explicitly inherited by this child. Values
    # stay outside JSON configuration so credentials are never indexed or shown.
    inherit_env: tuple[str, ...] = ()
    # http transport
    url: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    # Forward application-owned request identity only to explicitly local servers.
    forward_context: bool = False
    risk_classification: str = "untrusted"
    enabled: bool = True
    # The only tools of this server's catalogue that may ever be listed or
    # called. Empty means "whatever it offers", which is right for a server
    # written here and wrong for one written by somebody else.
    #
    # A third-party server's catalogue is its own to change. Microsoft's
    # Playwright MCP server, for instance, ships `browser_run_code_unsafe` and
    # `browser_evaluate` beside the navigation tools, and a capability flag on
    # their side is their decision to revisit, not ours to depend on. Naming
    # the permitted tools here means a catalogue that grows overnight does not
    # widen what this system can do.
    allowed_tools: tuple[str, ...] = ()
    # Hosts this server's arguments may name.
    allowed_hosts: tuple[str, ...] = ()
    # Whether this server fetches whatever address it is handed.
    #
    # It decides which way an empty `allowed_hosts` reads, and the two answers
    # are opposite. For a search tool an empty list means "no restriction",
    # which is correct: its job is the open web behind a screened query, and
    # it goes to one known provider either way. For a server that navigates,
    # an empty list must mean "nowhere" - a browser wired up with nobody
    # having said where it may go should be able to go nowhere, not
    # everywhere. Declared rather than guessed from tool names, because a
    # rule that depends on a third party's naming is a rule that changes when
    # they rename something.
    navigates: bool = False
    # This server lives on a LAN device whose DHCP address can change, so when
    # its configured host stops answering, scan the subnet for it rather than
    # staying down until an operator edits the URL. Off by default: a server
    # with a stable address should fail loudly at that address, not be hunted.
    discover: bool = False

    # Reject a configuration that cannot be connected to, rather than failing
    # later with a confusing transport error.
    def __post_init__(self) -> None:
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"{self.server_id}: stdio transport requires a command")
        if self.transport == "http" and not self.url:
            raise ValueError(f"{self.server_id}: http transport requires a url")
        if self.transport not in {"stdio", "http"}:
            raise ValueError(f"{self.server_id}: unknown transport {self.transport}")


@dataclass(frozen=True, slots=True)
class MCPTool:
    """One tool as the live server currently declares it.

    Name, description and schema are untrusted third-party text. They are
    stored for discovery and shown to the model as data, and can never
    authorize an invocation on their own.
    """

    server_id: str
    name: str
    description: str
    input_schema: dict[str, Any]

    # Identify everything the model is shown about this tool, so a stored
    # descriptor is detectably stale when the server changes any of it.
    #
    # The description is fingerprinted alongside the schema deliberately. A
    # server that keeps its schema but rewrites its description can smuggle
    # instructions to the model without altering its contract - the rug-pull
    # window. Hashing the schema alone would leave that change invisible.
    @property
    def schema_fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "name": self.name,
                "description": self.description,
                "input_schema": self.input_schema,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # Summarize what the tool takes, for embedding alongside its description.
    # Values are never included: only the shape of the input is discoverable.
    @property
    def input_purpose(self) -> str:
        properties = self.input_schema.get("properties")
        if not isinstance(properties, dict) or not properties:
            return "no input"
        required = self.input_schema.get("required")
        required_names = set(required) if isinstance(required, list) else set()
        parts = []
        for field, spec in list(properties.items())[:12]:
            kind = ""
            if isinstance(spec, dict):
                kind = str(spec.get("type") or "")
            marker = "" if field in required_names else " optional"
            parts.append(f"{field}{f' ({kind})' if kind else ''}{marker}")
        return ", ".join(parts)
