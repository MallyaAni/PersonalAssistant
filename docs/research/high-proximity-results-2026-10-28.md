# 52-week-high proximity tilt: C3 result — 2026-10-28

**Status: FAILED the pre-registered gate. The arm is closed and is not
retried.** This is the result of `high-proximity-preregistration-2026-10-28.md`,
run after the note was committed. Nothing changes in the live rule, the
board, or any prompt. The live rule stays frozen through the 252-session
review.

## The result

S&P 500 point-in-time, installed `Rule` (A entry, B hold, 1% minimum trade,
band block, 0.25 volatility target, 0.5 exposure floor, 25% cap, next-open
fills), 25 bp, choosing window 2016-2023. The installed P/E `extra` tilt is
kept in every arm; only the leader score source changes.

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline (installed) | 10.6747% | −33.3296% | 0.6736 | 26.2893% | −19.1375% | 1.6743 | 14.2725% | 0.8842 |
| **high only (primary)** | **10.2438%** | **−32.6553%** | **0.6674** | 23.4748% | −17.7688% | 1.6308 | 13.2995% | 0.8611 |
| reverse high (placebo) | 11.1636% | −34.6002% | 0.6966 | 21.2459% | −16.8154% | 1.4800 | 13.5357% | 0.8507 |
| high + residual blend | 10.3907% | −34.0137% | 0.6622 | 24.0666% | −17.7547% | 1.6061 | 13.5385% | 0.8542 |

| arm | choosing CAGR | choosing DD | choosing Sharpe |
|---|---:|---:|---:|
| baseline at 10 bp | 11.5355% | −34.6861% | 0.7083 |
| high at 10 bp | 11.2158% | −34.6022% | 0.7107 |
| baseline, IT+Comm | 8.9152% | −36.6600% | 0.5296 |
| high, IT+Comm | 8.8118% | −34.4963% | 0.5325 |

Mean invested and mean names: baseline 0.9590 / 81.9, high 0.9521 / 78.7,
reverse 0.9205 / 78.9, blend 0.9518 / 78.6.

## The dispersion diagnostic

Read before any arm, as registered. The cross-sectional interquartile range
of `H` among members was 0.1203 at the median, 0.0745 at the 10th
percentile, 0.0481 at the minimum and 0.2624 at the maximum over 2,013
choosing sessions; 0.10% of sessions (2 of 2,013) fell below 0.05. The
median is well above the fixed 0.05 floor, so the rank is not noise and
the study proceeded. The median member sat at 0.9137 of its 52-week high.

## The gate

| component | threshold | result | verdict |
|---|---|---|---|
| choosing Sharpe | ≥ 0.7236 (baseline + 0.05) | 0.6674, −0.0062 vs baseline | **fail** |
| choosing CAGR | ≥ 10.1747% (baseline − 0.5 pp) | 10.2438%, +0.07 pp above the floor | pass |
| choosing drawdown | ≥ −31.3296% and no deeper than −35% | −32.6553%, 1.33 pp deeper than the bar | **fail** |
| reverse arm | improvement > reverse's improvement | −0.0062 vs +0.0231 | **fail** |
| placebo | improvement > 95th percentile of 200 random highs | −0.0062 > −0.0216 | pass |
| perturbation | high and blend scores before the cutoff unchanged | true | pass |
| score identity | every finite cell equals close / trailing max | true, 0 bad cells | pass |
| reverse identity | reverse is exactly `1 - h` | true | pass |
| off null | installed book reproduced exactly | all seven fields true | pass |
| score multiset | placebo preserves finite scores per session | true | pass |
| strength-zero | scores inert, equal slots | true | pass |

The high-only arm fails three components: it is 0.0562 Sharpe below the
+0.05 bar, its drawdown is 1.33 points deeper than the 2-point improvement
bar (though 0.67 points shallower than the installed baseline), and the
reverse-high placebo beats it by 0.0293 Sharpe. The conjunction fails, so
the study stops.

