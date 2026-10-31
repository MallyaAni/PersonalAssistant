# Pre-release earnings de-risking on the honest universe: the result — 2026-10-31

**Status: FAILED the pre-registered gate. The overlay is not adopted.** This is
the result of `earnings-derisk-preregistration-2026-10-31.md`, run after the
note was committed (`983c77d4`). The overlay is not added to the rule, the
board, or any prompt, and is not retried without a new pre-registration.
Nothing live changed. The earnings-calendar block already on the desk is
descriptive and stays descriptive.

## The question and the gate

Does trimming a held name to half its target, and blocking a new entry, in the
five reviewed sessions before its predicted earnings release — with a 20-session
overdue tail — reduce the book's worst drawdown enough to justify the return it
gives up? The pre-registered gate, on S&P 500 point-in-time at 25 bp over the
choosing window 2016-2023, is a conjunction:

1. worst drawdown at least **2.0 percentage points shallower** than the
   installed rule's (−33.3296%, so no deeper than −31.3296%);
2. CAGR no worse than **1.0 point below** the installed rule's (10.6747%, so at
   least 9.6747%);
3. Sharpe no worse than **0.02 below** the installed rule's (0.6736, so at
   least 0.6536);
4. the drawdown improvement above the **95th percentile of 200 random-removal
   placebos**;
5. the perturbation check passes;
6. the off, trim1, no-flag and flag-0 nulls pass.

## The result

Run on the frozen `~/dsv41/pit2/cache.npz` with only the new overlay fields
changed. The baseline reproduces the risk dial's 0.25/25 line to 1e-9: choosing
10.6747% / −33.3296% / 0.6736; reported 26.2893% / −19.1375% / 1.6743; all
14.2725% / −33.3296% / 0.8842.

S&P 500 point in time, **25 bp** (the gating row):

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all DD | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| installed | 10.6747% | −33.3296% | 0.6736 | 26.2893% | −19.1375% | 1.6743 | 14.2725% | −33.3296% | 0.8842 |
| Trim5-50 (primary) | 9.6885% | −33.8375% | 0.6266 | 24.2027% | −18.8028% | 1.5913 | 13.0508% | −33.8375% | 0.8281 |
| Trim3-50 | 9.9505% | −34.3511% | 0.6382 | 25.1634% | −18.9592% | 1.6289 | 13.4639% | −34.3511% | 0.8460 |
| Trim10-50 | 9.0967% | −36.3094% | 0.5919 | 23.7843% | −19.2896% | 1.5723 | 12.4941% | −36.3094% | 0.7945 |
| Trim5-75 | 10.3459% | −35.2915% | 0.6496 | 25.9458% | −18.9271% | 1.6396 | 13.9462% | −35.2915% | 0.8576 |
| Trim5-25 | 8.3289% | −31.1695% | 0.5846 | 20.5468% | −17.4897% | 1.5110 | 11.1597% | −31.1695% | 0.7731 |
| Blackout-only | 10.7290% | −34.6352% | 0.6681 | 26.1415% | −17.9144% | 1.6968 | 14.2840% | −34.6352% | 0.8776 |
| Trim-only | 9.7078% | −35.1543% | 0.6246 | 24.5023% | −18.8063% | 1.6090 | 13.1294% | −35.1543% | 0.8287 |
| IT+Comm-only | 10.4672% | −35.1759% | 0.6540 | 25.0701% | −18.7533% | 1.6340 | 13.8479% | −35.1759% | 0.8538 |
| No-tail | 9.6652% | −34.2638% | 0.6225 | 24.4402% | −18.8650% | 1.5947 | 13.0798% | −34.2638% | 0.8253 |

S&P 500 point in time, **10 bp** (reported, not gated): installed 11.5355% /
−34.6861% / 0.7083; Trim5-50 10.6452% / −35.0576% / 0.6727. Reported window
25.4809% / −19.6572% / 1.6107 versus 25.7187% / −18.2667% / 1.6845; all 14.7657%
/ −34.6861% / 0.8970 versus 14.1372% / −35.0576% / 0.8814.

## The verdict

**Criteria 1, 3 and 4 fail; 2, 5 and 6 pass.**

- The choosing-window drawdown is **0.5079 points deeper** (−33.8375% versus
  −33.3296%), against the +2.0-point requirement.
