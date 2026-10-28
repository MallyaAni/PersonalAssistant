# Chart-judgment entry timing: result (fails the pre-registered gate)

Pre-registration: [chart-judgment-preregistration-2026-10-27.md](chart-judgment-preregistration-2026-10-27.md),
frozen after the pilot (prompt sha d3517c2ff812). Evidence and code: `~/dsv41/vision/` on spark1
(`main.jsonl`, `score_main.log`, `runner.py`, `chartlib.py`, `labels.py`, tests).

## What ran
- 670 grade-A entries of the installed rule, 2016-02 to 2026-10 (pilot's 30 excluded); 666 scored
  (4 had no Alpaca bars at the time: DELL 2017-18, SMCI 2019).
- DeepSeek-V4.1-Flash-1017 saw daily, hourly and 15-minute charts (EMAs, support/resistance, session
  VWAP, extended and overnight hours shaded), cut at each checkpoint, anonymised and rebased, and
  answered under a strict JSON schema: buy_now, limit with a price, or wait.
- 1,978 checkpoints, 0 malformed answers. Fills: 529 regular hours, 110 pre-market, 15 overnight,
  12 after-hours; 541 limit fills, 125 market. It bought at the first checkpoint 194 times (median
  checkpoint 1); it never let the window run out.

## Gate
| Test | Result | Verdict |
|---|---|---|
| G1 mean improvement vs buying at the next open, after costs | +3.0 bp, 95% CI [-12.8, +16.7] | FAIL |
| G2 beats a placebo that shuffles its decisions across entries | +3.0 vs placebo 90th pct -3.7 (median -18.1) | pass |
| G3 positive in both halves | 2016-20 -4.7 bp, 2021-26 +9.0 bp | FAIL |

By year (bp): 2016 +6.8, 2017 +5.5, 2018 +1.9, 2019 -24.8, 2020 -6.2, 2021 +18.8, 2022 +38.3,
2023 -45.4, 2024 +6.6, 2025 -5.4, 2026 +57.4 (n 42, informational; the model's training cutoff is
not published). Mechanical comparators: a limit at session VWAP +5.0 bp, at the hourly EMA21 +5.2 bp.

## Reading
The model's timing is better than random timing with the same patience (G2), but no better than
simply buying at the next open, and no better than a mechanical limit at VWAP. The few basis points
are noise next to a typical 20-session move of ~220 bp. Entry timing is not where this rule loses
money, so the chart judgment is not adopted for entries. Per the rules, it is not retried without a
new pre-registration (e.g. exits, or using the judgment to skip entries rather than to time them).
