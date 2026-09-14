# Next technical-timing evaluation

Recorded September 13, 2026, before running the portfolio experiment below.
This is an evaluation plan, not an enabled trading policy or a measured result.

## Question

Can technical exits followed by confirmed re-entry improve the current funded
strategy after costs, without relying on the hindsight available in last week's
A+ audit? The prior single-position study found that the tested EMA rules
filtered losses but also delayed HPE and sold before its recovery. It omitted
re-entry, competition for capital and the multiweek holding period.

## Keep the comparison controlled

Use identical initial cash, saved decision availability, universe, allocation
limits, rebalance clock and FOMC lifecycle in every arm. Test three arms:

1. The current production execution policy as the baseline.
2. Baseline entries plus the already specified technical structure exit and
   re-entry on recovery of that structure.
3. The already specified confirmed pullback entry plus that same exit/re-entry.

Retain the production daily Bollinger-rejection buy blocker in every arm.
Use the existing EMA periods and completed daily/hourly/15-minute readings.
Do not search for a better period or profit percentage on these outcomes.
The exit requires both completed 15-minute and hourly closes below EMA21.
Re-entry requires those closes to recover above EMA21, a bullish 15-minute
candle and the previously defined daily trend alignment. Require an intervening
flat state and a new completed signal; an old signal cannot re-enter immediately.
Re-entry remains bounded by current allocation eligibility and the FOMC cap.

## Execution and funding

**Known baseline limitation, reproduced before this experiment:** the current
`_Book._fill` allows negative cash. Starting with $100, filling one share at
$120 with 10 bp costs leaves **−$20.12**. This was observed against live backend
`84d07faf` on September 13 and is pinned by the strict expected-failure test
`test_trading_execution_funding.py`. The existing split-price fill also nets
opening purchases with closing proceeds without an intraday funding ledger.
Fix and evaluate that boundary first; do not score new timing rules against an
unqualified cash-only baseline. If borrowing is intentionally modeled instead,
it must have explicit limits and financing costs, and be labeled as leverage.

The unchanged current-policy replay was also measured through September 11,
2026, starting January 1, 2021: **220 of 1,429 sessions** ended with negative
cash; peak gross exposure was **131.7917% of equity**. The lowest cash balance
was −1.219944 in units of the initial equity (the simulator starts at 1.0,
not $100,000). This is end-of-day evidence; it does not capture potentially
larger intraday borrowing before closing sales. The run used 10 bp costs,
`LIVE_POLICY`, `event_risk.live_path`, and `event_lifecycle=True` on an
asof-bounded `ResearchStore`. It did not place trades or change live settings.
No claim about cash-constrained returns follows from this leveraged replay.

Executed simulator SHA-256:
`712219fb1b0b59e249f1695fecb6d4842dff9a034013ed62dace22a22a9512ee`.
Research-store CLI SHA-256:
`060f66429724c4af64e6036a0c6798c9baadeb9a10de60dd5d6f1f32ac02dfb6`.
The diagnostic source and result are retained under `/tmp/desk-funding-diagnostic*`
on Spark1. Its first host attempt lacked isolated settings; the second imported
an unrelated `/tmp/timeit.py`; supplying test-only settings and using Python
safe-path mode resolved those environment issues. The final run exited zero.

- A signal becomes actionable only when its candle and all longer-timeframe
  inputs are complete. Fill at the following eligible bar, never retrospectively
  at that signal's close or at a favorable price inside its high/low range.
- Process a chronological ledger of cash and whole shares. Charge traded
  notional, bound buys by available cash and preserve price-unavailable holdings.
  A planned closing sale cannot fund a purchase earlier that day.
- Preserve the baseline's actual opening/closing and green-day rules. The
  experimental technical exit is a separate reason; specify its interaction
  with those rules before running. For these arms, a confirmed technical exit
  executes next bar independently of the ordinary rebalance green-day hold.
- Event reductions retain priority. A technical recovery cannot restore shares
  forbidden by an active event cap or replay an already filled event order.
- Compare the entire funded portfolio, including cash and names that never
  enter. Do not average only the trades that happened to fill.
- Evaluate the same arms at 10 and 25 bp per side. These are cost assumptions,
  not estimates of executable spread; also report the separate observed paper
  decision-price drift when new durable receipts become available.

## Evidence boundaries

Freeze the input hashes, data revisions, signal specification and code revision
before each run. Exclude any input published after its simulated decision.
Saved live records beginning September 4 are the actual decision replay;
earlier reconstructed grades are a separate historical simulation, with their
point-in-time coverage and fixed-universe selection bias disclosed.

Last week's observations are development evidence, not a holdout. Keep later
saved decisions untouched while building the evaluator. The first report on
those decisions must identify every arm, costs, missing data, filled and missed
signals, equity, drawdown, turnover, time in cash and event exposure. A short
forward period is an interim result, not sufficient evidence to promote a rule.

Separate post-guidance FOMC evaluation on a continuous account, as the current
policy does. Do not restart cash or the rebalance clock at the split, and do not
attribute historical returns to a guidance regime that did not yet exist.

## Before considering adoption

Prove no future-candle influence, no spending of future sale proceeds, no
duplicate same-signal re-entry, conservation of cash/shares after costs, and
FOMC priority with persisted partial fills. Compare complete portfolio paths,
not one favorable stock or a single terminal return. Report return versus
drawdown and turnover explicitly; fewer losing trades is not itself a gain.
Any further parameter changes make another development experiment and require
fresh forward evidence. No candidate is promoted merely for winning this sample.
