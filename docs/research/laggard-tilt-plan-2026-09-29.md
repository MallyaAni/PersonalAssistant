# One bounded portfolio test of the frozen sequence laggard

Written before this portfolio rule is run. This does not refit the model,
change the registered forward shadow, or authorise any live change.

## Why this specific test

Stage 3's post-hoc sequence laggard was more informative than its original
funded exclusion overlay. A full exclusion can create cash at the 20% name
cap; the executor can later buy an excluded name back. This test uses a
**partial reduction with stock recipients**, so neither a full exclusion nor
extra target cash is required. Its likely benefit is small; even the previous
frictionless full-exclusion ceiling was below the older selection floor on
2016–2023. One run settles whether the partial integration is worth further
attention. Do not tune the amount after reading it.

## Frozen rules

Compare `/4`, sequence tilt, and a fixed placebo tilt. Each reads the identical
point-in-time restricted report and the unchanged `profit_taking.control_options`.
No new mid-cycle sell rule, timing gate, live planner hook or cap increase.

At each allocator call, start from `/4`'s exact targets. Among positively
targeted names with finite sequence forecasts, require at least three. Reduce
the lowest-scoring name by **half its target**, limited to the recipients'
combined headroom. Distribute that amount to the other finite-forecast,
positively targeted names in proportion to their room under 20%. Missing
forecasts retain their baseline weight. If no room exists, return the exact
baseline. The sum of stock targets and target cash are unchanged. All ties use
existing ticker-column order. Grades and membership still govern eligibility.

Targets are consulted at scheduled resets and by the existing cash redeploy
path, as for the original stage-3 overlay. No assumption is made that changed
targets are already executed: actual funded fills and held weights decide P&L.
In particular, green-open suppression and existing breakout entries remain.

Placebo: identical reduction and redistribution, but choose the name by
SHA-256 of `laggard-placebo-7|date|ticker`, not by forecast. Keep the real
forecast's availability mask. This is one fixed control, not a random-seed
search. These are two additional evaluated rules in an already heavily searched
history, not fresh independent tests of the post-hoc discovery.

Inputs pinned:

- Existing trusted public report/cache:
  `dbe55808a0be2ea01932f5212da28cf72dffffa0fe3ea8b097727b304f8a8b91`.
  Restricted report, membership and frozen SPY/QQQ histories from the completed
  selective study. Reuse data only, never its rejected learner/strategy code.
- Existing walk-forward sequence forecasts:
  `c89f17f7f7e68639f30c05537daf7eeb55afb7a311290d315f1d34201cec2ff2`.

## Execution, evaluation and stop

20 start offsets, 10 and 25 bp one-way costs. Both funded stock variants,
unchanged `/4`, and funded buy-and-hold SPY and QQQ use matching calendars.
Report 2018–2023, 2024–2026 and full history separately, every annual block,
and descriptive causal SPY regimes (prior-close above/below trailing 200-day
mean; prior 20-session annualised volatility above/below 20%). Regime slices
show mean daily returns, not fictional standalone compounded portfolios.

Every stock account has a saved cash/fill/mark journal independently replayed
before its statistics are accepted. Report actual turnover/exposure and verify
all-zero targets or all-missing forecasts reproduce `/4`. Preserve all curves
and metadata.

Call the result RESEARCH_PROMISING, never PROMOTE, only if at 25 bp the
sequence tilt gains at least one CAGR percentage point over `/4` on 2018–2023,
beats it at 16/20 offsets, does not worsen median max drawdown by more than
one percentage point in either main window, has nonnegative paired mean return
in 2024–2026, and beats placebo's median CAGR in both windows. At the fixed
representative offset 10, require positive lower 95% paired-return benefit
under a 63-calendar-day block bootstrap (2,000 draws, seed 7) in 2018–2023.
Report 10-bp sensitivity; it cannot rescue a failed 25-bp verdict.

These are advancement screens, not multiplicity-adjusted proof after hundreds
of trials. All history is development evidence. A promising result still needs
independent evidence and live integration review; any failed criterion ends this
rule without a cap/size/threshold sweep. No automatic deployment.

Pre-result clarification: the validation shorthand originally said
"all-zero/missing forecasts", conflicting with the precise finite-score/tie
rule above. All-zero **targets** and missing forecasts are no-ops. Finite equal
scores, including zero, still select the first eligible column. The implemented
rule and running account code are unchanged; this clarification precedes reading
any historical return statistics.
