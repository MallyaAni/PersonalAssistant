# Candidate: `grade-led-leader-weight/1` (leader-tilted equal weight at a 0.25 volatility target)

Branch `sizing-candidate-20261021`, created from `main` at `d12064cc`.
Head: `02add811` (two commits: `fb568d06` the policy, `02add811` the expected-failure
marks on the review replays; see "What the tests say"). Nothing here is installed,
pushed or deployed; no file under `data/` was written.

What it is: the sizing arm the scorecard of 2026-10-21 picked
(`docs/research/sizing-timing-validation-2026-10-21.md`, last two sections:
`ew_graded_leader_25`), installed as a policy beside the grade-led rules the
paper account runs today. Contract:
`docs/research/grade-led-leader-weight-contract-2026-10-21.md`. Everything but
the size of each eligible name is the installed `grade-led-learned-sizing/1`.

## Files in this folder

| file | what |
|---|---|
| `0001-Add-the-grade-led-leader-weight-sizing-candidate.patch` | `git format-patch d12064cc..fb568d06`: the policy, the wiring, the tests, the contract |
| `source_identity.md` | the 43-entry `learned_live_holding.source_identity()` table at `fb568d06` (computed in the functional image from the worktree) |
| `config.proposed.json` | the live `config.json` with only `policy` changed and `release_receipt_sha256` to be recomputed |
| `release.proposed.json` | schema `learned-holding-release/1`, the new source table, `approved_at` and `evidence_sha256` for the owner |
| `evidence.proposed.json` | honest fields; `authorization` and `targeted_tests` for the owner, the scorecard numbers labelled as not forward evidence |

The second commit (`02add811`) touches only three test files; `git format-patch
d12064cc..02add811` reproduces both if a reviewer wants the marks as a patch.

## How to install (by hand, under the paper lock)

`backend/cli/market_release_admission.candidate` refuses a bundle that changes
`policy` ("Trading approval cannot change models, costs, policy or evidence"),
so this goes in the way the grade-led policy did on 2026-10-13, not through a
renewal bundle:

1. Merge the branch (or apply the patch) and deploy that revision, so the
   running image carries the 43 sources whose hashes `release.proposed.json`
   lists. Recompute `source_identity()` in the deployed image and compare it to
   `source_identity.md`; if the merge changed any bound file, the table in
   `release.proposed.json` must be regenerated from the deployed revision.
2. Write `evidence.json` from `evidence.proposed.json` with `authorization`,
   `source_revision` and `targeted_tests` filled in; put `sha256(evidence.json)`
   into `release.json` as `evidence_sha256`, set `approved_at`, and put
   `sha256(release.json)` into `config.json` as `release_receipt_sha256`.
3. Install the three files atomically (`market_release_admission.replace_file`
   semantics: write beside, chmod 0600, `os.replace`) while holding
   `paper.transaction(root)`, then run `python -m backend.cli.market_release_admission`
   preflight: it must answer `ADMITTED` with the new table.
4. The first ordinary nightly and the following real session are the
   acceptance; until then `fresh_ordinary_paper_acceptance` stays UNVERIFIED.

Rolling back is the reverse: restore the three archived files; the old release
binds the old 41-source table and so needs the previous deployed revision.

## What changed in code

- `backend/market/grade_led_leader_policy.py` (new): `leader_weights(closes, sized)`,
  the one pure function (equal slots, `point_in_time.TILTS["leader"]` at strength
  0.5, basket realised volatility over 63 sessions scaled to 0.25, cap `growth.CAP`,
  never levered); `size_report(report, names, blocked, current)` applies it to a
  report's trailing window; `GradeLedLeaderFundedPolicy(GradeLedFundedPolicy)`
  overrides `_required_stocks` (grades admit; no per-name risk reading),
  `_size` (the leader weights instead of the optimiser), `_unavailable_holdings`
  (only ungraded holdings are set aside) and the order wording in `plan`.
- `backend/market/joint_funded_policy.py`: the optimiser block of
  `JointFundedPolicy.decide` is now `_size(...)`, the retained-capital scan of
  `RetainedMarketConditionedFundedPolicy.decide` is `_unavailable_holdings(...)`,
  and `sizing_reason` / `target_basis` are class attributes; the existing
  policies run the same statements in the same order (81 existing joint/grade-led
  tests unchanged and passing).
- `backend/market/grade_led_policy.py`: `preserve_grade_holdings(..., basis=None)`.
- `backend/market/learned_live_holding.py`: the module and its contract in
  `source_identity()`, `GradeLedLeaderHoldingPolicy`, `GRADE_LED_POLICIES`, the
  allow-list, the factory and the pre-account publication for either id.
- `backend/market/strategy_model_allocation.py`: `targets_from_model(..., policy)`
  sizes unit capital with `leader.size_report` under the new id (receipt carries
  `leader_sizing`, no `optimizer`); `read` accepts either id.