- The Sharpe is **0.0470 lower** (0.6266 versus 0.6736), against the −0.02
  floor.
- The CAGR delta is **−0.9862 points**, which passes the −1.0-point floor by
  0.0138 points. That is a pass on a technicality, not a result: the arm gives
  up almost all of the return the floor allows and still does not cut drawdown.
- The placebo's 95th percentile is a **+7.2808-point** drawdown improvement;
  the primary's improvement is **−0.5079 points**, so criterion 4 fails by a
  wide margin.

The conjunction fails, so the arm is closed. No sensitivity arm rescues it:

- **Trim5-25** is the only arm that cuts drawdown materially: −31.1695%, a
  **+2.1601-point** gain that would pass criterion 1. It pays **−2.3458 points
  of CAGR** and **−0.0890 of Sharpe**, failing criteria 2 and 3. It is also
  still below the placebo p95.
- **Blackout-only** (−34.6352%), **IT+Comm-only** (−35.1759%) and **No-tail**
  (−34.2638%) are all deeper than the installed book. Restricting the flag to
  the owner's sector pair does not help; the sector concentration is not where
  the drawdown comes from.
- **Trim3-50**, **Trim10-50**, **Trim5-75** and **Trim-only** are all deeper
  than the installed book. Widening the window makes it worse (Trim10-50 is
  2.98 points deeper), which is the opposite of a pre-release effect.

The reported window is not a rescue either. Trim5-50's reported drawdown is
0.3347 points shallower, but its reported CAGR is 2.0866 points lower and its
reported Sharpe is 0.0830 lower; the full-period drawdown is 0.5079 points
deeper. No window shows a risk-adjusted improvement.

## The overlay's bite

`bite` against the installed book over all 2,970 sessions:

- The overlay removes weight in **2,331 sessions (78.48%)**.
- Mean removed weight is **3.6982%** of equity when active and **2.7368%** over
  all sessions; the maximum is **20.0116%**.
- **98,069** member name-sessions are flagged: **74,455** in the pre-window and
  **23,614** in the overdue tail (24.1% of flagged member name-sessions).
- **18,761** flagged name-sessions are held names that the trim halves;
  **79,308** are unheld names that the blackout blocks from entry.

This is not a marginal overlay. It is active in more than three quarters of
sessions and removes up to a fifth of equity, and it still leaves the worst
drawdown slightly deeper than the installed book. The flags are frequent, but
they do not mark the sessions where the book's drawdown is set.

## The placebo

Two hundred random-removal draws, seeds 20261101..20261300. Each draw removes
the primary arm's per-session removed weight from a random subset of eligible
unprotected names with positive target, using the same engine and cash
treatment; only the choice of names differs. All 200 draws are finite.

- Mean drawdown improvement: **+4.9275 points**.
- 95th percentile: **+7.2808 points**.
- Maximum: **+7.7583 points**.

Random removal of the same weight buys far more drawdown reduction than the
earnings flags do. The flags therefore carry no drawdown information on this
universe; if anything, the names they select are worse for drawdown than a
random draw. The primary's −0.5079-point result is below the placebo mean, not
just below its 95th percentile.

## The null and perturbation checks

- **Off null.** `Rule(earnings_trim=None, earnings_blackout=False)` reproduces
  the installed book exactly: equity, weights and trades byte-identical, and
  the baseline matches the risk dial's 0.25/25 line to 1e-9.
- **Trim1 null.** `Rule(earnings_trim=1.0, earnings_blackout=False)` is
  byte-identical to the installed book.
- **No-flag null.** The primary settings with an all-False flag matrix are
  byte-identical to the installed book.
- **Flag-0 null.** On the synthetic panel, a flagged unheld name has target 0,
  a flagged held name has target exactly 0.5× its ordinary target, a protected
  flagged name is unchanged and an unflagged name is unchanged.
- **No future data.** Changing every close after the 60% session (2022-01-31)
  leaves the book and its early trades identical
  (`future_identical: true`). The unit test
  `test_earnings_overlay_reads_only_past_closes` asserts the same on a
  synthetic panel where the overlay binds.
- **Unit tests.** 28 tests pass in `backend/tests/test_policy_book.py`,
  including the overlay trims/blocks, the protected holding, the off/one
  byte-identical checks, the placebo's equal removed weight and fixed seed, the
  configuration errors and the perturbation check.

