# Forward record, week of 2026-10-26 to 2026-10-30

**Status: a weekly tracking entry under P1. This note makes no live change, no
interim performance decision, and is not a verdict on the rule.** The installed
rule `grade-led-leader-weight/1` is frozen for the 252-session forward window
(`position-sizing-and-rule-freeze-2026-10-30.md`), and the protocol's review is
after 252 completed sessions. This note records what the week produced so the
record exists in one place; it does not compare the rule to an alternative or
recommend one.

## The week at a glance

- Five sessions, 2026-10-26 through 2026-10-30. GOOGL's earnings reaction on
  10-29 (reaction −12.6% on 5.9× volume) set the tape: the event watch measures
  the book's mean at **−5.45%** across 95 members from the shock to 10-30.
- Paper account equity: **86,989.84** at the 10-23 close → **84,166.47** at the
  10-30 close, **−3.25%** for the week and **−15.83%** since the 2026-09-04
  start at 100,000. The week's peak was 88,419.54 on 10-27; the fall from that
  peak to 10-30 is **−4.81%**.
- Daily equity: 87,628.97 (10-26, +0.74%), 88,419.54 (10-27, +0.90%),
  88,020.35 (10-28, −0.45%), 85,661.85 (10-29, −2.68%), 84,166.47 (10-30,
  −1.75%).
- Cash 68,902.90 → 43,911.58; invested **20.8% → 47.8%** of equity. The rise is
  mechanical, not discretionary: the pre-meeting FOMC cut was retired on
  2026-10-28 (`fbe24a87`; the 10-28 plan ran `fomc-hold-through-meeting/1` with
  the cut disabled), the open October cycle restored at the 15:45 ET decision
  close, and the ordinary joint-funded plan then bought. After the pending plan
  fills at decision prices, cash is **49.97%** of equity (`idle_cash_share`).
- Positions 10 → 11: ALAB, COHR, GEV, HPE, INTC, MU, NTAP, SMCI, SNDK, SNPS,
  TSM. Three orders are queued for the 11-02 open: sell 2 SNPS, buy 1 GEV,
  buy 3 STX.

## Benchmarks for the same week

Close-to-close 2026-10-23 → 2026-10-30, adjusted closes (dividends included):

| line | return |
|---|---:|
| SPY | −0.56% |
| QQQ | −1.97% |
| equal weight, the book's 94 names | −1.32% (median −0.28%, 48 of 94 down) |
| paper account, broker marks at the nightly snapshot | −3.25% |

The paper account is **not** a regular-session close-to-close series. Its marks
are the broker's latest price at the ~19:30 ET snapshot, which can include
after-hours prints. INTC is the clearest case this week: the 10-29 regular close
was $92.07, the 10-29 desk mark was $70.85 (the after-hours price, −23%), and
the 10-30 regular close was $65.76. The account therefore felt part of INTC's
move on 10-29 and part on 10-30. The benchmark table is indicative; the forward
shadow below is the clean, same-mechanics comparison.

The equal-weight line is the book's current 94 names, so it is survivor-biased
in the same way as every book-level study; it is the relevant execution
universe, not a point-in-time S&P 500.

## The forward shadow (same mechanics, 10 bp)

Five sessions, first decision 2026-10-23, last mark 2026-10-30. Fill at the next
session's adjusted open, mark at adjusted closes, 10 bp per unit of weight
traded, cash earns nothing.

| track | return | max drawdown | turnover |
|---|---:|---:|---:|
| installed planned | −2.25% | −4.52% | 0.727 |
| installed engine_next | −3.00% | −5.12% | 0.716 |
| honest installed planned | −3.51% | −4.54% | 1.269 |
| honest installed engine_next | −4.14% | −4.99% | 1.088 |
| f3 planned | −2.50% | −5.00% | 0.639 |
| honest f3 planned | −3.71% | −5.13% | 1.000 |
| SPY | −0.96% | −2.15% | 1.000 |

