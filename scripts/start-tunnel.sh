#!/usr/bin/env bash
# Start the public tunnel and report the address it was given.
#
# Two modes, and which one runs depends only on whether a named tunnel has been
# set up:
#
# **Named** — `ANIOS_TUNNEL_NAME` in .env, pointing at a tunnel created once
# against the Cloudflare account that holds the domain. The hostname is stable,
# so nothing downstream has to be rewritten and a restart changes no addresses.
# This is the mode to be in; `docs/DEVELOPMENT_GUIDE.md` has the one-time setup.
#
# **Quick** — the fallback, and what this did exclusively before a domain
# existed. A quick tunnel mints a new random hostname every time it starts, so
# this also rewrites DISCOVERY_CALENDAR_BASE_URL: an address embedded in an
# invite and left pointing at a dead hostname fails silently on the recipient's
# phone rather than here.
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

# Read the named-tunnel settings without sourcing .env, which would execute
# whatever is in it and export every key in the file.
env_file="$root/.env"
read_env() {
    [ -f "$env_file" ] || return 0
    sed -n "s/^$1=//p" "$env_file" | tail -1 | tr -d '\r' | sed 's/^"//;s/"$//'
}
tunnel_name="$(read_env ANIOS_TUNNEL_NAME)"
public_host="$(read_env ANIOS_PUBLIC_HOSTNAME)"

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

# A named tunnel serves a hostname that already exists in DNS, so there is no
# address to discover, nothing downstream to rewrite, and a restart is invisible
# to anyone holding a link.
if [ -n "$tunnel_name" ]; then
    if [ -z "$public_host" ]; then
        echo "ANIOS_TUNNEL_NAME is set but ANIOS_PUBLIC_HOSTNAME is not." >&2
        echo "Both are needed: the tunnel to run, and the hostname to report." >&2
        exit 1
    fi
    echo "==> Starting named tunnel '$tunnel_name'"
    : > "$log"
    "$exe" tunnel --no-autoupdate run "$tunnel_name" >"$log" 2>&1 &
    pid=$!
    # Registration is the only thing worth waiting for. Reporting a hostname
    # before the tunnel has connected invites the check below to test an address
    # that is about to work and does not yet.
    for _ in $(seq 1 30); do
        grep -qiE "registered tunnel connection|connection.*registered" "$log" && break
        kill -0 "$pid" 2>/dev/null || { echo "Tunnel exited. See $log" >&2; exit 1; }
        sleep 2
    done
    echo "https://$public_host"
    echo
    echo "Tunnel is running as pid $pid. Stopping it takes the site offline."
    echo "Nothing downstream needs updating: the hostname is stable."
    echo "Log: $log"
    echo
    echo "Verify from somewhere that is not this machine — a check from here can"
    echo "resolve back to the local stack and report a healthy site that is"
    echo "publicly dead:"
    echo "    docker compose exec -T backend python -c \\"
    echo "      \"import urllib.request;print(urllib.request.urlopen('https://$public_host/healthz',timeout=15).status)\""
    exit 0
fi

echo "==> Starting quick tunnel (no ANIOS_TUNNEL_NAME set)"
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

# Point calendar links at the address that actually exists now. Only the quick
# tunnel needs this: a named tunnel's hostname does not change, which is most of
# the reason to move to one.
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
