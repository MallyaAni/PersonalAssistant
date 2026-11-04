Status: resolved 2026-11-04 by the report-bound leader live path release
(`a3299064`). No live change was made while diagnosing it. The `/3` forward
record starts with the first ordinary nightly after the repair deploy; it had
zero completed sessions before the repair.

# Forward-record blocker: the learned monthly generation expired on 2026-11-01

## Summary

The first ordinary nightlies under `/2` (2026-11-02) and `/3` (2026-11-03)
both refused to trade with
`ValueError: Current causal timing publication required`. The installed
learned-holding stack is a single October 2026 generation: the holding model,
the execution-timing publication and the residual month all have
`fit_date = 2026-10-01`, and all three admission checks require the observed
or decision session to fall in the fit month. The first November session is
2026-11-02, so every one of them is expired. The nightly stops at the first
check (timing); the holding-model check at `forward_arithmetic.py:243` would
fail next with `ValueError: Current causal model publication required`.

The `/3` install on 2026-11-03 reused the October generation unchanged. Its
evidence records `model_publications_unchanged: true`, `no_new_fits: true`
and `fresh_ordinary_paper_acceptance: "UNVERIFIED; required after
installation"`. That acceptance was not run before the month boundary.

No monthly producer exists on this host, and the frozen inputs the October
generation was fitted from are no longer on disk. The forward record cannot
start under `/3` as installed.

## Exact failure

`~/desk_daily.log`:

```text
paper book: not traded (ValueError: Current causal timing publication required)
```

Both nights, with the same health verdict:

```json
{"session": "2026-11-02", "status": "failed",
 "reasons": ["today's book was not written (last session 2026-10-30)",
             "nightly log: paper book: not traded (ValueError: Current causal timing publication required)",
             "strategy publication is for 2026-10-30, not today"]}
```

```json
{"session": "2026-11-03", "status": "failed",
 "reasons": ["today's book was not written (last session 2026-10-30)",
             "nightly log: paper book: not traded (ValueError: Current causal timing publication required)",
             "strategy publication is for 2026-10-30, not today"]}
```

The path is:

```text
backend/cli/market_daily.py:840        learned_live_holding.prepare(root, report)
backend/market/learned_live_holding.py:404  timing_bytes = _timing(root, config, original, started)
backend/market/learned_live_holding.py:259  forward_execution.load_publication(..., observed_at=now)
backend/market/forward_execution.py:309     raise ValueError("Current causal timing publication required")
```

`forward_execution._admit` rejects the October publication on either of two
month equalities (`forward_execution.py:305-309`):

```python
or np.datetime64(published.date(), "M") != day.astype("datetime64[M]")
or np.datetime64(observed.date(), "M") != day.astype("datetime64[M]")
```

The residual month has the same rule in
`forward_probability_timing._validate_residual_month` (lines 50-83).

The holding model is the second failure. `prepare` reaches
`forward.observe_close`, which calls `forward_arithmetic.load_publication`
with `decision_session=str(panel.dates[-1])`
(`forward_arithmetic.py:347-352`). `_admit` requires
`decision_date.astype("datetime64[M]") == fit_date.astype("datetime64[M]")`
(`forward_arithmetic.py:243`). A read-only check on the installed bytes:

```text
>>> forward_arithmetic.load_publication(
...     "data/market/desk/learned-holding/model",
...     receipt_sha256="858163d5...",
...     observed_at="2026-11-03T23:30:00-05:00",
...     decision_session="2026-11-03")
ValueError: Current causal model publication required
```

The risk bank (`holding_risk_bank.load_bank`) has no month equality; it is
not the blocker.

## Installed October generation

| artifact | file | fit date | published | expiry |
|---|---|---|---|---|
| holding model | `desk/learned-holding/model/publication.json` | `2026-10-01` | `2026-10-04T18:35:30-04:00` | October 2026 |
| timing publication | `desk/learned-timing/model/publication.json` | `2026-10-01` | `2026-10-05T11:48:25-04:00` | October 2026 |
| residual month | `desk/learned-timing/residual/residuals.json` | `2026-10-01` | — | October 2026 |

