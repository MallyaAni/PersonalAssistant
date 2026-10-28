# Residual-momentum leader tilt: C1 result — 2026-10-28

**Status: FAILED the pre-registered gate at the primary arm. The arm is
closed and is not retried.** This is the result of
`residual-momentum-preregistration-2026-10-28.md`, run after the note was
committed. Nothing changes in the live rule, the board, or any prompt. The
live rule stays frozen through the 252-session review.

## The result

S&P 500 point-in-time, installed `Rule` (A entry, B hold, 1% minimum trade,
band block, 0.25 volatility target, 0.5 exposure floor, 25% cap, next-open
fills), 25 bp, choosing window 2016-2023. Only the leader score source
changed: the installed trailing 63-session return rank is replaced by the
rank of `baselines.residual_momentum(length=120, skip=21,
beta_lookback=120)`, mapped by the installed `1 + 0.5 * (2r/(n-1) - 1)`.

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| installed (baseline) | 10.6747% | −33.3296% | 0.6736 | 26.2893% | −19.1375% | 1.6743 | 14.2725% | 0.8842 |
| **R120 (primary)** | **10.2836%** | **−33.4361%** | **0.6607** | 22.2232% | −17.4098% | 1.5053 | 13.0547% | 0.8334 |
| R252 (sensitivity) | 10.5690% | −34.6443% | 0.6746 | 24.9561% | −18.1836% | 1.6646 | 13.8853% | 0.8768 |

| arm | choosing CAGR | choosing DD | choosing Sharpe |
|---|---:|---:|---:|
| installed at 10 bp | 11.5355% | −34.6861% | 0.7083 |
| R120 at 10 bp | 11.3136% | −32.3935% | 0.7211 |
| installed, IT+Comm | 8.9152% | −36.6600% | 0.5296 |
| R120, IT+Comm | 10.7031% | −33.9693% | 0.6063 |

Mean invested and mean names: baseline 0.9590 / 81.9, R120 0.9452 / 79.3,
R252 0.9349 / 75.6.

## The gate

| component | threshold | result | verdict |
|---|---|---|---|
| choosing Sharpe | ≥ 0.7236 (baseline + 0.05) | 0.6607, −0.0129 vs baseline | **fail** |
| choosing CAGR | ≥ 10.1747% (baseline − 0.5 pp) | 10.2836%, +0.11 pp above the floor | pass |
| choosing drawdown | ≥ −31.3296% and no deeper than −35% | −33.4361%, 2.1 pp deeper than the bar | **fail** |
| placebo | improvement > 95th percentile of 200 random tilts | −0.0129 > −0.0399 | pass |
| perturbation | scores before the cutoff unchanged | true | pass |
| off null | installed book reproduced exactly | all seven fields true | pass |
| score multiset | placebo preserves finite scores per session | true | pass |
| strength-zero | scores inert, equal slots | true | pass |

R120 fails two gate components: the Sharpe improvement is negative, and the
worst drawdown is deeper than the installed rule's, not 2 points shallower.
The conjunction fails, so the study stops.

The placebo pass is not evidence of a gain. All 200 random tilts lost Sharpe
relative to the installed rule (min −0.1117, median −0.0687, max −0.0228);
R120's −0.0129 is merely less bad than every random assignment. The placebo
asks whether the score's assignment matters at all, and it does, but the
assignment R120 makes is worse than the installed trailing-return one.

The strength-zero run decomposes the tilt: equal slots at the same rule
measure 0.6474 Sharpe and −34.9503% drawdown. The installed tilt adds
+0.0262 Sharpe over equal slots; R120 adds +0.0133. Residual momentum at
this horizon is a weaker tilt than the raw one, not a harmful one.

## The baseline path

The registered baseline reproduces the risk dial's 0.25/25 line exactly
(≤1e-9 on every window and metric) under the current hold-through
`event_risk.live_path`. A diagnostic run with the retired cut path pinned
fails reproduction: the choosing window is exact, but the reported window
differs by up to 4.9408e-3 in Sharpe. The risk dial's baseline was measured
on the hold-through path, which is the installed path after the FOMC
retirement candidate went live on 2026-10-28. The pre-registration's
"installed FOMC path" is that path, not the retired cut.

## What this closes

C1 in `top-tier-algorithms-2026-10-28.md` is closed. Beta-adjusting the
leader tilt at 120/21/120 does not improve the installed rule on the
choosing window; it lowers CAGR, lowers Sharpe and deepens the drawdown.
The 252-session horizon is Sharpe-neutral (+0.0011) and deeper in drawdown;
the 10 bp line is mildly better (+0.0128 Sharpe, 2.3 pp shallower drawdown)
but far below the +0.05 bar and does not gate; IT+Comm is better
(+0.0768 Sharpe, +1.78 pp CAGR, 2.7 pp shallower drawdown) on 16 names,
does not gate, and is not a rescue. None of the reported arms change the
stop.

The pre-registration forbids retrying with a different length, skip, beta
lookback, strength or window without a new note saying what changed and
why. No such retry is registered. The next candidate in the ranked list is
the next task, not a re-parameterization of this one.

## Artifacts

- Runner: `/home/animallya96/dsv41/pit2/resid/resid_study.py`
- Payload: `/home/animallya96/dsv41/pit2/resid/resid_study.json`
- Scratch engine: `policy_book_resid.py`, `leader_resid.py` (copies of
  `backend/market/policy_book.py` and
  `backend/market/grade_led_leader_policy.py` with the optional score
  argument); `smoke.py` passed before the study ran.
- Placebo seeds 20261028–20261227; runtime 355 s.
- The production nightly never passes `leader_scores`; the scratch engine
  is not merged and no bound source changed.

## References

- `docs/research/residual-momentum-preregistration-2026-10-28.md`
- `docs/research/top-tier-algorithms-2026-10-28.md`, candidate C1
- `docs/research/risk-dial-2026-10-28.md` for the baseline lines
- Blitz, Huij & Martens (2011); Daniel & Moskowitz (2016)
