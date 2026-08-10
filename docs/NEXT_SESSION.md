# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-08-09, America/New_York (semantic memory capture verified)

## Memory meaning is selected semantically, not by regex — VERIFIED

The first fix for `hi my name is Jen and i like acting, theater, networking
events` bounded a preferred-name regex. That contradicted the established
requirement that memory understand the user's meaning rather than accumulate
phrase rules. The production regex proposal module and its tests have now been
removed.

One local `MemoryProposalAgent` backed by `qwen/qwen3.5-4b` reads the whole
current utterance and returns grammar-constrained typed candidates for preferred
name, response style, locality, interests, entity relationship, workflow,
titled reference, semantic fact, and episodic event. Application code only
validates bounds and safe field shapes, attaches conversation/trace provenance,
and routes visible user approval; the model still has no persistence authority.
Profile facts may coexist, while general memory keeps one best candidate to
limit noisy proposals. The previous dedicated interest agent was removed.

Real Qwen evidence:

- the exact reported sentence returned `preferred_name = Jen` and `acting`,
  `theater`, `networking events`;
- `Everyone knows me as Jen. Stage performance and professional mixers are my
  thing.` returned the same preferred name and semantically mapped the interests
  onto the existing `testuser` labels instead of creating duplicates;
- `Would someone named Jen enjoy theater?` returned no proposal.
- the first semantic-fact rehearsal exposed an over-conservative/misclassified
  pet fact; after tightening the semantic contract, three different ways of
  saying the dog is called Biscuit all returned `semantic_fact`, `I love
  training dogs` returned only interest `dog training`, and the dog-name
  question still returned nothing.

The rebuilt backend and real authenticated Chromium path as `testuser` showed
both exact proposals, **Approve all 2** issued preferred-name 200 and interests
201, and readback returned `Jen` plus all three interests. Loading cleared, the
composer re-enabled, and browser Console, page, failed-network, and backend
exception checks were empty. The container received the increased 256-token
structured-output budget.

- Regression: 82 focused backend tests pass; Ruff passes; two focused
  Playwright tests and the frontend production build pass; 17 architecture diagrams
  and the published architecture page are synchronized.
- MyPy reached two pre-existing errors in `backend/discovery/link_graph.py`.
- Next atomic Scout task remains the Mac recipient-grant repair described below.

## One introduction now captures name and Scout interests — VERIFIED

The exact `testuser` message `hi my name is Jen and i like acting, theater,
networking events` exposed two boundaries. Preferred-name extraction consumed
the following `and I ...` clause, producing `Jen and i like acting`, and the
conversation service allowed only one memory proposal per turn, so that bad
name proposal suppressed the semantic interest result. The focused Qwen
classifier itself was correct and returned `acting`, `theater`, and `networking
events` before any code changed.

Name extraction now ends before a following `and I` or `but I` clause. A chat
turn may emit every compatible profile proposal (name, response style,
locality, and Scout interests), while general semantic/episodic memory keeps
the existing single-best rule. The frontend queues the streamed proposals so
each remains independently approval-gated rather than the last event replacing
the first.

The backend image was rebuilt from the working tree, `backend` was recreated,
and the gateway restarted. Through the real authenticated HTTP path as
`testuser`, the exact message streamed `preferred_name = Jen` followed by the
three Scout interests; approvals returned 200 and 201. Readback returned
profile name `Jen` and all three interests. A real headless Chromium session as
`testuser` rendered both cards in order, approved them, cleared the queue and
loading state, and recorded no Console, page, or failed-network errors. Backend
logs contain the chat and both approval requests with no exception.

- Regression: 72 focused backend tests pass; Ruff passes; three focused
  Playwright proposal regressions pass; the frontend production build passes.
- `FAILED` validation command: a broad title-based Playwright grep did not
  finish within 180 seconds and emitted no result. This does not invalidate the
  exact deterministic browser test or the real integrated Chromium acceptance,
  both of which passed.
- Next atomic Scout task remains the Mac recipient-grant repair described below;
  after delivery is verified, add deterministic geographic result rejection.

### Follow-up: multi-fact consent is now explicit — VERIFIED

