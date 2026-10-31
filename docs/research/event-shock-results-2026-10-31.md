# Event-shock detection: results — 2026-10-31

**Status: A1 STOPPED as underpowered before the gate. A2 ran and failed. A3 is
descriptive. Nothing goes live; no overlay is pre-registered.**
This is the result of `event-shock-preregistration-2026-10-31.md`, run after the
note was committed. The detector is descriptive alerting either way; it does not
change sizes, grades, orders or prompts.

## The question

Can the desk find earnings shocks, fear and election dates from its own stored
data, without being told the event in hindsight — and does a detected negative
shock predict continuation in the name (A1) or contagion in the AI complex (A2)?
A3 reports the two cached midterms and the next date, and never gates.

## The scan: it found the event without being told

`backend/cli/market_event_watch.py --scan` reads every book name's latest stored
release, computes EPS and revenue change, the five tone fields and their change,
the reaction-session return, the volume ratio, and the installed grade. It was
not given GOOGL, or any date. It returned:

- **GOOGL 2026-10-29**, 1 session before the scan: EPS 2.12, **−76.7% QoQ** and
  **−26.1% YoY**; revenue $127,577M, **+24.7% YoY**; reaction **−12.6%** on
  **5.9×** the prior 20-session median volume; tone guidance 0.0, demand 0.8,
  pricing 0.0, capex 0.7, supply 0.3, summed tone change −0.2; grade **C**,
  headline "Avoid: sentiment and value against, none for"; action hold, target
  0.0%. It meets the pre-registered rule (EPS drop and reaction ≤ −5%).
- Eight other latest-release shocks: INTC 2026-10-30 (−28.6% reaction, grade A),
  NOW 2026-10-29 (−26.9%, grade B), META 2026-10-22 (−7.0%, grade C), CRDO
  2026-09-02 (−20.0%), DDOG 2026-08-06 (−19.0%), PANW 2026-09-02 (−9.3%), SWKS
  2026-07-29 (−5.4%), OKLO 2025-03-25 (−6.4%).
- 20 large adverse price moves in the last 5 sessions, each on at least 2×
  volume, including FFIV −20.4%, FTNT −20.1%, MRVL −13.2%, QCOM −11.1%, AMD
  −10.9%, ARM −10.0%, SNDK −13.5%, DDOG −11.5%.
- Book mean return since the GOOGL shock: **−5.5% across 95 names**; worst INTC
  −28.6%, SNDK −13.5%, AAOI −12.8%, GLXY −11.7%.
- Calendar: next election **2026-11-03**, a midterm, **2 sessions** away; next
  FOMC **2026-12-09**, 27 sessions away.

The INTC row is the point of the detector: grade A and a mechanical shock can
disagree, and the scan reports both without reconciling them. The scan makes no
model call, reads no prompt, and writes only under
`data/market/research/event-watch/`. It is **not** wired into the nightly; that
would touch the live pipeline and needs the owner's authorization.

## A1: own-name continuation — stopped

The pre-registration stops the arm if fewer than 200 shock events in 2016-2023
have a full 20-session window. There were **114**; every one has a full window.
The gate was not evaluated, and the G1/G2/G3 fields are null in the result.

Point estimates, reported as description only, not as a gate result:

| horizon | n | mean excess | 95% CI | months |
|---|---:|---:|---:|---:|
| 20 | 114 | **+1.52%** | −2.21% .. +5.05% | 60 |
| 60 | 114 | **+1.81%** | −2.78% .. +6.60% | 60 |

The sign is the opposite of the hypothesis: after a large drop and a sharp
negative reaction, the average name **bounced** versus SPY, not continued down.
The yearly means are negative in only 3 of the 8 choosing years at both horizons
(2018, 2019, 2023 at 20; 2018, 2019, 2020 at 60), so G3 would have failed too.
2024-2026, reported and never tuned on: 66 events, **+2.41%** at 20 (CI +0.13%
.. +4.39%) and **+4.14%** at 60 (CI −0.44% .. +9.20%) — the same bounce.