The holding model's input identity is the frozen open-source snapshot cohort
`8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58`; the
timing publication and residual month bind the same cohort. The holding
config is `desk/learned-holding/config.json`, policy
`grade-led-leader-weight/3`, release `4966fd7d...`, timing config
`d03339a3...`.

## Why a November refit is not available locally

- **No producer.** `forward_execution.fit_month` and
  `forward_execution.prepare_residuals` have no checked-in caller outside
  tests. `forward_arithmetic.fit_month` likewise has no CLI. The crontab and
  systemd timers contain no monthly model job; the nightly only reads the
  installed artifacts.
- **No input snapshot.** The holding model's `input_identity` names
  `/prepared.npz`, `/forecasts.npz`, `/held-proof.json`,
  `/saved-held/*`, `/saved-bridge/*` and `/bridge-proof.json` under the
  original snapshot. The documented directory
  `/home/animallya96/scratch/open-source-inputs-20261001` no longer exists,
  and no local `.npz` matches the cohort hash.
- **Even the snapshot would fit October, not November.** The snapshot ends
  2026-09-30. `forward_arithmetic.fit_month` accepts a dataset whose last
  date is the session before the fit month, or which contains the fit month's
  first session. A November fit needs a prepared dataset through at least
  2026-10-30. No local artifact has that data.
- **The timing model needs the same kind of archive.** `fit_month` requires a
  complete saved-distributions dataset ending on the prior session or
  containing the fit month's first session. The residual month needs the
  original authenticated `SavedDistributions` context.

## Impact

- `/3` forward record: zero completed sessions; the 252-session clock has not
  started. The `/2` record also had zero sessions.
- Paper account: last traded session 2026-10-30. At the 2026-11-04T00:30:02Z
  preflight snapshot: equity 83,134.58, cash 42,020.11, 12 held. No orders
  since 2026-10-30.
- Strategy publication and intraday plan are stuck at 2026-10-30.
- Alerting: both failures logged `notify-operator: bridge unreachable`; the
  dead-man's switch also failed to deliver, so no page reached the owner.

## Options

1. **Simplify the live path to match the approved contract (recommended).**
   The `/3` contract already says the policy does not read the learned
   scenario distribution or run the growth optimiser, and routes every leg to
   `next_open`; the learned fifteen-minute timing is not consulted. Make
   `learned_live_holding.prepare` stop requiring the monthly holding model,
   timing publication and residual month for grade-led policies, and keep the
   installed risk bank and report validation. This removes a broken monthly
   dependency the rule does not use, aligns the implementation with the
   contract, and lets the forward record start. It is a live-path code change
   and needs a new release, the full gate and the owner's authorization; it
   does not change sizing, grades, execution or the risk dial.
2. **Rebuild the monthly generation.** Build a new prepared dataset from
   current authenticated data, fit a new holding model, timing publication and
   residual month, and install them with a new release. This changes the
   model identity, needs its own pre-registration and acceptance, and adds
   complexity the direction doc is trying to remove.
3. **Recover the original inputs and refit October.** This would restore the
   October artifact, not a November one. Not a fix.
4. **Leave `/3` installed and accept a stalled record.** Not recommended.

## Recommendation

Option 1. It is the smallest change that makes the installed rule operable,
and it follows the direction doc's simplification rule rather than adding a
new model generation. Do not relax the month checks, fabricate a November
receipt, hand-edit the installed artifacts, or install anything without the
owner's explicit authorization.

## Scope of option 1

The `/3` policy itself does not need the monthly model: `GradeLedLeaderFundedPolicy`
overrides `_size` with `size_report` from the report's trailing closes,
overrides `_required_stocks` without a risk read, and routes every leg to
`next_open`. The parent `decide` uses the reader only for `dates`, `symbols`
and `validate_report`; it does not call `distribution` on the leader path.

The work is in the factory, not the policy:

- `learned_live_holding.prepare` currently loads the risk bank, the timing
  publication/residual, the monthly holding model, and a current close
  observation, then builds `ForwardVolatilityHoldingReader(original, current)`.
  A grade-led path needs a reader that supplies the risk bank's `dates` and
  `symbols`, validates the current report against them, and refuses
  `distribution` rather than fabricating a forecast.
