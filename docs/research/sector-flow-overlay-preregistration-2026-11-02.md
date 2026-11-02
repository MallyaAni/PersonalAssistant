# Pre-registration: sector flow and the QQQ brake on the honest universe

Written 2026-11-02 before the first run. Research only: no live rule, order,
grade, prompt or risk dial changes, and no live file is written.

## Question

Does following sector money flow — refusing new money to the sectors with the
weakest trailing returns, or tilting the book toward the strongest — improve
the installed joint rule on the honest S&P 500 point-in-time universe at
25 bp, and would the predeclared QQQ trend brake have reduced the recent
drawdown? The program objective is median Sharpe at least 1.0, median worst
drawdown no deeper than -35%, and median CAGR above SPY, with paired
significance against the base.

## What the diagnostics already say

- The live book is **80 of 94 names Information Technology**, 9 Industrials,
  2 Utilities, 2 Communication Services, 1 Consumer Discretionary. **All 8
  A/A+ names are IT.** The latest desk target is 46.75% IT and 3.25%
  Industrials, gross 50%. There are no Financials, Health Care, Energy,
  Materials, Real Estate or Consumer Staples names in the live universe. A
  sector overlay on the live book cannot diversify it; the universe is
  AI/software by mandate.
- The predeclared QQQ brake (`backend/agents/trading/desk/trend_brake.py`:
  200-session mean, enter below 0.97, exit above 1.02, hysteresis) was
  risk-off for 9 sessions in 2026 (2026-03-26..2026-04-08) and for **none**
  of the 2026-09-04..2026-10-30 window. QQQ fell 3.86% over that window while
  the live paper account (policy /1) fell 15.83%. The brake would not have
  known.
- Sector momentum on the cache through 2026-10-23: IT was the **top** of the
  11 GICS sectors on 2026-09-04 (+40.66% trailing 126 sessions) and
  2026-09-30 (+47.04%). A flow-following rule would have favored IT, not
  avoided it. The crash was in the leading sector, which is the case a flow
  rule cannot protect against.
- The prior static sector cap (2026-10-31) failed and is closed: the cap
  never binds on the honest universe (IT+Communication Services mean 16.48%,
  max 39.67%). The prior C5 sector sleeve (2026-10-29) failed: it was another
  tech-heavy exposure, correlated 0.67/0.57 with the live book, and momentum
  added +0.015 over the placebo median, below the placebo p95. This study is
  not a retry of either: it is a flow gate and tilt on the installed rule's
  existing A-name book, plus the predeclared QQQ brake, not a static cap or a
  separate sleeve.

## Data

- The broad honest-universe report
  `market_universe_hindsight_research.broad_report(store)` over
  `/home/animallya96/deploy/anios/data/market`, regraded with the installed
  analyst votes (`value` 3, `fundamental` 1, `technical` 1, `sentiment` 1),
  restricted to the dated S&P 500 membership
  `~/dsv41/universe/sp500_membership_history.csv`.
- The base is the installed joint rule `leader_ewma_minA_floor50_pe` (A hold,
  63-session leader tilt 0.5, EWMA-20 volatility target 0.25 with floor 0.5,
  25% cap, P/E-history tilt 0.5). It is re-scored in the same process as the
  overlays so the paired control is apples-to-apples, and its all-window
  25 bp median CAGR is checked against the existing installed-joint payload's
  0.13650402269141293 to 5e-6. If the check fails, the run stops and nothing
  is interpreted.
- 20 offsets, costs 10 and 25 bp, the same `market_pit_scorecard.build`
  sessions, membership mask and controls as the installed-joint scorecard.
- Sector labels: `market_pit_scorecard._sectors()`, the current GICS labels
  used by the prior sector studies, with the theme fallback. A name with no
  label, or a sector with fewer than 3 valid members, is neutral (not gated
  or tilted). Current labels are not point-in-time; this is a limitation
  shared with the prior sector studies.
- QQQ adjusted closes from the store, aligned to the panel calendar, with no
  interior gaps allowed.

## Arms

The base is `leader_ewma_minA_floor50_pe`. Each overlay wraps that factory;
the base's sizing is unchanged except where the overlay says.

1. **Flow gate** (`gate`): at each decision session t, compute each sector's
   mean trailing 126-session return over its member names in the dated
   membership with finite positive adjusted closes at t-126 and t; a sector
   needs at least 3 such names to be ranked. The bottom 3 of the ranked
   sectors are lagging. A name whose target at t is positive but whose
   **actual book target at t-1** was zero (a new entry) and whose sector is
   lagging is removed; the removed weight is redistributed pro rata to the
   remaining positive targets so the base's gross is preserved, then the 25%
   cap is re-applied with pro-rata redistribution. Held names in lagging
   sectors are kept. A blocked name stays "new" until it actually enters, so
   the gate persists while its sector is lagging. If fewer than 6 sectors are
   ranked, the gate does nothing. Parameters fixed: 126 sessions, bottom 3 of
   the ranked sectors, no tuning.
