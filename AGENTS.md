# AniOS Agent Instructions

## Source of truth

Use the current implementation, configuration, tests, and observed runtime behavior as the source of truth for what AniOS does today. Runtime evidence is authoritative only when its source revision or built artifact is known; a stale container does not override newer source code. Documentation records intent and verified knowledge, while an ADR records a decision rather than proof of implementation.

Before changing the repository, read:

- [README.md](README.md)
- [Current session handoff](docs/NEXT_SESSION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development and validation guide](docs/DEVELOPMENT_GUIDE.md)
- [Roadmap](docs/ROADMAP.md)

Read [Security](docs/SECURITY.md) when a task affects data, credentials, authentication, logging, external access, or permissions.

## Working method

- Restate the exact objective, acceptance criteria, and relevant `VERIFIED`, `FAILED`, and `UNVERIFIED` facts before editing.
- Keep work limited to the requested atomic task. A task may intentionally advance a `SCAFFOLDED` or `PLANNED` capability only when the user or approved handoff puts it in scope.
- Inspect the relevant implementation before planning or editing. Do not infer behavior from filenames, interfaces, mocks, documentation, or a health response.
- Preserve unrelated user changes and recheck files that may be changing concurrently.
- Reproduce a failure, identify the first failing boundary, test one evidence-backed hypothesis, make one targeted change, and repeat the original acceptance path.
- After three unsuccessful targeted hypotheses, stop editing and report the evidence, attempts, and next investigation needed.
- Keep business logic separate from framework and infrastructure details where the existing architecture supports it.
- Do not hardcode production secrets or log credentials, tokens, or unnecessary personal data.
- Explicit user instructions, including read-only requests, override routine documentation-update procedures.

## Git checkpoints

Git is recoverable code history, documentation is reasoning context, and functional tests are proof of behavior. A commit is not a verified checkpoint merely because it exists.

- When Git is available, record the starting branch, `HEAD`, and working-tree state before editing, then report the final state.
- Preserve pre-existing modifications and keep task changes separable. Do not stage or commit unrelated user work.
- Create commits, tags, branches, worktrees, reverts, or other Git mutations only when authorized by the user or the requested workflow.
- Call a commit a verified checkpoint only when its exact tree passed the applicable acceptance path; record the commit SHA and evidence in `NEXT_SESSION.md` after verification.
- For recovery, prefer inspecting or branching from the verified SHA without overwriting the current worktree.
- Never run `git reset --hard`, `git clean -fd`, `git restore .`, destructive checkout commands, or force pushes without explicit approval.
- If Git is unavailable, report Git state as `UNAVAILABLE` and do not invent branch, commit, or diff information.

## Completion rule

A running process, open port, successful health check, compiled file, passing unit test, or HTTP 2xx response does not by itself prove that a task achieved its goal.

Before declaring a task complete:

1. Run the relevant startup command and identify the exact source revision or image being exercised.
2. Exercise the actual user or system acceptance path.
3. Validate expected content, state transitions, side effects, persistence, logs, and error handling—not only reachability.
4. Run relevant automated tests and builds.
5. Report every applicable criterion as `VERIFIED`, `FAILED`, or `UNVERIFIED` with concrete evidence.

User-interface behavior is `VERIFIED` only after an automated browser test or a documented manual browser session exercises the intended workflow. Serving HTML or reaching an API is insufficient. UI validation should fail on page exceptions, blocking console errors, failed required network requests, incorrect rendered content, broken interactions, or missing required persistence.

If functional validation cannot be performed, do not label the behavior verified. Follow [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md).

## Documentation ownership

- `README.md`: stable overview, entry points, and documentation map.
- `docs/ARCHITECTURE.md`: current architecture facts and explicitly labeled future design.
- `docs/DEVELOPMENT_GUIDE.md`: setup, commands, debugging, testing, and validation procedures.
- `docs/ROADMAP.md`: milestone status and planned capabilities.
- `docs/NEXT_SESSION.md`: frequently rewritten verified handoff and next atomic task.
- `docs/CHANGELOG.md`: append-only history of meaningful verified changes.
- `docs/SECURITY.md`: current security posture and planned controls.
- `docs/adr/`: durable architectural decisions.

After implementation or debugging, rewrite `NEXT_SESSION.md` when runtime evidence or the next task changed. Update other documents only when facts within their ownership changed. Never record code as complete in the changelog unless its intended behavior passed functional validation.
