# AniOS Security

This document separates current security facts from future requirements. A control labeled `PLANNED` is not implemented protection.

## Current security posture

- AniOS supports invited password accounts. An operator mints an expiring
  one-time registration code; only its SHA-256 digest is stored, and browser
  registration consumes it atomically with account and session creation.
  Argon2id hashes are stored for
  passwords; a successful login creates a random opaque browser token, while
  PostgreSQL stores only its SHA-256 digest. The host-only cookie is HttpOnly,
  SameSite=Lax by default, revocable on logout, password reset, or account
  disable, and must use `Secure=true` for HTTPS deployment. There is an
  invitation-gated registration endpoint, not unrestricted public signup.
- Login names and owned data identities are separate even when their values are
  equal. The current primary account uses `ani.mallya` for both; every protected
  handler uses that server-derived owner and rejects a different path/body user
  with 403. Authentication is enabled in the current local `.env` and the live
  backend was re-verified with `AUTH_REQUIRED=true`; an owner-token cross-read
  of another Scout profile returns 403 and an anonymous read returns 401.
- Account storage contains the normalized login name, stable owner ID, Argon2id
  hash, active flag, and timestamps. Session storage contains the owner, token
  digest, expiry, and optional revocation time—never the raw token. Memory
  delete-all intentionally does not delete authentication records. The current
  CLI disables access and revokes sessions but offers no account deletion, so a
  future destructive account-removal workflow must enumerate owned data,
  backups, artifacts, and audit retention explicitly.
- Redis applies global attempt windows and normalized-login failure windows to
  both login and registration. The boundary fails closed if shared protection
  is unavailable and returns bounded retry time after repeated failures.
- Chat and memory routes retain expiring HMAC-signed bearer tokens for local
  automation and least-privilege testing. When authentication is required,
  missing, invalid, expired, or revoked browser sessions return 401 and a
  subject that differs from the requested user returns 403.
- A token may be restricted to least-privilege scopes (`chat`, `memory:read`, `memory:write`, `tools:invoke`, `vision`, or the `memory`/`tools` groups). A route requires the scope matching its action - a read needs `memory:read`, a write needs `memory:write` - and a token lacking it returns 403 before the handler runs. A token with no scope claim (the default, and every token issued before scopes existed) stays unrestricted, so scopes narrow a token without a migration. Scopes limit what a valid token can reach; they are not a substitute for the ownership check, which still binds every request to the token subject.
- `SECRET_KEY` signs legacy local bearer tokens when authentication is enabled.
  It must be high-entropy and stored outside source control. Those bearer tokens
  expire but are not individually revocable; password browser sessions are.
