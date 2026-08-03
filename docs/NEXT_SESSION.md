# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-08-03, America/New_York

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

The current URL is a `trycloudflare.com` quick tunnel started by hand:

```bash
cloudflared tunnel --url http://localhost:8080
```

**It does not survive a reboot and the hostname is random every time.** When it
changes, `DISCOVERY_CALENDAR_BASE_URL` in `.env` must be re-pointed or every
calendar link already sent stops resolving.

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

## Open defects, in priority order

### 1. Explicit "remember this" saves nothing, and claims it did

Reproduced end to end through the public URL:

```
CHAT 1 >  "I've made a note of that: your dog's name is Biscuit."
CHAT 2 >  "I don't have information about your dog's name..."
semantic_memory: 0   memory_facts: 0   episodic_memory: 0
```

Root cause: **all eight proposal extractors in `backend/memory/proposals.py`
return `None`** for `"Remember that my dog is called Biscuit."` They are narrow
lexical matchers for specific shapes (preferred name, locality, interest) and
nothing covers an ordinary fact about a person's life.

Two defects, and the second is worse:

- no rule captures general facts, so almost nothing reaches memory;
- the assistant asserts a save it does not control and did not make. An honest
  "I cannot save that" would have surfaced this immediately.

`semantic_memory` and `episodic_memory` are empty for every real account.

### 2. Presentation slides render empty

Three of five slides in a generated deck had a title and purpose and nothing
else. Confirmed mechanism:

- `points` is **required** on `PlannedSlide` (`min_length=2`), so bullets always
  exist;
- a non-bullets layout (`statistic`, `section`, `comparison`) deliberately
  suppresses them — see the comment on the field;
- that layout's own fields (`statistic_value`, `quote`, `table_rows`) are all
  `default=None`.

So a slide validates with nothing renderable and nothing notices. Nondeterminism
follows: an earlier run of the same prompt did emit `stat_value: "11"`.

Fix: fall back to rendering the points when a layout's data is missing, and/or
require the field for the layout that was chosen. Each slide also gets only
1,024 tokens for a ~20-field object, which squeezes those fields out first.

### 3. Deck content is ungrounded

The per-slide contract solicits `statistic_value`, `quote_attribution`,
`table_rows` and `chart_series` with no retrieval behind them, so the model
invents them. Observed: *"a quarter of the world's 37-year-old inhabitants"*,
Apollo described as staying on budget, and `statistic: 11` for the number of
lunar landings (there were six). Fix is to ground the deck in search results at
outline time; the shared Tavily pool already provides the metering story.

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
