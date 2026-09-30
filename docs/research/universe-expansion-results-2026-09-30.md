# A reshaped: grading a larger point-in-time universe. Results (2026-09-30)

**Verdict: RECORD on all three arms. No `/6` proposal.** The mechanism the
registration claimed is real (with 500 names the cap never binds and the
book is a ~60-name equal-weight portfolio), and what it buys is a
shallower drawdown and a tenth of the single-name risk; what it costs is
13 CAGR points on the deciding window and 28 on the recent one, against
the control, on every one of 20 offsets. The registration's prior named
this outcome ("a RECORD that prices diversification rather than a PASS")
as the most likely, and it is what the data say. Cumulative trial count:
457.

Registration: `docs/research/universe-expansion-plan-2026-09-30.md`
(`ce6b07c0`). Code: `research/universe-expansion` at `a4f5e788`. Payloads
and the verdict are committed under `docs/research/scorecards/universe-expansion/`;
`python -m backend.cli.universe_verdict` reproduces every number below
from those files alone.

## What was run

spark1, store `data/market` as of **2026-09-29**, CPU only, niced, one run
after another (`~/scratch/univ/step3/run.sh`), the market open and the
model servers untouched. All lines: `desk.run` with `EXPECTATIONS_GAP`,
`--graded-cap 0.25` (every A/A+ name at equal weight, cap 25%, gross 1.0,
reset every 20 sessions), 20 offsets, 10 and 25 bp, the point-in-time mask.

| run | membership file | names | wall | peak RSS |
|---|---|---|---|---|
| control (book-94) | `membership_history.csv` | 94 | 4:54 | 1.5 GB |
| U-sector | `membership_history_sp500.csv` | 531 (11 sector groups) | 9:24 | 2.8 GB |
| U-flat | `membership_history_sp500.csv` | 531 (one group) | 9:01 | — |
| U-tone | `membership_history_sp500.csv` | 267 with tone (11 groups) | 6:33 | 1.9 GB |
| null test | `membership_history.csv` | 94, both paths | 7:31 | 1.8 GB |

The universe run is 1.9× the book's, inside the registration's 2-3×
estimate (the expectations gap already built the 531-name panel).

**Order of work, as registered.** The 437 missing `edgar_facts_versions`
were fetched first (531 of 531 stock members now have versions, 0 failed);
the universe membership file was built and committed (549 intervals, 548
names, 347 in the index at 2016-01-04); the **null test passed** (the
book-94 through the cohort path reproduces the plain path: grades and
scores equal, 24 of 24 lines equal to the bit at two offsets and two
costs) before any arm was run; the arms were run and no number read until
all four payloads were on disk.

## The lines, 25 bp, median across 20 offsets

`rule / point-in-time` is the arm; `equal weight / point-in-time` is its
survivorship hurdle (every eligible name, equal weight, same clock).

**2016-2023 (deciding)**

| line | control | U-sector | U-flat | U-tone | SPY | QQQ |
|---|---|---|---|---|---|---|
| rule / PIT, median CAGR | **28.0%** | 14.9% | 15.8% | 16.9% | 13.2% | 18.6% |
| rule / PIT, worst offset | 26.2% | 13.5% | 14.2% | 14.9% | | |
| rule / PIT, worst drawdown | -47.9% | -38.6% | -37.7% | -37.0% | -33.7% | -35.1% |
| rule / PIT, median Sharpe | 0.98 | 0.83 | 0.87 | 0.90 | 0.76 | 0.86 |
| offsets above QQQ | 20 | 0 | 0 | 0 | | |
| EW / PIT, median CAGR | 27.7% | empty † | empty † | 16.0% | | |

**2024-2026 (seen; veto only)**

| line | control | U-sector | U-flat | U-tone | SPY | QQQ |
|---|---|---|---|---|---|---|
| rule / PIT, median CAGR | **47.6%** | 19.5% | 23.2% | 23.8% | 20.4% | 24.7% |
| rule / PIT, worst offset | 35.3% | 17.5% | 20.5% | 21.7% | | |
| rule / PIT, worst drawdown | -32.0% | -20.0% | -19.4% | -19.6% | -18.8% | -22.8% |
| rule / PIT, median Sharpe | 1.30 | 1.32 | 1.41 | 1.39 | 1.27 | 1.16 |
| offsets above QQQ | 20 | 0 | 4 | 8 | | |
| EW / PIT, median CAGR | 29.8% | empty † | empty † | 14.9% | | |