Deltas over the five sessions: installed planned **−1.29 points vs SPY**;
honest installed planned **−2.55 points vs SPY**; f3 vs installed planned
**−0.25 points**; honest f3 vs honest installed planned **−0.20 points**. The
daily-difference standard deviation for installed vs SPY is **1.10 points**
against a mean daily difference of **−0.25 points**; five sessions cannot
separate that from noise. The f3 and honest-f3 tracks are forward candidates,
not live; they are recorded, not promoted.

The shadow's SPY line is fill-to-fill from the 10-26 open with a 10 bp cost, so
it is not the raw close-to-close SPY figure above. The installed and honest
tracks run on different universes (the honest tracks are the point-in-time S&P
500, the installed tracks the live book), so compare like with like: f3 against
installed, honest f3 against honest installed.

## Plan parity

Four rows in `data/market/desk/plan_parity.json`:

| session | path | verdict |
|---|---|---|
| 2026-10-27 | event | ok |
| 2026-10-28 | ordinary | ok |
| 2026-10-29 | ordinary | **mismatch** |
| 2026-10-30 | ordinary | ok |

**3 of 4 ok.** The 10-29 mismatch: the ordinary plan refused with
`inconsistent_account_equity`. Broker equity 85,661.85 was **$8.72 (1.0 bp)**
below cash 43,910.22 plus quote marks 41,760.353 — two broker snapshots fetched
separately, one for equity/cash and one for positions. The guard refused any
excess over 1e-10 of equity, so sub-cent rounding blocked the plan and the
board. Fixed in `6b66598e`: `MARK_RECONCILIATION_TOLERANCE = 1e-3`, marks
scaled to implied equity, and a larger disagreement or cash above equity still
refuses. The 10-30 receipt carries the fixed source (`joint_funded_policy.py`
sha `aca167f9...`) and the 10-30 row is ok. The fix is in the 2026-10-31 release
(`approved_at` 2026-10-31T00:54:18Z), deployed with `983c77d4`, admission
ADMITTED, post-deploy ok. The 10-29 row stays as written; no counterfactual is
reconstructed.

## Fill fidelity and slippage

The execution journal for the week has fills on two sessions:

- **2026-10-28:** 8 fills, $17,522.86 notional, all-in **+76.53 bp**; the
  benchmark split is unmeasured for these fills.
- **2026-10-29:** 8 fills, $19,615.29, all-in **−38.02 bp**; drift **+5.74 bp**,
  slippage **−43.76 bp**.

Week total: **16 fills, $37,138.15, all-in +16.0 bp**.

All-time: 134 fills, $371,965.32; all-in **+15.55 bp**; absolute scatter
**167.24 bp**; the split is measured on 87 fills and $275,848.40: drift
**+52.92 bp**, slippage **−34.88 bp**. Recent 20 sessions: 125 fills,
$352,375.24, all-in **+16.68 bp**; measured 78 fills and $256,258.33, drift
**+56.96 bp**, slippage **−37.18 bp**.

Definitions: **drift** is the decision price to the first price the order could
trade at (the next open, the closing auction for a scheduled sell, or the
reference bar for an intraday cut); **slippage** is that benchmark to the fill.
Positive is a cost. Drift is display-only and is never netted into P&L. The
all-in positive figure is mostly the overnight gap; the part the desk controls,
slippage, is negative on the measured set (fills better than the benchmark),
driven by sells (by side: +0.28 bp on buys, −53.75 bp on sells). One week of
two fill sessions is not evidence about execution quality; the all-time and
20-session figures are the stable view.

## Exposure and turnover

- Invested **47.8%** at broker marks, cash 52.2%; after the pending plan, cash
  49.97%.
- Shadow turnover: **0.727** installed planned, **1.269** honest installed
  planned; per fill 14.5% and 25.4%.
- The live week's fills are $37,138.15, about **43% of average equity** in
  traded notional.
- The exposure move from ~21% to ~48% is a policy-driven restoration from a
  low, not a discretionary call. It means the week's return is on a rising
  exposure path, not a constant one, so the week is not a clean read on the
  rule at a fixed size.

