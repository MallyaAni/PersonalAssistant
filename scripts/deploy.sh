#!/usr/bin/env bash
# Bring the running system up to the current commit.
#
#   bash scripts/deploy.sh              # pull, then rebuild what changed
#   bash scripts/deploy.sh --no-pull    # deploy the working tree as it stands
#   bash scripts/deploy.sh --skip-gate  # ship without the routing gate
#
# Written to be run over any remote shell:
#
#   ssh ani-desktop 'cd /path/to/AniOS && bash scripts/deploy.sh'
#
# Pushing to git changes nothing by itself — no process here watches the
# repository, and the running containers serve whatever images were last built.
# This is the step in between, and it is deliberately manual: the public URL has
# real users on it, and rebuilding unreviewed code on push is how a typo becomes
# an outage someone else notices first.
#
# The order matters. Back up before migrating, migrate before starting the code
# that expects the new schema, and verify after — a container that restarts is
# not evidence that anything works.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/docker-compose.yml")
pull=true
gate=true
for arg in "$@"; do
    case "$arg" in
        --no-pull)   pull=false ;;
        --skip-gate) gate=false ;;
    esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "Current state"
before="$(git -C "$root" rev-parse --short HEAD)"
echo "at $before on $(git -C "$root" rev-parse --abbrev-ref HEAD)"
if [[ -n "$(git -C "$root" status --porcelain)" ]]; then
    # Deploying a dirty tree is legitimate while developing, but it means the
    # running system does not correspond to any commit, so say so out loud.
    echo "WARNING: working tree has uncommitted changes; the deployed state will"
    echo "         not match any commit."
fi

if $pull; then
    step "Pulling"
    git -C "$root" pull --ff-only
fi

after="$(git -C "$root" rev-parse --short HEAD)"
if [[ "$before" == "$after" ]] && $pull; then
    echo "already at $after"
fi

# Rebuild only what the change actually touched. A full rebuild of every image
# takes minutes and is almost never what a deploy needs.
step "Deciding what to rebuild"
changed="$(git -C "$root" diff --name-only "$before" "$after" 2>/dev/null || true)"
services=()
if [[ -z "$changed" ]] || grep -qE '^(backend/|requirements|pyproject|Dockerfile)' <<<"$changed"; then
    # All six services that build from the root Dockerfile. Three of them -
    # local-capabilities, memory-maintenance, storage-collection - were missing
    # here, so a backend change deployed cleanly and left those containers
    # running last week's code with nothing reporting a difference.
    services+=(
        backend discovery-worker presentation-worker
        local-capabilities memory-maintenance storage-collection
    )
fi
if [[ -z "$changed" ]] || grep -qE '^frontend/' <<<"$changed"; then
    services+=(frontend gateway)
fi
if [[ ${#services[@]} -eq 0 ]]; then
    echo "no code changes; skipping rebuild"
else
    echo "rebuilding: ${services[*]}"
    step "Building"
    "${compose[@]}" build "${services[@]}"
fi

step "Gating"
# Before the backup and the migration on purpose: a failing gate at this point
# has changed nothing, and the running system is still on the previous images.
# --skip-gate exists because a model gate can flake and the public URL has real
# users; a hotfix that cannot ship is a worse outage than the regression this
# guards against.
if $gate; then
    if ! bash "$root/scripts/gate.sh"; then
        echo "Routing gate failed; the running system was left on the previous code." >&2
        echo "Re-run with --skip-gate only if you have read the failure and accept it." >&2
        exit 1
    fi
else
    echo "WARNING: routing gate skipped by request"
fi

step "Backing up before touching the schema"
bash "$root/scripts/backup-db.sh"

step "Applying migrations"
"${compose[@]}" up -d --wait db
if ! "${compose[@]}" run --rm -e POSTGRES_HOST=db \
    -v "$root/migrations:/app/migrations:ro" \
    backend python -m alembic upgrade head; then
    echo "Migration failed; the running system was left on the previous code." >&2
    exit 1
fi

step "Restarting"
if [[ ${#services[@]} -gt 0 ]]; then
    "${compose[@]}" up -d "${services[@]}"
else
    "${compose[@]}" up -d
fi

# A restarted container proves nothing, and neither does the gateway's own
# health page — that is served by Nginx and would answer even with the backend
# down. This asks for a private API route instead, which only answers correctly
# when Nginx reaches the backend *and* the authentication boundary is intact.
# One check, covering the whole chain.
step "Verifying"
ok=false
code=000
for attempt in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w '%{http_code}'         --max-time 5 http://localhost:8080/api/v1/memory/probe || echo 000)"
    case "$code" in
        401 | 403)
            ok=true
            break
            ;;
        200)
            # A private route answering without credentials means the boundary
            # is gone, which is worse than being down. Stop immediately.
            echo "FATAL: a private route answered $code without credentials" >&2
            break
            ;;
    esac
    sleep 3
done

if $ok; then
    echo "backend reachable through the gateway and refusing anonymous access ($code)"
else
    echo "verification failed: private route returned $code, expected 401/403" >&2
    echo "recent backend logs:" >&2
    "${compose[@]}" logs --tail 20 backend >&2 || true
fi

step "Result"
echo "deployed $after"
$ok || { echo "verification failed" >&2; exit 1; }
