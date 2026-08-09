# Scout — handoff

Read `AGENTS.md` first; it covers the working method and the operational traps.
This file is only the things a fresh session cannot discover by reading code.

## What just landed

Memory now reaches the sweep at both ends: `personal_context.py` reads approved
facts, `aiming.py` turns each interest into a search subject and a ranking
vector, and `reranking.py` orders the shortlist against the same facts. The
query skeleton and the query budget are unchanged.

Ranking is now a three-stage cascade, each stage using the instrument suited to
its question: embeddings for recall (`relevance.py`), a local ONNX cross-encoder
for precision and attribution (`precision.py`), then the model for constraints
memory states (`reranking.py`). Only the first decides eligibility.

Full evidence and the measured numbers are in `docs/NEXT_SESSION.md`. Two
negative results are recorded in the code itself because they will otherwise be
re-attempted: the exclusion wording in `reranking.py`, and the sigmoid-versus-
logit measurement in `cross_encoder.py`.

**It is not deployed.** The images were not rebuilt, so nothing has run through
a container. The cross-encoder also needs its weights fetched first (see
`DEVELOPMENT_GUIDE.md`) or it disables itself and ranking is embeddings-only.
Rebuild `backend` and `discovery-worker`, then `docker compose restart gateway`.

## Measure before changing anything

`python -m backend.cli.evaluate_discovery_ranking` scores filtering against 21
items that reached real digests; `--with-model` also scores attribution. The
baseline is listing recall 0.46 and happening retention 1.00, and the seven
listings still getting through are named in the output — that is the work queue.

This exists because two changes were shipped on single examples and both were
wrong: a cross-encoder reported as improving attribution that made the same
error more confidently on the first real digest, and a listing filter that
emptied a live digest. Use the harness.

## The next task

**Give Scout something to know.** The plumbing built above has nothing to carry:
`memory_facts` holds three non-projection rows in the entire database, all
`preferred_name`, and `semantic_memory` holds one row belonging to a throwaway
account. For `ani.mallya` the personal context reads empty, so the planner is
never called and every query is still the bare interest label.

The capture constraint has now been addressed in source. One local
`MemoryProposalAgent` reads the whole current utterance and returns typed,
approval-gated profile and general-memory candidates. No regex or keyword
extractor decides what the user meant. The next proof needed for Scout is a
real approved personal fact beyond name/interests, followed by a sweep that
shows the bounded fact changes search aiming or reranking without leaking raw
personal text.

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
2. **Geographic rejection.** Still open, and now visible in the labelled cases:
   `concertfix.com/concerts/arlington-tx` reached an Arlington, Virginia digest,
   and a chamber-of-commerce index for Alexandria Bay, New York reached an
   Alexandria, Virginia one. Deterministic, cheap, and it has waited long
   enough.
3. **Route listings to the feed proposer instead of the bin.** `feed_finder` and
   `LinkGraphExpander` already propose sources from discovered pages. "Movie
   showtimes near Alexandria" is a bad digest item and a good source candidate,
   so the biggest failure mode becomes an asset rather than a rejection.
4. **A structured event source.** Ticketmaster, Eventbrite, or Songkick return
   events with start times and coordinates, which removes the listing/happening
   distinction, the date parsing, and the geography problem at once. Feeds are
   already the "source of record" in the design; almost nobody configures one,
   so web search does all the work and fights this fight every sweep.
3. **Describe before re-ranking, if the budget allows.** Both re-rank stages see
   scraped page titles because `_make_readable` runs after selection. They get
   the summary text too, so neither is blind, but a readable name would help.
   The cost is describing a shortlist of sixteen rather than a digest of eight.
4. **Let the model decide "is this a page about one happening or a list of
   them".** `listing_filter.py` decides it from a keyword vocabulary, and
   measured against realistic titles it misses 3 of 6 directory pages phrased
   without its words ("Community Bulletin Board", "Arlington Farmers Markets",
   "Trail Guide: Northern Virginia") while wrongly rejecting none of 4 real
   happenings. The URL half of that filter is genuinely structural and should
   stay. The title half is a language judgement, and it is nearly free to fix:
   `summarize.py` already sends the page text to the model and already returns a
   typed decision that drops finds (`already_happened`), so this is one more
   field on a call that is already being made, judged on the page rather than
   the title. Keep the deterministic filter in front of it, the way
   `CascadingSearchRouter` keeps its rules in front of its classifier.

**Do not "improve" these with a model.** They look like the same kind of code
and are not: `core/egress.py` (a model asked to redact its own prompt can be
talked out of it, a pattern cannot), the date patterns in `sources/web.py` and
`url_dates.py` (a read date is the whole guarantee; an inferred one is a
confidently wrong calendar entry), and the validators in `auth_service.py` and
`presentations/validation.py`.

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
