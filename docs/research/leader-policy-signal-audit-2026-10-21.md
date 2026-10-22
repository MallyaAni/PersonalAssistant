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

## Overlays scored against the installed rule (all window, 25 bp, 20 offsets)

| overlay | CAGR | worst DD | Sharpe | verdict |
|---|---|---|---|---|
| installed | 22.0% | −34.2% | 0.99 | — |
| trade band 1% (`banded_allocator`) | 22.0% | −35.4% | 0.98 | no gain after costs |
| trade band 2% | 21.9% | −35.1% | 0.98 | no |
| QQQ under 50-day EMA → half exposure | 18.2% | −35.2% | 0.93 | no: the drawdowns arrive before the trend turns |
| QQQ under 50-day EMA → cash | 14.1% | −41.7% | 0.78 | no |
| QQQ under 200-day EMA → half | 20.2% | −34.2% | 0.97 | no |
| trailing stop 15% (`trailing_stop_allocator`) | 20.6% | −38.6% | 0.95 | no: whipsaw |
| trailing stop 25% | 21.4% | −35.7% | 0.98 | no |
| enter at A, hold while ≥B (`grade_hysteresis_allocator`) | 21.6% | −37.1% | 0.94 | no: the per-signal exit finding does not survive at the book level |
| no entry within 7 days of a release, cadence-expected (`earnings_guard_allocator`) | 22.0% | −35.5% | 1.00 | no (2024–26: 28.2% / −29.8%, better) |
| same, with the actual date (the bound) | 21.8% | −35.0% | 0.99 | no |

Nothing tested tonight beats the installed rule on the owner's criterion
(more return for no more drawdown). The two per-signal findings (exits
too early, entries before earnings) are real at the signal level and
disappear at the book level once the slots they free are reallocated:
the book is a portfolio, and these overlays move money between names
that are all exposed to the same factor. The return and the drawdown
both come from that factor, which is why the volatility target is the
only lever that has moved the drawdown so far.

The edge, where there is one, is in which names get the A: that is the
grading engine, and `market_grade_quality_research.py` reads it next.

## What the entries that failed had in common

Each of the 557 entries with a 60-session outcome, bucketed by what the
rule could see at the close it decided (mean / median excess over QQQ at
60 sessions, and the share that beat it):

| the name's own 63-session return | n | mean | median | beat |
|---|---|---|---|---|
| below 0 | 127 | +5.1% | +1.4% | 57% |
| 0 to 25% | 320 | +3.3% | +2.6% | 62% |
| 25 to 50% | 90 | −1.7% | −3.9% | 39% |
| above 50% | 20 | 0.0% | −1.5% | 45% |

| QQQ's 20-session return | n | mean | median | beat |
|---|---|---|---|---|
| below −3% | 93 | +6.1% | +5.7% | 61% |
| −3% to 3% | 195 | +2.4% | +2.0% | 56% |
| 3% to 8% | 206 | +2.6% | +2.1% | 60% |
| above 8% | 63 | −0.6% | −2.2% | 38% |

| the name against its 252-session high | n | mean | median | beat |
|---|---|---|---|---|
| more than 30% below | 48 | +7.0% | +6.8% | 63% |
| 15–30% below | 83 | +3.7% | +0.1% | 51% |
| 5–15% below | 152 | +4.7% | +2.9% | 63% |
| within 5% | 274 | +0.7% | +0.9% | 53% |

The rule chases. Its entries into names that had already run a quarter
or more in three months, or made with the index up more than 8% in a
month, or within 5% of the name's yearly high, were the entries that
lost; the entries into names that had pulled back were the ones that
earned. This is the owner's "buy the dip" put in numbers, and it is an
entry rule, not a sizing rule: the leader tilt that sizes a held leader
up is not contradicted, since it acts on names already in the book.
Scored as overlays (`chase_guard_allocator`): defer an entry while the
name's 63-session return is above 25% (`leader_ewma_chase25`), while
QQQ's 20-session return is above 8% (`leader_ewma_chase_q8`), either
(`leader_ewma_chase_both`), and the first on the B cut
(`leader_ewma_minB_chase25`).

Scored (all window, 25 bp, 20 offsets):

| arm | CAGR | worst DD | median DD | Sharpe |
|---|---|---|---|---|
| installed (A cut) | 22.0% | −34.2% | −32.3% | 0.99 |
| A cut, no entry while the name ran >25% in 63 | 22.3% | −35.4% | −31.0% | 1.13 |
| A cut, no entry while QQQ ran >8% in 20 | 21.8% | −35.2% | −32.2% | 0.98 |
| A cut, either | 21.9% | −35.4% | −30.4% | 1.12 |
| B cut | 26.0% | −34.3% | −32.8% | 1.11 |
| B cut, no entry while the name ran >25% | 23.7% | −33.9% | −31.2% | 1.13 |

The name's own run is the guard that matters (the index bar adds
nothing). On the A cut it raises the Sharpe from 0.99 to 1.13 and the
median drawdown by a point, for a point more at the worst; on the B cut
it gives back two points of CAGR for half a point of worst drawdown. By
the owner's criterion the B cut alone stays the candidate; the no-chase
guard is the next thing to put in front of him, as a Sharpe improvement
rather than a return one, once the B cut has a forward record.

## Sizing by grade (scored last)

A multiplier per letter on top of the leader tilt (A+ 1.5x, A 1.0x, B
0.75x; `grade_tilt_allocator`): B cut 26.5% at −35.1% (against the B
cut's 26.0% at −34.3%); A cut 23.5% at −36.0% (against 22.0% at −34.2%).
Half a point of return for a point of drawdown: not adopted.

## Overnight verdict

Of everything scored (eleven overlays, nine parameter neighbours, three
grade cuts, two chase guards, two grade tilts), one change clears the
owner's bar: admit at B. It is built on branch `entry-grade-b`, release
files ready, to be installed after the 2026-10-22 close. The chart
audit after the replay deploy (94 names × 3 frames, 0 console errors,
header words 6 Buy / 4 Sell / 84 blank) matches the board.
