# Pre-registration: chart-judgment entry timing (multi-timeframe screenshots, local vision LLM)

Written 2026-10-27 before any model call on test data. Nothing below changes after the pilot except
the items marked "frozen after pilot", whose final hashes are appended at freeze time.

## Question
When the installed grade-led rule opens a position (grade turns A), can the local vision model
(deepseek-v4.1-flash-1017, :8000), looking at daily / hourly / 15-minute charts cut at the moment of
decision, choose a better moment and price to buy than the rule's next regular open - around the
clock (overnight 20:00-04:00 ET, pre-market 04:00-09:30, regular, after-hours 16:00-20:00)?

## Sample
- Entries: every BUY with before == 0 in the installed replay
  (research/policy-replay/leader_ewma_minB_floor50/2026-10-23, 95 names), decided on or after 2016-02-01.
- Pilot: 30 entries drawn with numpy default_rng(7) from entries decided 2025-01-01..2026-10-23.
  Used only to debug renderer, prompt and parsing; EXCLUDED from every gate statistic.
- Bars: Alpaca 15Min, split-adjusted. SIP 2016-01-01.. (04:00-20:00 ET); BOATS 2024-09-16..
  (20:00-04:00 ET). Daily context from the same 15m bars (regular session 09:30-16:00) plus the
  deploy store's daily bars for history before 2016 where needed.

## Decision clock (ET)
- Signal: trade.decided = session t (grade computed from the close of t). Baseline A fills at the
  first regular 15m bar open of t+1 (09:30).
- Checkpoints for arm B, from day t: 20:00 (only nights with BOATS data), 04:00, 09:45, 11:00, 13:00,
  15:00, 16:15, repeating through the 16:15 checkpoint of session t+5 (window = 5 sessions).
- At checkpoint T the model sees only bars whose end time <= T.

## What the model sees (anonymised)
Three PNG charts, no ticker, no calendar dates, prices rebased so the last close before T = 100:
1. Daily, ~250 completed sessions + today's partial candle: candles, volume, EMA 9/21/50/200,
   20-session and 252-session high/low, confirmed swing-pivot support/resistance lines
   (5 bars each side, confirmed only once the 5 later bars exist before T).
2. Hourly from the 15m bars incl. extended/overnight (~15 sessions): candles, EMA 21/50, the same
   S/R lines, non-regular sessions shaded.
3. 15-minute, last 3 trading days incl. extended/overnight: candles, session VWAP anchored at 04:00 ET
   (20:00 for the overnight session), EMA 9/21, non-regular sessions shaded.
Text: the current session name and time of day, that a fundamental/technical grade has just turned
this stock into a buy candidate, how many checkpoints remain, its own previous decision in this
window, and the per-session cost. Output JSON: {"action": "buy_now"|"limit"|"wait", "limit": price on
the rebased scale or null, "reason": short}. Temperature 0, max_tokens 600 (frozen after pilot).

## Fill simulation (arm B)
- buy_now: fills at the open of the first bar starting at or after T.
- limit: live until the next checkpoint; fills on the first bar starting >= T whose low is strictly
  below the limit, at min(bar open, limit). Re-decided at every checkpoint.
- wait: nothing.
- Window ends unfilled: B-forced buys at the close of the last regular bar of session t+5.
- Costs (one side, bp): regular 5, pre-market/after-hours 15, overnight 30. A pays 5.

## Primary statistic
Per entry: improvement_bp = 1e4 * (ln P_A - ln P_B) - (cost_B - cost_A) for arm B-forced.
(Both arms hold to the same later date, so the difference in outcome is exactly this.)

## Gate (all three must pass)
- G1: mean improvement > 0 and the month-block bootstrap (2000 draws) 95% CI lower bound > 0.
- G2: placebo. For each of 50 seeds, every entry is given another random entry's decision sequence,
  expressed relative to the then-current price (action, limit offset as % of the last close, by
  checkpoint index), and filled on this entry's bars with the same rules and costs. B's mean must
  exceed the 90th percentile of the 50 placebo means. This keeps the mix of waiting and limit
  depth and removes only the chart-specific information.
- G3: mean improvement > 0 in both 2016-2020 and 2021-2026 separately.

## Reported, not gated
- B-veto: entries B never fills; their 20- and 60-session forward returns from A's fill vs the filled
  ones (does "don't buy yet" avoid losers?).
- 2026 entries and post-2026-07-01 entries separately (the model's training cutoff is not published;
  anonymisation is the primary leakage control, a late-sample check the secondary).
- Fill timing by session (overnight / pre / regular / after), share of limit vs market fills.
- Two mechanical comparators: limit at session VWAP, limit at the hourly EMA21, each re-placed at
  every checkpoint with the same fills and costs.

## Look-ahead controls
- Renderer test: perturbing every bar after T leaves the three PNGs byte-identical; perturbing a bar
  before T changes them.
- Prompt test: no ticker, no year, no date string, no absolute price in the prompt text or image
  metadata.
- Fill test: a decision at T can only fill on bars starting >= T.

## What passing buys
Only the next step: an account-level replay through policy_book with B's fills, then a forward
shadow on live data. No live change on this result alone.

## Clarification, 2026-10-27, before any model call (implementation detail, no change of intent)
- The window's last checkpoint is 15:00 ET of session t+5; its order lives until that session's
  regular close (16:00), where B-forced buys at the close if still unfilled. "Through the 16:15
  checkpoint of t+5" above should read "through the 15:00 checkpoint of t+5": a 16:15 check after the
  forced close would be meaningless.
- The 20:00 checkpoint exists from 2024-09-16 (first BOATS overnight bar in the data), not on earlier nights.
- A decision whose interval until the next checkpoint has no bars (thin early extended hours) simply
  does not fill; the next checkpoint decides again.
- An unparseable reply counts as "wait" and is recorded with its raw text.

## Amendment, 2026-10-27, before any model call: structured labels
- The reply is decoded under a strict JSON schema (labels.DECISION_SCHEMA): a discriminated union
  of {analysis, action: buy_now} | {analysis, action: limit, limit > 0} | {analysis, action: wait}.
  The model cannot emit any other label; the code compares only against labels.Action / Session
  enum members. "reason" is replaced by "analysis" (<= 600 chars), generated before the label.
- Consequently an unparseable reply can only be a truncated one; it still counts as wait and is
  recorded with finish_reason.

## Freeze after pilot, 2026-10-27 (pilot: 30 entries, 107 checkpoints, 0 parse errors, 0 truncations)
- Frozen: system prompt sha d3517c2ff812, max_tokens 600, temperature 0, model deepseek-v4.1-flash-1017.
- sha256 runner.py / chartlib.py / labels.py: 3859b55f8a63c0f56c07bffec6667b4caa7cd41edb23bd8e22d0cca9262bfc48 fb2ffeb071044ac07893e35f4850090ac925d934b1252cf2227f5dc2c9de8ca4 6fba9152226cd6165402dc7fcbf4356c419c0c0c33c7b59fa0bd6708da43785e 
- No change to prompt, renderer or rules after seeing the pilot. Pilot entries stay excluded.