## Descriptive context, not part of P1

- **Event watch, as of 10-30:** 9 negative earnings shocks (CRDO, DDOG, GOOGL,
  INTC, META, NOW, OKLO, PANW, SWKS), 20 adverse price moves in five sessions,
  book mean −5.45% across 95 members since the GOOGL shock. Next election
  2026-11-03 (2 sessions); next FOMC 2026-12-09 (27 sessions).
- **Earnings calendar, as of 10-30:** 88 names, 69 upcoming, 6 held with an
  upcoming release, 1 overdue.
- Both are descriptive alerting. Neither grades, sizes, orders, nor prompts.
  The pre-release de-risking overlay failed its pre-registered gate and the
  intraday reaction measurement was null/negative; neither is live.

## What this week does and does not say

- **It does say:** the installed planned book lost 2.25% over the five-session
  shadow window against SPY's −0.96%, with a 4.52% drawdown; the paper account
  lost 3.25% on broker marks; parity was 3 of 4 with the one mismatch explained
  and fixed; the controllable part of execution was negative on the measured
  fills; exposure roughly doubled.
- **It does not say the rule is broken or good.** Five sessions, one path, a
  1.10-point daily difference standard deviation against a −0.25-point mean
  daily difference. The protocol's review is after 252 completed sessions; no
  interim decision is allowed, and none is made.
- **No change:** rule, grades, targets, orders, prompts, risk dial, earnings
  calendar and event watch are unchanged by this note.

## Disclosures

- **Five sessions, one path.** The week contains a live event-risk change (the
  FOMC pre-meeting cut was retired on 10-28), so the installed shadow track is
  a blend of two overlay states. The exposure path is not constant.
- **Broker marks vs regular closes.** The paper account's equity is marked at
  the broker's latest price at the nightly snapshot, which can include
  after-hours prints; the benchmarks are regular-session adjusted closes. The
  account's −3.25% is not a regular close-to-close return.
- **Shadow vs account.** The forward shadow is a separate ledger with adjusted
  opens and closes and 10 bp costs; it is not the account, and its SPY line is
  fill-to-fill, not close-to-close.
- **Parity mismatch is historical.** The 10-29 row is retained as written; the
  fix's effect is shown by the 10-30 row and will be tested again on 11-02. No
  counterfactual plan is reconstructed, because that would be a hindsight
  exercise.
- **Execution split is partial.** Drift and slippage are measured only where a
  benchmark exists (87 of 134 fills all-time, 78 of 125 in the recent 20
  sessions). Drift is display-only.
- **Survivorship.** The 94-name equal-weight line is today's book, not the
  point-in-time S&P 500. The absolute levels are flattered; the shadow's
  installed-vs-SPY comparison is the fair one.
- **Not a performance verdict.** The 252-session review is the protocol's
  decision point. This note is a tracking entry, not a gate.

## Artifacts

- Forward shadow score: `data/market/research/forward-shadow/scores/score_latest.json`
  (written 2026-10-31T01:09:14Z).
- Daily shadow equity: `data/market/research/forward-shadow/scores/daily_equity_latest.csv`.
- Execution quality: `data/market/desk/execution.json` (written
  2026-10-30T23:49:27Z).
- Plan parity: `data/market/desk/plan_parity.json`.
- Desk records: `data/market/desk/asof=2026-10-23..2026-10-30/desk.json`.
- Event watch: `data/market/research/event-watch/asof=2026-10-30/event_watch.json`.
- Earnings calendar:
  `data/market/research/earnings-calendar/asof=2026-10-30/earnings_calendar.json`.
- Program: `docs/research/trading-program-2026-10-28.md` (P1); freeze:
  `docs/research/position-sizing-and-rule-freeze-2026-10-30.md`.

**Next weekly entry:** the week of 2026-11-02. The three orders queued on 10-30
fill at that open, and the 11-02 parity row is the first ordinary row after the
2026-10-31 deploy.