The placebo pass is again not evidence of a gain. All 200 random high
tilts lost Sharpe relative to the baseline (min −0.0851, median −0.0485,
max −0.0039). The high arm's −0.0062 is worse than every random assignment
in the top 5% of the distribution and worse than the best draw, −0.0039.
Its assignment matters, but it is worse than the installed tilt.

## What the arms say

The proximity tilt is the weakest of the three arms at 0.6674 choosing
Sharpe. It does improve the drawdown slightly (−32.6553% against
−33.3296%), but only by 0.67 points, one-third of the registered bar, and
it gives up 0.43 pp of CAGR. The reported window is worse on every metric:
1.6308 Sharpe against 1.6743, 23.47% CAGR against 26.29%, and a shallower
drawdown that does not compensate. This is a consistent loss, not a
trade-off the gate should accept.

The reverse arm is the finding. Ranking the names farthest from their
highs first earned 0.6966 choosing Sharpe, +0.0231 over the installed
rule and +0.0293 over the proximity arm; it also earned the deepest
choosing drawdown of the arms (−34.6002%) and the worst reported-window
Sharpe (1.4800 against 1.6743). In the choosing window this book rewarded
distance from the high, not proximity — the opposite sign to George &
Hwang. The pre-registration treats that as a stop condition, not a
candidate: the reverse arm was a one-run directional placebo, its
reported-window result is poor, and a sign that flips between windows is
not a sizing signal. It is not retried and not promoted.

The blend with the C1 residual leg is the worst arm (0.6622), consistent
with C1's failure: adding a weak residual score to a weak high score does
not produce a better leader reading.

The strength-zero decomposition is consistent. Equal slots measure 0.6474
Sharpe; the installed tilt adds 0.0262, the high tilt adds 0.0200, the
reverse tilt adds 0.0493, and the blend adds 0.0149. The installed tilt
remains the best of the registered tilts on the choosing window.

The 10 bp line does not rescue the arm: the high tilt measures 0.7107
against the baseline's 0.7083 (+0.0024), well inside the noise the gate
was designed to reject. IT+Comm is flat (+0.0030 Sharpe, −0.10 pp CAGR,
2.16 pp shallower drawdown on 16 names), does not gate, and is not a
rescue.

## What this closes

C3 in `top-tier-algorithms-2026-10-28.md` is closed. The 52-week-high
proximity hypothesis is not supported on the choosing window: the tilt
lost Sharpe, missed the drawdown bar, and was beaten by its own reverse.
The reverse result is recorded as a negative finding about this book, not
as a new candidate. The next research slot is C4, the SUE coverage audit;
C5, the sector-rotation sleeve, remains an owner decision and is not
spliced into the AI book.

The pre-registration forbids retrying with a different high window (251,
252 or 253 sessions), a different high definition (intraday versus close),
a different blend weight, strength, dispersion threshold or window
without a new note saying what changed and why. No such retry is
registered.

## Artifacts

- Runner: `/home/animallya96/dsv41/pit2/resid/high_study.py`
- Payload: `/home/animallya96/dsv41/pit2/resid/high_study.json`
- Engine: the C1 scratch copies `policy_book_resid.py` and
  `leader_resid.py`, unchanged; the production nightly never passes
  `leader_scores` and no bound source changed.
- Placebo seeds 20261028–20261227; runtime 381 s.
- A first attempt stopped on a broadcast bug in the dispersion median
  line, before any arm was read; the fix touched only that diagnostic
  line. The score, arms, gate and thresholds are exactly as registered.
- The baseline reproduced the risk dial line exactly and the off null
  reproduced the installed book on all seven fields.

## References

- `docs/research/high-proximity-preregistration-2026-10-28.md`
- `docs/research/residual-momentum-results-2026-10-28.md` for C1's failure
- `docs/research/value-momentum-blend-results-2026-10-28.md` for C2's
  failure
- George & Hwang (2004), "The 52-Week High and Momentum Investing",
  Journal of Finance
- Bhootra & Hur (2013), "The Timing of 52-Week High Signals", Journal of
  Banking & Finance
- `docs/research/top-tier-algorithms-2026-10-28.md`, candidate C3
