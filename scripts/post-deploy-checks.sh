#!/usr/bin/env bash
# The live checks that run against an already-deployed system.
#
#   bash scripts/post-deploy-checks.sh <commit>
#
# Split out of deploy.sh on 2026-09-06 so the deploy does not wait on them.
# They verify a system that is *already serving*: deploy.sh restarts the
# containers, health-checks the gateway, writes the deployed marker, and only
# then starts this. Blocking on it added forty minutes to every deploy during
# which nothing about the running system changed - and on three deploys that
# day the wait ended in a timeout while every individual check had printed
# PASS, because the model's six concurrent slots were busy.
#
# What they are:
#   sweep_journeys           every capability walked end to end over HTTP as a
#                            guest, asserting on the reply, the database and
#                            the turn's trace
#   exercise_search_scenarios the search chain, its budget and its meter, as
#                            the operator
#
# Red pages the operator, exactly as before. The verdict is also written to
# data/.post-deploy-status so the next session can read what happened without
# parsing a log.
set -euo pipefail
trap 'status=$?; if [[ $status -ne 0 ]]; then echo "post-deploy-checks.sh: exiting with status $status at line ${BASH_LINENO[0]:-?} (${BASH_COMMAND})" >&2; fi' EXIT

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/docker-compose.yml")
after="${1:-unknown}"
status_file="$root/data/.post-deploy-status"

post_ok=true
summary=()
for check in backend.cli.sweep_journeys backend.cli.exercise_search_scenarios; do
    # Bounded: a journey that waits on a machine that is off keeps its
    # stream alive with heartbeats, and deploy #6's sweep never returned
    # (2026-08-27). Forty minutes is twice a full sweep.
    # Not `output="$(...)"` on its own: under `set -e` a red check makes
    # that assignment exit the script before it prints or pages - deploys
    # #6 and #7 ended silently at this line (2026-08-27).
    status=0
    output="$(timeout 2400 "${compose[@]}" exec -T backend python -m "$check" 2>&1)" || status=$?
    if [[ $status -eq 124 ]]; then
        output+=$'\n'"GAP  ${check##*.}: no result within 40 minutes"
    fi
    printf '%s\n' "$output"
    short="${check##*.}"
    # A journey that failed once and passes when re-run alone is a wobble
    # in a model judgement, not a regression: recorded here as flaky, and
    # the operator is not paged for it. Seven deploys in a day each paged
    # for one such journey (2026-08-28). A journey that fails twice pages.
    # The harness is judged by a model too, and it has no --only, so a
    # single flaky scenario re-runs the whole set once. That is cheap now
    # that repeated questions are served from the answer cache, and it
    # stops one wobble paging the operator at midnight (deploy #24: the
    # events format check wanted a map link and one reply left it out,
    # while the pinned suite for that format passed).
    if [[ $status -ne 0 && $check == backend.cli.exercise_search_scenarios ]]; then
        echo "retrying the search harness once"
        if timeout 1200 "${compose[@]}" exec -T backend python -m "$check" </dev/null 2>&1 | tail -8; then
            echo "$check: passed on retry (flaky)"
            summary+=("$short OK after retry (flaky)")
            continue
        fi
    fi
    if [[ $status -ne 0 && $check == backend.cli.sweep_journeys ]]; then
        names="$(grep -o "gaps=\[.*\]" <<<"$output" | tail -1 | python3 -c "import sys,ast; raw=sys.stdin.read().strip(); print('\n'.join(ast.literal_eval(raw.split('=',1)[1])) if raw else '')" 2>/dev/null || true)"
        if [[ -n "$names" ]]; then
            still=()
            flaky=()
            # `</dev/null` is load-bearing: `docker compose exec -T` reads
            # stdin, and inside `while read <<<"$names"` it swallowed the
            # remaining names. Deploy #25 gapped two journeys, retried
            # only the first, and reported the sweep green - a retry that
            # hid a red, which is worse than no retry at all.
            retried=0
            while IFS= read -r name; do
                [[ -z "$name" ]] && continue
                retried=$((retried + 1))
                echo "retrying journey once: $name"
                if timeout 900 "${compose[@]}" exec -T backend python -m backend.cli.sweep_journeys --only "$name" </dev/null 2>&1 | tail -3; then
                    flaky+=("$name")
                else
                    still+=("$name")
                fi
            done <<<"$names"
            # Every gap must have been re-checked before this counts as a
            # pass: a name the loop never reached is not a name that passed.
            wanted=$(grep -c . <<<"$names")
            if [[ ${#still[@]} -eq 0 && $retried -eq $wanted && $retried -gt 0 ]]; then
                echo "$check: passed on retry ($retried re-checked; flaky: $(IFS='; '; echo "${flaky[*]}"))"
                status=0
                summary+=("$short OK after retry (flaky: $(IFS='; '; echo "${flaky[*]}"))")
                continue
            fi
            if [[ $retried -ne $wanted ]]; then
                echo "retry re-checked $retried of $wanted gaps; treating as failed" >&2
            fi
        fi
    fi
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

# The verdict where a person or a later session can read it in one line,
# rather than by grepping a log whose name they have to find first.
mkdir -p "$(dirname "$status_file")"
printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$after" "$($post_ok && echo ok || echo FAILED)" > "$status_file"
printf 'checks: %s\n' "$(IFS='; '; echo "${summary[*]}")" >> "$status_file"

if ! $post_ok; then
    bash "$root/scripts/notify-operator.sh" "AniOS $after is live and healthy; a post-deploy check is red: $(IFS='; '; echo "${summary[*]}")" || true
    echo "post-deploy checks: FAILED - $(IFS='; '; echo "${summary[*]}")" >&2
    exit 1
fi
echo "post-deploy checks: all green - $(IFS='; '; echo "${summary[*]}")"
