# AniOS

Claude Code reads this file; Codex and other agents read `AGENTS.md`. The
instructions are the same, so they live in one place rather than drifting apart.

**Read [AGENTS.md](AGENTS.md) and follow it.** It covers the source-of-truth
rule, the working method, the required comment on every new function, git
checkpoint discipline, the completion rule for what counts as verified, document
ownership, and diagram maintenance.

One rule is easy to skip and is the reason several defects here shipped: **a
change that adds or alters a prompt is not complete until a functional test in
`backend/tests/functional/` exercises it against the real runtime and asserts
on what came back.** Structural tests prove the call happened. They cannot
tell you the answer got worse.

Pay particular attention to **Operational traps in this repository**. Every entry
there cost real time or real data, and none of them are discoverable by reading
the code.
