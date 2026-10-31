# Pre-registration: event-shock detection and post-shock returns on the honest PIT universe

Written 2026-10-31 before any run of the study. This is the event-discovery step
the owner asked for: the system must find earnings shocks, fear and election dates
from its own ingested data, without being told the event in hindsight. It follows
the failed tone-surprise study (`tone-surprise-results-2026-10-28.md`) and the
failed SUE study (`sue-rank-ic-results-2026-10-29.md`); it is not a retry of
either. It is an association study, not a trading rule: no costs, no portfolio, no
live use. A detector description and a separate defensive-overlay pre-registration
are the only things a pass buys.

Disclosure: before this note was written, a coverage count on the live book
(94 names, tone records) counted releases with a reaction session in the panel and
the number that would meet the shock thresholds below. It computed reaction-session
returns but no forward return, no gate statistic and no study sample. The
thresholds were fixed from that count and the two prior studies, not from a
forward-return result.

## Question

1. **A1, own-name continuation.** When a PIT S&P 500 name reports a large earnings
   drop and the market reacts sharply negative on the reaction session, does the
   name's forward excess return continue negative over 20 and 60 sessions?
2. **A2, contagion.** When a hyperscaler reports such a shock, do other PIT members
   in the AI-complex sectors underperform the benchmark over the same horizons?
3. **A3, elections (descriptive).** What did the market do around past midterm
   elections, and when is the next one? Two midterms are in the cache; this section
   is reported and never gates.

## Data

- PIT cache: `~/dsv41/pit2/cache.npz`, the frozen honest point-in-time S&P 500
  cache used by C1-C3, the risk dial, the tone study and the SUE study: 532
  tickers, 2,970 sessions 2015-01-02..2026-10-23 for the study, and the live scan
  extends to the latest stored session (2026-10-30 at the time of writing). The
  `member` matrix is session-level membership; `adj_close` is the split-adjusted
  close; `sector` is the sector label. The cache has no volume.
- Filings: the store's `edgar_facts_versions` frames
  (`~/deploy/anios/data/market/edgar_facts_versions`), read with
  `fundamentals_asof.versions_from_frame`. Primary earnings: `net_income`
  (`NetIncomeLoss` and its fallback tiers); diagnostic: `eps`
  (diluted/basic); revenue (`RevenueFromContractWithCustomerExcludingAssessedTax`
  and its tiers) is a diagnostic and a live-scan field. The five foreign private
  issuers (ASML, FDXF, NBIS, SIMO, TSM) are excluded from the primary sample and
  stay in the denominator; SPY is the benchmark and has no frame.
- Live scan only: the live store's tone frames (`language.stored_records`) and
  daily bars for the 94 book names, which carry volume. That universe is
  survivor-biased and is descriptive, never gated.
- Elections: deterministic, computed in code, not read from a table. Election day
  is the first Tuesday after the first Monday in November. A midterm is an even
  year not divisible by four.

## Signal

- Quarter series: the earliest filing per period end, quarter spans only
  (`span_kind == "quarter"`, 80-100 days), with a finite value and a filing date.
- Comparison quarters: the prior quarter is the latest period end 60-120 days
  earlier in the same series; the year-ago quarter is the period end 350-380 days
  earlier.
- Earnings change: `(E_q - E_c) / |E_c|`, requiring both values finite and
  `E_c != 0`. The absolute denominator keeps the sign meaningful when the
  comparison is a loss: a larger loss is a negative change.
- Negative earnings shock: QoQ <= -0.20 **or** YoY <= -0.10.
- Reaction session `t`: the first cache session at or after `Version.available`
  (the store's conservative publication rule: a filing accepted at or after 16:00
  ET becomes available the next day).
- Reaction return: `adj_close[t] / adj_close[t-1] - 1`.
- Shock event: a negative earnings shock **and** a reaction return <= -0.05, with
  the name a PIT member at `t`. A name has at most one shock event per period end;
  the earliest filing per period end is the only one kept. Volume is not in the
  PIT cache and does not enter the study definition; a volume ratio of at least 2
  is a live-scan confidence field only.
- Forward excess return at horizon h: the name's
  `adj_close[t+h] / adj_close[t] - 1` minus SPY's same-window return. Price return,
  no costs. Require finite prices at `t` and `t+h`. h = 20 and 60 sessions.

## A1: own-name continuation

- Sample: shock events on PIT members with a reaction session in 2016-01-01..
  2023-12-31 (choosing). 2024-2026 is reported and never tuned on.
- Statistic: the mean forward excess return across events, with a 95% block
  bootstrap resampling calendar months (2,000 draws; every event in a month moves
  together, because earnings cluster in seasons).
- **G1:** the mean is less than 0 and the 95% CI upper bound is less than 0, at both
  20 and 60 sessions.
- **G2:** 200 placebo draws. Each shock event is reassigned to a uniformly random
  session of the same name in the same calendar year that is a PIT-member session
  and is not within 20 sessions of any real shock event for that name; the forward
  excess is recomputed at that session. The real mean must be strictly below the
  5th percentile of the placebo means at both horizons.
- **G3:** the yearly mean excess is negative in at least 5 of the 8 choosing years,
  at both horizons.

All three must hold at both horizons for A1 to pass.

## A2: hyperscaler contagion

