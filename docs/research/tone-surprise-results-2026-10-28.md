# Tone surprise: S-only result — 2026-10-28

**Status: FAILED the pre-registered gate. The secondary arms were not run.**
This is the result of `tone-surprise-preregistration-2026-10-28.md`, run
after the note was committed. The signal is not added to the grade, the
board, or any prompt, and is not retried without a new pre-registration.

## The question and the gate

Does the change in the five release-tone fields from the previous release
predict beta-adjusted residual forward returns on the desk's panel? The
pre-registered gate, on 2016-2023 at 20 sessions, is a conjunction:

1. mean rank IC at least 0.02;
2. Newey-West t at lag 20 at least 2.0;
3. IC above the 95th percentile of 200 placebo shuffles that preserve the
   missing mask.

The 60-session result is reported and does not gate. 2024-2026 is reported
only and was never tuned on.

## The result

Run on the live market store, point-in-time book membership, beta-adjusted
residual returns, `min_names=20`, benchmark excluded. The Newey-West lag is
one period, which is twenty sessions because the ICs are computed every
twenty sessions.

| horizon | window | n | mean IC | t | NW t | hit |
|---|---:|---:|---:|---:|---:|---:|
| 20 | 2016-2023 choosing | 101 | **+0.0352** | 1.71 | **1.79** | 53.5% |
| 20 | 2024-2026 reported | 34 | −0.0311 | −0.95 | −0.98 | 50.0% |
| 60 | 2016-2023 choosing | 34 | −0.0163 | −0.42 | −0.42 | 41.2% |
| 60 | 2024-2026 reported | 11 | −0.1533 | −3.73 | −4.78 | 9.1% |

Placebo, 200 draws on the choosing window: 20 sessions mean −0.0009,
95th percentile **+0.0341**; 60 sessions mean −0.0027, 95th percentile
+0.0499.

Strict-alignment sensitivity (a release first counts the session after its
reaction date), reported beside the registered arm and not a second trial:

| horizon | window | n | mean IC | t | NW t |
|---|---:|---:|---:|---:|---:|
| 20 | 2016-2023 | 101 | +0.0303 | 1.53 | 1.56 |
| 20 | 2024-2026 | 34 | −0.0343 | −1.03 | −1.03 |
| 60 | 2016-2023 | 34 | −0.0046 | −0.12 | −0.12 |
| 60 | 2024-2026 | 11 | −0.1449 | −3.37 | −5.15 |

## The verdict

Criterion 1 passes: +0.0352 is above the 0.02 floor. Criterion 3 passes
barely: +0.0352 is 0.0011 above the placebo's 95th percentile. **Criterion 2
fails: the Newey-West t is 1.79, below the 2.0 gate.** The pre-registration
makes the conjunction the gate, so S-only fails. The 60-session choosing
result is negative, and the reported 2024-2026 window is negative at both
horizons, strongly so at 60 sessions. The strict alignment does not rescue
it. The secondary arms (S-added, S-blend) are not run, as the note requires.

## The null and perturbation checks

- **Zero signal.** A constant score over the same mask produces `n = 0`
  defined ICs and no ranking; it is not silently read as neutral.
- **No future data.** Changing every release after the 60% session leaves
  the signal before it byte-identical (`future_identical: true`); changing
  the newest release on or before it changes the signal
  (`newest_changes: true`, AAOI).
- **Strict alignment.** The implementation differs from the legacy
  alignment only on sessions that are a release's reaction date; the unit
  test asserts this on a synthetic panel.

## Coverage and disclosure

- 3,622 scored releases across panel names at run time. The pre-registration
  quoted 3,451 when the note was written; the nightly tone refresh has added
  releases since. The count is reported, not used.
- 99.2% of eligible point-in-time name-sessions carry a surprise. Once a
  name has a second release it always has a view, so only the early panel is
  thin.
- The release reader is a modern language model reading historical text;
  the text is historical, the reader is not. The tone-validity leak test
  remains the precedent, and the caveat stays attached to every number.
- The store holds bars only for today's names; the book membership is point
  in time but the universe is survivor-biased. The 2024-2026 window is
  reported, not a clean out-of-sample test.
- The guidance-change field is already one of the sentiment analyst's four
  scored legs. The S-only arm is not independent of the incumbent, and
  S-blend would overlap further; neither changes this verdict.

## What this means

The sentiment analyst's *level* score carries a measured edge (rank IC
0.039, t 3.0 at twenty sessions; 0.037 after the leak test). The *change*
in that tone does not carry it: the twenty-session IC is marginal, its
HAC t is below the gate, the sixty-session result is negative, and the
post-2023 window is negative. The release-tone layer keeps the change
fields for the analyst's existing guidance leg; no new use is added.

**Closed.** Not retried without a new pre-registration and a forward
shadow. The result is written beside the pre-registration, as the protocol
requires.
