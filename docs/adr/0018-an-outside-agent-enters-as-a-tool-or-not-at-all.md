# ADR 0018: An outside agent enters as a tool, or not at all

- Status: Accepted 2026-08-29. Applied twice on the day it was written: OpenClaw and DeepSeek Harness both assessed and both declined as runtimes, with the capability each was wanted for routed through the existing MCP boundary instead.
- Date: 2026-08-29

## Context

The operator wants the assistant to *do* things — book a table, fill a form,
put an event in a calendar — and twice in one day a published agent framework
looked like the shortest path there: first OpenClaw, then
[DeepSeek Harness](https://deepseek-harness.github.io/deepseek-harness/)
(`dsh`, MIT, `v0.1.2-alpha.1`, first published 2026-08-13).

Both are real, capable projects. `dsh` in particular is well documented, is
built as plugins over a Cordis kernel, and — checked rather than assumed — can
be pointed at this project's own vLLM endpoint with a placeholder credential,
so "it needs a cloud API key" is *not* the reason to decline it.

The reasons that matter are about this system.

## Decision

**A capability from outside enters AniOS as an MCP tool behind the existing
invocation boundary, or it does not enter.** No second agent runs beside this
one.

AniOS is deliberately one agent with one outbound boundary
(`docs/ARCHITECTURE.md`), one privacy screen on everything that leaves
(`backend/core/egress.py`), one risk classification per tool server, and one
place where a consequential action stops and asks
(`backend/services/mcp_invocation_service.py`). A second agent framework
running beside it does not inherit any of that: it brings its own tool
registry, its own approval prompt, its own session log and its own outbound
calls. Two things that can act on the operator's behalf under different rules
is not twice the capability; it is a boundary that no longer means anything.

Three specific findings behind the `dsh` decision, each verified rather than
assumed:

- **It does not solve the problem it was wanted for.** Core `dsh` has no
  browser automation and no computer use; its `packages/web` README says the
  web group "owns web access only: no browsing or extraction". The browser
  capability associated with it comes from third-party community plugins, two
  of which are ordinary **MCP servers** — which this system can consume
  directly, today, through `MCP_SERVERS_JSON`.
- **It cannot sit behind our boundary.** `dsh` is an MCP *client* only; there
  is no server package. It could only be shelled out to as a peer, owning its
  own registry, approvals and egress — the definition of a second agent.
- **The maturity does not match the deployment.** Sixteen days old at the time
  of writing, alpha, issues disabled, breaking changes promised, and a
  workstation posture throughout: a loopback-only single-user web UI, a
  workspace-rooted filesystem, an SDK profile that pins `danger-full-access`,
  and plugin installation through `pnpm`. This system serves a real operator
  and approved users on two machines that need a physical button press to
  restart.

## Consequences

- The booking and browsing work stays as planned: a new MCP server, classified
  so it is **not** auto-invocable, so every call goes through the same gates as
  any other consequential tool — argument egress screening, descriptor
  fingerprinting, and a confirmation that names the amount.
- Third-party MCP servers are third-party code. They get pinned versions and
  their own container, and they are never `npx -y` at run time.
- A booking is a *write* with money or identity attached. It gets the treatment
  `send_imessage` already has: the model proposes, a person confirms, and the
  target is never something the model wrote.
- This ADR is not a judgement on either project, and it should be revisited if
  one of them ever ships something as an MCP server. The rule is about where a
  capability sits, not about who wrote it.

## Alternatives considered

- **Adopt `dsh` as the runtime and port AniOS onto it.** Rejected: it would
  replace an encrypted multi-user service with a workstation agent, and every
  component named as replaceable (the loop, the registry, the approval policy,
  sessions, scheduling) turned out to be a regression on inspection — AniOS's
  selector is deliberately narrower than a generic registry, its approval
  policy classifies servers and screens arguments, and its sessions are sealed.
- **Run `dsh` as a subprocess for "hard" tasks only.** Rejected: that is the
  second agent, with a smaller blast radius but the same missing boundary.
- **Take its ideas and none of its code.** Accepted where they apply. The one
  worth naming is its provider `compat` block, and this project already has
  provider-neutrality by configuration.