The user then cleared `testuser` memory and repeated the same sentence. Runtime
logs showed the chat completed but the browser submitted only the Scout-interest
approval; no preferred-name request reached the backend. A read-only Chromium
replay proved the name was correctly first in the queue, but the card described
the second fact only as `1 more memory proposal waiting`, making it easy to skip
one fact and assume the other approval covered the sentence.

The approval card now previews every queued value and offers **Approve all 2**
while retaining per-item approval and dismissal. Batch UX saves each typed
endpoint in order; if a later request fails, already saved facts are reported,
the failed and unattempted proposals remain actionable, and the error is shown.
A real Chromium run as `testuser` submitted the exact sentence and used that
single action. Network evidence was preferred name 200 plus Scout interests
201; readback was name `Jen` and all three interests. The card and loading state
cleared, the composer enabled, and Console, page, and network-failure lists were
empty. The focused Playwright regression and production frontend build pass.

## Scout's prompts now live with Scout

Done. `agents/scout/` holds `aiming.py`, `reranking.py`, `describing.py` and
`place_suggest.py` — every prompt Scout injects. `discovery/` keeps the
machinery: the sweep, ranking, novelty, familiarity, delivery, and the
deterministic half of describing (`clean_title`,
`summarize_deterministically`, `text_from_html`), which never invents and which
several modules share.

Three things made it work, and are worth not undoing:

- `TextWriter` moved to `core/interfaces.py`. It had lived inside Scout's
  describe module, so every agent-shaped module imported that module for a type
  unrelated to Scout;
- `InterestAim` and `SweepAim` moved to `discovery/types.py`. They are data, so
  `precision.py` and `runner.py` take them from the domain and no type drags the
  agent layer in behind it;
- `runner.py` imports three classes from `agents/scout/`. That is the one edge
  from domain to agent, and it is deliberate: the runner *is* Scout's sweep
  body. There is no cycle — `agents/registry.py` reaches only
  `discovery/reachability.py`, which imports nothing back.

Deck is done too: `agents/deck/prompts.py` holds all five — the four contract
builders and the preambles that open each call — and `presentations/provider.py`
keeps the machinery, the JSON extraction, the per-layout schema and the view
builders that decide what a slide looks like to the model.

Diagram and memory capture are done too — `agents/diagram/prompts.py` and
`agents/memory/prompts.py`. Memory capture has no registry card because it is
not something the workspace lists; it is a step in every conversation, and the
folder exists only so its prompt sits with it.

**One thing left, and it is small.** `presentations/provider.py` still holds the
slide-content preamble inline, because that one is parameterised — it names
which slide of how many is being written, which is what stops each slide
restating the subject. It wants to be a function in `agents/deck/prompts.py`
taking index, total and deck title. An attempt at it broke the file on a string
escape and was reverted rather than left half-applied.

**Not moved on purpose:** `search/classifier.py` and
`artifacts/image_recall_classifier.py`. Both call a model, and both route rather
than produce work — they decide whether to search or to look for an image.
Treating a routing policy as an agent would put a folder round something the
workspace will never list. Decide that before moving them. Search routing and image recall are in
`search/classifier.py` and `artifacts/image_recall_classifier.py`, and those two
may be policies rather than agents — decide that before moving them.

## Where the prompts are

Every prompt Scout injects, so they can be read in one place:

| What it decides | File |
| --- | --- |
| Search subject and ranking vector per interest | `backend/discovery/aiming.py:147` |
| Order of the qualified shortlist against memory | `backend/discovery/reranking.py:102` |
| A find's name, its one-line description, and whether the page says it is over | `backend/discovery/summarize.py:183` |
| Place-name completion while typing | `backend/discovery/place_suggest.py:83` |

`docs/ARCHITECTURE.md` has the table of when each runs and what it costs.

Two of these are load-bearing in ways that are not obvious. `aiming.py` runs
even when memory is empty, which is every account today, because a two-word
interest cannot be matched against an event description at all. And
`summarize.py`'s `already_happened` is asked but no longer trusted alone: a
stated deadline is read deterministically in `url_dates.deadline_has_passed`,
after a digest offered a vote that closed a week earlier.

## Scout: where it stands and what is next

