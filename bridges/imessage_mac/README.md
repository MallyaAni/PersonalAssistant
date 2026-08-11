# iMessage bridge

Sends iMessages on behalf of AniOS. **Runs on a Mac**, not with AniOS.

Apple publishes no server-side iMessage API. The only unpaid way to send one is a
Mac signed into Messages, driven locally — so this is that machine's side of the
boundary. AniOS decides *whether* to send and what to say; this decides nothing
and only sends.

It speaks streamable HTTP rather than stdio precisely because the two are
different machines: AniOS may run on Windows today and a DGX Spark tomorrow, and
neither can spawn a process on the Mac.

## What it enforces on its own

A bridge that trusts its caller has no protections, so it holds three
independently of whatever asked it to send.

**A recipient allowlist.** It sends only to numbers or Apple IDs you list. This
is the last hop before a message reaches a real person, and the only place that
can refuse regardless of what AniOS was persuaded to ask for.

**A shared secret.** Anything on your network can reach an HTTP port. Without a
token this is an open "send an iMessage as me" endpoint. There is no default and
it refuses to start without one.

It is checked at the transport, as the `x-anios-bridge-token` header, and an
unauthenticated request is refused before it reaches any tool. It was originally
a tool argument, which cannot work against AniOS: every string argument passes
the outbound privacy gate before leaving, and a high-entropy secret is exactly
what that gate exists to stop.

**No AppleScript interpolation.** Arguments reach `osascript` as argv and are
read with `on run argv`, so a message body containing quotes or backslashes is
data, never script. Building the script by string formatting is how a bridge like
this becomes a remote code execution hole.

Attachments are restricted to `.ics` files whose bytes actually begin
`BEGIN:VCALENDAR`. A general file-sending endpoint on a machine signed into your
Apple ID is a much larger thing than this needs to be.

## Setup on the Mac

**Python 3.10 or newer is required**, because `mcp` requires it. macOS still
ships 3.9 as `python3`, and building the environment with that fails at install
time with `no matching distribution found for mcp` — which names the package
rather than the version that caused it. Check first, and use the newer
interpreter by name:

```bash
python3 --version                  # 3.10+? if not:
ls /usr/local/bin/python3.* /opt/homebrew/bin/python3.* 2>/dev/null
brew install python@3.12           # or the installer from python.org
```

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Print it — the same value goes into the AniOS side below.
export IMESSAGE_BRIDGE_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
echo "$IMESSAGE_BRIDGE_TOKEN"
export IMESSAGE_BRIDGE_RECIPIENTS="+15550100,+15550101"
# Let an AniOS operator approval add a recipient to a separate persisted file.
export IMESSAGE_BRIDGE_ALLOW_GRANTS=true
export IMESSAGE_BRIDGE_GRANTS="$HOME/.anios-imessage-bridge/granted-recipients.json"
# Loopback by default. Set this only when AniOS is on another machine.
export IMESSAGE_BRIDGE_HOST=0.0.0.0
export IMESSAGE_BRIDGE_PORT=8010
# Optional, and off unless you turn it on. See "Reading reactions" below.
export IMESSAGE_BRIDGE_READ_REACTIONS=true