- Compose contains development-only PostgreSQL credentials and an example backend secret in plaintext configuration. These values must not be reused outside local development.
- CORS allows credentials from `http://localhost:5173` and `http://127.0.0.1:5173`.
- The chat route validates a typed request and no longer prints the raw request body. Provider, framework, and manually added logs still require review because automated secret/PII redaction is not implemented.
- Chat system instructions, the current prompt, and up to the configured number of same-user prior conversation turns are sent over the private Compose network to the `vllm-main` service. The chat-completions adapter does not request a provider storage control, so vLLM configuration and process-level logging must be reviewed before sensitive use.
- Logging is ordinary text logging; automated secret or PII redaction is not implemented.
- Optional application-level encryption at rest is implemented. With `ENCRYPTION_KEY` set to an AES-256 key, conversation turns, episodic and semantic memory content, presentation titles/specifications, image/PPTX artifact bytes, and the phone numbers collected at sign-up (on the access request and the subscriber row) are sealed with AES-256-GCM before they reach PostgreSQL or the artifact volume; with no key configured the content is stored as plaintext, unchanged from earlier behaviour. This is defence in depth for data that leaves the running process without the key - a database dump, a copied volume, or a disk read while the app is stopped. It does not protect against an attacker who already holds the running process and its in-memory key, and it is weaker than, not a replacement for, OS full-disk encryption (BitLocker/LUKS), which remains the at-rest baseline. Coverage is deliberately partial: embedding vectors stay searchable and therefore unencrypted (an embedding is a residual disclosure vector, since it can be partially inverted), and columns used for deduplication or uniqueness - notably `memory_facts.normalized_value` and `fact_key` - are not encrypted because randomized encryption would break the equality they depend on. Backups are tested and scheduled: a nightly dump, replicated to a second host, with a restore proven end to end on 2026-08-23 (37 tables, 2,506 rows identical to live) and 65 sealed values decrypted from the restored copy with the escrowed key - see `docs/RESTORE.md`. The dump *file* is not itself encrypted, only the sealed columns inside it, and a database-native at-rest option is not implemented. Both copies share a room, so this survives a disk rather than a site.
- Losing `ENCRYPTION_KEY` after content has been sealed makes that content unrecoverable, and turning encryption off while sealed rows exist causes reads of those rows to fail loudly rather than return ciphertext. The key must be stored outside source control and off the same volume as the backups it protects; it is escrowed off both Sparks, and `docs/RESTORE.md` verifies it still reads a restored dump rather than assuming it does. Certificate pinning, scoped service credentials, and an audit log are not implemented by this repository.
- Redis and PostgreSQL ports are published to the host by the development Compose configuration. Redis now stores only expiring model-execution coordination keys, foreground waiter counts, and opaque lease tokens; it receives no prompts, drafts, model answers, user IDs, or artifact content.
- Personal-memory REST/UI deletion is implemented and queries filter by user ID. This is an authorization boundary only when signed-token authentication is enabled; auth-disabled mode is trusted-local logical scoping.
- Agent-memory tables for cache, working state, procedures, entities/relations, knowledge, and summaries are user-scoped and covered by export/delete-all and scoped record deletion. A dry-run/apply service and CLI purge expired application rows; external scheduling and backup deletion are not implemented.
- Personal-memory delete-all also removes the same owner's visual artifact rows,
  derived visual descriptions/embeddings, and opaque binary files. Database
  deletion returns only owned storage keys to the cleanup service; a file error
  is surfaced and the existing storage collector remains the recovery boundary
  for unavoidable database/filesystem non-atomicity.
- `MemoryCoordinatorAgent` receives only typed store methods. It selects bounded context deterministically and does not give the configured generation model SQL, raw table, durable-write, tool-invocation, or authorization capabilities.
- Retrieved personal, knowledge, procedure, entity, summary, and toolbox values are placed in a prompt section labeled as untrusted literal data. This is a defense-in-depth prompt boundary, not a complete prompt-injection sandbox.
- The private UI obtains its user identity from `/api/v1/auth/session`; it does
  not accept a local-storage user switch. Browser local storage contains only
  per-owner conversation and presentation job identifiers. Trusted-local mode
  deliberately returns configured owner `ani.mallya` without login, so it must
  not be exposed to another person or a public URL. The mobile navigation
  drawer displays the active account beside a labeled logout action so account
  switching does not depend on recognizing a compact header icon.
