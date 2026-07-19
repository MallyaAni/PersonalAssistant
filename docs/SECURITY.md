# AniOS Security

This document separates current security facts from future requirements. A control labeled `PLANNED` is not implemented protection.

## Current security posture

- Chat and memory routes support expiring HMAC-signed local user tokens. Authentication is disabled by default for trusted local development; when `AUTH_REQUIRED=true`, missing/invalid/expired tokens return 401 and a token subject that differs from the requested user returns 403.
- `SECRET_KEY` signs local user tokens when authentication is enabled. It must be high-entropy, stored outside source control, and rotated if disclosed; current tokens have expiry but no revocation list.
- Compose contains development-only PostgreSQL credentials and an example backend secret in plaintext configuration. These values must not be reused outside local development.
- CORS allows credentials from `http://localhost:5173` and `http://127.0.0.1:5173`.
- The chat route validates a typed request and no longer prints the raw request body. Provider, framework, and manually added logs still require review because automated secret/PII redaction is not implemented.
- Chat system instructions, the current prompt, and up to the configured number of same-user prior conversation turns are sent to the separately running LM Studio process over local HTTP. The chat-completions adapter does not request a provider storage control, so provider configuration and process-level logging must be reviewed before sensitive use.
- Logging is ordinary text logging; automated secret or PII redaction is not implemented.
- Database-at-rest encryption, application-level encryption, encrypted backups, certificate pinning, scoped service credentials, and an audit log are not implemented by this repository.
- Redis and PostgreSQL ports are published to the host by the development Compose configuration.
- Personal-memory REST/UI deletion is implemented and queries filter by user ID. This is an authorization boundary only when signed-token authentication is enabled; auth-disabled mode is trusted-local logical scoping.
- Agent-memory tables for cache, working state, procedures, entities/relations, knowledge, and summaries are user-scoped and covered by export/delete-all and scoped record deletion. A dry-run/apply service and CLI purge expired application rows; external scheduling and backup deletion are not implemented.
- `MemoryCoordinatorAgent` receives only typed store methods. It selects bounded context deterministically and does not give Gemma SQL, raw table, durable-write, tool-invocation, or authorization capabilities.
- Retrieved personal, knowledge, procedure, entity, summary, and toolbox values are placed in a prompt section labeled as untrusted literal data. This is a defense-in-depth prompt boundary, not a complete prompt-injection sandbox.
- The developer UI stores its active user and conversation IDs in browser local storage. Missing or legacy `dev_user_001` state now defaults to `ani.mallya`, but this convenience identifier is not authentication or proof of identity; production-like use must enable signed ownership checks.
- Assistant text is treated as untrusted CommonMark. ReactMarkdown creates approved React elements without enabling raw HTML parsing; browser acceptance proves an injected image/event handler creates no element and executes no script. User messages remain literal text.
- Preferred-name and response-style proposals are not persisted before explicit UI approval. Generic fact approval, correction, export, and deletion are constrained to the token subject when auth is enabled; auth-disabled mode remains caller-user-ID scoped.
- Semantic memory content is sent over local HTTP to the LM Studio embedding process. The configured embedding endpoint does not request provider-side storage, but LM Studio process logging/configuration must still be reviewed for sensitive use.
- Knowledge chunks, procedures, entities, summaries, tool descriptors, and semantic-cache queries are also sent to the configured local embedding process. Do not ingest secrets or private documents until LM Studio logging, retention, host access, and backup policy are acceptable for that data.
- No internet-search tool or outbound-search decision policy is implemented. Current chat traffic is sent only to the configured LM Studio endpoint; future search would add a separate external disclosure boundary.
- The maintainer architecture-candidate command sends the selected canonical diagram, maintainer request, and explicitly selected repository text to LM Studio. It accepts only loopback endpoints; bounds file roots, types, counts, and sizes; rejects traversal and common secret filenames; labels repository text as untrusted evidence; and cannot overwrite canonical diagrams. These controls do not detect every secret inside an otherwise allowed source file, so maintainers must inspect selected context and LM Studio logging before use.
- Raster uploads accept only actual single-frame PNG, JPEG, or WebP content within configured byte and pixel limits; declared MIME must match decoded content. Validated bytes are stored under opaque hashed user namespaces with atomic writes, SHA-256/size integrity metadata, signed-user ownership when auth is enabled, private/no-store content responses, and file-plus-row deletion. The browser fetches private bytes through the authenticated API and uses a temporary object URL that is revoked on unmount. Automated retention, encrypted storage/backups, malware scanning, and redacted media audit events are not implemented.
- Validated image bytes and a bounded user prompt are sent over loopback HTTP to Gemma in LM Studio for vision analysis. They are not sent to ComfyUI or an internet provider, but LM Studio process logging, host access, and retention still require review before sensitive images are used.

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

