# How good are the grades, and which analyst earns them

Date: 2026-10-22 (overnight). Script: `backend/cli/market_grade_quality_research.py`
(output `~/dsv41/replay/grade_quality.json` on spark1). Point-in-time
panel, 2015–2026, every name-session the universe knew at the time; the
grade and the stances are the desk's own as of that close; the outcome
is the name's return over the next 20 / 60 sessions less QQQ's.

## By grade (excess over QQQ)

| grade | name-sessions | 20 sessions | hit | 60 sessions | hit |
|---|---|---|---|---|---|
| A+ | 10,236 | +1.9% | 57% | +5.7% | 60% |
| A | 6,308 | +0.8% | 51% | +2.8% | 57% |
| B | 19,074 | +1.4% | 56% | +3.8% | 59% |
| C | 52,163 | +0.5% | 51% | +1.9% | 52% |

A+ is the signal. A without the release is weaker than B: the ladder is
A+ ≫ B > A > C, so the A cut the book is drawn at (A and A+ only) keeps
the weakest of the three upper grades and leaves out B. Spread of A+/A
over B/C: +0.7% at 20 sessions, +2.2% at 60.

By year (A+/A minus B/C at 60 sessions; mean excess of the A+/A names):
2016 +2.8% (+6.9%) · 2017 +2.3% (+5.0%) · 2018 +2.4% (+3.9%) · 2019
−2.5% (+1.8%) · 2020 +0.2% (+5.8%) · 2021 +1.7% (+2.0%) · 2022 −1.9%
(−1.1%) · 2023 +4.0% (+7.0%) · 2024 +3.1% (+1.7%) · 2025 +6.7% (+8.3%)
· 2026 +6.2% (+13.7%). The grades carried no selection edge in 2019 and
2022, which is the same shape the policy's own entries showed.

## By analyst (bullish minus bearish names, 60 sessions)

| analyst | bullish mean | bearish mean | spread | coverage |
|---|---|---|---|---|
| value | +7.0% | +1.6% | +5.3% | 50% |
| rotation | +4.6% | +0.5% | +4.0% | 21% |
| fundamental | +3.7% | +1.5% | +2.2% | 53% |
| technical | +3.7% | +1.5% | +2.2% | 60% |
| sentiment (release tone) | +3.7% | +3.2% | +0.5% | 59% |

The valuation analyst separates names best; the release-tone analyst
barely separates them on its own (+0.5%), yet it is the gate to A+,
and A+ is the best grade. The tone matters as a condition on the other
votes, not as a vote. That is also the analyst with the hindsight
caveat (a modern reader of historical text), so its small standalone
spread is reassuring rather than disappointing.

## What this suggests, to be measured not assumed

1. Draw slots at B or better (`leader_ewma_minB`) and at A+ only
   (`leader_ewma_aplus`): scored tonight against the installed A cut.
2. The ridge-weighted analysts were tested walk-forward before and lost
   (`grading.py`); that stands. A value-led vote is the next thing to
   score, as an arm, not a fit.
3. 2019 and 2022 are the years to study: what the A names had in common
   when they failed.
