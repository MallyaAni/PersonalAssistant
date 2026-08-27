#!/usr/bin/env bash
# Bring the running system up to the current commit.
#
#   bash scripts/deploy.sh              # pull, then rebuild what changed
#   bash scripts/deploy.sh --no-pull    # deploy the working tree as it stands
#   bash scripts/deploy.sh --skip-gate  # ship without the unit suite and routing gate
#   bash scripts/deploy.sh --skip-post  # ship without the post-deploy sweep and harness
#
# This is the only deploy path. `docker compose up --build` by hand skips
# every check below, and on 2026-08-26 a build shipped that way had a
# seven-test regression sitting unnoticed among what looked like stale
# failures. Green or nothing ships; after the restart the live checks run,
# and a red one pages the operator.
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
post=true
for arg in "$@"; do
    case "$arg" in
        --no-pull)   pull=false ;;
        --skip-gate) gate=false ;;
        --skip-post) post=false ;;
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
    # The whole unit suite first: it is a minute, and it is where a
    # regression in a "done" item shows up before any model is asked.
    if ! bash "$root/scripts/gate.sh" --unit; then
        echo "Unit suite failed; the running system was left on the previous code." >&2
        echo "Fix or delete the failing test - a red suite hides the next regression." >&2
        exit 1
    fi
    if ! bash "$root/scripts/gate.sh"; then
        echo "Routing gate failed; the running system was left on the previous code." >&2
        echo "Re-run with --skip-gate only if you have read the failure and accept it." >&2
        exit 1
    fi
else
    echo "WARNING: unit suite and routing gate skipped by request"
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

$ok || { echo "verification failed" >&2; exit 1; }

# The live checks, on the code that is now serving: every journey a person
# takes, and the search chain. They run after the restart because they need
# the deployed system; a failure here is reported loudly and paged, not
# rolled back - the previous images are still present for a manual
# `docker compose up -d` of them if the failure warrants it.
step "Post-deploy checks"
post_ok=true
summary=()
if $post; then
    for check in backend.cli.sweep_journeys backend.cli.exercise_search_scenarios; do
        output="$("${compose[@]}" exec -T backend python -m "$check" 2>&1)"
        status=$?
        printf '%s\n' "$output"
        short="${check##*.}"
        if [[ $status -eq 0 ]]; then
            echo "$check: passed"
            summary+=("$short OK")
        else
            echo "$check: FAILED" >&2
            post_ok=false
            # What actually failed, in the words the operator can act on: the
            # gap lines themselves. "See the deploy log" paged the operator
            # once (2026-08-26) with nothing to act on from a phone.
            gaps="$(grep -E '^GAP |^FAIL ' <<<"$output" | sed -E 's/^(GAP |FAIL +[0-9a-z]* )//; s/: route=.*//; s/ \|.*//' | head -3 | paste -sd ';' -)"
            summary+=("$short FAILED: ${gaps:-see log}")
        fi
    done
    if ! $post_ok; then
        bash "$root/scripts/notify-operator.sh" "AniOS $after is live and healthy; a post-deploy check is red: $(IFS='; '; echo "${summary[*]}")" || true
    fi
else
    echo "WARNING: post-deploy checks skipped by request"
fi

step "Result"
echo "deployed $after"
$post_ok || { echo "deployed, but a post-deploy check failed" >&2; exit 1; }