- Hyperscaler set, fixed before the run: MSFT, AMZN, GOOGL, META, ORCL.
- Event: a hyperscaler shock event at `t`, defined exactly as in A1.
- Peer set at `t`: PIT members at `t` whose cache sector is Information Technology
  or Communication Services (the two sectors that contain the AI complex; AMZN is
  Consumer Discretionary but its shock still moves the same complex), excluding the
  five hyperscalers, excluding any name with its own shock event within 10
  sessions, and requiring a finite `adj_close` at `t` and `t+h`. Require at least
  20 peers; events below that are reported and excluded from that horizon.
- Statistic: each event contributes the equal-weight mean forward excess return of
  its peers; the pooled statistic is the mean across events, with a 95% block
  bootstrap resampling event months (2,000 draws).
- **G1:** the pooled mean is less than 0 and the 95% CI upper bound is less than 0,
  at both 20 and 60 sessions.
- **G2:** 200 placebo draws. Each hyperscaler shock is reassigned to a uniformly
  random session of the same hyperscaler in the same calendar year that is a
  PIT-member session and is not within 20 sessions of any real shock for that
  name; the peer set is rebuilt at that session. The real mean must be strictly
  below the 5th percentile of the placebo means at both horizons.
- No G3 for A2: a few shocks per year make a yearly gate underpowered. Yearly
  means and counts are reported.

## A3: midterm elections (descriptive, not gated)

- Election dates in the cache: 2018-11-06 and 2022-11-08. The next midterm is
  2026-11-03.
- For each past midterm, report SPY's return and the equal-weight return of PIT
  members over the 20 sessions before the election and the 20 and 60 sessions
  after it, plus the path from 60 sessions before to 60 after.
- n = 2. This is a description of two observations, not evidence of a seasonality.
  It is reported so the owner can see the history beside the next date; no gate,
  no rule, no overlay.

## Live scan (descriptive, not gated)

The scan is the part that answers "find it without being told". It is mechanical
and runs after the close:

- For every book name, the latest filing's EPS and revenue QoQ and YoY, the five
  tone fields and their change from the previous release, the reaction-session
  return, the volume ratio against the prior 20-session median, the installed
  grade, action and target weight.
- The shock flag is the same mechanical rule as A1, with the volume ratio reported
  as confidence. The scan lists every name that meets it; it is not told which
  name to look at.
- The calendar section lists the next FOMC decision from
  `backend/market/data/fomc_decisions.csv`, the next election from the
  deterministic rule, and the sessions until each.
- Output is JSON under `data/market/research/event-watch/`, which is a research
  path; no live file is written. No model call and no prompt; every field is
  computed from stored data.

## Diagnostics (reported, not gated)

- EPS-based and revenue-based shock definitions, repeating A1 with the same
  thresholds; the yearly pattern.
- Positive shocks (QoQ >= +0.20 or YoY >= +0.10, reaction >= +0.05) for A1 and A2,
  to show whether the effect is symmetric.
- Sector-neutral A1: within each sector with at least 10 events, the mean excess,
  averaged across sectors; tests whether the raw result is a sector effect.
- Grade diagnostic: the mean excess among shock events whose PIT grade is A/A+
  (`grade >= 2`), where the live rule actually buys.
- The number of events per year, per horizon, and the share of events with a full
  forward window.
- For A2: the peer-count distribution, and the mean peer excess by hyperscaler.

## Look-ahead controls

- The event uses only filings whose `Version.available` is on or before `t`; the
  reaction return uses `t` and `t-1`; the forward return uses only prices after
  `t`; membership is the PIT matrix at `t`.
- Perturbation: for 100 sampled shock events, multiply every `adj_close` after `t`
  by a factor in [0.95, 1.05]; the event list and shock flags must be identical.
  Change `adj_close[t-1]` (the last close before the event) by +1% and the reaction
  return must change; for a borderline event the shock flag must change. Report
  the counts.
- The study reads no live book, no order, no position, and no prompt.

## Stop conditions

- If fewer than 200 shock events are available in 2016-2023 with a full 20-session
  window, stop and report that the sample is underpowered before the gate.
- If more than 10% of candidate filings have a missing comparison quarter, report
  the gap before the gate.
- If a gate fails, record it and stop. The arm is not retried with a different
  threshold, reaction window, horizon, peer definition or universe without a new
  pre-registration saying what changed and why.
- A2's failure does not reopen A1, and A3 cannot rescue either; the arms are
  separate.

## What passing buys

Only a pre-registration for a defensive overlay: after a detected shock, reduce
gross exposure or block new entries in the affected name or AI-complex sector for
a fixed number of sessions, run through the production policy engine
(`policy_book`) at 10 and 25 bp on the honest PIT universe, with its own placebo
and drawdown gate. A pass there would be a forward-shadow candidate, not a live
change. The live rule stays frozen through the 252-session review.

The detector itself is descriptive alerting either way. It does not change sizes,
grades, orders or prompts without that separate overlay gate.

## Clarifications

- This is not a retry of SUE or tone-surprise. SUE measured the surprise
  cross-sectionally without conditioning on the market's reaction, and its
  momentum control showed it was partly a momentum proxy. This study conditions
  on a large negative reaction and asks about continuation and contagion: a
  different question, sample and statistic.
- The study is an association test. A negative mean is not proof of a tradable
  short: the book is long-only, so the actionable form is defensive, and costs,
  turnover and the overlay's interaction with the installed grade are the
  overlay's problem.
- n = 2 midterms is not evidence. The election section is a calendar and a
  description, not a seasonality claim.
- The live scan is survivor-biased by construction (today's book names); that is
  why it is descriptive and why the study uses the honest PIT universe.
