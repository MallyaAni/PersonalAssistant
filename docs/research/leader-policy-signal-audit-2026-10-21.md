# Did the installed policy's signals make money? A per-signal audit without hindsight

Date: 2026-10-21 (overnight into 10-22). Policy: `grade-led-leader-weight/1`
(equal A/A+ slots, 63-session leader tilt 0.5, EWMA-20 volatility target
0.25, 25% cap, every leg at the next open). Generator:
`backend/cli/market_policy_replay_research.py`; output under
`data/market/research/policy-replay/ew_graded_leader_forecast_ewma/2026-10-21/`.

## Method

The rule is walked forward through every session from 2015-01-02 to
2026-10-21 on the point-in-time universe (names as they were known at each
date, `membership_history.csv`). On each close the rule sees only prices and
grades through that close. The sizing has no fitted model. A target set at
close t is treated as traded at the open of t+1. Each entry (target from
zero) and each exit (target to zero) is then judged by the name's close
t+h against QQQ's, h = 5, 20, 60 sessions. Costs are not charged here (the
scorecard charges them); this is the signal, not the book.

Caveat that cannot be cleared from inside this run: the grades include a
tone reading of each earnings release made by a modern language model
reading the historical text. The text is historical; the reader is not.

## The aggregate (585 entries, 574 exits, 2016–2026)

| after | entries beat QQQ | mean excess | median excess | mean return | worst |
|---|---|---|---|---|---|
| 5 sessions | 54% | +0.4% | +0.3% | +0.7% | −25.5% |
| 20 sessions | 51% | +0.9% | +0.1% | +2.2% | −28.9% |
| 60 sessions | 56% | +2.8% | +2.0% | +6.6% | −44.1% |

An entry is a coin flip at 20 sessions and a modest edge at 60: the money
is made by holding, not by timing the entry. That is consistent with the
scorecard (22% CAGR against QQQ's 18.9%) and with a 2016–2026 book of AI
and semiconductor names.

By year (entries; hit rate and mean excess at 20 / 60 sessions):
2016 55: 53% +0.5% / 56% +2.5% · 2017 51: 67% +2.8% / 75% +7.2% ·
2018 48: 58% +1.2% / 56% +0.8% · 2019 57: 40% −0.3% / 61% +3.1% ·
2020 58: 52% +2.4% / 60% +6.7% · 2021 56: 38% −1.8% / 43% +0.7% ·
2022 64: 44% +0.1% / 44% −0.7% · 2023 54: 65% +2.6% / 72% +5.5% ·
2024 36: 42% −1.0% / 53% −1.1% · 2025 50: 44% +0.3% / 48% +0.4% ·
2026 56: 63% +3.7% / 46% +5.7%.

2021, 2022 and 2024 had no edge at all. The rule earns in trending years
and gives it back in choppy ones; nothing in it reads the regime.

## The exits sell too soon

After an exit (the grade slipping below A), the exited name returned
+6.1% over the next 60 sessions on average, +2.4% over QQQ, beating QQQ
57% of the time. The downgrade is not a sell signal; on this book it is
noise the rule pays to act on. Two arms are being scored against the
installed rule tonight: `leader_ewma_holdB` (enter at A, hold while at
least B) and `leader_ewma_stop15/25` (a trailing stop in place of nothing).

## The rule churns

The leader tilt and the volatility target move every held slot a little
most sessions: 12,909 target moves of 0.05% or more across the book, 577
of 0.5% or more in MU alone, most of them resizes of a held name. The
charts draw entries, exits and reallocations of 2% or more and say how
many small resizes they left out. The paper account traded the same
nudges tonight (buy 1 TSM, buy 1 COHR). `leader_ewma_band1/band2` (trade
only when the target has moved 1% / 2%) are being scored; if the band
keeps the return after costs the policy should carry it.

## Names

Best mean 60-session excess among names with several entries: TER (10
entries, 60% beat, +18%), LITE (4, +15%), NVDA (27, 76%, +12%), AMD (18,
+12%), AMAT (14, 71%, +8%), KLAC (35, 66%, +5%). Worst single entries at
60 sessions: DDOG 2025-11-10 −44%, ON 2026-06-18 −40%, AMD 2018-09-21
−37%, MCHP 2020-01-09 −33%, CRWD 2024-06-24 −29%, MU 2022-04-01 −26%.

Since July 2026 the rule entered 31 times. The entries of 2026-09-04
(HPE +32% in 20 sessions, NTAP +21%, SMCI +9%, POWL +9%, STX +5%, DELL
+5%, GEV +5%) made the quarter; COHR 2026-09-23 (−21% in 20 sessions)
and CSCO 2026-08-11 (−9%) lost. The entries of 2026-10-05 onward (SNPS,
GEV, CRM, COHR, TSM) are too young to judge.

## What this changes

1. The charts now show this replay and nothing from any other policy.
2. The exit rule and the churn are the two measurable weaknesses; both
   have arms scoring overnight and either becomes a policy change only
   through the release ceremony, with the scorecard's twenty offsets as
   the evidence.
3. The regime dependence (2021/2022/2024 flat) is the open problem; the
   volatility target is the only regime reader the rule has.

## Entries before earnings

Matching each entry to the name's next 8-K item 2.02 acceptance date
(the actual release; a company announces its date weeks ahead, so a live
guard would know it): entries within 7 calendar days before a release
(n=46) beat QQQ 35% of the time at 20 sessions, mean excess −1.2%;
entries 8–21 days before (n=61) 57%, +2.5%; entries further out (n=471)
52%, +1.0%. A guard that defers a new entry until after a release due
within a week is supported by this sample; it needs an expected-date
feed (the release reader's "usual gap 91 days" is a start).

## Sensitivity of the installed parameters (all window, 25 bp)

| arm | CAGR | worst DD | Sharpe |
|---|---|---|---|
| installed (s0.5 w63 t0.25 cap0.25 span20) | 22.0% | −34.2% | 0.99 |
| target 0.20 | 20.0% | −30.4% | 1.03 |
| target 0.30 | 23.3% | −41.1% | 0.96 |
| tilt 0.25 | 22.3% | −34.6% | 0.99 |
| tilt 0.75 | 21.1% | −36.5% | 0.97 |
| cap 0.20 | 20.2% | −34.6% | 0.97 |
| cap 0.33 | 23.1% | −36.3% | 0.99 |
| EWMA span 10 | 22.0% | −37.2% | 0.98 |
| EWMA span 40 | 22.0% | −34.6% | 0.98 |

The installed point is not on a cliff. The 0.20 target is the one
neighbour a more cautious owner would pick: two points of CAGR for four
points less drawdown.