## A2: hyperscaler contagion — failed

Three hyperscaler shock events (MSFT 2016, ORCL 2022 twice), 6 event-horizon
observations; peers per event 47 to 69, median 69.

| horizon | events | pooled peer mean excess | 95% CI |
|---|---:|---:|---:|
| 20 | 3 | **−0.21%** | −2.14% .. +2.44% |
| 60 | 3 | **+2.97%** | +0.82% .. +6.29% |

G1 fails at both horizons: the 20-session mean is not distinguishable from zero,
and the 60-session mean is positive with a CI entirely above zero. G2 fails.
There is no measured contagion; if anything peers outperformed after 60
sessions. By hyperscaler: MSFT +2.41% (4 observations), ORCL −0.66% (2).

## A3: midterms — descriptive, n = 2

| election | before 20 (members / SPY) | after 20 (members / SPY) | after 60 (members / SPY) | 60 before → 60 after (members / SPY) |
|---|---|---|---|---|
| 2018-11-06 | −3.07% / −4.27% | −1.54% / −1.92% | +1.48% / −0.15% | −0.28% / −2.18% |
| 2022-11-08 | +9.20% / +6.78% | +3.49% / +2.92% | +9.20% / +7.78% | +1.40% / −3.60% |

Two observations. This is a calendar and a description, not a seasonality claim,
and it gates nothing. The next midterm is 2026-11-03.

## Diagnostics (reported, not gated)

- **EPS-based definition:** 112 events, +1.84% at 20 (CI −1.97% .. +5.40%) and
  +1.82% at 60 (CI −4.15% .. +7.18%). Same bounce, no significance.
- **Revenue-based definition:** 36 events, +6.97% at 20 (CI −1.63% .. +15.84%)
  and +7.35% at 60 (CI −2.32% .. +19.38%). Positive point estimate, CI spans
  zero, small n.
- **Positive shocks:** 177 events, **+2.44%** at 20 (CI +0.92% .. +3.94%) and
  **+3.06%** at 60 (CI +0.59% .. +5.55%). This is the only arm whose CI excludes
  zero at both horizons, and it is **diagnostic only** — it was not gated, and
  the negative shock it is symmetric to does not predict continuation.
- **Grade A subset:** 12 events, −0.19% at 20 and −2.00% at 60; both CIs span
  zero. Too few events to say anything about the names the live rule buys.
- **Sector-neutral A1:** +0.41% at 20 and +0.25% at 60 across 5 sectors, so the
  raw bounce is not a sector effect.

## Controls

- **No future data:** for 100 sampled events, multiplying every price after the
  reaction session by a factor in [0.95, 1.05] left the event list and shock
  flags identical in 100/100 cases.
- **Reaction is real:** changing the close before the event by +1% changed the
  reaction return in 100/100 cases.
- **Borderline:** CINF at −4.9% flags false, at −5.1% flags true.

## What this means

- The discovery half works: the scan names the release, the reaction, the volume
  and the grade from stored data, with no hindsight and no prompt. That was the
  owner's requirement, and it is met by `backend/market/event_watch.py` plus
  `backend/cli/market_event_watch.py`.
- The prediction half does not: a detected negative shock is followed by a
  bounce, not continuation, and there is no measured peer contagion. A1 could
  not even reach its pre-registered sample size, which is itself the finding:
  this shock definition is rare on the honest PIT universe.
- The positive-shock drift is interesting but ungated and would need its own
  pre-registration. It is not a live rule and is not retried here.
- No overlay is pre-registered. The live rule stays frozen through the
  252-session review. The detector is descriptive alerting only.

**Closed for A1 and A2.** Not retried with a different threshold, reaction
window, horizon, peer definition or universe without a new pre-registration
saying what changed and why. The result is written beside the pre-registration,
as the protocol requires.
