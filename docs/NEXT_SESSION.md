# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-08-08, America/New_York (iMessage bridge Mac-side verification)

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
- **The bridge needs the Mac to actually stay up.** `pmset -g` showed
  `sleep 1` (1 minute) by default on this machine; fixed with
  `sudo pmset -c sleep 0` and `sudo pmset -c disksleep 0` (scoped to AC power
  only, on purpose — battery behavior is untouched). A laptop's lid still
  forces sleep regardless of `pmset` unless it's in clamshell mode with an
  external display attached.
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

Was: all eight extractors in `backend/memory/proposals.py` returned `None` for
"Remember that my dog is called Biscuit.", and the assistant claimed a save
anyway. Now `propose_semantic_fact` catches an explicit save request that no
narrower proposer claimed, and the reply is honest.

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
