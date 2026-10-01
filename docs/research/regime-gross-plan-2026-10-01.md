# Regime gross (B2): the day-type model's tail probability gates exposure. Pre-registration (2026-10-01)

**Status: registered before any code or number.** Queue item B2 of
[the survey](sota-survey-2026-10-01.md), run after and against
[B1, volatility targeting](vol-target-plan-2026-10-01.md). B1 scales the
book to its own realised volatility; this note asks whether a *regime
signal* - a learned probability that tomorrow is a tail day for the
basket - cuts exposure in the storms better than that simpler rule.

## The question

Shu, Yu and Mulvey (2024) allocate on a sparse jump model's regime with a
one-day lag and report an information ratio of 0.4-0.5 against equal
weight on 2007-2024 with better drawdowns; their own caveat is that
regimes flip about twice as often in real time as in hindsight. Does a
point-in-time regime probability, read at the previous close, lower this
book's worst drawdown (−43% on 2016-2023, −25% on 2024-2026) without
giving up the return - and does it do so *better than a fixed volatility
target*, which needs no model at all?

## What is known before this note (disclosed)

- **B1 is registered and not yet run** (`bd814b64` plan, `d8a38ad6`
  build; the desktop link to spark1 is down). Its three targets (20%, 25%,
  30% a year) are the control this study has to beat. Nothing has yet been
  measured on a regime gate on this desk.
- **The day-type model has no skill as a forecaster.** The 09-26 study
  (`pit-arms-2026-09-26.md`, `scorecards/day_type.json`): out-of-sample
  Brier skill against the trailing base rate on 2016-2023 is −0.001 at
  best (horizon 1, boosted model), verdict INSUFFICIENT EVIDENCE. Its
  exposure diagnostic - scale the basket to 1 − p when p exceeds
  climatology - gave up three to six CAGR points for three to four points
  of drawdown, the shape of every brake measured here. So the prior is
  low: a gate built on a probability with no skill over climatology can
  only help by what the climatology itself carries (volatility
  clustering), which is what B1 reads directly.
- **The real-time caveat applies with force.** The probability is refit
  on a schedule, read a session late, and gates at a hard threshold; every
  one of those makes a regime rule whipsaw more in real time than the
  published backtests show.
- Name-level volatility sizing and every stop lost
  (`vol-sizing-2026-09-27.md`, `catastrophe-stop-2026-09-27.md`); the
  learned QQQ-drawdown brake lost CAGR for its drawdown.

## The probability is point in time, and must be produced, not read

`backend/market/day_type.py` builds the study (features that are trailing
statistics of the panel, the point-in-time book mask and the regime
analyst's context; a label that is the equal-weight basket's open-to-open
return over the next H sessions below the bottom tenth of its own trailing
250-session distribution) and `day_type.walk_forward` scores it: a refit
every 63 sessions on an **expanding window** of rows whose labels matured
before the fit (purge of H + 22 sessions), the first fit after 750
sessions - about mid-2018 on this panel, which is why the 09-26 study
scored 1,388 sessions of 2016-2023 - and each block's probabilities come
from the model fit before it. `data/market/desk/day_type.json` stores only
the scores (Brier, skill, the diagnostic); no model and no per-session
series are stored, and nothing in the repo fits the model on all of the
data. So the series is **reproduced at run time by the same walk-forward**,
not refit on a new schedule: the existing cadence (quarterly, expanding,
purged, from mid-2018) is stricter than a yearly refit and already honest,
and a test on this branch proves it point in time by changing every price
after a session and asserting no probability at or before it moves.

Fixed now, from the 09-26 study's own choosing-window numbers (a choice
made on a published figure, disclosed here): **horizon 1, the boosted
model** (Brier skill −0.001; the logistic model −0.032, every five-session
model worse). Before the first fit the probability is undefined and the
gross is 1, so 2016 to mid-2018 is the control by construction; the
drawdowns of late 2018, 2020 and 2022 are inside the gated span.

## The rule

p(t−1) is the walk-forward tail probability at the close of t−1. Then

    gross(t) = 1        when p(t−1) < θ, or p(t−1) is undefined
    gross(t) = g_low    when p(t−1) ≥ θ

applied to the targets decided at t's close and filled at t+1's open,
exactly as B1 applies σ̂(t−1): the same `simulate.run(gross_path=...)`
mechanism, the same cost on the rescaling trades, cash earning nothing,
the weights the policy's, scaled. Three pairs (θ / g_low), fixed now:
**0.3 / 0.5, 0.5 / 0.5, 0.5 / 0.0**. Reported, deciding nothing: 0.5 / 0.5
combined with B1's 25% target as the per-session minimum of the two
grosses (does the regime gate add anything to the volatility target?).

The base rate of the label is about 10%, so a session with p ≥ 0.5 is a
session the model calls five times riskier than usual; the share of
sessions each pair fires on is recorded, and a pair that fires on none is
the control and RECORD.

## Criteria, fixed now

The trade is B1's, measured twice. A pair **REPLACES** only if, against
**both** the gross-1 control **and the best registered B1 target**, on the
median of 20 offsets at 25 bp: the worst drawdown falls by at least 5
points on both windows while the CAGR falls by at most 3 points on each,
**or** the Sharpe ratio rises by 0.15 on both windows with the drawdown
not worse; and the paired daily difference is not negative at NW t ≤ −2
on either window against either control. A regime rule that clears the
control and not the volatility target is **RECORD (does not beat the vol
target)**: the simpler rule stands. Anything else is **RECORD**.

The best registered B1 target is read from B1's verdict file before any
B2 number is: the REPLACES target with the largest deciding-window
drawdown gain, or, if none REPLACES, the registered target with the
largest deciding-window drawdown gain. Deflated Sharpe at the cumulative
count is reported and does not decide.

**Null test:** θ = 1.0 (a threshold no probability reaches) reproduces the
control bit for bit, through the same scaled path.

## Trials and prior

Three trials; cumulative 474 → 477. Prior: **~20%** that a pair clears the
drawdown trade against the control, **~10%** that one also beats the best
B1 target. The likely finding is that the gate fires rarely at θ = 0.5,
fires in the same weeks the volatility target is already low at θ = 0.3,
and the combination reported beside them adds nothing to B1.

## Order of work

1. This note, committed alone. 2. Build with tests: the point-in-time
series (`regime_gross.tail_probability`, reusing `day_type.walk_forward`,
with the no-future-row test), the gross rule, `--gross-regime THRESH:GLOW`
(repeatable) on `market_pit_scorecard` through the same gross path as
`--gross-target`, the reported combination, the null test, the two-control
verdict (`market_regime_gross`), an independent check under
`docs/research/scorecards/regime-gross/`. 3. Run on spark1 (CPU) after
B1's payloads exist. 4. Write-up, report.