`python -m backend.cli.evaluate_discovery_ranking` scores the pipeline against
21 items that reached real digests. Baseline: **listing recall 0.46, happening
retention 1.00**. The seven listings still getting through are named in the
output — that is the work queue, not an aggregate to admire. `--with-model` also
scores attribution through the aiming and cross-encoder stages.

Ranking is a three-stage cascade: embeddings for recall (`relevance.py`), a
local ONNX cross-encoder for precision and attribution (`precision.py`), then
the model for what memory states (`reranking.py`). Only the first decides
eligibility. All of it is deployed; a fresh checkout must fetch the
cross-encoder weights (`DEVELOPMENT_GUIDE.md`) or that stage disables itself.

Queued, in priority order:

1. **Audience restrictions, deterministically.** `summarize.py` already reads
   page text and already drops finds, so add a restricted-audience field there.
   Say it in the digest name first so the user can judge; filter only in code,
   only against an explicitly stated fact. Do not push this into the re-ranker's
   prompt — measured, and it inferred gender from nothing.
2. **Geographic rejection.** Visible in the labelled cases:
   `concertfix.com/concerts/arlington-tx` reached an Arlington, Virginia digest,
   and a chamber-of-commerce index for Alexandria Bay, New York reached an
   Alexandria, Virginia one. Deterministic, cheap, and long overdue.
3. **Route listings to the feed proposer rather than the bin.** `feed_finder`
   and `LinkGraphExpander` already propose sources from discovered pages. "Movie
   showtimes near Alexandria" is a bad digest item and a good source candidate.
4. **A structured event source.** Ticketmaster, Eventbrite, or Songkick return
   events with start times and coordinates, removing the listing/happening
   distinction, the date parsing, and the geography problem at once. Feeds are
   already the design's "source of record"; almost nobody configures one, so web
   search does all the work and fights this fight every sweep.
5. **Earn back or delete `is_a_listing`.** It is computed and unused.

Volatile state: **`DISCOVERY_NOVELTY_ENABLED=false`** in `.env`, so digests
repeat until it is turned back on — it must be on before anything runs
unattended. Seen items were purged for `ani.mallya`. The Mac bridge grants work.
`jenos1` has "Social" and "Network" as separate interests, almost certainly one
phrase split at capture, and it will keep producing odd matches until corrected.

## Scout searches and ranks for the person — VERIFIED in source, NOT DEPLOYED

A sweep used to be handed a two-word interest label and a city, so the query was
`{label} {place} {month year}` and the vector a candidate was scored against was
the embedding of `label`. Approved memory reached neither. Three new modules
close that:

- `discovery/personal_context.py` reads one account's **approved, unexpired**
  facts and remembered sentences, skips the interest and locality projections
  (already typed into the profile), drops `preferred_name` and `response_style`,
  screens every statement through the same `OutboundPrivacyPolicy` that guards
  chat search, and bounds the result to 12 statements of 200 characters;
- `discovery/aiming.py` asks Qwen once per sweep to turn each interest plus
  those facts into a **search subject** and a **ranking profile**. The skeleton
  `{subject} {place} {month year}` and the query budget are unchanged. A subject
  carrying a digit, a month, the place, query syntax, or anything the egress
  screen would rewrite is rejected and the bare label used instead;
- `discovery/reranking.py` ranks a shortlist twice as wide as the digest and has
  Qwen order it against the same facts. It can never admit what deterministic
  ranking rejected, and if it excluded everything the deterministic order ships.

Both stages are behind `DISCOVERY_PERSONAL_QUERIES_ENABLED` and
`DISCOVERY_MEMORY_RERANK_ENABLED` (default true, added to the Compose allowlist
for `backend` and `discovery-worker`, verified present in `docker compose
config`). With either off, or with no model, no memory, or an unparseable reply,
the sweep searches and ranks exactly as it did before.

### Measured against the live runtime, read-only, no search budget spent

Real vLLM (`qwen/qwen3.5-4b`) and the real embedding service, for a person whose
approved facts said they run casually at weekends, are a man, prefer
beginner-friendly things they can attend alone, like live jazz and dislike
stadium shows, and do not drink:

```
Run Clubs    -> casual weekend group runs   Hiking  -> beginner-friendly hikes
Concerts     -> live jazz and blues         Line Dancing / Wine Tasting -> unchanged
```

