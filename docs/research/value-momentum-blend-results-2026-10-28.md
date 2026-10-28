# Value × residual-momentum blend: C2 result — 2026-10-28

**Status: FAILED the pre-registered gate at the blend arm. The arm is
closed and is not retried.** This is the result of
`value-momentum-blend-preregistration-2026-10-28.md`, run after the note was
committed. Nothing changes in the live rule, the board, or any prompt. The
live rule stays frozen through the 252-session review.

## The result

S&P 500 point-in-time, installed `Rule` (A entry, B hold, 1% minimum trade,
band block, 0.25 volatility target, 0.5 exposure floor, 25% cap, next-open
fills), 25 bp, choosing window 2016-2023. The installed P/E `extra` tilt is
kept in every arm; only the leader score source changes.

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline (installed) | 10.6747% | −33.3296% | 0.6736 | 26.2893% | −19.1375% | 1.6743 | 14.2725% | 0.8842 |
| residual only (control) | 10.2836% | −33.4361% | 0.6607 | 22.2232% | −17.4098% | 1.5053 | 13.0547% | 0.8334 |
| **value only (reference)** | **10.8314%** | **−34.2675%** | **0.6903** | 21.4185% | −17.9301% | 1.5217 | 13.3021% | 0.8529 |
| **blend (primary)** | **10.5493%** | **−33.1021%** | **0.6748** | 24.0557% | −18.2863% | 1.6204 | 13.6853% | 0.8681 |

| arm | choosing CAGR | choosing DD | choosing Sharpe |
|---|---:|---:|---:|
| baseline at 10 bp | 11.5355% | −34.6861% | 0.7083 |
| residual at 10 bp | 11.3136% | −32.3935% | 0.7211 |
| value at 10 bp | 11.7515% | −32.0339% | 0.7501 |
| blend at 10 bp | 11.1507% | −33.1809% | 0.7055 |
| baseline, IT+Comm | 8.9152% | −36.6600% | 0.5296 |
| blend, IT+Comm | 10.8313% | −34.9255% | 0.6149 |

Mean invested and mean names: baseline 0.9590 / 81.9, residual 0.9452 /
79.3, value 0.9318 / 75.5, blend 0.9447 / 78.0.

## The gate

The reference is the best single arm on the choosing window. Value-only
wins it at 0.6903 Sharpe; the residual-only control reproduces C1 exactly
(max absolute difference 0.0) and is not a rescue.

| component | threshold vs value-only | result | verdict |
|---|---|---|---|
| choosing Sharpe | ≥ 0.7403 (value + 0.05) | 0.6748, −0.0155 vs value | **fail** |
| choosing CAGR | ≥ 10.3314% (value − 0.5 pp) | 10.5493%, +0.22 pp above the floor | pass |
| choosing drawdown | ≥ −32.2675% and no deeper than −35% | −33.1021%, 0.83 pp deeper than the bar | **fail** |
| placebo | improvement > 95th percentile of 200 random blends | −0.0155 > −0.0538 | pass |
| perturbation | blend scores before the cutoff unchanged | true | pass |
| off null | installed book reproduced exactly | all seven fields true | pass |
| control | residual-only reproduces C1 | max abs difference 0.0 | pass |
| score multiset | placebo preserves finite scores per session | true | pass |
| strength-zero | scores inert, equal slots | true | pass |

The blend fails two gate components: it is 0.0655 Sharpe below the +0.05
bar over value-only, and its drawdown is 0.83 points deeper than the 2-point
improvement bar. Its drawdown is nevertheless shallower than the installed
baseline's (−33.1021% against −33.3296%), and its CAGR is above the value
arm's floor. The conjunction fails, so the study stops.

The placebo pass is again not evidence of a gain. All 200 random blends
lost Sharpe relative to value-only (min −0.1460, median −0.0810, max
−0.0430); the blend's −0.0155 is merely less bad than every random
assignment. The blend's assignment matters, but it is worse than the value
arm's.

## What the arms say

Value-only is the best single arm: +0.0167 choosing Sharpe over the
installed baseline at 25 bp, but with a 0.94-point deeper drawdown and a
lower reported-window Sharpe (1.5217 against 1.6743). It is a real but
small improvement, below the pre-registered +0.05 margin, and it is not a
candidate. This arm also carries the registered double-counting risk: the
leader slot ranks value while the installed P/E `extra` tilt is still
applied, so the arm is two value exposures. Even doubled, value adds only
0.0167 Sharpe, which suggests the installed P/E tilt already captures most
of the value signal in this book.

The blend dilutes that value leg with the residual leg C1 showed to be
weak. It lands within 0.0012 Sharpe of the installed baseline and improves
the drawdown by only 0.23 points; it does not beat the best single arm. The
strength-zero decomposition is consistent: equal slots measure 0.6474
Sharpe, the installed tilt adds 0.0262, and the blend adds 0.0275 — the
blend recovers the installed tilt's gain, not more.

The 10 bp line is the strongest reported result: value-only measures 0.7501
Sharpe with a −32.03% drawdown, 0.0418 above the baseline's 0.7083 and 2.65
points shallower. It is reported, does not gate, and the primary cost is
25 bp; it does not rescue the arm. IT+Comm is also better for the blend
(+0.0853 Sharpe, +1.91 pp CAGR, 1.73 points shallower drawdown) on 16
names, does not gate, and is not a rescue.

## What this closes

C2 in `top-tier-algorithms-2026-10-28.md` is closed. The blend hypothesis
is not supported on the choosing window: value and residual momentum do
not combine into a better leader tilt than value alone, and value alone
does not clear the pre-registered margin at 25 bp. The next candidate is
C3, the 52-week-high proximity tilt, which is independent of both legs
tested here.

The pre-registration forbids retrying with a different blend weight,
strength, length, skip, beta lookback, value transform or window without a
new note saying what changed and why. No such retry is registered.

## Artifacts

- Runner: `/home/animallya96/dsv41/pit2/resid/blend_study.py`
- Payload: `/home/animallya96/dsv41/pit2/resid/blend_study.json`
- Engine: the C1 scratch copies `policy_book_resid.py` and
  `leader_resid.py`, unchanged; the production nightly never passes
  `leader_scores` and no bound source changed.
- Placebo seeds 20261028–20261227; runtime 288 s.
- The residual-only control reproduced C1's choosing line exactly
  (10.2836% / −33.4361% / 0.6607).

## References

- `docs/research/value-momentum-blend-preregistration-2026-10-28.md`
- `docs/research/residual-momentum-results-2026-10-28.md` for C1's failure
- `docs/research/pe-history-tilt-2026-10-24.md` for the installed P/E tilt
- `docs/research/top-tier-algorithms-2026-10-28.md`, candidate C2
- Asness, Moskowitz & Pedersen (2013)