python3 server.py
```

## Reading reactions

Scout sends a digest as one message per find so each can carry a tapback — the
👍 or 👎 you get by long-pressing a bubble. That is the only way it learns what
someone actually liked, rather than what they said they already knew.

Apple provides no callback when a reaction is left, so the only way to see one is
to read the Messages database. That needs **Full Disk Access** for whatever runs
this bridge (`Terminal`, or the LaunchAgent's executable), which is a different
and larger grant than the automation permission sending needs. It is therefore
off by default, and turning it on is a deliberate decision:

```bash
export IMESSAGE_BRIDGE_READ_REACTIONS=true
# Optional; defaults to ~/Library/Messages/chat.db
export IMESSAGE_BRIDGE_MESSAGES_DB="$HOME/Library/Messages/chat.db"
```

What it reads is deliberately narrow, and worth checking against the code rather
than taking on trust:

- the database is opened **read-only**, so this cannot write to it or take a
  lock Messages would notice. Read-only rather than immutable, because immutable
  makes SQLite skip the write-ahead log, where a message sent moments ago still
  is;
- AniOS asks with the **bodies of messages it composed itself**, and the bridge
  answers by position: "the third one you gave me was thumbed up". It cannot be
  asked about a message AniOS did not send, because it has nothing to match such
  a message against;
- **no message text is ever returned.** Bodies are read to compare them and
  discarded; only positions, a reaction type and a timestamp come back. There is
  no tool here that can be asked what anyone has said;
- only 👍 and 👎 are reported. The other four tapbacks are ambiguous about
  whether someone wants more of something.

### Reacting from a phone, in a thread with yourself

A digest sent to your own Apple ID gives your phone a **different message object**
from the one this Mac sent. React there and the tapback points at the phone's
copy — a row this Mac never stored — so it arrives referencing nothing, and no
amount of matching will connect it.

React in Messages **on this Mac** and it records immediately. Subscribers are
unaffected: a normal recipient's reaction references the sender's own message,
which is the case the feature is built for. It is only the owner messaging
themselves that cannot work, and that is exactly what testing tends to use.

Leave it off and everything still works: digests send exactly as before, and
AniOS records that it sent them with no identifier and collects no feedback.

When the bridge runs as a LaunchAgent, put both grant variables in its
`EnvironmentVariables` dictionary and reload the agent. Setting them only in an
interactive Terminal does not reach an already-running LaunchAgent. The grant
file is an extension of the operator's allowlist: keep it private and writable
only by the logged-in bridge account.

The Mac also needs to be:

- **signed into iMessage** in Messages;
- **granted Automation permission** for Messages — macOS prompts on the first
  send, and it must be accepted while someone is at the keyboard;
- **awake and logged in.** Messages can only send from an active user session, so
  sleep silently breaks this. `caffeinate -s` prevents sleep only while the Mac
  is on AC power; use `caffeinate -i` for a battery-safe idle-sleep assertion,
  or change the applicable macOS power setting. Closing the laptop lid still
  sleeps the Mac unless it is in supported clamshell mode.

## Pointing AniOS at it

Add the bridge to `MCP_SERVERS_JSON` using the Mac's LAN address, then enable
egress:

```jsonc
[
  {
    // `server_id`, not `id`, and `http`, not `streamable-http` — those are the
    // names the parser reads, and an entry it cannot parse is skipped silently.
    "server_id": "imessage",
    "transport": "http",
    "url": "http://<mac-lan-ip>:8010/mcp",
    "headers": { "x-anios-bridge-token": "<the token printed above>" },
    // Sending is not replay-safe: a dropped connection does not prove the
    // message was not delivered. Only `read_only` and `trusted` are retried, so
    // this must be neither, or a timeout can send the same digest twice.
    "risk_classification": "untrusted",
    "enabled": true
  }
]
```

```bash
DISCOVERY_EGRESS_ENABLED=true
DISCOVERY_IMESSAGE_SERVER_ID=imessage
DISCOVERY_IMESSAGE_TOOL=send_imessage
```

From a container, the Mac is its **LAN address** — `host.docker.internal`
resolves to the machine running Docker, which is not the Mac.

## Moving AniOS to a DGX Spark

Nothing here changes. The bridge is host-independent: it only needs AniOS to
reach it over the network, so moving AniOS from Windows to a Spark means
updating one URL. The Mac remains the sender because that is an Apple hardware
constraint, not an architectural choice.

## Verifying before trusting it

```bash
# Refused: not on the allowlist.
curl -s -X POST http://<mac-lan-ip>:8010/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"send_imessage",
       "arguments":{"token":"...","to":"+19999999999","body":"test"}}}'
```

Send to yourself first. The failure modes worth seeing before you trust it are a
declined Automation prompt and a sleeping Mac, and both are quiet.
