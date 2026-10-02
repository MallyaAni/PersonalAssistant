#!/usr/bin/env bash
# Bring the running system up to the current commit.
#
#   bash scripts/deploy.sh              # fetch, gate, then rebuild what changed
#   bash scripts/deploy.sh --no-pull    # deploy the checkout's HEAD as it stands
#   bash scripts/deploy.sh --skip-gate  # ship without the unit suite and routing gate
#   bash scripts/deploy.sh --skip-post  # ship without the post-deploy checks
#   bash scripts/deploy.sh --wait-post  # wait for the sweep instead of detaching it
#   bash scripts/deploy.sh --run-post   # force the full post-deploy sweep and harness
#   bash scripts/deploy.sh --dry-run    # fetch and gate for real, then only say what would change
#   bash scripts/deploy.sh --restore    # put the checkout back on data/.deployed-commit
#   bash scripts/deploy.sh --deploy-dir=DIR  # act on DIR instead of this script's checkout
#
# Gate first, touch second (2026-10-02). The cron jobs - the market balancer
# every 15 minutes from 09:00 to 16:00 ET and the 19:30 ET nightly - run
# Python straight from the deploy checkout (~/deploy/anios on spark1), and
# the `anios_frontend` Vite dev server mounts its frontend/. This script used
# to pull into that checkout and build the `:latest` images before the gate
# ran, so a failed gate left cron, the dev server and the next plain
# `docker compose up -d` on code that had just failed: on 2026-10-02 the
# checkout sat on the failed 0dfdcd89 while the containers ran 8be5ecbe.
# Now the target commit is gated in its own worktree under
# <deploy-dir>/../.gate/<sha>, against a test database of its own
# (anios_gate_deploy), and only a pass moves the checkout, builds and tags
# images, and restarts anything. A failed gate exits non-zero having changed
# nothing. A failure after the checkout moved but before the restart puts the
# checkout and the `:latest` tags back. Never `git pull` or `git merge` into
# the deploy checkout by hand: that is exactly the ungated window this closes.
#
# Around the desk: the checkout only moves when no market_balancer or
# market_daily is running and no balancer run is about to start, and the
# script refuses to start (or to move the checkout) between 19:20 and 19:55
# ET, the nightly's window. Market-hours deploys are allowed (operator,
# 2026-10-02); they wait for a gap between balancer runs instead. A lock
# (data/.deploy.lock, flock) refuses a second deploy while one runs. At start
# the script warns loudly when the checkout's HEAD is not the deployed commit,
# and --restore checks the deployed commit out again.
#
# A change that touches nothing the backend runs - the frontend, docs - takes
# the short path (2026-09-08): no unit suite, no routing gate, no backup, no
# migration, just the rebuild of the images it touched and the restart.
# Those gates guard backend regressions and model routing, which a
# frontend-only diff cannot change; the frontend's own type check runs in
# its image build. Before this every deploy took the full fifteen minutes
# and a wording change waited on a hundred model calls.
#
# The credit-consuming post-deploy sweep and search harness (one live
# provider query per question) run only when the change touched the search
# chain or the router's tool choice; any other deploy runs the cheap smoke
# instead. See "Post-deploy checks" below - on 2026-08-29 deploy sweeps
# spent 344 of the month's 403 searches, against an allowance that is no
# longer free.
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
# The order matters. Gate before touching anything, back up before migrating,
# migrate before starting the code that expects the new schema, and verify
# after — a container that restarts is not evidence that anything works.
#
# The whole script is one function called on the last line, so bash has read
# all of it before the checkout - which contains this file - moves.

set -euo pipefail

# See scripts/gate.sh: Git Bash rewrites the paths inside a `-v` argument and
# docker then creates a host directory named after the mangled result. This
# script mounts migrations/ the same way. A no-op on Linux, where deploys run.
export MSYS2_ARG_CONV_EXCL='*'
export MSYS_NO_PATHCONV=1

# What the exit handler needs to know about how far the deploy got.
# phase: "untouched" until the checkout moves, "moved" until the restart
# begins (a failure in between is rolled back), "restarted" after.
phase=untouched
gate_tree=""
prev_head=""
root=""
declare -A old_image_ids=()

