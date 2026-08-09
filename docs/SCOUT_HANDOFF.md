# Scout — handoff

Read `AGENTS.md` first; it covers the working method and the operational traps.
This file is only the things a fresh session cannot discover by reading code.

## What just landed

Memory now reaches the sweep at both ends: `personal_context.py` reads approved
facts, `aiming.py` turns each interest into a search subject and a ranking
vector, and `reranking.py` orders the shortlist against the same facts. The
query skeleton and the query budget are unchanged. Full evidence and the
measured numbers are in `docs/NEXT_SESSION.md`; the negative result about
exclusion wording is recorded in `reranking.py`'s own docstring because it will
otherwise be re-attempted.

**It is not deployed.** The images were not rebuilt, so nothing has run through
a container. Rebuild `backend` and `discovery-worker`, then `docker compose
restart gateway`.

## The next task

**Give Scout something to know.** The plumbing built above has nothing to carry:
`memory_facts` holds three non-projection rows in the entire database, all
`preferred_name`, and `semantic_memory` holds one row belonging to a throwaway
account. For `ani.mallya` the personal context reads empty, so the planner is
never called and every query is still the bare interest label.

So the constraint has moved upstream, from discovery to capture. `chat` only
proposes a fact when one of the extractors in `backend/memory/proposals.py`
claims the utterance, and those are regex-shaped: the semantic-fact catch-all
needs an explicit "remember that…". Meanwhile `ScoutInterestProposalAgent`
already shows the shape that works — the local model reads one utterance and
proposes something the user approves in a visible card. The same thing for
*facts about the person* is what would fill this in.

Two cautions from the work just done:

- capture is what makes this real, and it is also what makes it sensitive. A
  proposal card is the boundary: nothing reaches a sweep that the user did not
  approve, and `personal_context.py` re-checks that at read time;
- do not measure this with a synthetic profile alone. The aiming stage was
  measured with a hand-written context because no real one existed, and that
  measurement cannot tell you whether real captured facts are the *kind* of
  facts that aim a query well.

## Also queued, in priority order

1. **Audience restrictions, deterministically.** Still open, and now with
   evidence about how *not* to do it. `summarize.py` already reads page text and
   already drops finds, so add a restricted-audience field there. Say it in the
   digest name first so the user can judge; filter only in code, only against an
   explicitly stated fact in approved memory. Do not push this into the
   re-ranker's prompt — that was measured and it inferred gender from nothing.
2. **Geographic rejection.** The Arlington, Virginia rehearsal admitted a result
   explicitly located at Globe Life Field in Arlington, Texas. A stated place
   that contradicts the active locality should be rejected before the digest, in
   code.
3. **Describe before re-ranking, if the budget allows.** The re-ranker sees
   scraped page titles because `_make_readable` runs after selection. It gets
   the summary text too, so it is not blind, but a readable name would help it.
   The cost is describing a shortlist of sixteen rather than a digest of eight.

## State to know

- **`DISCOVERY_NOVELTY_ENABLED=false`** in `.env`. Digests repeat until this is
  turned back on; it must be on before anything runs unattended.
- **Seen items were purged** for `ani.mallya` to get clean test results.
- **The Mac bridge grants work.** `IMESSAGE_BRIDGE_ALLOW_GRANTS=true` is set and
  `allow_recipient` was verified returning "Recipient allowed."
- **The public URL is a quick tunnel** (`scripts/start-tunnel.sh`). It dies on
  reboot and mints a new random hostname every start. A named tunnel is free but
  needs a domain on Cloudflare DNS.
- **Run the backend suite with `AUTH_REQUIRED=false`.** With it, 1020 tests pass
  on this host. Without it, roughly nineteen legacy anonymous API tests return
  401 and look like regressions. Four more modules fail on Windows for optional
  dependencies that live only in the container.
- **Codex also edits this tree.** Check `git status` before committing and stage
  only your own files.

## Traps that cost time here

- **Compose declares a per-service env allowlist.** A key in `.env` reaches
  nothing until it is added to that service. Verify with
  `docker compose exec -T <svc> printenv`.
- **Migrations are baked into the image.** `alembic upgrade head` silently does
  nothing until `docker compose build backend`.
- **The gateway builds the frontend.** A restart does not rebuild it; a frontend
  change needs `docker compose build gateway`.
- **Recreating `backend` drops live users** on the tunnel. It has happened twice,
  and once a real user reported the agent as broken because of it.
- **An optional field in a response grammar is a field the model will skip.**
  The re-ranker's `excluded` list was never emitted at all until the schema
  marked it required — three greedy runs returned only an order. If a model
  seems to be ignoring part of a contract, check whether the grammar lets it.