Best-interest margins, bare label vs aimed vector:

| candidate | bare | aimed |
| --- | --- | --- |
| Saturday Morning Social Run | 0.633, margin 0.071 | 0.757, **margin 0.132** |
| Live Jazz Trio at Blues Alley | 0.644, margin 0.054 | 0.737, **margin 0.118** |
| Beginner Line Dancing Social | 0.768, margin 0.208 | 0.843, margin 0.206 |
| Stadium Tour: Arena Rock | 0.640, margin 0.119 | 0.690, margin 0.159 |

Genuine matches separate roughly twice as far — which is what
`MIN_ATTRIBUTION_MARGIN` (0.035) exists to cope with. **And enrichment cannot
encode exclusion**: the stadium show scored *higher* after enrichment for
someone whose facts say they dislike stadium shows. That is the case for having
both stages rather than either.

The re-ranker put the social run, the jazz trio and the beginner class first and
pushed the stadium show, the wine festival and a women-only race last — correct
for this person, deterministic across repeated greedy runs.

### The women-only defect is mitigated, not fixed

The re-ranker ranked the stated women-only race last and did **not** exclude it,
for a person whose facts state they are a man. Strengthening the wording was
tried and measured, and is recorded in `reranking.py`: with a worked example it
excluded all three restricted-or-disliked items — turning two *preferences* into
eligibility bars — and on a control context with **no fact about gender** it
still excluded the women-only race. That is the inference this must never make.
The conservative wording stayed. Audience restriction still needs the
deterministic route: a restricted-audience field read out of the page in
`summarize.py`, said in the digest, filtered by code against an explicit fact.

### The binding constraint is upstream: memory is empty

`memory_facts` holds exactly three non-projection rows across the whole
database, all `preferred_name` (which this deliberately never reads), and
`semantic_memory` holds one row belonging to a throwaway test account. So for
`ani.mallya` the personal context reads empty, the planner is not called, and
every query is the bare label — verified by running the planner against that
real account. The plumbing is in place and has nothing to carry. Making Scout
personal from here is a memory-capture problem, not a discovery problem.

- Regression: **1020 backend tests pass** with `AUTH_REQUIRED=false`, including
  28 new ones; Ruff and strict MyPy clean on `backend/discovery` (two
  pre-existing `link_graph.py` errors untouched); 17 diagrams synchronized.
- `UNVERIFIED`: no sweep has run through the built containers. The images were
  not rebuilt and `backend`/`discovery-worker` were not recreated, because doing
  so drops live users on the tunnel. Rebuild both, then `docker compose restart
  gateway`, before claiming live behaviour.


## Scout account isolation restored at the live runtime — VERIFIED

A report that a `jenos1` 9:30 PM subscription triggered the primary user's
phone exposed two separate facts. PostgreSQL already held distinct owners:
`ani.mallya` owns the 9:30 PM schedule and five interests, while `jenos1` now
owns a 10:00 PM schedule and twelve different interests. Their subscriber address
digests are also different, and the 9:30 delivery belongs to the
`ani.mallya` run and subscriber. The worker reads the run's `user_id` and uses
that same owner for profile retrieval and subscriber selection.

The first failing boundary was nevertheless security-critical: the live
backend was a stale container with `AUTH_REQUIRED=false`, even though `.env`
and the current Compose rendering both specify `true`. In trusted-local mode
the ownership dependency intentionally accepts caller-supplied user IDs. The
backend was recreated from current Compose configuration and the gateway was
restarted. Direct live bearer requests now prove:

- both owners can read their own profile and schedule (HTTP 200);
- the interest sets are separate and disjoint (five vs. twelve);
- an `ani.mallya` token cannot read `/discovery/jenos1` (HTTP 403);
- an anonymous request cannot read `/discovery/ani.mallya` (HTTP 401);
- backend logs record those 403/401 decisions without an exception.

The phone UI also hid the signed-in identity and represented logout only as an
unlabeled compact-header icon. The mobile navigation drawer now shows
`Signed in as <user>` beside a labeled **Sign out** action. Playwright at
390x844 exercised both the deterministic app and the rebuilt production
gateway: it opened the drawer, confirmed the live authenticated account,
received HTTP 204 from logout, and reached the login screen with no Console or
page errors or failed network requests.

