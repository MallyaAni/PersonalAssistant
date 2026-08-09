# Scout — handoff

Read `AGENTS.md` first; it covers the working method and the operational traps.
This file is only the things a fresh session cannot discover by reading code.

## The next task

**Put what memory knows about the user into the Tavily search queries.**

Today a query is a template in `backend/discovery/sources/web.py::_queries`:

```python
queries.append(f"{label} {place} {when}")   # "Run Clubs Arlington, Virginia August 2026"
```

The only things about a person that reach a search are a two-word interest label
and their city. Every approved fact in memory reaches nothing — the sweep is
handed a `DiscoveryProfile` (interests + localities) and never reads memory.

That is why a man was sent a women-only running event: the query contains no
person, so the results are for everyone, and ranking is then asked to sort
candidates that were never chosen with him in mind. This is upstream of ranking
and worth doing first — better candidates beat better sorting.

**The agreed shape:**

- the **model chooses the subject** of each query, from approved memory facts —
  "casual weekend group runs" rather than "Run Clubs";
- the **template keeps its skeleton**, `{subject} {place} {month year}`;
- the **query budget is unchanged** — same count, better aimed.

Do not let the model write free-form queries. The current phrasing was measured,
and the comment in `_queries` records it: `"events near X upcoming"` kept **0 of
5** results while naming the month kept **6 of 9** across three interests. The
`{place} {month year}` skeleton is what makes results be about one happening
rather than a directory page.

Two things this needs that do not exist: the runner has no access to memory
facts, and search is metered — a bad query spends real budget, so compare
candidate quality across a couple of real sweeps before trusting it.

## Also queued, in priority order

1. **Audience restrictions.** Scout suggested a women-only event to a man.
   `summarize.py` already reads page text and already drops finds (that is how
   `already_happened` works), so add a restricted-audience field. Then:
   *first* say it in the digest name so the user can judge, *second* filter only
   against an explicitly stated fact in approved memory. Never infer an
   attribute like gender from a name or from behaviour. Some "Women's Run"
   events are open to all, which is why visibility comes before filtering.
2. **Rank against a richer user vector.** `runner.py::_interest_vectors` embeds
   the bare label, so the entire user representation is a two-word string. This
   is why scores cluster: measured over real candidates, a genuine concert
   scored 0.612 against "Concerts" and a lantern festival scored 0.616 against
   "Line Dancing". That clustering is what forced `MIN_ATTRIBUTION_MARGIN`
   (0.035). Measure before shipping: score real candidates against thin labels
   vs enriched vectors and check the correct ones actually separate. Embeddings
   will never encode exclusion, so this does not replace item 1.
3. **One-line test fix.** `backend/tests/test_discovery_delivery.py` still
   asserts the old opening; it needs `startswith("Scout · ")`. Left unstaged
   because Codex has uncommitted work in that same file.

## State to know

- **Seen items were purged** (all users) to get clean test results.
- **`DISCOVERY_NOVELTY_ENABLED=false`.** Digests repeat until this is turned
  back on; it must be on before anything runs unattended.
- **The Mac bridge grants work.** `IMESSAGE_BRIDGE_ALLOW_GRANTS=true` is set and
  `allow_recipient` was verified returning "Recipient allowed."
- **The public URL is a quick tunnel** (`scripts/start-tunnel.sh`). It dies on
  reboot and mints a new random hostname every start. A named tunnel is free but
  needs a domain on Cloudflare DNS.
- **Test baseline: ~19 failures on the host**, all `401 Unauthorized` in API
  tests, all pre-existing. Do not chase them. Confirm any new failure against a
  clean worktree at `HEAD` before assuming it is yours.
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
