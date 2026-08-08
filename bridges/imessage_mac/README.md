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
# Loopback by default. Set this only when AniOS is on another machine.
export IMESSAGE_BRIDGE_HOST=0.0.0.0
export IMESSAGE_BRIDGE_PORT=8010

python3 server.py
```

The Mac also needs to be:

- **signed into iMessage** in Messages;
- **granted Automation permission** for Messages — macOS prompts on the first
  send, and it must be accepted while someone is at the keyboard;
- **awake and logged in.** Messages can only send from an active user session, so
  sleep silently breaks this. `caffeinate -s` or an Energy Saver change.

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