Regression evidence: the auth, delivery, schedule, and worker suites pass 45
tests, including a new two-user delivery assertion that only the requested
owner's approved address is selected; two focused mobile browser tests pass;
and the production frontend build passes.

### `jenos1` phone delivery — FAILED at the Mac grant boundary

The current Mac MCP bridge advertises both `send_imessage` and
`allow_recipient`, but an idempotent grant for the already consented and
operator-approved `jenos1` subscriber returns a tool error that explicitly
identifies bridge grants as disabled. The subscriber remains deliverable in
AniOS but has zero successful deliveries and `recipient_not_allowed`; nothing
was redirected to `ani.mallya`.

The latest 10:00 PM run fetched five candidates and persisted five selected
future/undated items. Its `delivered_at` field is only the claim-before-send
marker and is not evidence of receipt: the subscriber row was not touched and
the user received nothing. A read-only replay of that stored digest through the
current delivery logic selects exactly the one `jenos1` subscriber and would
make one channel call. Do not replay the old message; its durable retry payload
has already been cleared.

The Mac LaunchAgent must persist `IMESSAGE_BRIDGE_ALLOW_GRANTS=true` (and may
set an explicit writable `IMESSAGE_BRIDGE_GRANTS` path), then reload/restart
the bridge. Re-approve the existing subscription or invoke the idempotent grant
again, confirm `granted`, and validate a new owned digest reaches only the
masked `jenos1` destination.

### Next atomic Scout task after delivery is verified

Add and validate geographic result rejection. The live Arlington, Virginia
rehearsal correctly found local basketball/baseball results but also admitted a
college-baseball result explicitly located at Globe Life Field in Arlington,
Texas. Reject an explicit place that contradicts the active locality/region
before it can enter the digest — deterministically, in code: this is a string
comparison against a stated place, not a judgement.

## Scout rejects explicitly past search results — VERIFIED

The live `ani.mallya` rehearsal reproduced two user-visible problems: Scout
returned a prior line-dancing event as an undated possibility, and its message
opened with the mechanical phrase `Worth a look — no date given`. The first
failure was at web-result conversion: an explicit date before today and no
date at all both became `None`, so relevance treated the past event as an
undated mention.

`WebEventSource` now preserves the distinction long enough to reject an
explicit date before today. Current and future explicit dates retain their
typed value; genuinely undated results remain bounded mentions. The fixed
digest renderer now says either `I found this, but couldn't confirm the date`
or the plural equivalent instead of implying an undated result is confirmed
upcoming.

Live authenticated evidence on the rebuilt backend:

- the same non-persisting `ani.mallya` rehearsal exercised four MCP
  `internet/search_web` calls through Tavily, Nomic embedding/ranking, and the
  digest renderer with no backend exception;
- the candidate pool fell from 27 to 26 because the explicitly past result was
  rejected before ranking;
- the returned message used the new uncertainty wording and contained no old
  heading;
- Chromium opened the real signed-in `ani.mallya` Scout panel, ran **Try it**,
  rendered the new wording, and reported no blocking Console or page errors;
- 286 discovery backend tests, Ruff, strict MyPy, five focused Scout browser
  tests (two passed and three correctly skipped without live credentials), the
  separately credentialed live browser acceptance, and the frontend production
  build passed.

At the user's request, all 28 `discovery_seen_items` rows owned by
`ani.mallya` were deleted after validation so another real test starts clean.
The scoped count is now zero; `jenos1` and `del_2a87abb15636` rows were left
unchanged. Interests, locality, schedules, subscriptions, familiar-item
dismissals, memory, and run history were not deleted.

## Semantic chat interests configure Scout — VERIFIED, generalized

The original `testuser` failure was at chat capture, not Scout retrieval. That
focused interest classifier has since been generalized into the typed
`MemoryProposalAgent` described at the top of this handoff. It still sends only
the current utterance and existing interest catalogue to local Qwen, has no
persistence or tool capability, and returns up to eight validated labels.
Approval writes every selected interest fact and Scout projection in one
database transaction; a capacity or projection failure rolls the batch back.

