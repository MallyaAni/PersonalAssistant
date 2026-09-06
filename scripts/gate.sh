#!/usr/bin/env bash
# Refuse to ship a routing regression.
#
#   bash scripts/gate.sh          # the routing matrix - what deploy.sh calls
#   bash scripts/gate.sh --all    # every functional test, on demand
#   bash scripts/gate.sh <path>   # one file
#
# Why this exists. Four built-in tools - schedule_task, manage_tasks,
# save_skill, manage_skills - shipped with no routing coverage and *could not*
# have had any: TOOL_NAMES did not list them, so the label test rejects a case
# using them, and evaluate_tool_selection scored every one of their decisions as
# "no tool". The first thing that broke was the part nothing measured: asked to
# move a reminder, the assistant said it had, and no write happened. Coverage
# now exists; this is the thing that runs it without someone remembering to.
#
# Two properties matter more than the tests themselves:
#
#   1. A skip is a failure. ANIOS_REQUIRE_FUNCTIONAL=1 (set on the compose
#      service) converts every skip in backend/tests/functional into a failure,
#      because "the Spark was down" and "the prompt still works" otherwise
#      produce the same green, and the moment the models are unreachable is the
#      moment a gate most needs to say no.
#
#   2. It runs against the real router. These are model decisions; a stub would
#      measure the stub.
#
# On the database: the matrix needs none. The tests that do touch Postgres
# follow the convention in backend/tests/test_scheduled_task_repository.py -
# rows tagged with a throwaway user id, removed in the same test. That is
# INSERT and DELETE against tagged rows, never DDL, so anios_db's real data is
# not in the blast radius and no scratch database is created.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/docker-compose.yml" --profile test)

# What a deploy gates on by default, and the reason each one is here.
#
# It was the tool-selection matrix alone, with a note that the whole directory
# had not been timed. It has been now, one suite at a time, and the ones below
# are the ones whose failures reach a person rather than a log:
#
#   tool_selection_matrix  - 51 cases, ~9.5 min. Selection collapsing is the
#                            failure that makes everything else look broken.
#   diagram_generation     - 11 cases, ~2 min. Added 2026-08-30 after a group
#                            chat got "I couldn't create that diagram" twice
#                            from a defect that had been live and unnoticed:
#                            the unit suite passed throughout, because the
#                            model's output was the thing that was wrong.
#   saying_yes             - 19 cases, ~1.5 min. "Yes" to an offer is the
#                            commonest instruction there is, and it had a hole
#                            in it that no structural test could see.
#   burst_readiness        - the judgement that decides whether to answer at
#                            all, including whether a tapback accepts an offer.
#   trajectory_evaluation  - Phase 1 of the execution-boundary repair: whole
#                            turns against the real loop, not just the first
#                            tool. One measured-rate test against the real
#                            router plus the deterministic scoring; ~95s.
#
# Everything else stays out until it earns a place the same way: a real failure
# that reached a person, and a measured cost.
targets=(
    "backend/tests/functional/test_tool_selection_matrix_behaviour.py"
    "backend/tests/functional/test_diagram_generation_behaviour.py"
    "backend/tests/functional/test_saying_yes_behaviour.py"
    "backend/tests/functional/test_burst_readiness_behaviour.py"
    "backend/tests/functional/test_trajectory_evaluation_behaviour.py"
)
unit=false
case "${1:-}" in
    --all)  targets=("backend/tests/functional") ;;
    # The whole unit suite, green or fail. It needs the compose Redis (the
    # login rate limiter and the search budget answer 503 / grant everything
    # without one - 19 tests read as "stale" for two days for exactly that)
    # and every directory a test reads, mounted from the checkout.
    --unit) targets=("backend/tests"); unit=true ;;
    "")     ;;
    # Several files at once, so one command covers everything a change
    # touches. Passing four paths and silently gating on the first was worth
    # a wrong "gate passed" on 2026-08-30.
    *)      targets=("$@") ;;
esac
target="${targets[*]}"

# Deselected by path, visibly rather than by a marker nobody reads:
# test_gateway_follows_the_backend.py shells out to the docker CLI to inspect
# the running gateway and backend containers. That is a different execution
# context from every other file here and it cannot work from inside one of them.
# test_image_text_language_behaviour.py generates a picture on the desktop
# that hosts ComfyUI, which is off at times; a required-functional skip would
# fail every deploy for a machine being asleep. It is run by hand (see the file).
# Container paths: pytest runs inside the image, where the checkout is
# mounted at /app. Host paths here are silently not matched - which is how
# `--unit` once collected the whole real-model suite and ran for an hour.
ignores=(
    --ignore=/app/backend/tests/functional/test_gateway_follows_the_backend.py
    --ignore=/app/backend/tests/functional/test_image_text_language_behaviour.py
)
if $unit; then
    ignores+=(--ignore=/app/backend/tests/functional)
    "${compose[@]}" up -d --wait redis db >/dev/null
fi

echo "==> Gating on $target"
echo "    (a skipped test counts as a failure here)"

# The working tree is mounted over the image's copy for the same reason
# verify-migrations.sh does it: without this the gate measures whatever was
# baked in at the last build, so a case added since would appear to pass while
# never having run.
# docs/ and deploy/ are mounted too: tests that hold the design documents to
# the serving script must see the working tree, not the last image build.
# Every file a test reads is mounted from the checkout, not taken from the
# image: the image is rebuilt rarely, and on 2026-08-26 the internet-env
# guard and the What's-on pack test were failing against an image from
# 2026-08-24 that predated both files.
# --build so the gate runs the image this commit describes. functional-tests
# is behind the `test` profile and is not in deploy.sh's rebuild list, so
# without it the gate runs whatever image was last built: on 2026-09-06 the
# unit suite failed because ruff, added to the test stage in that same commit,
# was missing from the stale image, and because scripts/ was the copy baked
# into it rather than the checkout.
if "${compose[@]}" run --rm --no-deps --build \
    -v "$root/backend:/app/backend:ro" \
    -v "$root/scripts:/app/scripts:ro" \
    -v "$root/prompts:/app/prompts:ro" \
    -v "$root/docs:/app/docs:ro" \
    -v "$root/deploy:/app/deploy:ro" \
    -v "$root/skills:/app/skills:ro" \
    -v "$root/bridges:/app/bridges:ro" \
    -v "$root/.env.example:/app/.env.example:ro" \
    -e REDIS_URL=redis://redis:6379/0 \
    functional-tests \
    python -m pytest "${targets[@]}" "${ignores[@]}" \
        -q -p no:cacheprovider --no-header; then
    echo "==> Gate passed"
    exit 0
fi

echo "==> Gate FAILED" >&2
exit 1
