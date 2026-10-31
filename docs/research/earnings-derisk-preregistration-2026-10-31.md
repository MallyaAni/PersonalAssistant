# Pre-release earnings de-risking on the installed rule: pre-registration — 2026-10-31

**Status: registered before any portfolio run for this arm.** This note fixes
the question, the overlay, the arms, the gate and the placebo before the first
simulation. It is a research candidate for the 2027 review, not a live change.
Nothing here changes the live rule, the board, an order, or any prompt.

The only measurements taken before registration are (a) the predictor's own
walk-forward accuracy and (b) how often its flags would touch a graded name.
Neither is a portfolio result. No `policy_book.simulate` run with this overlay
has been made, and no arm below has a number yet.

## Why this arm

The owner's concern is that a bad earnings release can move a whole sector, and
that the desk should act before the event rather than after it. The prior
event-shock study answered the after-the-event question: the measured reaction
was a bounce (+1.52% at 20 sessions, +1.81% at 60), A2 found no forward
contagion, and A1 was stopped as underpowered. Selling after the event sells at
the bottom. This arm tests the other side: reduce exposure *before* a predicted
release, when the risk is still ahead.

The store has no announced forward earnings date. The only data-only date is
each company's own 8-K item 2.02 filing history, so the calendar predicts the
next release from the prior same-quarter releases. The predictor is already
shipped as a descriptive desk block (`backend/market/earnings_calendar.py`,
scan `earnings-calendar/1`); this study is the first time it would influence a
target weight.

The prior risk studies bound the expectation. Every price stop was a false
alarm and cost 0.1–1.4 CAGR points; the chase guard failed its honest-universe
gate; the risk dial's exposure sweep was nearly flat; the sector cap never bound
on the honest universe (0 of 2,970 sessions) and failed its gate. A pre-event
trim is a different mechanism — it is calendar-timed, not price-timed — but the
burden is the same: it must buy drawdown it is worth paying for.

## The signal and the overlay

**The signal.** At each close `t`, for each name with at least `MIN_RELEASES`
(5) stored 8-K item 2.02 filings filed on or before `t`, the predictor returns
the next expected release `p(t)` from `backend.market.earnings_calendar.predict`
with its fixed design: `HORIZON_YEARS=3`, `MATCH_DAYS=50`, `QUARTER_DAYS=91`,
same-quarter candidates shifted by whole calendar years, median candidate,
interval fallback. The prediction is constant between two filed releases and
changes only when a release is filed. A filing dated `t` is treated as known at
the close of `t`, matching the 19:30 ET scan.

**The flag.** A name is flagged at close `t` when
`sessions_until(t, p(t)) <= W` and `sessions_until(t, p(t)) >= -TAIL`, where
`sessions_until` is the signed count of reviewed sessions from `t` to `p(t)`
(the live helper, `earnings_calendar.sessions_until`). The window therefore
starts `W` sessions before the predicted date and runs through `TAIL` sessions
past it. The tail exists because an unfiled release is still ahead: a prediction
whose date has passed is early, not finished. After `TAIL` sessions the
prediction is treated as stale and the name is restored.

**The overlay.** At close `t`, after the ordinary leader target and after the
protected-holding adjustment, for every flagged name that is not protected
(`g < 0`):

- if the name is unheld (`shares == 0`) and `earnings_blackout` is true, its
  target is set to 0 — no entry into a predicted release;
- if the name is held and `earnings_trim` is not None, its target is multiplied
  by `earnings_trim` (the primary arm uses 0.5).

A protected holding is never trimmed or blocked. The freed weight stays cash;
the target is not renormalized into other names. The overlay is applied after
the ordinary plan; when the sector cap is also set it is applied after the cap
(the study runs with `sector_cap=None`, so the order is only a unit-test
contract).

The overlay reads only closes, grades, band, holdings, sector labels and
filings on or before `t`. The perturbation test changes every close after a
cutoff and asserts the flagged names and the targets before it are identical;
changing a filing's filed date before the cutoff changes the flags after it.

## Data and point-in-time rules

- **Prices, grades, membership, sector.** `~/dsv41/pit2/cache.npz`, the frozen
  S&P 500 point-in-time cache used by the risk dial, the chase guard, the
  sector-cap study and the event-shock study: 532 tickers and 2,970 sessions
  (2015-01-02..2026-10-23), fields `dates`, `tickers`, `benchmark`, `member`,
  `sector`, `open`, `close`, `adj_close`, `grades`, `band`, `tilt`.