† The equal-weight hurdle on 400+ names asks for 0.24% legs, and the live
execution floor the simulator enforces (`paper.MIN_TRADE`, 0.5% of
equity) skips every one, so the line holds cash throughout and reads 0.0%.
The arms' own legs (1.5-3.3%) clear the floor. The hurdle is therefore
unreadable for U-sector and U-flat under the live policy, and the
within-run "rule minus EW" pairs for those two arms compare the rule with
cash and are not quoted. U-tone's hurdle (188 names, ~0.5% legs) is
priced. See "Limits".

## Against the control: the paired daily difference at the median offset

Arm's `rule / point-in-time` minus the control's, session by session,
25 bp, Newey-West t at lag 20, PSR, and the deflated Sharpe at 457
cumulative trials (trial variance = the across-arm variance of the three
paired-difference Sharpes, 9.6e-6, as the earlier stages computed it).

| arm | window | mean bp/day | NW t | PSR | DSR@457 |
|---|---|---|---|---|---|
| U-sector | 2016-2023 | -5.6 | -2.44 | 0.02 | 0.01 |
| U-sector | 2024-2026 | -9.0 | -1.50 | 0.09 | |
| U-sector | all | -5.9 | -2.81 | 0.01 | |
| U-flat | 2016-2023 | -5.0 | -2.25 | 0.02 | 0.01 |
| U-flat | 2024-2026 | -8.1 | -1.46 | 0.09 | |
| U-tone | 2016-2023 | -5.5 | -2.62 | 0.01 | 0.00 |
| U-tone | 2024-2026 | -7.5 | -1.44 | 0.10 | |

Offsets on which the arm's 2016-2023 CAGR is above the control's: **0 of
20** for every arm.

## The criteria, as registered (25 bp)

| | criterion | U-sector | U-flat | U-tone |
|---|---|---|---|---|
| 1 | median CAGR lead ≥ 2.0 points on both windows | **FAIL** (-13.1 / -28.1) | FAIL (-12.2 / -24.5) | FAIL (-11.1 / -23.8) |
| 2 | paired NW t ≥ 2.0 on 2016-2023 | **FAIL** (-2.44) | FAIL (-2.25) | FAIL (-2.62) |
| 3 | above the control on ≥ 15 of 20 offsets | **FAIL** (0) | FAIL (0) | FAIL (0) |
| 4 | worst drawdown not worse by > 3 pts; worst single-name day not worse | ok (-38.6% vs -47.9%; -1.0% vs -3.3%, -0.5% vs -4.7%) | ok | ok |
| 5 | sessions with < 5 A/A+ names below 5% on both windows | ok (0.0% / 0.0%) | ok (0.0% / 0.0%) | ok (0.0% / 0.0%) |
| 6 | DSR of the paired difference ≥ 0.95 | **FAIL** (0.01) | FAIL (0.01) | FAIL (0.00) |
| | **verdict** | **RECORD** | RECORD | RECORD |

## The mechanism, measured

The registration's added measurement, the A/A+ count per session among
eligible names, and the concentration block (target weights, not fills):

| | control 2016-23 | control 2024-26 | U-sector 2016-23 | U-sector 2024-26 | U-tone 2016-23 | U-tone 2024-26 |
|---|---|---|---|---|---|---|
| eligible names, median | 30 | (94 today) | 416 | (528 today) | 188 | (266 today) |
| A/A+ per session, median | 7 | 5 | 58 | 69 | 32 | 35 |
| A/A+ per session, 10th pct | 4 | 2 | 44 | 62 | 26 | 31 |
| sessions with < 5 | 17.3% | 42.9% | 0.0% | 0.0% | 0.0% | 0.0% |
| effective names, median | 7 | 5 | 58 | 69 | 32 | 35 |
| largest weight, median / max | 14% / 25% | 20% / 25% | 1.7% / 3.3% | 1.5% / 1.8% | 3.1% / 5.6% | 2.9% / 3.9% |
| cash, median / max | 0% / 75% | 0% / 75% | 0% / 0% | 0% / 0% | 0% / 0% | 0% / 0% |
| worst single-name day | -3.3% | -4.7% | -1.0% | -0.5% | -1.0% | -0.8% |

So the claim's first half holds exactly: the cap-bound sessions go from a
fifth (deciding) and two fifths (recent) to none, the cap never binds
(largest weight 3.3% against a 25% cap), and idle cash is gone. The A
count scales as the disclosure said it would: about a quarter of the
eligible names on the book (7 of 30) and a seventh within sectors (58 of
416). The
registration's arithmetic was that this spends the idle cash; the book's
idle cash was measured at a point a year per 5% of cap, and the arms
recover none of it because what they hold instead earns less.

## Reading

