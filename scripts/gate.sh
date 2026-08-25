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

# The matrix alone by default. 51 cases against a serialized GPU is a cost a
# deploy can carry; the whole directory is not, until someone has timed it.
target="backend/tests/functional/test_tool_selection_matrix_behaviour.py"
case "${1:-}" in
    --all) target="backend/tests/functional" ;;
    "")    ;;
    *)     target="$1" ;;
esac

# Deselected by path, visibly rather than by a marker nobody reads:
# test_gateway_follows_the_backend.py shells out to the docker CLI to inspect
# the running gateway and backend containers. That is a different execution
# context from every other file here and it cannot work from inside one of them.
# test_image_text_language_behaviour.py generates a picture on the desktop
# that hosts ComfyUI, which is off at times; a required-functional skip would
# fail every deploy for a machine being asleep. It is run by hand (see the file).
ignores=(
    --ignore="$root/backend/tests/functional/test_gateway_follows_the_backend.py"
    --ignore="$root/backend/tests/functional/test_image_text_language_behaviour.py"
)

echo "==> Gating on $target"
echo "    (a skipped test counts as a failure here)"

# The working tree is mounted over the image's copy for the same reason
# verify-migrations.sh does it: without this the gate measures whatever was
# baked in at the last build, so a case added since would appear to pass while
# never having run.
# docs/ and deploy/ are mounted too: tests that hold the design documents to
# the serving script must see the working tree, not the last image build.
if "${compose[@]}" run --rm --no-deps \
    -v "$root/backend:/app/backend:ro" \
    -v "$root/prompts:/app/prompts:ro" \
    -v "$root/docs:/app/docs:ro" \
    -v "$root/deploy:/app/deploy:ro" \
    functional-tests \
    python -m pytest "$target" "${ignores[@]}" \
        -q -p no:cacheprovider --no-header; then
    echo "==> Gate passed"
    exit 0
fi

echo "==> Gate FAILED" >&2
exit 1