- **Earnings dates.** `edgar_events` frames in the live store, snapshot
  `asof=2026-10-23`, 529 of the 532 cache names. A frame carries every stored
  8-K filing with `filed`, `items`, `form`; only `form == "8-K"` with item
  `2.02` is read. At a backtest close `t` only filings with `filed <= t` are
  read, so the calendar is point-in-time even though the frame is a current
  snapshot.
- **Universes.** The S&P 500 point-in-time membership (`member`) is the gating
  universe. The Information Technology + Communication Services subset is
  reported, not gated; the IT+Comm-only arm restricts the flags to those
  labels.
- **Costs.** 10 and 25 bp. The primary gate is at 25 bp; 10 bp is reported.
- **Windows.** Choosing 2016-01-01 through 2023-12-29 (the cache's first sizable
  session is `START=64`, 2015-04-07); reported 2024-01-02 through 2026-10-23;
  all 2015-04-07 through 2026-10-23. The reported window is never tuned on.
- **Engine.** `policy_book.simulate` with the installed `Rule` and only the new
  research fields set: A entry / B hold, 1% minimum trade, band block, the
  installed FOMC path, 25% name cap, 0.5 exposure floor, 0.25 volatility target,
  next-open fills. The overlay is a new `simulate(..., earnings=...)` input, a
  per-session boolean flag matrix, plus `Rule.earnings_trim` and
  `Rule.earnings_blackout`; the defaults are off and must reproduce the
  installed rule byte-identically.
- **Baseline.** The same run with the overlay off. It must reproduce the risk
  dial's 0.25/25 line exactly: S&P 500 PIT choosing
  10.6747% CAGR / −33.3296% worst drawdown / 0.6736 Sharpe; reported
  26.2893% / −19.1375% / 1.6743; all 14.2725% / −33.3296% / 0.8842. If it does
  not, the study stops.

## The arms

1. **Trim5-50 (primary).** `W=5`, `TAIL=20`, `earnings_trim=0.5`,
   `earnings_blackout=True`, all sectors. The gate applies to this arm only.
2. **Trim3-50 (sensitivity).** `W=3`, otherwise as the primary.
3. **Trim10-50 (sensitivity).** `W=10`, otherwise as the primary.
4. **Trim5-75 and Trim5-25 (sensitivity).** `earnings_trim=0.75` and `0.25`,
   otherwise as the primary.
5. **Blackout-only (sensitivity).** `earnings_trim=None`,
   `earnings_blackout=True`, `W=5`.
6. **Trim-only (sensitivity).** `earnings_trim=0.5`, `earnings_blackout=False`,
   `W=5`.
7. **IT+Comm-only (sensitivity).** The primary overlay, but a name is flagged
   only when its cache `sector` is Information Technology or Communication
   Services. This is the owner's sector-correlation question directly.
8. **No-tail (sensitivity).** `TAIL=0`, otherwise as the primary. It shows how
   much of any effect is the overdue window.
9. **Random-flag placebo (200 draws).** Seeds 20261101..20261200. Each draw
   removes the primary arm's per-session **removed weight** `R(t)` from a
   uniformly random subset of eligible unprotected names with positive target,
   rather than from the flagged names. At each session the draw computes
   `R(t) = sum(target_ordinary) - sum(target_primary)` (the primary overlay's
   removed weight) and scales a random subset's weight `G` by
   `max(0, G - R) / G`; if `G < R`, it removes all of `G` and records the
   session as short. The placebo is on S&P 500 PIT at 25 bp, choosing window.
   It uses the same engine, the same held definition and the same cash
   treatment; only the choice of names differs.
10. **Off null.** `earnings_trim=None`, `earnings_blackout=False` must
    reproduce the installed book exactly.
11. **Trim1 null.** `earnings_trim=1.0`, `earnings_blackout=False` must
    reproduce the installed book exactly: scaling by 1 cannot move a target.
12. **No-flag null.** An all-False flag matrix with the primary settings must
    reproduce the installed book exactly.
13. **Flag-0 null.** With the primary settings, every flagged unprotected
    unheld name has target 0 after the overlay and every flagged unprotected
    held name has target exactly `0.5 ×` its ordinary target (to floating
    tolerance), on a synthetic panel.

## The gate

**Trim5-50 passes if, on S&P 500 PIT at 25 bp, choosing 2016-2023:**

- choosing-window worst drawdown is at least **2.0 percentage points shallower**
  than the installed rule's (−33.3296%, so no deeper than −31.3296%), and