# Print a section heading the way every deploy log has shown them.
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# A commit's abbreviated SHA, as the rest of the log prints them.
short() { git -C "$root" rev-parse --short "$1"; }

# Say plainly, after a refusal or a failed gate, that nothing was touched.
nothing_changed() {
    echo "$1" >&2
    echo "NOTHING CHANGED: $root is still at $(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo '?');" >&2
    echo "                 no image was built or tagged and no container was restarted." >&2
}

# The wall clock in New York as HHMM; tests pin it with ANIOS_DEPLOY_CLOCK.
et_hhmm() {
    if [[ -n "${ANIOS_DEPLOY_CLOCK:-}" ]]; then
        echo "$ANIOS_DEPLOY_CLOCK"
    else
        TZ=America/New_York date +%H%M
    fi
}

# Whether it is now inside the nightly's window, 19:20-19:55 ET.
in_nightly_window() {
    local now
    now=$((10#$(et_hhmm)))
    ((now >= 1920 && now < 1955))
}

# Whether a desk job that imports from the checkout is running right now.
desk_job_running() {
    pgrep -f "${ANIOS_DEPLOY_DESK_PATTERN:-[b]ackend\.cli\.market_(balancer|daily)}" >/dev/null 2>&1
}

# Seconds until the next quarter-hour balancer tick, when that tick is a real
# cron run (weekday, 09:00-16:45 ET) less than a minute away; empty otherwise.
seconds_to_balancer_tick() {
    [[ "${ANIOS_DEPLOY_TICK_GUARD:-1}" == 1 ]] || return 0
    local now left next hour dow
    now=$(date +%s)
    left=$((900 - now % 900))
    ((left < 60)) || return 0
    next=$((now + left))
    hour=$((10#$(TZ=America/New_York date -d "@$next" +%H)))
    dow=$(TZ=America/New_York date -d "@$next" +%u)
    if ((hour >= 9 && hour <= 16 && dow <= 5)); then
        echo "$left"
    fi
}

# Block until no balancer or nightly is importing from the checkout and no
# balancer run is about to start; fail after ANIOS_DEPLOY_WAIT_SECONDS.
wait_for_desk_jobs() {
    local waited=0 announced=false tick
    local limit="${ANIOS_DEPLOY_WAIT_SECONDS:-1800}" poll="${ANIOS_DEPLOY_POLL_SECONDS:-10}"
    while :; do
        if desk_job_running; then
            if ! $announced; then
                echo "waiting for the running market_balancer/market_daily to finish before touching $root"
                announced=true
            fi
            if ((waited >= limit)); then
                echo "a desk job was still running after ${limit}s" >&2
                return 1
            fi
            sleep "$poll"
            waited=$((waited + poll))
            continue
        fi
        tick="$(seconds_to_balancer_tick)"
        if [[ -n "$tick" ]]; then
            echo "a balancer run starts in ${tick}s; letting it start and finish first"
            sleep $((tick + 15))
            waited=$((waited + tick + 15))
            continue
        fi
        return 0
    done
}

# Hold an exclusive lock for the whole run, so a second deploy refuses rather
# than interleaving with this one on the checkout, the images or the gate DB.
take_lock() {
    local lock_file="${ANIOS_DEPLOY_LOCK:-$root/data/.deploy.lock}"
    mkdir -p "$(dirname "$lock_file")"
    exec 9>>"$lock_file"
    if ! flock -n 9; then
        nothing_changed "Another deploy holds $lock_file ($(head -c 200 "$lock_file" 2>/dev/null)); refusing to start a second one."
        exit 1
    fi
    printf 'pid %s since %s\n' "$$" "$(date -u +%FT%TZ)" >"$lock_file"
}

# The commit the last successful deploy recorded, as a full SHA, or empty.
deployed_commit() {
    local marked
    marked="$(cat "$deployed_marker" 2>/dev/null || true)"
    [[ -n "$marked" ]] || return 0
    git -C "$root" rev-parse --verify -q "$marked^{commit}" || true
}

# Warn loudly when the checkout the cron jobs run is not the deployed commit.
self_check() {
    local head marked
    head="$(git -C "$root" rev-parse HEAD)"
    marked="$(deployed_commit)"
    if [[ -n "$marked" && "$head" != "$marked" ]]; then
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
        echo "!!! WARNING: $root is at $(short "$head"), but the deployed commit" >&2
        echo "!!! (data/.deployed-commit) is $(short "$marked"). The cron jobs and the Vite dev" >&2
        echo "!!! server run $(short "$head"); the containers run $(short "$marked")." >&2
        echo "!!! \`bash scripts/deploy.sh --restore\` checks $(short "$marked") out again;" >&2
        echo "!!! a successful deploy moves both to the new commit." >&2
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    fi
}

# Whether the checkout has edits to tracked files (untracked data/ and
# secrets/ symlinks are expected there and do not count).
tracked_changes() {
    [[ -n "$(git -C "$root" status --porcelain --untracked-files=no)" ]]
}

# --restore: put the checkout back on the deployed commit between desk runs,
# without touching images or containers.
restore_checkout() {
    step "Restoring the checkout to the deployed commit"
    local head marked
    head="$(git -C "$root" rev-parse HEAD)"
    marked="$(deployed_commit)"
    if [[ -z "$marked" ]]; then
        echo "no usable deployed commit in $deployed_marker; nothing to restore to" >&2
        exit 1
    fi
    if [[ "$head" == "$marked" ]]; then
        echo "checkout already at the deployed commit $(short "$marked")"
        return 0
    fi
    if tracked_changes; then
        nothing_changed "The checkout has edits to tracked files; not resetting over them."
        exit 1
    fi
    if $dry_run; then
        echo "dry run: would wait for the desk jobs, then move $root $(short "$head") -> $(short "$marked")"
        return 0
    fi
    if ! wait_for_desk_jobs; then
        nothing_changed "Gave up waiting for the desk jobs."
        exit 1
    fi
    # --keep moves the branch and refuses rather than overwrite a local edit.
    git -C "$root" reset --quiet --keep "$marked"
    echo "checkout moved $(short "$head") -> $(short "$marked"); images and containers untouched"
}

# The commit this deploy would ship, found without touching the checkout:
# what `git pull --ff-only` would reach, or HEAD itself with --no-pull.
resolve_target() {
    local head upstream
    head="$(git -C "$root" rev-parse HEAD)"
    if ! $pull; then
        target="$head"
        return 0
    fi
    # Called as a condition, where `set -e` is off: every step checks itself.
    if ! git -C "$root" fetch --quiet; then
        nothing_changed "git fetch failed."
        return 1
    fi
    if ! upstream="$(git -C "$root" rev-parse --verify -q '@{u}')"; then
        nothing_changed "The checkout has no upstream branch (detached HEAD?); use --no-pull or check a branch out."
        return 1
    fi
    if git -C "$root" merge-base --is-ancestor "$head" "$upstream"; then
        target="$upstream"
    elif git -C "$root" merge-base --is-ancestor "$upstream" "$head"; then
        echo "checkout is ahead of its upstream; deploying its HEAD"
        target="$head"
    else
        nothing_changed "The checkout and its upstream have diverged; a fast-forward is impossible."
        return 1
    fi
}

# Check out the target commit in a fresh worktree of its own, with the deploy
# checkout's .env beside it, so the gate reads that commit while nothing the
# cron jobs import moves.
make_gate_tree() {
    local gate_root="${ANIOS_DEPLOY_GATE_DIR:-$(dirname "$root")/.gate}"
    gate_tree="$gate_root/$after"
    if [[ -e "$gate_tree" ]]; then
        git -C "$root" worktree remove --force "$gate_tree" 2>/dev/null || rm -rf "$gate_tree"
    fi
    git -C "$root" worktree prune
    mkdir -p "$gate_root"
    git -C "$root" worktree add --quiet --detach "$gate_tree" "$target"
    if [[ -e "$root/.env" ]]; then
        ln -s "$(readlink -f "$root/.env")" "$gate_tree/.env"
    fi
    echo "gating $after in $gate_tree"
}

# Remove the gate worktree, whatever the outcome.
drop_gate_tree() {
    [[ -n "$gate_tree" ]] || return 0
    git -C "$root" worktree remove --force "$gate_tree" 2>/dev/null || rm -rf "$gate_tree"
    git -C "$root" worktree prune 2>/dev/null || true
    gate_tree=""
}

# Make sure the live db and redis are up, starting them from the deploy
# checkout (never from the gate tree) when a real deploy finds them down.
ensure_infra() {
    local running
    running="$("${compose[@]}" ps --status running --services 2>/dev/null || true)"
    if grep -qx db <<<"$running" && grep -qx redis <<<"$running"; then
        return 0
    fi
    if $dry_run; then
        echo "dry run: db or redis is not running, and a dry run starts nothing" >&2
        return 1
    fi
    "${compose[@]}" up -d --wait redis db >/dev/null
}

# Run the unit suite, then the routing gate, from the gate worktree: its own
# scripts and code, the live project's db and redis, the deploy's own test DB.
run_gates() {
    local -a gate_env=(
        COMPOSE_PROJECT_NAME="$project"
        ANIOS_GATE_DB="${ANIOS_DEPLOY_GATE_DB:-anios_gate_deploy}"
        ANIOS_GATE_SKIP_INFRA=1
        ANIOS_FUNCTIONAL_TESTS_IMAGE="anios-functional-tests:deploy-gate"
    )
    if ! ensure_infra; then
        nothing_changed "db/redis unavailable for the gate."
        return 1
    fi
    # The whole unit suite first: it is a minute, and it is where a
    # regression in a "done" item shows up before any model is asked.
    if ! env "${gate_env[@]}" bash "$gate_tree/scripts/gate.sh" --unit; then
        nothing_changed "Unit suite failed on $after."
        echo "Fix or delete the failing test - a red suite hides the next regression." >&2
        return 1
    fi
    if ! env "${gate_env[@]}" bash "$gate_tree/scripts/gate.sh"; then
        nothing_changed "Routing gate failed on $after."
        echo "Re-run with --skip-gate only if you have read the failure and accept it." >&2
        return 1
    fi
}

# Move the checkout to the gated commit, fast-forward only, once no desk job
# is importing from it and the nightly's window is closed.
checkout_gated() {
    if ! wait_for_desk_jobs; then
        nothing_changed "Gave up waiting for the desk jobs; the gate passed but nothing was moved."
        return 1
    fi
    if in_nightly_window; then
        nothing_changed "The gate passed, but it is now inside the nightly's window (19:20-19:55 ET). Re-run after 19:55 ET."
        return 1
    fi
    if [[ "$(git -C "$root" rev-parse HEAD)" != "$prev_head" ]]; then
        nothing_changed "The checkout moved during the gate (someone pulled or merged into it); not deploying over that."
        return 1
    fi
    # Called as a condition, where `set -e` is off, so the merge checks itself;
    # from here on a failure is rolled back by the exit handler.
    phase=moved
    if [[ "$prev_head" != "$target" ]] && ! git -C "$root" merge --ff-only --quiet "$target"; then
        echo "fast-forward to $after failed" >&2
        return 1
    fi
    echo "checkout at $after (was $(short "$prev_head"))"
}

# The image each built service produces, as compose names it.
service_images() {
    local listed svc
    listed="$("${compose[@]}" config --images "${services[@]}" 2>/dev/null | sed 's/:latest$//' || true)"
    for svc in "${services[@]}"; do
        if grep -qx "$project-$svc" <<<"$listed"; then
            echo "$project-$svc"
        else
            echo "WARNING: no image named $project-$svc for $svc; not tagging it" >&2
        fi
    done
}

# Build the touched services from the checkout, then tag each image with the
# commit as well as :latest, remembering the previous :latest for a rollback.
build_and_tag() {
    local -a images=()
    local image
    mapfile -t images < <(service_images | sort -u)
    for image in "${images[@]}"; do
        old_image_ids[$image]="$(docker image inspect --format '{{.Id}}' "$image:latest" 2>/dev/null || true)"
    done
    "${compose[@]}" build "${services[@]}"
    for image in "${images[@]}"; do
        docker tag "$image:latest" "$image:$after"
    done
    if ((${#images[@]})); then
        echo "tagged :$after and :latest: ${images[*]}"
    fi
}

# Undo a deploy that failed after the checkout moved but before the restart:
# the checkout and the :latest tags go back to where they were.
roll_back_unrestarted() {
    local image
    echo "deploy failed before the restart; putting the checkout and :latest back" >&2
    wait_for_desk_jobs || echo "WARNING: rolling the checkout back while a desk job runs" >&2
    git -C "$root" reset --quiet --keep "$prev_head" ||
        echo "ROLLBACK FAILED: reset $root to $(short "$prev_head") by hand" >&2
    for image in "${!old_image_ids[@]}"; do
        if [[ -n "${old_image_ids[$image]}" ]]; then
            docker tag "${old_image_ids[$image]}" "$image:latest" ||
                echo "ROLLBACK FAILED: retag $image:latest to ${old_image_ids[$image]}" >&2
        fi
    done
    nothing_changed "Rolled back."
}

# On any exit: drop the gate tree, roll back a half-done deploy, and name the
# line a failure stopped at. Deploys #6-#8 (2026-08-27/28) ended at the
# post-deploy step with nothing in the log; whatever the cause, the next one
# says where it stopped and with what status.
on_exit() {
    local status="$1" line="$2" command="$3"
    drop_gate_tree || true
    if [[ $status -ne 0 && "$phase" == moved ]]; then
        roll_back_unrestarted || true
    fi
    if [[ $status -ne 0 ]]; then
        echo "deploy.sh: exiting with status $status at line $line ($command)" >&2
    fi
}

# The deploy itself, from arguments to the detached post-deploy checks.
main() {
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    pull=true
    gate=true
    post=true
    force_post=false
    dry_run=false
    restore=false
    # The live checks verify a system that is already serving, so the deploy no
    # longer blocks on them (2026-09-06): forty minutes of every deploy was spent
    # waiting on checks that could change nothing about what was running, and on
    # three deploys that day the wait ended in a timeout with every individual
    # check green. They run detached and page on red; --wait-post restores the
    # old behaviour for a deploy someone wants to watch to the end.
    wait_post=false
    local arg
    for arg in "$@"; do
        case "$arg" in
            --no-pull)   pull=false ;;
            --skip-gate) gate=false ;;
            --skip-post) post=false ;;
            --wait-post) wait_post=true ;;
            --run-post)  force_post=true ;;
            --dry-run)   dry_run=true ;;
            --restore)   restore=true ;;
            --deploy-dir=*) root="$(cd "${arg#--deploy-dir=}" && pwd)" ;;
        esac
    done
    # One compose project whichever directory a command runs from: the gate
    # tree's directory name would otherwise name a second project, whose db
    # and redis collide with the live ones' fixed container names.
    project="${COMPOSE_PROJECT_NAME:-$(basename "$root" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')}"
    export COMPOSE_PROJECT_NAME="$project"
    compose=(docker compose -f "$root/docker-compose.yml")
    # What is actually running, not what the checkout happens to be at: the
    # checkout used to be pulled by hand between deploys (a docs commit, a
    # hotfix), and diffing against the pre-pull HEAD then found "no code
    # changes", rebuilt nothing, and ran the post-deploy checks against the old
    # images (2026-08-27, deploy #6). The last successful deploy writes its
    # commit here; with no marker the fallback is the checkout's HEAD. data/ is
    # a symlink to the shared checkout's (~/anios/data on spark1), so the
    # marker, the post-deploy verdict and the lock survive a fresh clone.
    deployed_marker="$root/data/.deployed-commit"

    take_lock
    if in_nightly_window; then
        nothing_changed "Refusing to start: $(et_hhmm) ET is inside the nightly's window (19:20-19:55 ET)."
        exit 1
    fi

    step "Current state"
    prev_head="$(git -C "$root" rev-parse HEAD)"
    before="$(cat "$deployed_marker" 2>/dev/null || git -C "$root" rev-parse --short HEAD)"
    echo "running $before; checkout at $(git -C "$root" rev-parse --short HEAD) on $(git -C "$root" rev-parse --abbrev-ref HEAD)"
    self_check
    if $restore; then
        restore_checkout
        return 0
    fi
    if tracked_changes; then
        if $gate; then
            # The gate runs on a commit in its own worktree; it cannot see
            # edits sitting in this checkout, so it cannot vouch for them.
            nothing_changed "The checkout has uncommitted edits to tracked files, which the gate cannot see. Commit them, or deploy with --skip-gate."
            exit 1
        fi
        echo "WARNING: working tree has uncommitted changes; the deployed state will"
        echo "         not match any commit."
    fi

    if $pull; then
        step "Fetching (the checkout is not touched until the gate passes)"
    fi
    resolve_target || exit 1
    after="$(git -C "$root" rev-parse --short "$target")"
    if [[ "$before" == "$after" ]]; then
        echo "already running $after"
    fi

    # Whether the change could touch the search chain or the router's tool
    # choice - the only things the credit-consuming post-deploy sweep verifies
    # that a fresh deploy's live searches are worth. The sweep and the search
    # harness spend one provider query per live question, and on 2026-08-29
    # deploy sweeps accounted for 344 of the month's 403 searches against an
    # allowance that is no longer free. A change to the desk or the frontend
    # skips them; --run-post forces them regardless. An empty diff is treated
    # as full, so a re-run of the same commit still verifies everything.
    search_paths='^backend/mcp/|^backend/services/|^backend/tools/|^backend/core/prompts/|^backend/agents/(chat|reply|scout)/|^backend/cli/(sweep_journeys|exercise_search_scenarios|tool_selection_cases|real_utterances|evaluate_tool_selection)\.py|^prompts/(routing|reply|search|scout|referent|refinement)/|^skills/|^bridges/'
    search_touched=false
    changed="$(git -C "$root" diff --name-only "$before" "$after" 2>/dev/null || true)"
    if $force_post || [[ -z "$changed" ]] || grep -qE "$search_paths" <<<"$changed"; then
        search_touched=true
    fi

    # Rebuild only what the change actually touched. A full rebuild of every image
    # takes minutes and is almost never what a deploy needs. Decided here, built
    # only after the gate passes and the checkout has moved.
    step "Deciding what to rebuild"
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
        echo "will rebuild after the gate: ${services[*]}"
    fi
    # The short path: a known diff that touches nothing the backend runs.
    # Anything under these paths is backend code, its dependencies, the
    # schema, the compose file, the scripts the gate reads, or a file a
    # backend test holds to the checkout; everything else (frontend/, docs/)
    # cannot change what the gates measure.
    backend_paths='^(backend/|requirements|pyproject|Dockerfile|migrations/|docker-compose|scripts/|prompts/|skills/|bridges/|deploy/|\.env\.example)'
    frontend_only=false
    if [[ -n "$changed" ]] && ! grep -qE "$backend_paths" <<<"$changed"; then
        frontend_only=true
        echo "no backend change in $before..$after: taking the short path (no gate, no backup, no migration)"
    fi

    step "Gating"
    # Before anything is touched, on purpose: the gate runs on $after in its
    # own worktree, so a failing gate at this point has changed nothing - the
    # checkout, the images and the containers are all as they were.
    # --skip-gate exists because a model gate can flake and the public URL has
    # real users; a hotfix that cannot ship is a worse outage than the
    # regression this guards against.
    if $frontend_only; then
        echo "frontend-only change; the gates measure nothing it can affect"
    elif $gate; then
        make_gate_tree
        run_gates || exit 1
        drop_gate_tree
    else
        echo "WARNING: unit suite and routing gate skipped by request"
    fi

    if $dry_run; then
        step "Dry run"
        echo "gate stage passed for $after; a real deploy would now:"
        echo "  wait for market_balancer/market_daily, then move $root $(short "$prev_head") -> $after"
        echo "  build and tag :$after + :latest: ${services[*]:-nothing}"
        if ! $frontend_only; then echo "  back up and migrate"; fi
        echo "  restart, verify, and record $after in $deployed_marker"
        echo "dry run: nothing was changed"
        return 0
    fi

    step "Checking out the gated commit"
    checkout_gated || exit 1

    if [[ ${#services[@]} -gt 0 ]]; then
        echo "rebuilding: ${services[*]}"
        step "Building"
        build_and_tag
    fi

    if $frontend_only; then
        step "Backup and migrations"
        echo "frontend-only change; the schema is untouched"
    else
        step "Backing up before touching the schema"
        bash "$root/scripts/backup-db.sh"

        step "Applying migrations"
        "${compose[@]}" up -d --wait db
        if ! "${compose[@]}" run --rm -e POSTGRES_HOST=db \
            -v "$root/migrations:/app/migrations:ro" \
            backend python -m alembic upgrade head; then
            echo "Migration failed." >&2
            exit 1
        fi
    fi

    step "Restarting"
    phase=restarted
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
    local ok=false code=000 attempt
    for attempt in $(seq 1 30); do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8080/api/v1/memory/probe || echo 000)"
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
    # rolled back - the previous images are still present (tagged with their
    # commit) for a manual `docker compose up -d` of them if the failure
    # warrants it.
    step "Result"
    # Written before the live checks, not after: the system is up, healthy and
    # serving this commit at this point, and that is what the marker records. A
    # red check afterwards is a fault in what is deployed, not a claim that
    # something else is.
    mkdir -p "$(dirname "$deployed_marker")"
    printf '%s\n' "$after" >"$deployed_marker"
    echo "deployed $after"

    # A cron pull alone must not activate new paper-order execution code.
    if $gate && ! $frontend_only; then
        "${compose[@]}" exec -T backend python -m backend.cli.market_event_recovery --activate
    fi

    step "Post-deploy checks"
    # The detached checks get `9>&-` so they do not inherit the deploy lock
    # and hold it for the forty minutes they can run.
    if ! $post; then
        echo "WARNING: post-deploy checks skipped by request"
    elif ! $search_touched; then
        # The change did not touch the search chain or the router's tool choice,
        # so the credit-consuming sweep and search harness are not worth their
        # live searches (2026-08-29: 344 of the month's 403 searches came from
        # deploy sweeps, against an allowance that is no longer free). The cheap
        # smoke still runs; --run-post forces the full set.
        checks_log="$root/data/post-deploy-$after-$(date +%Y%m%dT%H%M%S).log"
        mkdir -p "$(dirname "$checks_log")"
        setsid nohup bash "$root/scripts/post-deploy-checks.sh" --cheap "$after" >"$checks_log" 2>&1 </dev/null 9>&- &
        echo "cheap checks running in the background: $checks_log"
        echo "verdict: data/.post-deploy-status (a red one pages the operator)"
    elif $wait_post; then
        bash "$root/scripts/post-deploy-checks.sh" "$after" \
            || { echo "deployed, but a post-deploy check failed" >&2; exit 1; }
    else
        checks_log="$root/data/post-deploy-$after-$(date +%Y%m%dT%H%M%S).log"
        mkdir -p "$(dirname "$checks_log")"
        # Detached from this shell and its process group, so the checks outlive
        # the ssh session a deploy is usually run over.
        setsid nohup bash "$root/scripts/post-deploy-checks.sh" "$after" >"$checks_log" 2>&1 </dev/null 9>&- &
        echo "live checks running in the background: $checks_log"
        echo "verdict: data/.post-deploy-status (a red one pages the operator)"
    fi
}

trap 'on_exit "$?" "${BASH_LINENO[0]:-?}" "$BASH_COMMAND"' EXIT
trap 'echo "deploy.sh: received SIGHUP, continuing" >&2' HUP

main "$@"
