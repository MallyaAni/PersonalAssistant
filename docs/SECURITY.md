# AniOS Security

This document separates current security facts from future requirements. A control labeled `PLANNED` is not implemented protection.

## Current security posture

- The FastAPI routes do not implement authentication or authorization.
- `SECRET_KEY` is required by settings, but no current request path uses it to validate a token.
- Compose contains development-only PostgreSQL credentials and an example backend secret in plaintext configuration. These values must not be reused outside local development.
- CORS allows credentials from `http://localhost:5173` and `http://127.0.0.1:5173`.
- The chat route prints the raw request body. Requests may contain personal content, so this diagnostic logging is not suitable for sensitive or production use.
- Logging is ordinary text logging; automated secret or PII redaction is not implemented.
- Database-at-rest encryption, application-level encryption, encrypted backups, certificate pinning, scoped service credentials, and an audit log are not implemented by this repository.
- Redis and PostgreSQL ports are published to the host by the development Compose configuration.
- Personal profile and memory models exist, but access-control and deletion workflows are not implemented.

AniOS is therefore a local development scaffold, not a hardened system for sensitive production data.

## Current development requirements

- Never commit real API keys, tokens, passwords, private documents, or user memories.
- Use non-production credentials for local development and rotate any credential that is accidentally exposed.
- Do not include secrets, full prompts, personal content, or raw external documents in logs unless a narrowly scoped diagnostic explicitly requires it and the output is handled safely.
- Validate external input at the API boundary. The current raw chat-body parsing is not a model for future endpoints.
- Review CORS, published ports, debug settings, and logging before exposing the service beyond the local machine.
- Treat database resets and memory deletion as destructive operations requiring explicit approval.
- Document new data collected, its storage location, retention, deletion path, and every component allowed to access it.

## PLANNED security controls

The following controls are requirements for future milestones, not current features:

- `PLANNED`: local user authentication and secure password handling;
- `PLANNED`: scoped API and service tokens with expiration and revocation;
- `PLANNED`: authorization boundaries for conversations, profiles, memories, documents, and tools;
- `PLANNED`: OS keychain or dedicated secret-store integration;
- `PLANNED`: encryption at rest and encrypted, tested backups;
- `PLANNED`: structured audit events with trace IDs and sensitive-data redaction;
- `PLANNED`: prompt-injection defenses and trust labels for retrieved or external content;
- `PLANNED`: sandboxing, allowlists, least-privilege credentials, and explicit user confirmation for tools;
- `PLANNED`: TLS and outbound-provider trust controls;
- `PLANNED`: mobile token storage and biometric integration;
- `PLANNED`: retention, export, correction, and deletion controls for personal data.

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