- choosing-window CAGR is no worse than **1.0 percentage point below** the
  installed rule's (10.6747%, so at least 9.6747%), and
- choosing-window Sharpe is no worse than **0.02 below** the installed rule's
  (0.6736, so at least 0.6536), and
- the drawdown improvement (installed drawdown minus Trim5-50 drawdown) exceeds
  the **95th percentile of the 200 random-flag placebos' drawdown improvements**,
  and
- the perturbation check passes, and
- the off null, the trim1 null, the no-flag null and the flag-0 null pass.

The reported window, the 10 bp result, the IT+Comm universe and every
sensitivity arm are reported but do not gate. A pass on the choosing window
with a worse full-period or reported result must be stated in the note; it does
not become a pass by silence. The study also reports the fraction of sessions
where the overlay removes weight, the mean and maximum removed weight, the
number of blacked-out entries and trimmed held names, and the split between the
pre-window and overdue parts of the flag.

## The null tests

Before any arm is read, the implementation must reproduce the incumbent:

- The off null, trim1 null and no-flag null produce equity, weights, trades,
  cash and the final plan byte-identical to the installed rule on the frozen
  cache and on the unit market.
- The flag-0 null: on a synthetic panel, a flagged unheld name is not bought,
  a flagged held name is trimmed by exactly the factor, a protected flagged name
  is unchanged, and an unflagged name is unchanged.
- The perturbation test changes every close after the 60% session and asserts
  the flagged names and the targets before it are identical; a second test
  moves a filing's filed date before the cutoff and asserts the flags after it
  change. Both are unit tests on a synthetic panel.
- The random-flag placebo with a fixed seed removes the primary arm's per-session
  removed weight from a group that is not the flagged group; a unit test asserts
  the removed weights match on a synthetic panel.

A failure stops the study.

## What is already known, disclosed before the run

- **Predictor accuracy, measured before registration on the same store
  snapshot:** 39,422 walk-forward predictions (each release predicted from
  filings strictly before it), median absolute error 3 days, 78.3% within 5
  days; same-quarter method 39,311 predictions, median 3 days, 78.5% within 5;
  interval fallback 111 predictions, median 20 days, 18.0% within 5. This is a
  predictor measurement, not an overlay result.
- **Flag frequency, measured before registration:** on the choosing window,
  87.0% of sessions have at least one flagged graded (grade ≥ 1) member and the
  mean is 11.4 flagged graded names per session (maximum 92 over all sessions).
  22.2% of flagged graded name-sessions are in the overdue tail rather than the
  pre-window. These counts exclude the final open interval after each name's
  last stored release, so the true frequency is slightly higher. The overlay
  is not vacuous on this universe.
- **Survivorship.** The events store carries 529 of the cache's 532 names — the
  names the desk still carries today. The price history is survivor-biased in
  the same way. Absolute levels are flattered; the comparison across arms is
  the point.
- **The cache is frozen at 2026-10-24.** Grades, band, tilt and membership are
  the desk as it stood then. Only the overlay changes across arms, so the
  comparison is clean, but the absolute levels are not a fresh backtest of
  today's desk.
- **The prediction is an estimate.** The store has no announced date; the
  predicted date can be early or late, and the measured 5-day hit rate is about
  78%. The overlay is a probabilistic de-risking, not a confirmed event.
- **Earnings risk may be paid for.** The prior event-shock study found a
  post-shock bounce. Trimming before the event gives up the pre-event drift and
  the bounce for the names that beat, and the gate's CAGR floor is the price.
  A result that cuts drawdown but gives up more than 1 point of CAGR fails.
- **The overlay is not in the live sizing path.** `policy_book` is the
  simulator; the live nightly plan sizes through
  `grade_led_leader_policy.size_report`. A pass here is a candidate for a shared
  helper in both paths, a release ceremony and a 252-session forward shadow, not
  a live change. The calendar block already on the desk is descriptive and
  stays descriptive regardless of this result.

## What passing and failing mean

- **Pass:** a 2027 review candidate. The note records the gate, the reported
  window and the full-period result. No live change; the program's freeze
  stands. A live candidate would need the same helper in `size_report` and
  `policy_book`, the release ceremony, and a 252-session forward shadow.
- **Fail:** written down with its evidence in `docs/research/`; not retried
  without a new pre-registration. The overlay is not added to the rule, the
  board, or any prompt.

## Amendments

None before the first run.
