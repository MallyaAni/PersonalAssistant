# Volatility targeting of the book (B1): gross exposure scaled to a fixed volatility. Pre-registration (2026-10-01)

**Status: registered before any code or number.** Queue item B1 of
[the survey](sota-survey-2026-10-01.md). This is the first candidate
aimed at the book's worst drawdown (−43% on 2016-2023, −25% on
2024-2026) rather than its return.

## The question

Moreira and Muir (2017) scale exposure by the inverse of recent variance;
Cederburg et al. (2020) showed the real-time version does not help; Xu
(2024) shows a *constant* volatility target (12% a year) with two
conditional switches adds 0.20 of Sharpe out of sample on momentum-type
factors and survives 40 bp of costs. Does scaling this concentrated,
momentum-tilted long book to a fixed volatility lower its drawdown
without giving up the return that makes it worth running?

## What is known before this note (disclosed)

- Name-level volatility sizing lost (`vol-sizing-2026-09-27.md`, every
  variant); stops lost (`catastrophe-stop-2026-09-27.md`). Those scale
  *names*; this scales the *book* and holds the names' relative weights.
- The book's realised volatility is high (CAGR 28-47% with −43%/−25%
  drawdowns); a 12% target would hold it mostly in cash, which is why
  the targets below are the book's own scale.
- `graded-equal-weight/5` runs at gross 1.0; the simulator and
  `market_pit_scorecard` already price a gross below 1 as cash.

## The rule

gross(t) = min(1, σ* ÷ σ̂(t)), where σ̂(t) is the annualised standard
deviation of the book's own daily returns over the last 20 sessions
(the simulated book at gross 1, known at the close of t−1), applied to
the next session's targets; weights are the policy's, scaled. Cash earns
nothing. Trades from rescaling pay the same 25 bp. Three targets, fixed
now: **σ* = 20%, 25%, 30%** a year. Reported, deciding nothing: 15%, a
60-session σ̂, and Xu's two switches (gross 0 when the trailing 120-session
book return is negative; no scaling when the trailing risk-return
intercept is negative).

## Criteria, fixed now

A target **REPLACES** gross 1.0 if, on the median of 20 offsets, the
worst drawdown falls by at least 5 points on **both** windows while the
CAGR falls by at most 3 points on each, **or** the Sharpe ratio rises by
0.15 on both windows with the drawdown not worse; and the paired daily
difference against the control is not negative at NW t ≤ −2 on either
window; deflated Sharpe at the cumulative count ≥ 0.95 is reported but,
for a drawdown rule, does not decide. The null test: σ* = ∞ reproduces
the control bit for bit. Anything else is **RECORD**.

## Trials and prior

Three trials; cumulative 471 → 474. Prior: 40% that a target clears the
drawdown criterion, 10% the Sharpe criterion. The likely finding is that
the 2020 and 2022 drawdowns shrink and 2023-2024's recovery is partly
missed; the operator decides whether that trade is one he wants, which is
why the criterion is written as a trade and not as a return floor.

## Order of work

1. This note, committed and pushed. 2. Build with tests: a `--gross-target`
option on `market_pit_scorecard` (the scaling applied in the simulator's
walk, σ̂ from the simulated path so it is point-in-time), the null test,
payload fields for the drawdown path, the verdict, an independent check.
3. Run on spark1 (CPU). 4. Write-up, report.
