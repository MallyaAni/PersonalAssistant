# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-08-02, America/New_York

## Current boundary

AniOS now supports operator-invited self-service profiles. The operator mints
an expiring one-time code, and a friend chooses their username and password in
the browser. The raw code is shown once; PostgreSQL stores only its digest.
Account creation, invitation consumption, and the first revocable session are
one transaction. There is no unrestricted public signup.

The production-style local entry point is `http://localhost:8080`. Its
loopback-only Nginx gateway serves the compiled React application and proxies
the API on the same origin. Public HTTPS ingress is not configured yet.

## Runtime, database, and Git identity

- Branch: `main`.
- Session-start and current `HEAD`:
  `31624f84796f6e1a22a702153d321e35502fc8a3`.
- Task source exercised: the current uncommitted working tree layered on that
  `HEAD`; no commit or push was authorized.
- Backend and gateway images were rebuilt from this working tree. The running
  backend has authentication enabled; gateway, backend, database, Redis, vLLM,
  renderer, worker, and local-capability services are healthy.
- Database migration head: `20260802_0025`.
- A pre-migration logical backup was written to
  `data/backups/anios_db-20260802-114539.sql.gz`. The encryption key is required
  to read sealed content after restore. No database reset, volume deletion, or
  recovery operation was used.

## VERIFIED

- A scratch database built 32 tables from zero at head `20260802_0025`; the
  real database upgraded additively from `0024` after the fresh backup.
- One-time registration stores only a SHA-256 digest and expiry, locks the code
  for consumption, creates a normalized owner/account, and issues the first
  digest-only session atomically. Reuse returns 400; username conflicts return
  409; login and registration share Redis attempt limits and 429 retry timing.
- The browser exposes sign in, invited profile creation, password confirmation,
  visible failures, and logout. Production output contains a relative API base,
  so remote clients use the gateway origin instead of their own localhost.
- Real Chromium through `http://localhost:8080` created two independent invited
  profiles. Profile A stored a unique semantic marker through the live Nomic
  embedding path, logged out, and profile B received 403 for A's memory, an
  empty own snapshot, and no result when semantically searching A's exact
  marker. After logout and password login, A saw its stored row and retrieved
  the marker semantically. Page exceptions were empty; only the expected 401
  and 403 network console entries occurred. All temporary accounts, sessions,
  invitations, and memory rows were removed afterward.
- Full backend regression: `772 passed` with seven dependency/deprecation
  warnings under the documented `AUTH_REQUIRED=false` test baseline; auth tests
  explicitly enable the boundary. Full deterministic Chromium regression:
  `44 passed`. The production TypeScript/Vite build passed with only the
  existing large-chunk advisory.
- The same-origin gateway serves the compiled application, proxies session and
  owned API requests, preserves SSE/upload settings, emits the configured
  response headers, and is loopback-only on the host.

## FAILED

- The first registration acceptance returned 409 because SQLAlchemy updated an
  invitation's account foreign key before inserting the new account. Flushing
  the account inside the same transaction fixed the first failing boundary;
  the original two-profile acceptance then passed.
- Chromium rejected the registration form's username pattern because the
  hyphen was invalid under the current `v` regex mode. Escaping it removed the
  console error; both credential and registration UI tests pass.
- The first final live persistence check fetched immediately after clicking
  login and received 401 before the cookie was installed. Waiting for the
  signed-in owner fixed the test synchronization; the repeated live recall path
  passed.
- A first full backend run inherited the live `.env` value
  `AUTH_REQUIRED=true`; four legacy anonymous API tests returned 401, while 768
  passed. The documented test baseline rerun passed all 772.
- One existing spoofed-browser-state test restored an unmocked conversation,
  received a real 401, and correctly returned to login. Keeping transcript
  restoration inside its deterministic auth boundary fixed the harness; the
  full 44-test browser rerun passed.

## UNVERIFIED

- Tailscale is not installed or signed in on this Windows host. No public
  Funnel hostname, external TLS request, off-network friend registration, or
  mobile-browser workflow has been exercised.
- The real `ani.mallya` password remains private and was not used by automated
  validation. The owner should still manually verify login, chat restoration,
  and logout through the gateway.
- Session refresh/rotation, account recovery, MFA, browser administration,
  per-user envelope encryption, and a destructive account-removal workflow
  remain planned.
- The documented Windows-to-macOS database/artifact/key restore procedure has
  not been exercised on a Mac.

## Next atomic task

Install and sign in to Tailscale on the host, obtain its node hostname, and
publish only `http://127.0.0.1:8080` through Tailscale Funnel. Then set the
public HTTPS origin as trusted, enable Secure cookies, rebuild, and repeat
registration/login/logout, SSE chat, semantic isolation, upload/download, and
presentation/image timeout acceptance from a device outside the home network.
Friends should use the HTTPS link directly and should not install Tailscale.