1. **The return is name choice, not the grade.** The control's 28.0% is
   the AI-and-software book; its own hurdle, EW of every eligible book
   name, is 27.7%. The universe arms at 15-17% sit between SPY (13.2%) and
   QQQ (18.6%), where an equal-weight portfolio of 60 large names should
   sit. Grading 500 names with the same five analysts does not find the
   book's drift elsewhere; it averages it away across eleven sectors,
   which is the "against" case the prior stated.
2. **Sector ranks and a flat rank read the same.** U-sector 14.9%, U-flat
   15.8%: the choice of cross-section moves the answer by less than an
   offset's worth of noise, and neither is near the control. The grade's
   meaning was preserved by the sector rank (58 A names, not 80) at no
   gain in return.
3. **Tone is worth about two points and does not change the verdict.**
   U-tone (16.9%) beats U-sector (14.9%) on the deciding window with A+
   possible everywhere, and its rule line beats its own EW hurdle by 0.9
   points (paired t -0.26; the CAGR gap is drawdown shape, not a daily
   edge) on 2016-2023 and by 8.9 points (t 1.65) on 2024-2026. Completing
   tone for the 264 names without it would not make the universe a
   candidate.
4. **Risk is where the arms win, and it is priced at 13 points a year.**
   Worst drawdown -38.6% against -47.9% over the whole history, the worst
   single-name day a third to a tenth of the control's, Sharpe on the
   recent window 1.32 against 1.30 at half the return. That is
   diversification doing what it does, and the operator's mandate (a
   concentrated AI-and-software book) is the decision that declines it.
5. **The recent window vetoes on its own.** 19.5% against 47.6% (worst
   offset 17.5% against 35.3%), below SPY. The control's 2024-2026 is the
   concentrated bet the registration said a larger book cannot make.

## Survivorship, as disclosed

Both the control and the arms hold only names with bars in the store: 16
book exits and 216 index exits since 2016 are absent, so every absolute
CAGR here is inflated, the arms' more than the control's (the arms'
2016-01-04 book is the ~340 constituents that stayed). The paired
difference against the control shares the bias on the control's names
only; the arms' extra names are all survivors, which flatters the arms.
The verdict survives a bias in the arms' favour.

## Limits

- **The EW hurdle is not priced for U-sector and U-flat** under the live
  execution floor (above). The registered criteria do not read it (all six
  are against the control), so the verdict does not depend on it; the
  grade-versus-EW paired number the registration called "the readable
  number" for survivorship is available only for U-tone. Pricing it would
  mean either an allocator-level hurdle that ignores `MIN_TRADE` or a
  smaller EW basket, both outside this registration; noted, not done.
- Overlay names that are also constituents in non-book sub-industries
  (AMZN, META, AAPL, GOOGL, ... 20 names) are eligible from their index
  entry in the universe file and from their September 2026 overlay commit
  in the book file. This follows the registration's rule for each file and
  favours the arms (they hold those names through 2016-2025; the control
  does not).
- Today's GICS sector is carried backward (the 2018 and 2023
  reclassifications), and an analyst's own leg blend runs over the whole
  panel with only the final rank taken within the sector (`cohort.py`,
  Choices 2 and 3). Neither is plausibly worth 13 points.
- The control's lines differ from the 2026-09-26 cap sweep (28.7% / 48.5%)
  by the store day (2026-09-29 here); they are the scorecard's own numbers
  on the day the arms were run, as registered.

## What a RECORD does

Nothing moves: no `/6`, no change to the paper account, no proposal to the
operator beyond this note. The universe path (`--universe`,
`--membership`, `cohort.py`) and the versioned facts for 531 names stay in
the repository; the facts also serve the expectations gap and any later
study that needs the fundamental analyst outside the book. Trial count
457 is the cumulative figure the next registration deflates against.

## Recomputation

`python -m backend.cli.universe_verdict --dir docs/research/scorecards/universe-expansion`
reads the four payloads, prints the verdict lines above and writes
`verdict.json`. An independent script (fresh Newey-West at lag 20, medians
taken from each row's `cagrs`, the median-offset curve compounded into a
CAGR) agreed with `verdict.json` on every criterion number to 1e-6 during
the write-up.

Payload sha256:

    control.json          2ae1168e70ac206cfe5c714f8220885f42ca3c9cd13c5a4b5d218237d921391f
    universe_sector.json  c88c9a06f7c4e36666578f2edba3fc4bbb2967b10fb50761a79cdeefddcc5495
    universe_flat.json    2e43d2d78d9489a336558333b328a5d4d9cef4018e8c757debb0b3e735a456bf
    universe_tone.json    10ec446f58d1517ebb84d2b01eb2e300af57711373d8291257257558b4b7b2e0
    verdict.json          7237c8f5e204462b351ff0e87ff45eaae19b70025d52f0775d1f9c7d15421e35