- `backend/market/strategy_publication.py`: `build` accepts the leader holding
  policy; `_strategy_identity(sources, cost_bps, policy)` names the policy and,
  for the leader, includes `grade_led_leader_policy.py`; `validate` accepts either id.
- Readers that merely identify the policy accept either id: `market_daily`
  (type tuples, grade row fields, `_record_targets`), `live_model_decision`,
  `grade_parity` (basis per policy), `learned_holding_transition`,
  `learned_personal_guidance`, `learned_order_observation`, `personal_history`,
  `backend/api/v1/market.py`.
- Left alone on purpose: `strategy_history_publication.validate_binding` and
  `backend/cli/market_live_model_history.py` (they pin the audited counterfactual
  history, which was produced with the learned sizing); `strategy_model_history`
  (its result is that history); the `"policy"` label in the `unavailable`
  responses of `live_model_decision`, `model_allocation_view` and
  `market_allocation.py` (no configuration in hand there). Under the leader
  policy the historical-publication pages keep serving the grade-led history
  they were produced with, and say so by their own `policy` field.

## What the tests say

New: `backend/tests/test_grade_led_leader_policy.py`, 15 tests: the pure function
(equal slots at strength 0, tilt order and 1.5x/0.5x ratio, scale in (0, 1] at four
volatilities, cap excess to cash, exact window and finite closes, nothing read
outside the trailing window), the funded `decide()` with a held A+ name, a B exit
and an ungraded holding (partition arithmetic, no `optimizer`/`scenario` claim),
sizes equal to the pure function, blocked names that cannot grow, a held name
without a window refusing the night's sizing but not the exit, order wording and
timing, unit-capital targets equal to the funded arithmetic, and configuration
selection through `learned_live_holding.prepare` (which also runs the
pre-account publication and reads it back).

Extended: `test_learned_live_holding.py::test_installed_current_heads_and_funded_nightly`
gains a `leader` case (the real `market_daily.paper_trade` path over the paper HTTP
fixture); `test_reconciliation_release_admission.py` has its two AST pins moved to
this tree (previous values recorded beside them, as on 2026-10-19).

Marked expected failures (strict), four tests: the replays of the
observed-reference review (`test_strategy_publication_admission`,
`test_strategy_initial_publication` x2, `test_strategy_reference_source_review`)
reconstruct the 41-source holding module exactly and cannot once the candidate
binds 43 and extends the selector. No review type was added, because the
admission CLI cannot use one for a policy change.

Runs (functional image, worktree mounted, no database or redis):

| run | result |
|---|---|
| `backend/tests` minus `functional/`, `test_historical_*.py` and the three frozen-30 binding tests (the gate's own ignore list), before the four marks | 11269 passed, 250 failed, 111 skipped, 7 xfailed, 12 errors in 11m56s; every failure and error is a database, redis, auth or network connection the plain `docker run` does not have (`Connect call failed ... 5432`, 401s), plus the four review replays above and one `test_market_desk_api` holdings test that needs the database |
| the whole `backend/tests` tree, nothing ignored, after the marks | 11642 passed, 657 failed, 1071 skipped, 10 xfailed, 47 errors in 13m16s; the extra failures over the gate-shaped run are `functional/` (needs the model runtime), `test_historical_*` (needs the private fixture tree) and the three frozen-30 binding tests the gate leaves out; no market, strategy, paper or learned-holding module fails outside those and the database-backed `test_market_desk_api` holdings test |
| the 26 market/strategy/paper/learned modules this change touches or binds (`test_grade_led_leader_policy`, `test_learned_live_holding`, `test_grade_led_policy`, `test_joint_funded_policy`, `test_learned_holding_transition`, `test_strategy_publication*`, `test_strategy_initial_publication`, `test_strategy_reference_source_review`, `test_market_release_admission`, `test_reconciliation_release_admission`, `test_settlement_release_admission`, `test_live_model_decision*`, `test_grade_led_parity`, `test_grade_parity`, `test_learned_personal_guidance`, `test_personal_guidance_api`, `test_learned_order_observation`, `test_personal_history`, `test_strategy_model_extension`, `test_strategy_model_history`, `test_verify_joint_funded`, `test_strategy_position_view`) | 463 passed, 4 xfailed (the review replays), 15 subtests passed in 53s |
| `test_grade_led_leader_policy.py` | 15 passed |
| `ruff check` on the new module and test | clean; the touched lines in the other files add no new warnings beyond the files' pre-existing style (`strategy_publication.py` is written in a compressed style with many pre-existing E501) |

## What it does not claim

The scorecard numbers are point-in-time, not forward evidence; three settings of
one parameter are not a fit but are not a forward test either. The 25% per-name
cap was not part of the scorecard arm (it ran uncapped) and is the installed hold
limit, not a new parameter. No model was fitted or retrained, no history was
rerun, and no performance claim follows from installing this.