Live authenticated evidence on the rebuilt backend:

- direct `POST /api/v1/chat` returned a complete SSE stream with one
  `discovery_interests` proposal containing basketball, soccer, baseball, and
  hiking;
- direct approval returned 201 and the owned Scout profile contained exactly
  those four `user_explicit` interests;
- Chromium repeated the conversation, approved the card, opened Agents → Scout
  → Configure, and saw all four strength controls; streaming terminated, the
  composer re-enabled, and post-login Console/page errors were empty;
- another profile remained empty in the integration test;
- a live non-persisting Scout rehearsal in Arlington, Virginia spent four MCP
  `internet/search_web` requests, each reached Tavily with HTTP 200, Nomic
  embedded/ranked the candidates, and Qwen produced the visible descriptions.

The browser run also found and fixed an adjacent authenticated Scout UI defect:
subscription read/write/delete used bare `fetch`, omitted the session cookie,
and emitted 401s. They now use the shared authenticated request boundary.

Validation: 127 relevant backend tests passed; Ruff and strict MyPy passed; two
deterministic Scout browser tests passed; the authenticated live Scout browser
test passed; the frontend production build passed; all 17 canonical diagrams
and `architecture.html` are synchronized. A combined full-backend/full-browser
run exceeded its 10-minute orchestration ceiling and ended with a Playwright
EPIPE, so the complete suites are `UNVERIFIED` for this tree rather than failed.

## Scout's iMessage channel — VERIFIED working end to end

The bridge (`bridges/imessage_mac/`) is running on a real Mac (not AniOS's
Windows host) and a message sent through it was confirmed received on the
allowlisted phone. Both the header-auth transport fix (`d3001d9`) and the
backend's own missing `docker-compose.yml` allowlist entries for
`DISCOVERY_IMESSAGE_SERVER_ID`/`DISCOVERY_IMESSAGE_TOOL` (`6e77969` — the
fourth instance of the environment-allowlist trap this session) were needed
before this worked; either alone left it silently broken.

What the Mac side needed, none of which is obvious from the bridge's own code:

- **Python 3.10+, not the system `python3`.** A stock macOS install (and this
  Mac specifically) ships an ancient `python3` (3.7 here) via an old
  python.org installer; `mcp` requires 3.10+ and fails at `pip install` with
  "no matching distribution found for mcp", which names the package rather
  than the interpreter as the cause. Installing a newer Python via Homebrew on
  an unsupported-for-bottles macOS version (this Mac: Ventura 13.7, Intel)
  means several dependencies build from source, and that build fails outright
  if Xcode Command Line Tools are older than Xcode 15.2 — this Mac's shipped
  CLT was from 2019 (`clang 11.0.0`) and needed
  `sudo rm -rf /Library/Developer/CommandLineTools && sudo xcode-select --install`
  before Homebrew's `openssl@3`/`readline` builds would even compile.
- **The Automation permission prompt is silent when nobody can answer it.**
  The first `osascript` call to Messages/System Events from a non-interactive
  or remote-controlled shell hangs for the AppleEvent timeout
  (`-1712`) and never surfaces a clickable dialog. It only works once someone
  runs an AppleScript call to Messages from an interactive Terminal window
  they're physically at, and clicks Allow.
- **The bridge needs the Mac to actually stay up.** `pmset -g` shows battery
  `sleep 1` (one minute); its existing AC settings are `sleep 0` and
  `disksleep 0`. `caffeinate -s` is AC-only, so it cannot keep this laptop awake
  on battery. A separate LaunchAgent at
  `~/Library/LaunchAgents/com.anios.imessage-bridge-awake.plist` now runs
  `caffeinate -i` with `RunAtLoad` + `KeepAlive`. It was verified on 2026-08-08:
  the assertion appeared as `PreventUserIdleSystemSleep`, killing it made
  launchd respawn it with a new PID, and the bridge continued to return its
  expected unauthenticated `401`. A laptop's lid still forces sleep regardless
  of this assertion unless it is in clamshell mode with an external display
  attached.