- Assistant text is treated as untrusted CommonMark. ReactMarkdown creates approved React elements without enabling raw HTML parsing; browser acceptance proves an injected image/event handler creates no element and executes no script. User messages remain literal text.
- Every chat-classified memory proposal (preferred name, response style, discovery interests/locality, entities, procedures, knowledge, episodic and semantic facts) is persisted immediately by the application, with no user approval step; the reply-adjacent card reports what was already written, for visibility and debugging, not consent. Generic fact correction, export, and deletion are constrained to the token subject when auth is enabled; auth-disabled mode remains caller-user-ID scoped.
- The iMessage bridge is the one inbound message-content ingress. Behind a
  separate Mac-side grant (`IMESSAGE_BRIDGE_READ_INCOMING`, off by default), its
  `read_messages` tool returns the bodies of incoming one-to-one iMessages from
  senders on the Mac operator's allowlist. Who may be heard is decided on the
  Mac, never by the caller; strangers' bodies are filtered inside the bridge
  process and never leave it, and bodies are never logged on either machine
  (no redaction layer exists). Group chats are a separate, env-only grant
  (`IMESSAGE_BRIDGE_GROUPS` + `IMESSAGE_BRIDGE_READ_GROUPS`, 2026-08-28):
  from a listed room only messages addressed to the assistant - a reply in a
  thread on its bubble, a mention, its name - from allowlisted senders are
  forwarded, with the room's participant list; everything else in the room
  is discarded on the Mac. The backend adds a second wall: every participant
  must be an approved subscriber or the room is answered nowhere (the
  operator is texted once a day per room, without the strangers' addresses).
  A room is its own account; what it may know about a member is a fixed
  allowlist (name and Scout interests, `backend/memory/tastes.py`), and a
  fact said in the room is never written into another member's memory
  (`backend/memory/attribution.py`; ADR 0016). Inbound text runs through the same
  conversation pipeline as the web UI, **including immediate memory
  persistence — an explicit operator decision** (2026-08-21). What makes that
  acceptable for senders beyond the operator is **per-sender account
  scoping**, verified live 2026-08-22: each allowlisted address maps to that
  person's own account, so their turns run in their context, their texts
  persist into their memory only, and no sender's prompt carries another
  account's memory. A sender's words can still become durable facts with no
  approval step — but only their own. Storage and deletion follow the
  existing conversation/memory paths (sealed under `ENCRYPTION_KEY` like
  every other turn); the backend's poll-cursor and dedup state hold
  addresses and opaque identifiers, never bodies. Denying a request clears
  its phone, phone digest, and password hash; deleting an account also
  deletes the access request that created it (which the schema-driven purge
  cannot reach, as it has no `user_id` column), so a number does not outlive
  the person.
- **The phone/address lookup digest is a keyed HMAC** (closed 2026-08-25;
  was the recorded unkeyed-digest gap). `discovery.addressing.address_digest`
  is HMAC-SHA256 keyed from `ENCRYPTION_KEY` (falling back to `SECRET_KEY`
  where no sealing key is configured), used by sign-up, approval, subscriber
  enrolment, and iMessage sender matching alike, so a database dump alone no
  longer lets the ~10^10 phone keyspace be enumerated offline. Existing rows
  were re-digested with `backend/cli/rekey_address_digests.py` — idempotent,
  and the digest dies with its key: rotating `ENCRYPTION_KEY`, or restoring
  a dump from before the rekey, requires running it again or approved people
  silently stop being recognised. The Mac bridge keeps normalized plaintext
  allowlists and is unaffected. A source-inspection test pins all four call
  sites to the keyed function.
- Semantic memory content is sent over the private Compose network to the `vllm-embedding` service. The configured embedding endpoint does not request provider-side storage, but vLLM process logging/configuration must still be reviewed for sensitive use.
- Knowledge chunks, procedures, entities, summaries, tool descriptors, and semantic-cache queries are also sent to the configured local embedding process. Do not ingest secrets or private documents until vLLM logging, retention, host access, and backup policy are acceptable for that data.
- Internet research is an explicit outbound boundary: deterministic routing and
  query normalization run before `OutboundPrivacyPolicy`;
  credential/account identifiers are blocked, personal framing is minimized,
  and only the resulting public query reaches the read-only
  `internet/search_web` MCP server. The provider policy prefers an isolated
  request-isolated Gemini 3.5 Flash-Lite/Google Search worker when configured, falls back
  to Tavily, and uses both only for explicit verification. The Google worker
  receives no AniOS identity, history, memory, private document, image bytes,
  credentials, or general tools. For an explicit search about a recalled image,
  one bounded stored analysis or generation prompt may be appended before the
  same screening; image bytes are never sent, and a sensitive combined query is
  blocked. Result text is bounded and quoted as untrusted data. Broad PII
  classification and approval for sensitive-but-useful queries remain
  incomplete.
- Google's unpaid Gemini service may use submitted prompts and responses to
  improve its products and may subject them to human review. Do not route
  sensitive, confidential, personal, or private-memory content to that worker.
  The local SQLite budget stores only provider, Pacific date, and request count;
  it contains no query or result text. Its 450/day default is a protective cap,
  not a contractual or distributed rate limit, and AniOS never enables billing
  automatically.
- Qwen may choose at most one action per turn from a single native tool-calling call offered by `MainActionSelector`: the live `search_web` schema, built-in image/diagram/delegation actions, and a user-scoped semantic shortlist of the user's own tools whose schemas were re-read from locally configured `trusted` or `read_only` MCP servers. A name the call did not actually offer this round is refused before any downstream effect, regardless of what the model returns. The model cannot invoke a toolbox tool directly: AniOS revalidates the live fingerprint, description, schema, arguments, and privacy policy. Consequential servers are not offered to autonomous chat selection.
- The application-owned local capability FastMCP server is configured `untrusted` and
  requires explicit confirmation. Its schemas omit user, conversation, and
  trace identifiers; the backend forwards those values as request metadata
  only because this local server opts into `forward_context`. Other MCP servers
  receive no application context by default. Visual and presentation tool
  results omit binary bytes and private storage keys, but the sidecar still has
  database, artifact-volume, vLLM, ComfyUI, and presentation-renderer
  access and is not a security sandbox.
- Stdio MCP children receive the SDK's default safe environment plus only
  operator-named `inherit_env` variables. The built-in internet server inherits
  Tavily and Google search configuration names; secret values are not stored in
  descriptor memory, MCP JSON examples, quota storage, model prompts, source
  cards, or tool-status events.
- The maintainer architecture-candidate command sends the selected canonical diagram, maintainer request, and explicitly selected repository text to the configured local inference endpoint. It accepts only loopback endpoints; bounds file roots, types, counts, and sizes; rejects traversal and common secret filenames; labels repository text as untrusted evidence; and cannot overwrite canonical diagrams. These controls do not detect every secret inside an otherwise allowed source file, so maintainers must inspect selected context and provider logging before use.
- Raster uploads accept only actual single-frame PNG, JPEG, or WebP content within configured byte and pixel limits; declared MIME must match decoded content. Validated bytes are stored under opaque hashed user namespaces with atomic writes, SHA-256/size integrity metadata, signed-user ownership when auth is enabled, private/no-store content responses, and file-plus-row deletion. The browser fetches private bytes through the authenticated API and uses a temporary object URL that is revoked on unmount. Automated retention, encrypted storage, malware scanning, and redacted media audit events are not implemented; backups are tested and scheduled (`docs/RESTORE.md`).
- Validated image bytes and a bounded user prompt are sent over the private Compose network to Qwen in `vllm-main` for vision analysis. They are not sent to ComfyUI or an internet provider, but vLLM process logging, host access, and retention still require review before sensitive images are used.
- A successful initial image analysis creates an owner-scoped derived semantic
  description containing only the artifact handle, bounded analysis text, and
  model provenance. Recall joins that entry back to a ready artifact owned by
  the same user before it can reach a prompt. Deleting the artifact deletes its
  derived description in the same PostgreSQL commit; legacy orphan rows remain
  inaccessible and cannot consume the live retrieval shortlist.
- Presentation briefs and selected-slide feedback are sent only to Qwen in the configured local vLLM service. Creation briefs and progressive drafts are persisted on user-scoped durable jobs; `ENCRYPTION_KEY` seals those text fields through the same AES-256-GCM column boundary as the deck specification. Each feedback revision also stores the non-secret stable target slide ID needed to reconstruct its owned per-slide conversation. The model sees no storage keys and cannot authorize, lease, persist, render, or promote revisions. A dedicated worker receives database and vLLM access so it can claim jobs and invoke the focused LangGraph; it is a process boundary, not a security sandbox. A dedicated local renderer receives only a strict validated deck specification; it writes to an isolated temporary directory, serializes LibreOffice jobs, returns bounded PPTX bytes, and cleans the temporary files. PostgreSQL stores user-scoped job state, append-only revision metadata, and the canonical specification; the opaque artifact volume stores each revision's PPTX. Owned deletion removes the deck, job/revision rows, and linked binaries. Automated retention, package malware scanning, and process isolation remain planned; backups are tested and scheduled (`docs/RESTORE.md`).

AniOS is therefore a local development scaffold, not a hardened system for sensitive production data.

## Current development requirements

- Never commit real API keys, tokens, passwords, private documents, or user memories.
- Use non-production credentials for local development and rotate any credential that is accidentally exposed.
- Do not include secrets, full prompts, personal content, or raw external documents in logs unless a narrowly scoped diagnostic explicitly requires it and the output is handled safely.
- Validate external input at the API boundary and return sanitized client errors without provider internals.
- Review CORS, published ports, debug settings, and logging before exposing the service beyond the local machine.
- Treat database resets and memory deletion as destructive operations requiring explicit approval.
- Document new data collected, its storage location, retention, deletion path, and every component allowed to access it.

## PLANNED security controls

The following controls are requirements for future milestones, not current features:

- `VERIFIED`: one-time invited registration, Argon2id password login,
  server-derived route ownership, shared login/registration attempt limits,
  HttpOnly browser sessions, logout, password reset, account enable/disable,
  and session revocation. Unrestricted signup, recovery, MFA, and a browser
  administration UI remain `PLANNED`;
- `VERIFIED` (bounded): user tokens carry least-privilege scopes enforced per route action, rejected unknown scopes fail at issue time, and unscoped tokens stay unrestricted for compatibility; token revocation and service-to-service tokens remain `PLANNED`;
- `VERIFIED`: subject ownership checks cover current chat, conversation snapshot/export/deletion, personal-memory, tool-memory, visual-artifact, generated-image, upload, content, image-analysis, presentations/revisions/download/deletion, and explicit/chat-initiated tool routes when auth is enabled; per-server user credential scopes remain `PLANNED`;
- `PLANNED`: OS keychain or dedicated secret-store integration;
- `VERIFIED` (bounded, opt-in): AES-256-GCM application-level encryption of conversation, memory, image, and presentation content when `ENCRYPTION_KEY` is set, with lazy plaintext migration and authenticated ciphertext; full-store coverage (embeddings and dedup columns are intentionally excluded), tested and scheduled backups are `VERIFIED` (restore and key-decryption proven, `docs/RESTORE.md`) while encryption of the dump file itself and a database-native at-rest option remain `PLANNED`;
- `PLANNED`: structured audit events with trace IDs and sensitive-data redaction;
- `VERIFIED` (bounded): live MCP descriptions and results are inspected, instruction-shaped descriptions are quarantined, and external values are labeled untrusted; comprehensive prompt-injection isolation remains `PLANNED`;
- `PLANNED`: sandboxing, allowlists, least-privilege credentials, and explicit user confirmation for tools;
- `VERIFIED`: stored tool descriptors/searches and user-tool memories are partitioned by user and server; changed schema fingerprints deactivate prior descriptors, and every invocation performs live registry re-resolution. Automatic refresh/change notifications remain `PLANNED`;
- `VERIFIED`: tool-memory APIs have no raw argument/output/resource/credential fields, accept only allowlisted derived preferences and outcome categories, and reject common credential/secret markers. Broader PII classification remains `PLANNED`;
- `VERIFIED`: semantic tool discovery is persistence metadata only and grants no permission; native selection produces only a plan, while live local trust, confirmation policy, schema validation, and privacy gates authorize execution;
- `VERIFIED` (bounded): application context forwarding is opt-in per configured
  MCP server; the local capability facade keeps ownership IDs outside model-visible
  arguments and returns public artifact metadata only. Service-to-service
  authentication, network isolation, and per-server credential scopes remain
  `PLANNED`;
- `VERIFIED`: whether a turn needs live search is the main model's own native
  tool-calling decision (`MainActionSelector`), not a deterministic gate — the
  retired regex-plus-classifier cascade remains in the tree, tested standalone,
  but is no longer reachable from a live turn. The model chooses to call the
  tool and writes the query; it still cannot execute the call itself or reach
  the network directly. The query it writes passes through the same
  egress screening, minimization, and budget enforcement described below
  regardless of how the decision was reached, and a tool name the model
  returns that was not actually offered in that round's call is refused
  before any downstream effect;
- `VERIFIED` (bounded): outbound query classification/minimization blocks credentials, common account identifiers, and identifying personal framing; broader PII/document classification remains `PLANNED`;
- `PLANNED`: user review of the sanitized query whenever useful search depends on private or materially identifying context; if a safe query cannot be formed, no request is sent;
- `VERIFIED` (Tavily runtime; Google deterministic): search results are bounded
  untrusted prompt data and source cards preserve per-provider provenance;
  claim-level citation evaluation, a durable redacted decision audit, and a
  live Google-grounding acceptance remain incomplete;
- `PLANNED`: TLS and outbound-provider trust controls;
- `VERIFIED` (local boundary): a loopback-only same-origin Nginx gateway serves
  the compiled UI and proxies API/SSE/upload/download traffic. `PLANNED`:
  remote-UI ingress through one TLS hostname and an
  authenticated deny-by-default edge/tunnel. The edge must protect both static
  UI assets and `/api`, validate its session at the origin, proxy SSE and
  bounded uploads/downloads, and forward only to a same-origin local gateway.
  PostgreSQL, Redis, vLLM, ComfyUI, the renderer, artifact storage, and
  internal MCP services must remain non-public. A client-side-only password,
  secret embedded in JavaScript, unprotected static host, or public backend
  port is not an acceptable access control.
- `VERIFIED`: diagram artifacts have logical user ownership, conversation/trace provenance, allowlisted type/size/line validation, strict browser rendering with HTML labels disabled, sanitized failure events, scoped listing/deletion, and local Mermaid/SVG download. Auth remains disabled by default for trusted-local development;
- `VERIFIED`: upload MIME/signature/size/pixel limits, single-frame enforcement, opaque local binary-file isolation, integrity checks, private content responses, media file-plus-row deletion, and generated-image disconnect cancellation with terminal state and provider interruption. Binary retention/export, encryption of the dump file, malware scanning, and process-crash reconciliation remain `PLANNED`; diagram-stream disconnect cleanup is also `VERIFIED`;
- `VERIFIED`: refinements of generated, uploaded, or slide-attached images
  re-check ownership and stored byte integrity,
  send source pixels only to the configured local ComfyUI editor, validate the
  returned image before persistence, and retain immutable parent/source-hash
  provenance. Semantic post-edit verification remains `PLANNED`;
- `PLANNED`: generated-image observations, OCR, visual aliases, and semantic-description vectors inherit the source artifact's ownership, retention, export, correction, and deletion policy. Memory records must contain immutable owned handles rather than copied image bytes; every later use must re-check ownership, readiness, integrity, and deletion state. Sensitive OCR/derived descriptions require the same local-provider and residual-embedding disclosure treatment as personal semantic memory;
- `VERIFIED` (bounded): presentation inputs use strict typed schemas and size limits; job reads/cancellation are owner-scoped; encrypted job briefs/drafts are supported; stale-base edits fail before model use; only a validated ready revision can become current; downloads are private/no-store and ownership-scoped; structural OOXML and LibreOffice checks reject malformed output; and model/MCP responses expose no PPTX bytes or storage keys. Package malware scanning, worker/renderer sandboxing, retention, and service-to-service authentication remain `PLANNED`; tested backups are `VERIFIED`;
- `PLANNED`: mobile token storage and biometric integration;
- `VERIFIED`: application-level expiry, deterministic scoped purge, JSON export, correction, scoped record deletion, and delete-all propagation across current PostgreSQL tables; external scheduling, log/backup deletion, and encrypted backup lifecycle remain `PLANNED` and are intentionally deferred to the final security subsystem.
- `VERIFIED`: discovery export/delete coverage includes interests, localities,
  sources, seen items, subscribers, familiar items, schedules, and runs. Public
  API tests seed every table, verify exported categories and deletion counts,
  assert no owned rows remain, and prove another user's rows are untouched.
- `VERIFIED`: semantic Scout-interest capture sends only the current utterance
  to the configured local Qwen endpoint, requires grammar-constrained bounded
  output, and gives the classifier no persistence or tool capability. The
  application immediately performs an atomic user-scoped fact/profile write
  when the classifier proposes one, with no user approval step; model failure
  or a capacity conflict writes nothing.

## Security review for a change

Before accepting a security-sensitive feature, verify:

1. what untrusted input and sensitive data enter the flow;
2. authentication and authorization at every boundary;
3. least-privilege database, filesystem, network, and tool access;
4. secret storage and log redaction;
5. prompt-injection and data-exfiltration risks for LLM or retrieval paths;
6. retention, deletion, and failure behavior;
7. applicable functional security tests.

Record current blockers in [NEXT_SESSION.md](NEXT_SESSION.md), milestone requirements in [ROADMAP.md](ROADMAP.md), and durable security architecture decisions as new ADRs.

These future-tool requirements follow the data-minimization direction of the [NIST Privacy Framework](https://www.nist.gov/privacy-framework) and the least-functionality, complete-mediation, and sanitization guidance in OWASP's [Sensitive Information Disclosure](https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/) and [Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) risk descriptions. System prompts alone are not treated as an enforceable privacy control.

The MCP design also follows the [protocol's tool guidance](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) to treat tool annotations as untrusted unless they originate from trusted servers and to keep users able to inspect and deny tool calls. Tool discovery metadata is therefore a hint for selection, never an authorization decision.
