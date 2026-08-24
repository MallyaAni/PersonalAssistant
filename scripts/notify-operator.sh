#!/usr/bin/env bash
# Send one alert to the operator over the iMessage bridge.
#
#   bash scripts/notify-operator.sh "something broke"
#
# The point is observability the operator actually sees: this system already
# has an outbound channel and never used it to say when something failed - the
# bridge was once down nine days unnoticed. Wire this into a systemd OnFailure
# (see deploy/spark/systemd/anios-backup-failed.service) so a failed job pages
# the phone instead of a log nobody reads.
#
# Best-effort by design. If the alert path is unconfigured or the bridge is
# unreachable, it logs and exits 0: an alert that fails must never itself become
# a failure. It is host-level and curl-only on purpose - no backend, no Python
# package deps - so it works from a bare systemd unit even when the app is down.
#
# Reads three values from the environment or ./.env:
#   ALERT_BRIDGE_URL      the bridge MCP endpoint, e.g. http://<mac-lan-ip>:8010/mcp
#   ALERT_BRIDGE_TOKEN    the x-anios-bridge-token shared secret
#   OPERATOR_ALERT_PHONE  the operator's number in E.164, allowlisted on the Mac
set -uo pipefail

message="${1:-AniOS alert}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# From the environment first, then .env. `\r` stripped so a CRLF line ending
# cannot leave a trailing carriage return on the URL or token.
env_get() {
    grep -m1 -E "^\s*$1\s*=" "$root/.env" 2>/dev/null | cut -d= -f2- | tr -d ' \r\n'
}
url="${ALERT_BRIDGE_URL:-$(env_get ALERT_BRIDGE_URL)}"
token="${ALERT_BRIDGE_TOKEN:-$(env_get ALERT_BRIDGE_TOKEN)}"
to="${OPERATOR_ALERT_PHONE:-$(env_get OPERATOR_ALERT_PHONE)}"

if [[ -z "$url" || -z "$token" || -z "$to" ]]; then
    echo "notify-operator: alert path not configured; message was: $message" >&2
    exit 0
fi

# Build the JSON with python3 so a message containing quotes or newlines cannot
# break the payload. python3 is present on the Spark hosts; if it is somehow
# absent, fall back to a plain (quote-free) payload rather than failing.
if command -v python3 >/dev/null 2>&1; then
    payload="$(python3 - "$to" "$message" <<'PY'
import json, sys
to, message = sys.argv[1], sys.argv[2]
print(json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {"name": "send_imessage", "arguments": {"to": to, "body": message}},
}))
PY
)"
else
    payload="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"send_imessage\",\"arguments\":{\"to\":\"$to\",\"body\":\"${message//\"/}\"}}}"
fi

if curl -s -m 20 \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H "x-anios-bridge-token: $token" \
    -X POST "$url" -d "$payload" >/dev/null; then
    echo "notify-operator: alert sent"
else
    echo "notify-operator: bridge unreachable; message was: $message" >&2
fi
exit 0