- `VERIFIED`: optional signed local user authentication and route ownership checks; password-based login, token revocation, and account administration remain `PLANNED`;
- `PLANNED`: scoped API and service tokens with expiration and revocation;
- `VERIFIED`: subject ownership checks cover current chat, conversation snapshot/export/deletion, personal-memory, tool-memory, visual-artifact, generated-image, upload, content, and image-analysis routes when auth is enabled; live tool execution still requires authorization work;
- `PLANNED`: OS keychain or dedicated secret-store integration;
- `PLANNED`: encryption at rest and encrypted, tested backups;
- `PLANNED`: structured audit events with trace IDs and sensitive-data redaction;
- `PLANNED`: prompt-injection defenses and trust labels for retrieved or external content;
- `PLANNED`: sandboxing, allowlists, least-privilege credentials, and explicit user confirmation for tools;
- `VERIFIED`: stored tool descriptors/searches and user-tool memories are partitioned by user and server; changed schema fingerprints deactivate prior descriptors. Live registry refresh and pre-invocation revalidation remain `PLANNED`;
- `VERIFIED`: tool-memory APIs have no raw argument/output/resource/credential fields, accept only allowlisted derived preferences and outcome categories, and reject common credential/secret markers. Broader PII classification remains `PLANNED`;
- `VERIFIED`: semantic tool discovery is persistence metadata only and grants no permission or invocation path. Trusting live server metadata, authorization, confirmations, and execution remain `PLANNED`;
- `PLANNED`: a deterministic outbound-search gate that decides whether current information is required before the model can invoke search;
- `PLANNED`: outbound data classification and minimization that blocks credentials, secrets, private memory, private document text, and identifying health, financial, legal, account, or precise-location data from search queries;
- `PLANNED`: user review of the sanitized query whenever useful search depends on private or materially identifying context; if a safe query cannot be formed, no request is sent;
- `PLANNED`: treat search results as untrusted content, isolate them from system/tool instructions, cite sources, and record a redacted decision audit without retaining the sensitive source text;
- `PLANNED`: TLS and outbound-provider trust controls;
- `VERIFIED`: diagram artifacts have logical user ownership, conversation/trace provenance, allowlisted type/size/line validation, strict browser rendering with HTML labels disabled, sanitized failure events, scoped listing/deletion, and local Mermaid/SVG download. Auth remains disabled by default for trusted-local development;
- `VERIFIED`: upload MIME/signature/size/pixel limits, single-frame enforcement, opaque local binary-file isolation, integrity checks, private content responses, media file-plus-row deletion, and generated-image disconnect cancellation with terminal state and provider interruption. Binary retention/export, encryption/backups, malware scanning, and process-crash reconciliation remain `PLANNED`; diagram-stream disconnect cleanup is also `VERIFIED`;
- `PLANNED`: mobile token storage and biometric integration;
- `VERIFIED`: application-level expiry, deterministic scoped purge, JSON export, correction, scoped record deletion, and delete-all propagation across current PostgreSQL tables; external scheduling, log/backup deletion, and encrypted backup lifecycle remain `PLANNED` and are intentionally deferred to the final security subsystem.

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
