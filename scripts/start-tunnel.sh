#!/usr/bin/env bash
# Start the public tunnel and report the address it was given.
#
# A quick tunnel mints a new random hostname every time it starts, so this also
# rewrites DISCOVERY_CALENDAR_BASE_URL. Calendar invites embed that address, and
# one left pointing at a dead hostname fails silently on the recipient's phone
# rather than here.
#
# Replacing this with a named tunnel is the real fix: a stable hostname, and
# installation as a service so a reboot does not need anyone to run this.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log="$root/data/tunnel.log"
mkdir -p "$(dirname "$log")"

exe="cloudflared"
command -v "$exe" >/dev/null 2>&1 || exe="/c/Program Files (x86)/cloudflared/cloudflared.exe"
if ! [ -x "$exe" ] && ! command -v "$exe" >/dev/null 2>&1; then
    echo "cloudflared is not installed. winget install Cloudflare.cloudflared" >&2
    exit 1
fi

if ! curl -sf -o /dev/null --max-time 5 http://localhost:8080/; then
    echo "Nothing is serving on localhost:8080. Start the stack first:" >&2
    echo "    bash scripts/start-anios.sh" >&2
    exit 1
fi

# A second tunnel would serve the same site on a different hostname and quietly
# overwrite the calendar URL with it, so the first one becomes unreachable while
# still running.
if pgrep -f "cloudflared.*trycloudflare|cloudflared.exe" >/dev/null 2>&1 ||
    tasklist 2>/dev/null | grep -qi cloudflared; then
    existing="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" 2>/dev/null | head -1 || true)"
    echo "A tunnel is already running${existing:+ at $existing}." >&2
    echo "Stop it first if you want a new address." >&2
    exit 1
fi

echo "==> Starting tunnel"
: > "$log"
"$exe" tunnel --url http://localhost:8080 --no-autoupdate >"$log" 2>&1 &
pid=$!

# The address only appears once the tunnel has registered, so wait for it
# rather than reporting a hostname that does not exist yet.
url=""
for _ in $(seq 1 30); do
    url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" | head -1 || true)"
    [ -n "$url" ] && break
    kill -0 "$pid" 2>/dev/null || { echo "Tunnel exited. See $log" >&2; exit 1; }
    sleep 2
done
[ -n "$url" ] || { echo "No address after 60s. See $log" >&2; exit 1; }

echo "$url"

# Point calendar links at the address that actually exists now.
env_file="$root/.env"
if [ -f "$env_file" ] && grep -q '^DISCOVERY_CALENDAR_BASE_URL=' "$env_file"; then
    tmp="$(mktemp)"
    sed "s|^DISCOVERY_CALENDAR_BASE_URL=.*|DISCOVERY_CALENDAR_BASE_URL=$url/api/v1/discovery|" \
        "$env_file" >"$tmp" && mv "$tmp" "$env_file"
    echo "==> Updated DISCOVERY_CALENDAR_BASE_URL"
    echo "    Recreate the containers that read it so they pick it up:"
    echo "    docker compose up -d backend discovery-worker"
fi

echo
echo "Tunnel is running as pid $pid. Stopping it takes the site offline."
echo "Log: $log"