## Disclosures

- **Seed-range typo in the pre-registration.** Line 128 says "Seeds
  20261101..20261200", which is 100 values, while the same arm is registered as
  **200 draws** and the gate's criterion 4 is defined over the 200 placebos'
  95th percentile. The runner used `range(20261101, 20261101 + 200)`, i.e.
  20261101..20261300, which is 200 draws and matches the registered draw count
  and the registered percentile definition. The endpoint in the note is a
  typo; the draw count and procedure are as registered. This is disclosed
  rather than amended because results existed after the run.
- **Placebo candidate set.** The registered wording says the random subset is
  drawn "rather than from the flagged names". The implementation draws from
  every eligible unprotected name with positive ordinary target, so a flagged
  name can also be picked. This makes the placebo slightly more similar to the
  primary, not less; the primary still loses to the placebo mean and to the
  economic floors. The unit test asserts the removed weight matches and the
  seed is fixed, not the candidate-set exclusion.
- **Predictor accuracy.** 39,422 walk-forward predictions, median absolute
  error 3 days, 78.3% within 5 days; same-quarter 39,311 predictions, median
  3 days, 78.5% within 5; interval fallback 111 predictions, median 20 days,
  18.0% within 5. The predicted date is an estimate, not an announced date.
- **Flag frequency.** 87.0% of choosing-window sessions have at least one
  flagged graded member; the mean is 11.4 flagged graded names per session.
  The run's member-only count is 98,069 flagged name-sessions across all
  sessions, 24.1% of them in the overdue tail.
- **Survivorship and frozen cache.** The events store carries 529 of the
  cache's 532 names; the price history is survivor-biased. The cache is frozen
  at 2026-10-24, so grades, band, tilt and membership are the desk as it stood
  then. Only the overlay changes across arms, so the comparison is clean, but
  the absolute levels are not a fresh backtest of today's desk.
- **The overlay is not in the live sizing path.** `policy_book` is the
  account simulator; the live nightly plan sizes through
  `grade_led_leader_policy.size_report`. The new `Rule` fields default off and
  are not deployed.

## What this means

The owner's concern was that a bad earnings release can hit a whole sector, and
that the book should de-risk before it. The calendar now knows when a release
is expected, and the predictor is accurate enough to place a five-session
window. But the study says that acting on that window does not reduce the
book's worst drawdown: the overlay is active in 78% of sessions, removes up to
20% of equity, and still ends 0.51 points deeper than the installed book, while
giving up 0.99 points of CAGR and 0.047 of Sharpe. Random removal of the same
weight does far better (+4.93 points mean, +7.28 at the 95th percentile), so
the flags are not identifying the drawdown risk.

The economic reading is consistent with the prior event-shock study's bounce
finding: pre-release names tend to drift up into the release, so trimming them
gives up return; the book's worst drawdowns come from broad market moves, not
from the flagged names' releases. A pre-release overlay is the wrong
instrument for the owner's concern on this universe.

The earnings calendar stays live as descriptive alerting: it tells the desk
which names have a predicted release and how confident the prediction is. It
does not trim, block or size anything. The next candidate remains intraday
reaction at the 15-minute balancer, and it needs its own pre-registration and
an intraday-bar study before any run.

## Artifacts

- Pre-registration: `docs/research/earnings-derisk-preregistration-2026-10-31.md`,
  committed `983c77d4` before the first run.
- Runner: `~/dsv41/pit2/earnings_derisk.py` (outside git, research only).
- Payload: `~/dsv41/pit2/earnings_derisk.json`; log
  `~/dsv41/pit2/earnings_derisk.log`.
- Simulator parameters: `backend/market/policy_book.py` (`Rule.earnings_trim`,
  `Rule.earnings_blackout`, `Rule.earnings_random`, `simulate(earnings=...)`,
  `trim_earnings_target`); tests in `backend/tests/test_policy_book.py`.
- Calendar helpers: `backend/market/earnings_calendar.py` (`intervals`,
  `pre_release`); tests in
  `backend/tests/test_market_earnings_calendar.py`.

**Closed.** Not retried with a different window, tail, trim factor, sector
filter, universe or cost without a new pre-registration saying what changed and
why.
