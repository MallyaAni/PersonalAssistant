# FOMC risk-window evaluation — September 13, 2026

The hypothesis is plausible, but no tested overlay is established as a superior live trading rule. The recent period improved under several windows, while every tested variant reduced total return over the 2021–2026 comparison. Automatic exposure changes remain disabled. The three-session conditional window is a candidate for forward testing, not a qualified replacement.

Kevin Warsh became chair on May 22, 2026. His June press conference and August remarks describe the change in forward-guidance policy. These facts establish the policy context; they do not prove that it caused equity selloffs. Sources: [Fed biography](https://www.federalreserve.gov/aboutthefed/bios/board/warsh.htm), [June meeting](https://www.federalreserve.gov/monetarypolicy/fomcpresconf20260617.htm), [August remarks](https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm).

## Measured result

Forty-eight unique comparisons cover four windows, unconditional and conditional variants, two cost assumptions, and three starting dates. Input cutoff: September 11. Code: `35ebc0f9`. All partition readers, including nested expectations-gap inputs, are bounded to that cutoff.

From May 22 through September 11, the baseline returned **0.74%**, with a worst drawdown of **8.44%**, at 10 bp per traded notional. There are only **two completed meetings**, June 17 and July 29. The sample also contains the incomplete lead-in to September 16.

| Pre-meeting sessions | Trigger | Total return | Change versus baseline | Worst drawdown |
| --- | --- | --- | --- | --- |
| 1 | Always | 1.12% | 0.37 pp | 7.49% |
| 1 | SPY weakness | 1.17% | 0.43 pp | 7.49% |
| 3 | Always | 1.09% | 0.35 pp | 5.99% |
| 3 | SPY weakness | 1.09% | 0.35 pp | 5.99% |
| 5 | Always | 1.13% | 0.38 pp | 6.61% |
| 5 | SPY weakness | 1.13% | 0.38 pp | 6.61% |
| 10 | Always | 1.44% | 0.70 pp | 5.80% |
| 10 | SPY weakness | -1.22% | -1.96 pp | 7.86% |

At 25 bp costs, the three-session conditional variant returned **0.87%**, versus **0.62%** for baseline, with **6.02%** versus **8.46%** worst drawdown. In the longer 2021–2026 comparison at 10 bp, its simulated CAGR fell from **43.39% to 41.71%**, and drawdown worsened from **33.20% to 34.41%**. Those high historical growth rates are results on this selected universe and revised inputs, not forecasts.

Starting after the June announcement instead, that variant improved total return by **1.94 percentage points** at 10 bp and **1.83 points** at 25 bp. This slice has only **one completed meeting**. Changing the start changes the account's holdings and rebalance clock because each simulation starts in cash; these are alternative inception scenarios, not independent experiments.

## What was implemented

- Published NYSE holiday counts replace the incorrect future-event array clipping. September 16 is three sessions after September 11; a far-future date does not trigger the same warning. Unknown calendar coverage stays unknown.
- Configurable 1/3/5/10-session pre-meeting windows cut exposure to 50%, through the decision session, then restore at the next open.
- The conditional version waits for a negative five-session SPY move and stays reduced through the event, avoiding repeated cutting and restoring on one-day rebounds.
- The existing simulator handles share quantities, actual next-open prices and traded-notional costs. Event changes explicitly execute at the next open even if it is green; other trades follow LIVE_POLICY.
- No live planner imports the event overlay. This is research implementation, not automated order execution or a deployed shadow-account ledger.

The older calendar includes unscheduled 2020 actions and lacks point-in-time cancellation metadata; using those dates before the event would introduce lookahead. This comparison starts in 2021. [Fed 2020 calendar](https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm)

## Verification and limits

VERIFIED: 454 market/trading tests passed before two additional invariants were added; all six event-risk tests then passed, including no future-price influence, one cut and one restoration, costs, no change to LIVE_POLICY with unit scale, and a nested-reader cutoff test. Both pinned research runs completed; all 48 unique comparison rows are in [the JSON evidence](fomc-window-evaluation-2026-09-13.json).

UNVERIFIED: a profitable forward edge, causal attribution to the guidance change, live order lifecycle for the overlay, tax effects, a full spread/market-impact model, and results after the staged earnings-data correction. Existing historical-universe and financial-extraction limitations prevent calling the simulation production-grade investment proof.

Reproduce with `python -m backend.cli.market_fomc --asof 2026-09-11` and repeat with `--since 2026-05-22`. These are read-only evaluations. No real-money order was submitted, and no historical decision was rewritten.