- **The process itself needs to survive logout/crash, which `nohup` does
  not.** It now runs as a `launchd` LaunchAgent at
  `~/Library/LaunchAgents/com.anios.imessage-bridge.plist`
  (`RunAtLoad` + `KeepAlive`, verified by `kill -9`-ing the process and
  watching it respawn under a new PID within seconds). This only starts once
  the Mac's user account is actually logged into a GUI session — it is a
  LaunchAgent, not a LaunchDaemon, because Messages automation needs a real
  Aqua session, not just a booted machine.

**The Mac's LAN IP is the address in `MCP_SERVERS_JSON`, and it can move.**
Same failure shape as the tunnel hostname below: if this Mac's DHCP lease
changes, the configured `url` silently points at nothing and AniOS-side
delivery starts failing with no signal pointing at the address as the cause.
Consider a static DHCP reservation for this Mac if the bridge is meant to be
depended on rather than just demoed.

**The shared bridge token has already been rotated once** after an earlier
value was pasted into a chat transcript relaying setup instructions between
the two machines. Treat any token that has appeared in a conversation as
burned; regenerate rather than reuse.

## Public access is a temporary Cloudflare quick tunnel

Tailscale Funnel was abandoned after failing two different ways across two
accounts, neither failure ours:

- tailnet `tail5a235a`: both published ingress addresses completed TCP and then
  closed during the TLS handshake (`UNEXPECTED_EOF_WHILE_READING`), which is
  what a browser reports as `ERR_SSL_PROTOCOL_ERROR`;
- tailnet `tail080855` (a fresh account): Funnel and HTTPS certificates were
  both granted at the control plane — `tailscale status --json` shows the
  `funnel`, `https` and `funnel-ports` capabilities — and the Let's Encrypt
  certificate issued, but **no A or AAAA records were ever published**, so
  there was no address for anything to connect to.

Renaming a node never produced address records in either tailnet, which is a
second, separate quirk. Do not spend more time here without new evidence.

The current URL is a `trycloudflare.com` quick tunnel. Restore it with:

```bash
bash scripts/start-tunnel.sh
```

which waits for the address, prints it, and rewrites
`DISCOVERY_CALENDAR_BASE_URL` to match.

**It does not survive a reboot and the hostname is random every time**, so every
calendar link already sent stops resolving when it changes. The script handles
the rewrite; recreate `backend` and `discovery-worker` afterwards so they read
the new value.

The fix is a named tunnel, which needs a domain on Cloudflare (~$10/yr). That
buys a stable hostname and installation as a Windows service, so it starts
before login. Until then "the desktop rebooted" means everyone's link is dead.

Docker services now carry `restart: unless-stopped`, so the stack itself
returns when Docker Desktop starts. ComfyUI and local-capabilities deliberately
do not — they hold the GPU.

### Verify ingress from outside, never from this desktop

Tailscale loops its own hostnames back locally, so `curl` from the host
returned 200 in ~14 ms while the public path was dead. That produced a false
"verified working" report that cost several rounds. Use a TLS handshake from
inside a container, which has its own network namespace, and check **every**
published address:

```python
socket.create_connection((ip, 443), 10)
ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
```

## The three reported defects are fixed; one is only reduced

All three were reproduced, changed, and re-exercised against the running stack.
Details in [CHANGELOG.md](CHANGELOG.md).

### 1. Explicit "remember this" — VERIFIED fixed

Was: the former phrase extractors returned no proposal for "Remember that my
dog is called Biscuit.", and the assistant claimed a save anyway. The current
typed semantic agent selects `semantic_fact` without a phrase rule, while the
pre-answer save-state prompt keeps the reply honest.

Re-run of the original reproduction, through the API with auth on:

```
CHAT 1 >  "...I cannot store this myself, just approve the save card below."
          memory_proposal: kind=semantic_fact "my dog is called Biscuit."
approve -> 201        semantic count 0 -> 1
CHAT 2 (new conversation) >  "Your dog's name is **Biscuit**."
```

The honesty half needed two attempts, which is worth remembering: told only
that it could not write to memory, the model answered "your personal memory has
been updated". A blanket prohibition invites a passive rephrasing. What worked
was deciding the proposal **before** generating the answer and stating the
turn's real save state in the prompt, with the sentence to write.

### 2. Presentation slides render empty — VERIFIED fixed