- `strategy_publication.publish_prepared` currently publishes
  `strategy_model_allocation.targets_from_model` from the learned model. The
  simplification must decide whether the grade-led publication keeps a
  report-based model allocation or publishes only the funded plan; it must not
  invent model forecasts.
- The risk bank (`holding_risk_bank.load_bank`) has no month equality and can
  stay. The timing config hash can stay as an installed-config binding.
- Tests must prove: a grade-led config prepares with the monthly artifacts
  absent or expired; the timed policies still require them; the published
  record contains no fabricated model claim; and the `/3` plan is byte-for-byte
  the same on a fixture where the model is present and absent.
- The change alters `learned_live_holding.py` and possibly
  `strategy_publication.py`, both bound sources, so it needs the release
  ceremony, a new evidence file, the full gate and the owner's authorization.

This is a real refactor, not a one-line skip. Option 2 (rebuild the monthly
generation) is the alternative if the owner wants to keep the learned model
in the live path.

## Evidence

- `~/desk_daily.log` lines 32989-32990 (2026-11-02 traceback), 33137
  (2026-11-03 refusal), 33187-33188 (health verdict).
- `data/market/desk/nightly-health.json` and `nightly-freshness.json`.
- `data/market/desk/nightly-readiness.json` (2026-11-04T00:30:02Z account
  snapshot).
- `data/market/desk/asof=2026-10-30/desk.json` (last written book).
- Installed artifact hashes and fit dates as listed above.

## Resolution

Option 1 was implemented and installed through the release ceremony on
2026-11-04.

- Code: commit `a3299064ca68d75180532b3c319e3bce4d10dfa9`, "Bind the leader
  live path to the authenticated nightly report". The leader path now builds
  `backend/market/report_holding.py:ReportHoldingReader` from the
  authenticated nightly report and the installed risk bank; it never loads the
  monthly holding model, execution publication or residual month. `/1`,
  retained and timed policies keep the monthly path unchanged.
- The approved contract is unchanged: `grade-led-leader-weight/3`, same
  parameters, same next-open execution. The policy version stays `/3`.
- Install: `approved_at` 2026-11-04T18:05:42Z; archive
  `20261104T180542-leader-bfe1fa76433c4545a94bd896d774bf20`; evidence
  `eff9ece2f2e3c516c553321e83454c43d5c99726b1226c14d18151ab379a878b`;
  release `c3e44211031f2f4246c09eb8bbf3b5e7c5d7d2f23fe0f1fa4aa95b381618b360`;
  config `9bb15bb968a2c02856a8fad4e775a2218453fc3323d5d44e729e06d5fd4a06e2`;
  admission ADMITTED.
- Verification before install: full unit gate 11,730 passed, 94 skipped, 10
  xfailed, 48 subtests in 907.33s; targeted trading gate 180 passed, 1
  xfailed.
- Deploy: `scripts/deploy.sh` fast-forwarded the deploy checkout the cron
  jobs import (`~/deploy/anios`) to `058b7aed`; admission `ADMITTED` on host
  and container; `.post-deploy-status`
  `2026-11-04T18:32:28Z 058b7aed ok (cheap)`. The trading path is identical
  to the reviewed `a3299064`; the later commits are docs only.
- Candidate record:
  `docs/research/trading-approval-candidates-2026-11-04/report-bound-leader-live-path/`.
- Known degradations: the learned intraday entry display, the saved
  model-decision view and the account-independent model allocation reader
  refuse a report-based record and report unavailable; the nightly trading
  path is unaffected.
- Pre-nightly readiness check (2026-11-04, read-only): the live desk report
  panel is the 94-name book plus SPY (95 tickers); every one is in the
  installed risk bank's 96 symbols (the extra is QQQ). The bank's 2,953 dates
  (2015-01-02 .. 2026-09-30) are an exact prefix of the panel's 2,977 dates
  (2015-01-02 .. 2026-11-03). `ReportHoldingReader`'s symbol and
  calendar-prefix admissions therefore pass on the live report shape. No live
  artifact was changed.
- Remaining acceptance: the first ordinary nightly after deploy (2026-11-04
  19:30 ET) must complete and write a fresh plan, and the following paper
  session must fill. `evidence.json` keeps
  `fresh_ordinary_paper_acceptance: UNVERIFIED` until then.