2. **Flow tilt** (`tilt`): at each t, multiply each positive base target by
   `1 + 0.5 * (2 * p - 1)`, where `p` is the sector's percentile rank by the
   same trailing 126-session mean return (0 for the bottom ranked sector, 1
   for the top, linear in between); names in unranked sectors get `p = 0.5`
   and a multiplier of 1.0. Renormalize to the base's gross, then re-apply
   the 25% cap with pro-rata redistribution. Parameters fixed: 126 sessions,
   strength 0.5.
3. **QQQ brake** (`brake`): multiply the base targets by 0.5 on sessions
   where `trend_brake.risk_off_path` is True (200-session mean, enter below
   0.97, exit above 1.02, hysteresis, first 200 sessions risk-on), and by 1.0
   otherwise. No tuning.
4. **Gate plus brake** (`joint`): arm 1 then arm 3. Descriptive; not a
   candidate unless both primary arms pass.

The flow gate and tilt are the two readings of "follow the money": the gate
refuses new money to laggards, the tilt sends money to leaders. The brake is
the QQQ signal the owner asked about.

## Statistics

- Median and worst across the 20 offsets for CAGR, worst drawdown and Sharpe
  for each arm, at both costs, in 2016-2023, 2024-2026 and all sessions.
- Paired daily difference at the median offset (offset 10), arm minus base,
  25 bp: Newey-West t at lag 20, a 95% month-block bootstrap (2,000 draws,
  seed 20261102), and PSR, for each window.
- Per-offset CAGR sign: how many of the 20 offsets the arm is above the base.
- Executed turnover at the median offset, 25 bp, from the simulator's own
  `turnover` metric (notional traded per year over the average account), for
  the base and each arm.
- SPY and QQQ descriptive, from the base payload.

## Gate

Primary, all sessions at 25 bp, medians across the 20 offsets:

1. median Sharpe at least 1.0;
2. median worst drawdown no deeper than -35%;
3. median CAGR above SPY's median CAGR.

Secondary, all three for a PASS:

4. arm minus base paired mean greater than 0, Newey-West t at least 2.0, and
   the bootstrap 95% lower bound greater than 0;
5. arm above the base in at least 15 of 20 offsets;
6. the paired mean is positive in both 2016-2023 and 2024-2026.

Turnover: an arm is a candidate only if its executed turnover is no more
than the base's plus 1.0x/year. This is a candidacy limit, not a return gate;
the base's own turnover is reported against the program's about-2x/year
target.

Verdict per arm: PASS if primary and secondary pass and turnover passes;
PARTIAL if the primary passes and the secondary or turnover fails; FAIL if
the primary fails. The joint is descriptive and is not a candidate unless
both the gate and the brake PASS.

## What passing buys

A candidate overlay for a future policy/release and evidence for the owner's
mandate decision. It does not change the live rule; the 252-session forward
record continues. A passing flow arm would be forward-shadowed before any
live change. A passing brake would be a candidate for the next authorized
release, not an immediate live change.

## What failing means

Sector flow and the QQQ brake do not improve the installed joint rule on the
honest universe. The owner's hypothesis — that the system should have known
from QQQ or from sector flow — is not supported by the predeclared signals.
The recent crash was in the leading sector, so a flow-following rule would
have stayed in it, and the predeclared QQQ brake was off. The live book's
concentration is a universe/mandate issue, not an overlay issue; widening the
live universe is an owner decision, and the prior utilities measurement
(38.45% CAGR, 1.247 Sharpe, -42.05% DD against 34.12%, 1.178, -42.19% over
twenty start phases) is the evidence to weigh. A failure is recorded and not
retried with a different window, strength, sector count or brake threshold
without a new pre-registration saying what changed and why.

## Look-ahead and multiplicity

- The sector mean reads only trailing 126 closes through t; the gate's "new
  entry" reads the previous session's actual book target, not future prices;
  the tilt reads only trailing closes; the brake reads only QQQ closes through
  t. All causal by construction.
- Three primary arms plus one descriptive joint, parameters fixed before the
  run. No search over window, strength, bottom count, sector set or brake
  threshold. The 126-session window and 0.5 strength are the prior sector
  study's registered variants; the brake thresholds are predeclared in
  `trend_brake.py`.
- The deflated-Sharpe hurdle is descriptive, with the trial count from the
  program of record, not used to rescue a failed gate.
- Current GICS labels are not point-in-time; a name's sector could have
  changed historically. The prior sector studies share this limitation; the
  study does not claim historical sector membership.

## Data and reproducibility

- Run script `~/dsv41/universe/sector_flow.py`; payloads
  `sector_flow_gate.json`, `sector_flow_tilt.json`, `sector_flow_brake.json`,
  `sector_flow_joint.json`, and summary `sector_flow_summary.json` under
  `~/dsv41/universe/`.
- The base is re-scored in the same process and checked against
  0.13650402269141293 (all-window 25 bp median CAGR) to 5e-6; if the check
  fails, the run stops and the comparison is not interpreted.
- The run is as of 2026-10-30, the store's last complete session.