The mechanism was narrower than recorded. `statistic`, `quote`, `comparison`,
`chart`, and `table` already degraded to bullets through `_effective_layout`,
and the grammar already promotes each layout's fields to required. **`section`
was the only layout still discarding its points**, and it produces exactly the
reported symptom: a rule, a title, a purpose, nothing else. Confirmed by
compiling one directly (3 elements, both points gone) before changing anything.

Section slides now carry their points. Verified on three real generated decks:
12 slides, 0 rendering only a title and a purpose.

### 3. Deck content is ungrounded — reduced, not eliminated

`DeckResearch` runs one privacy-screened search per deck at outline time and
quotes bounded sources into the outline and every slide request. Verified live
inside `presentation-worker`: MCP → Tavily returned NASA and Smithsonian
sources, and the same brief sent verbatim had returned a slideware marketing
page until the brief was reduced to its subject.

Same brief, same model, measured:

| | ungrounded | grounded |
| --- | --- | --- |
| crewed landings | "seven" | "six" (correct) |
| dates | "Apollo 11 December 1969", "285-day intervals", "21-year span" | Apollo 8 December 1968 (correct) |
| crews | Apollo 12 crew wrong | Apollo 12 and 14 crews correct |

Two errors survived: the Apollo 11 module as "Eagles", and Charles Duke placed
on Apollo 15 (he flew Apollo 16). **Do not record this as solved.** Grounding
is wired, screened, metered, and degrades safely, but Qwen 3.5 4B with 1,024
tokens per slide still misreads its sources. The next lever is the slide token
budget or a stronger presentation role, not more prompt wording — that was
already tried here and is what the contract now says.

## Pin `mcp` below 2.0, and know why

`requirements.txt` had `mcp>=1.0.0` open-ended. Rebuilding the image today
resolved **mcp 2.0.0**, which removes `mcp.server.fastmcp` — imported by both
built-in stdio servers and the local-capabilities sidecar. The result: web
search and every MCP server broke in the containers while the host venv stayed
on 1.28.1 and the full test suite still passed. It is the rug-pull the MCP
guidance warns about, arriving through a Python dependency rather than a server.
Now pinned `<2.0.0` in both `requirements.txt` and `pyproject.toml`, verified as
1.29.0 with `fastmcp OK` in backend, presentation-worker, and
local-capabilities.

If MCP or search breaks after a rebuild, check the installed `mcp` version in
the container first.

## Things that look wrong and are not

- **`max_distance=0.96`** for image recall in `conversation_service.py`. It is
  not comparable to discovery's `0.08` novelty or `0.16` familiarity — those
  measure text embeddings, this measures image embeddings, where genuine
  matches sit around 0.90–0.94. Tightening it to 0.45 disabled recall and broke
  three tests. Any change needs the real distance distribution measured first.
- **Memory has no cross-user leakage.** Verified: zero nullable `user_id`
  columns in the schema, every retrieval filters on owner, and a guest asking
  for another account's data gets 403 rather than an empty list.

## Recently landed and verified

- Sign-up records an access request carrying the chosen username and password
  (hashed on arrival); approval creates the account outright. Verified through
  the public URL: request `201 pending` → login `401` → approve → login `200`.
- Accounts can be revoked (sessions destroyed immediately) or deleted. Deletion
  discovers its tables from `information_schema` rather than a hand-written
  list, because a hand-written list already shipped here missing eight
  discovery tables.
- Interactive search is metered per account, with a shared monthly pool sized
  to the real Tavily allowance and reconciled against their usage endpoint
  (which reported 37 credits spent the local counter knew nothing about).
  Usage is visible to the person spending it, not only the operator.
- Conversations are listed and deleted from the server; history no longer lives
  in one browser's `localStorage`.
- The sidebar opens as an overlay below 768px, so history is reachable on a
  phone.
- Scout's discovery profile is no longer injected into ordinary chat turns. A
  standing list of interests in every prompt bent unrelated answers toward
  them. Guarded by a test in `test_architecture_boundaries.py`.
- Image generation sends the subject rather than the sentence, and the global
  style suffix no longer names skin and hair — that wording put a person in
  every image, which is why a request for a car returned a woman leaning out of
  one.
