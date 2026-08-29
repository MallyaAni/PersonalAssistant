# The browser: a tool AniOS drives, not a second agent

How the assistant reaches a web page, why every gate in front of it is code
rather than an instruction, and what is not built yet.

The decision to take a browser as a tool rather than adopt an agent framework
is [ADR 0018](adr/0018-an-outside-agent-enters-as-a-tool-or-not-at-all.md).

## What it is

Microsoft's [Playwright MCP server](https://github.com/microsoft/playwright-mcp),
running as the `browser` container. It was taken rather than written because
the browser lifecycle, the ~24 interaction tools, and - the part that matters
most - the accessibility-tree snapshot are somebody else's maintained problem.
That snapshot is why no vision model is in this loop: the local DeepSeek reads
real DOM semantics rather than guessing at pixels.

What was *not* taken is the deciding: which page, which button, whether to
submit. That stays here, on the local model, inside this boundary.

## The five gates in front of it

Every one is enforced in code. None of them asks a model to behave.

1. **It is not auto-invocable.** `risk_classification: "untrusted"` means
   `backend/services/mcp_invocation_service.py` raises `confirmation_required`
   unless the call carries an explicit confirmation. Same class as the iMessage
   bridge: the model proposes, a person says yes, and only then does it run.
2. **Only named tools exist.** `allowed_tools` in `MCP_SERVERS_JSON` names the
   thirteen navigation tools that may ever be listed or called. The server's
   own catalogue is twenty-four and includes `browser_run_code_unsafe`,
   `browser_evaluate` and `browser_file_upload`; those are filtered out in
   `backend/mcp/client.py` before anything is indexed, so the model is never
   shown them and a stale descriptor cannot reach them
   (`mcp_invocation_service.resolve_tool` checks again).
3. **Only named hosts.** `navigates: true` makes an empty `allowed_hosts` mean
   *nowhere* rather than *anywhere*, and every argument that parses as a URL is
   checked against the list. Subdomains of a permitted host pass, because a
   booking flow moves between them; a suffix that is not on a dot boundary does
   not, so `notopentable.com` is refused.
4. **The browser refuses too.** `--allowed-origins` is the same rule enforced
   one layer down, and it covers what our layer cannot see: the subresources a
   page pulls in by itself. It defaults to an unresolvable origin, because
   passing this flag an empty value means "no restriction" rather than
   "nothing" - found by measurement, when a navigation succeeded through an
   empty list.
5. **Arguments are screened for egress** by the same `OutboundPrivacyPolicy`
   every other tool call passes, so a personal identifier cannot ride out in a
   URL.

Around those: the container has no capabilities (`cap_drop: ALL`), cannot gain
privileges, keeps its profile in memory so no cookie or card survives a run,
and sits on its own Docker network with no route to Postgres, Redis or the
model. Its Host-header allowlist (`--allowed-hosts`, a different thing from
`--allowed-origins` despite the name) names only `browser:8931`, so nothing
outside the compose network can drive it.

## Measured, on 2026-08-29

Run from inside the application against the live container:

```
1. the server's whole catalogue: 24 tools
   of which dangerous ones present: ['browser_evaluate', 'browser_file_upload', 'browser_run_code_unsafe']
2. after the allowlist: 13 tools
3. can it be called without a confirmation? False
   unconfirmed call refused: confirmation_required
4. confirmed, but no host named: host_not_allowed
5. a tool outside the allowlist: tool_not_offered
6. a host outside the allowlist: host_not_allowed
7. the permitted host, confirmed: Page URL: https://example.com/ - Page Title: Example Domain
```

With the shipped defaults, step 7 instead returns `ERR_BLOCKED_BY_CLIENT`: the
browser's own layer refuses, because no origin has been named.

## Status

| Piece | State |
| --- | --- |
| The container, pinned, isolated, on its own network | Deployed 2026-08-29 |
| Tool allowlist, enforced at the catalogue and again at the call | Deployed 2026-08-29 |
| Host allowlist, fail-closed for anything that navigates | Deployed 2026-08-29 |
| Proven end to end through the invocation service | Measured above |
| **Enabled for the operator** | **No** - not in `MCP_SERVERS_JSON`, and no host named |
| The navigation loop (page → constrained action → repeat) | **Not built** |
| A booking proposal a person confirms in the thread | **Not built** |
| Dry-run screenshot before any submit | **Not built** |

## What is deliberately not done

- **No stored card, ever.** The profile is in memory and the plan stops at
  payment: the checkout link goes to the phone for Apple Pay rather than the
  browser typing a card number. If that is ever to change, the only version
  worth building is a virtual card with its own low limit.
- **No logins, no captchas** until the plain-form path is proven on a form we
  own.
- **Nothing submitted without a confirmation naming the amount.** A booking is
  a write with money and identity attached; it gets the treatment
  `send_imessage` already has, where the target is never something the model
  wrote.
- **Not enabled by default.** The container runs; the tool is not offered to
  the model, because `MCP_SERVERS_JSON` does not list it yet.

## Tests

- `backend/tests/test_mcp_tool_allowlist.py` - the tool allowlist, the host
  allowlist, the fail-closed rule for navigating servers, and that a server the
  operator wrote is left alone.
