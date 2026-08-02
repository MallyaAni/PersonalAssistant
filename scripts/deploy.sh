#!/usr/bin/env bash
# Bring the running system up to the current commit.
#
#   bash scripts/deploy.sh              # pull, then rebuild what changed
#   bash scripts/deploy.sh --no-pull    # deploy the working tree as it stands
#
# Written to be run over Tailscale SSH from anywhere:
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
[[ "${1:-}" == "--no-pull" ]] && pull=false

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
    services+=(backend discovery-worker presentation-worker)
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

# A restarted container proves nothing. Ask the system whether it works.
step "Verifying"
ok=true
for attempt in $(seq 1 20); do
    if curl -fsS --max-time 3 http://localhost:8080/health >/dev/null 2>&1; then
        break
    fi
    [[ $attempt -eq 20 ]] && ok=false
    sleep 3
done

if $ok; then
    echo "gateway healthy"
else
    echo "gateway did not become healthy" >&2
fi

# The authentication boundary is the only thing between the public URL and this
# machine, so a deploy that quietly disabled it must not look like a success.
code="$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/v1/memory/probe || echo 000)"
if [[ "$code" == "401" || "$code" == "403" ]]; then
    echo "auth boundary holding ($code on an unauthenticated private call)"
else
    echo "WARNING: unauthenticated private call returned $code, expected 401/403" >&2
    ok=false
fi

step "Result"
echo "deployed $after"
$ok || { echo "verification failed" >&2; exit 1; }
