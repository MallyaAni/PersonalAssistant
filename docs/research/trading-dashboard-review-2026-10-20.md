# Trading dashboard review against the stated goal — 2026-10-20

Reviewed at `f345e395` (main after the trading session's merge of 2026-10-20).
Method: two independent code reads (decision logic; dashboard and chart), then
the load-bearing claims re-verified by hand in `strategy_model_history.py`,
`strategy_entries.py`, `execution_quotes.py`. Line numbers are from that commit.

**The goal, verbatim:** "the trading dashboard would show realtime suggestions
for stocks whether to buy, sell or do nothing along with the position size for
that action. On each ticker there would be a chart that displays these
suggestions as if they were replayed in the past at that moment without having
known the price action prior to that time so that i can visually validate".

## The one-paragraph verdict

The live side exists and is sound in structure: a nightly publication
(`desk/strategy-recommendations/latest.json`) carries per-name target weights
from the grade-led policy, and a 15-minute engine turns those into Buy / Sell /
Wait rows with a trade size. The validation side does not yet do what the goal
says. The chart's historical markers come from a replay that uses *today's*
fitted sizing and timing models on past dates (the contract note of
2026-10-13 says so in its own words: "trained later ... retrospective
current-model simulation, not ... out-of-sample evidence"), with no membership
mask, so it shows what the current model would have done knowing the future's
parameters, not what a model fitted at that moment would have done. Visually
validating on that chart validates the wrong thing. Everything else below is
secondary to fixing that.

## What is right

- A single current-recommendation object with provenance: `strategy_publication.build`
  (`backend/market/strategy_publication.py:96-157`) writes version, session,
  `as_of`, `valid_until`, receipt hash, per-name `target_weight` and evidence.
- Decisions at candle close fill at the *next* open, both live and in replay
  (`strategy_model_history.py:160-168`; `simulate.py:1821`); grade exits happen
  at the next day's open from `grades[day-1]`. Same-bar execution is ruled out.
- Trailing-only features (`levels.py`, `bands`, regime percentiles), as-of
  fundamentals keeping the earliest-filed version (`fundamental_features.py:158-202`),
  tone aligned at `reaction_date` forward (`language.py:325-340`), holiday-aware
  calendar. The classic leaks are handled.
- Staleness is modelled: `valid_until` on every row, `/desk/live` marks stale
  after 900 s, an expired publication reads as `unavailable`.

## Defects (fix these first)

1. **The replay is in-sample for every date before 2026-08.** `replay()`
   (`strategy_model_history.py:88-91`) calls `targets_from_model(report,
   policy.reader, ...)` with the frozen current reader, and timing uses the
   frozen current probability model; `daily_arithmetic_bridge.FREEZE =
   2026-08-17`. The affine bridge already refits monthly
   (`daily_arithmetic_bridge.py:275-300`); the sizing head and the timing
   model do not. Until they are refit walk-forward (or the chart says
   "in-sample" on every marker before the fit date), the chart cannot be used
   for validation. This is the gap between the goal and the build.
2. **No point-in-time universe in the replay.** `replay()` trades every panel
   name except SPY/QQQ (`:68`) and takes no membership mask;
   `point_in_time.py` exists precisely because the authors measured 42.3% CAGR
   on today's book against 18.8% point-in-time (`docs/research/pit-scorecard-2026-09-26.md`).
   Product A (`decision_history.target_matrix`) masks targets but not grades.
   Add a mask parameter and refuse unmasked input.
3. **Price-basis mixing in the replay, untested.** Shares are valued at
   `panel.adj_close[day-1]` (`:85-88`) but grade exits sell at `panel.open[day]`
   (`:121-128`) and entries fill at `execution_opens`, with no `session_scale`.
   If the producer passes raw opens next to adjusted closes, a split (NVDA
   2024, 10:1) misprices the book by 10x on that day. The unit test uses
   `adj_close == open == 100` throughout (`test_strategy_model_history.py:20`),
   so this is not covered. Either assert one basis at the boundary or scale
   explicitly as `simulate.py:40-45` does.
4. **Two chart histories, one vocabulary.** The Paper view's "Policy replay"
   layer draws `history/{ticker}.json`, a replay of the retired
   `graded-equal-weight/5` policy (`decision_history.py:63`,
   `ticker_chart_intraday.py:143-180`), while the Stocks view draws the
   grade-led simulation. Same colours, same words. Hide the layer when
   `history.policy != latest.policy`, or regenerate it under the live policy.
5. **A Buy size is visible for at most 30 seconds.** `valid_until =
   min(candle + 15 m, quote_at + 30 s)` (`strategy_entries.py:193`,
   `execution_quotes.MAX_AGE_SECONDS = 30`) while the page polls every 20 s
   (`DeskPanel.tsx:74, 1339`) and flips `now` on a timer (`:1365`). The size
   and the action blink to `—`/`Wait` between polls. Keep the last row with
   "as of hh:mm:ss, refreshing" until replaced, or make the quote validity at
   least the poll interval.
6. **16:00-19:30 ET blackout reads as a failure.** `valid_until` is the next
   session's close (`live_model_decision.py:255-272`), so after the close
   every row is `Unavailable` with "Refresh to retry" (`SignalBoard.tsx:405`)
   until the nightly publishes. Add `status: awaiting_nightly` and
   `next_publication_at` to `/desk/model-allocation` and say so.
7. **The live decision is mostly not on the chart.** A current marker is
   drawn only for a non-reference-format Buy in `execute`
   (`TickerChart.tsx:373`, `SignalBoard.tsx:178`); the reference format
   (`strategy-numerical-entries/2|3`) never draws, and Sell / Wait never draw.
   The chart should always carry the current call at its right edge.
8. **Replay rows without `valid_until` vanish on 15 m** (`TickerChart.tsx:384`);
   fall back to `at + 15 m`. Grade changes on the daily chart land on the
   decision date's own candle (`:309`) although the backend stamps them
   `next_open` — on the daily view they look known a day early.
9. **Live week-end detection differs from history**
   (`technical.py:178-181`): a Thursday before a holiday closes the week in
   the historical panel but not live. Small, but it is exactly the kind of
   live-vs-replay divergence the chart is supposed to rule out. Use the
   exchange calendar, which knows the next session in advance.
10. **Live and research grades use different fundamentals** (`current` vs
    `corrected`, `grade_parity.py:24-33`). Pick one.

## Design gaps against the goal

- **"Position size for that action" is a model-book percentage, not a size
  for the owner's account.** `targets_from_model` sizes a unit-capital book
  with `CAP = 0.25` and no equity, cash buffer or per-name risk
  (`adaptive_growth_policy.py:680-765`; publication says
  `account_basis: "no_account_inputs"`). Sells from `grade_led_policy.signals`
  carry no size at all; a sell size exists only as the reference-book delta
  in `strategy_reference_transition.project`. The dashboard should show one
  number the owner can act on: shares or dollars for *their* account, derived
  from the weight and the account, with the weight as the explanation.
- **"Do nothing" is five different things.** `Hold`, `Avoid`, `Wait`,
  `Unavailable`, `—` appear depending on format branch (`SignalBoard.tsx:243-278`).
  The goal names one neutral state. Collapse to `Do nothing` with a reason
  code (`at_target | no_allocation | grade_below_A | awaiting_candle |
  publication_expired`) shown beside it.
- **Three grade paths, five verdict surfaces.** Nightly grade, `/desk/live`
  re-grade, timing `prior_grade`; and on screen SignalBoard Action, TradeBoard
  Action, "Current chart judgment" (`currentRanking.ts:7-27`, a separate
  engine), OpportunityCard 0-10 and the letter grade. They can disagree for
  one name and nothing says which one is the call. Make the SignalBoard row
  the only verdict; demote the rest to an "Evidence" fold.
- **No confidence reaches the row.** The optimiser's
  `estimated_positive_return_probability` and the timing engine's
  `waiting_log_utility` stay inside the receipt (`strategy_publication.py:134-140`).
  Surface both; they are what lets a person weigh a 2% buy against a 6% one.
- **Nothing on screen names the policy or the sample.** `simulation.policy`
  is under a nested `<details>` (`TickerChart.tsx:1476`); there is no
  in-sample / out-of-sample marking anywhere in the frontend. Once defect 1
  is fixed, the chart needs a legend: policy id, replay window, fit date, and
  a visual difference between replayed, recorded-live and current markers
  (today all are the same filled circle, `:395-397`).
- **Replay vs recorded is the same marker.** Recorded live publications
  (`strategy_entry_history`, true point-in-time by construction) are merged
  into the same circle as replayed ones (`:389-395`). The recorded series is
  the honest validation set that grows every day; draw it hollow and keep it
  distinct.
- **LLM tone hindsight is unmeasured.** Releases back to 2018 were re-scored
  in September 2026 by a model that knows how those companies did
  (`data_vintage.py:1-45`). Re-score a sample with dates masked and compare
  stance agreement; if it moves grades, freeze tone to the model vintage.

## What the per-ticker view should look like

```
NVDA   $182.31 IEX 10:45:09 ET (fresh)                     [15m][D][W]
+-- NOW ------------------------------------------------------------------+
| BUY 2.4% of capital = 13 sh ($2,370)  -> position 8.0%                 |
| since 10:45:12 ET  valid to 11:00 ET  grade A (10-19 close)             |
| state: EXECUTE   (alternatives: WAIT / DO NOTHING: at target / EXPIRED) |
+-------------------------------------------------------------------------+
[ candles ............................................................ now ]
   * B 3.1%      * S 1.2%     o B 2.0% (recorded)   ^ A->B        <> BUY 2.4%
legend: * replay, walk-forward fit  o recorded live  <> current  ^ grade change
footer: grade-led-learned-sizing/1 · replay 2019-03 -> 2026-10 · next publish 19:30 ET
```

Markers before the walk-forward fit boundary (today: everything) must be
shaded or hidden until defect 1 is done; otherwise the legend would be lying.

## Suggested order of work

1. Walk-forward refit of sizing and timing in `strategy_model_history` (or an
   honest in-sample label per row) and the membership mask — this is the
   goal. 2. Price-basis assertion in `replay()` with a split in the test.
3. The three UI defects that make the live side look broken (30-second size,
   post-close blackout, current call not drawn). 4. One verdict surface, one
   "do nothing", account-sized action, confidence on the row. 5. Policy and
   sample legend on the chart; recorded-live markers kept distinct.

Also fixed on the way (not part of this review): three trading tests imported
siblings by bare module name and could not be collected by `deploy.sh`'s gate
(`009d5c87`).
