# ADR 0004: Hybrid Free-Tier Web Research

## Status

Accepted and partially runtime verified. The isolated Google ADK worker,
Google-first/Tavily-fallback policy, explicit cross-check mode, durable
non-content quota, MCP provenance, and browser source attribution are
implemented. Deterministic tests verify the Google branch; live direct API and
Chromium acceptance verify the Tavily fallback. Live Google calls were attempted
on 2026-07-23: Gemini 2.5 Flash and Flash-Lite rejected the new account, while
Gemini 3.5 Flash-Lite returned zero available Search Grounding quota. A real
Google-grounded result therefore remains `FAILED` for the tested free-only
account.

## Context

AniOS needs current public information without granting the primary local model
unrestricted internet access or paying for search. The existing deterministic
routing, outbound privacy screening, read-only MCP server, and Tavily adapter
already established the correct trust boundary. Google publishes model- and
plan-specific Search Grounding allowances in its
[current pricing](https://ai.google.dev/gemini-api/docs/pricing), and
[Google ADK](https://github.com/google/adk-python) provides a focused agent and
native search tool. Google's
[unpaid-service terms](https://ai.google.dev/gemini-api/terms) allow prompts
and responses to be used to improve Google products. Sending conversation
history or personal memory would therefore violate AniOS's data-minimization
direction.

The long-term architecture also needs specialized workers without allowing a
worker model to own permissions, provider selection, budget, durable state, or
the final user response.

## Decision

1. Gemma remains the local coordinator/final-answer model. Deterministic
   application policy decides whether internet research is allowed and
   privacy-screens the query before any provider call.
2. The primary optional research provider is a request-scoped Google ADK
   `Agent` using `gemini-3.6-flash` and the native `google_search` tool.
3. Every Google call uses a new in-memory single-turn session with prior
   contents disabled. The worker receives only the minimized public query under
   a constant anonymous worker ID. It receives no AniOS user/conversation ID,
   history, personal memory, private documents, image bytes, credentials, or
   general MCP tools.
4. Google output is accepted only when grounding metadata supplies attributable
   web sources. Missing or empty grounding is a provider failure, not an
   authority to answer without provenance.
5. Tavily is the fallback when Google is unconfigured, unavailable, empty,
   times out, or exhausts its local budget. An ordinary request spends only one
   provider. Explicit "verify", "cross-check", "double-check", or corroboration
   language runs each configured provider once and URL-deduplicates the merged
   sources.
6. A SQLite counter reserves Google calls atomically across short-lived stdio
   MCP processes. It stores only provider, Pacific calendar date, and count in
   a dedicated volume. The default limit is 450 calls/day as a local safety
   ceiling; it does not guarantee provider quota or free access. AniOS never
   enables billing or a paid fallback automatically.
7. Provider attribution survives provider output, compact MCP JSON, local
   validation, SSE, and browser source cards. Scores are nullable because
   Google grounding metadata does not expose Tavily-style relevance scores.
8. This worker is a specialized research subagent behind a narrow
   `SearchProvider` contract. It is not a general LangGraph multi-agent graph,
   durable agent runtime, tool executor, or A2A peer.

## Consequences

Benefits:

- AniOS can combine two independently configured search providers without
  coupling chat orchestration to either vendor;
- normal queries preserve quota while explicit verification can obtain
  independent provider coverage;
- the cloud worker cannot inspect AniOS memory or authorize tools;
- outages, quota exhaustion, and unattributed Google output degrade to Tavily
  instead of failing the whole chat turn;
- source cards expose which provider supplied each result.

Costs and risks:

- Google and Tavily remain external trust boundaries and can observe the
  screened query plus network metadata;
- Google's unpaid-service terms permit product-improvement use and potential
  human review, so only non-sensitive public queries are acceptable;
- the local quota is a protective budget, not proof of Google's current
  server-side allowance, which can change;
- SQLite coordinates the current local/Compose deployment but is not a
  distributed global rate limiter;
- provider-specific grounding quality, rate limits, and API behavior still
  require live monitoring and periodic reevaluation.

## Alternatives considered

- Tavily-only search was functional but left free Google capacity and native
  grounding unused.
- Google-only search was rejected because a key, quota, or provider outage
  would remove all internet research.
- Sending full conversation context to Gemini was rejected because the worker
  needs only the public research question and unpaid-service data handling is
  unsuitable for private context.
- Letting Gemma choose providers or invoke internet tools directly was rejected
  because freshness eligibility, privacy, quota, and fallback are application
  policy.
- Calling both providers for every query was rejected because it wastes both
  free allowances and adds latency without an explicit verification need.
