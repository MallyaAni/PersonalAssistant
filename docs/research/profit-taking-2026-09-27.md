# Profit-taking and dip-buying on the `/4` book: results (2026-09-27)

Pre-registration: [profit-taking-plan-2026-09-27.md](profit-taking-plan-2026-09-27.md).
Run on spark1 from `d07704ee`; the CNN drawdown forecasts for the two
model-based rules were trained on the RTX 5080 (`market_deep_stage2
--models cnn --targets drawdown20 --export-forecasts`, 18 minutes; OOS IC
0.088, t 4.8 on 2016-2023). Payload `docs/research/scorecards/profit_taking.json`
(the price-only first pass is `profit_taking_price.json`). Control:
`ew-redeploy` - the live executor as deployed tonight (exits on downgrade,
idle cash redeployed to targets). Seven registered variants, 280 simulator
runs; 20 offsets, 10 and 25 bp, point-in-time book.

## The table (live executor, 25 bp; medians across 20 offsets; bp/d and t paired against the control, Newey-West lag 20; "early" = share of trims after which the name closed higher 20 sessions later)

| variant | 2016-2023 CAGR | maxDD | vs ctl bp/d (t) | above ctl | trims/yr | early | fwd 20 | 2024-2026 CAGR | maxDD | vs ctl bp/d (t) |
|---|---|---|---|---|---|---|---|---|---|---|
| ew-redeploy (control) | 24.8% | -43.2% | — | — | — | — | — | 60.2% | -21.2% | — |
| trim-runup-20 (1.5× target → target) | 23.2% | -42.8% | -0.4 (-1.8) | 0/20 | 31 | 62% | +2.4% | 55.2% | -21.2% | -0.9 (-1.3) |
| trim-rsi (RSI>80 → half) | 23.7% | -43.2% | -0.1 (-0.5) | 0/20 | 6 | 52% | +0.1% | 53.4% | -21.2% | -2.5 (-1.9) |
| trim-band (z>3 → half) | 23.8% | -43.5% | -0.1 (-0.3) | 0/20 | 6 | 62% | +1.9% | 59.6% | -21.1% | -1.0 (-1.3) |
| dip-add (8% under EMA21 → 1.5×) | 24.8% | -43.1% | +0.2 (+2.0) | 12/20 | 12 adds | — | — | 61.1% | -21.2% | -0.7 (-0.9) |
| trim-dd-forecast (CNN worst decile → half) | 21.3% | -42.2% | -1.0 (-2.8) | 0/20 | 28 | 58% | +1.8% | 53.0% | -18.0% | -2.4 (-1.3) |
| trim-dd-forecast-stop (+15% stop) | 21.2% | -42.2% | -1.1 (-2.8) | 0/20 | 28 | 58% | +1.8% | 51.7% | -18.0% | -2.7 (-1.5) |

Full span 2016-2026: control 30.0%; trims 25.7-29.1%; dip-add 30.3%.

**Verdict: every variant RECORD.** No rule reaches the control on the
choosing window, let alone the +1.0-point floor. Dip-add is the one rule
that does not lose (+0.2 bp/d, t 2.0, 12/20 offsets) and it is worth about
nothing: +0.0 exposure-adjusted points.

## Reading it

1. **On this book, selling strength is selling too early.** Every trim rule,
   price-based or model-based, sold names that went on to rise: 52-63% of
   trims were followed by a higher close 20 sessions later, by 2-5% on
   average (the 2024-2026 numbers are worse - the trimmed names rose
   another 5% in the RSI case). The equal-weight reset already takes
   profit mechanically every 20 sessions by trimming winners back to
   target; anything faster than that gives up return on a momentum-graded
   book.
2. **The model does not rescue the idea.** The CNN's 20-session drawdown
   forecast has real skill (IC 0.09-0.15, t 5-9 in the stage-2 study), and
   the rule that trims its worst decile is the *worst* variant in the
   table: -3.4 points over the choosing window, t -2.8, 0 of 20 offsets
   above control. The forecast is right about which names will draw down
   and wrong about what to do with that, because on this book the names
   most likely to draw down are the ones carrying the return - the same
   finding as the volatility-sizing trial, from a different model and a
   different target.
3. **Buying dips is a small, real, positive effect - and it is already in
   the executor.** Dip-add earned +0.2 bp/d at t 2.0 on the choosing
   window because adding to a graded name that is 8% under its EMA is a
   slightly better use of cash than pro rata. It is below the floor and
   it is not adopted as a rule; but the redeploy leg deployed tonight
   already puts idle cash into the names *below target*, which is the
   dip-add mechanism in its measured, non-tilted form.
4. **What the board can honestly say.** BUY: the name entered the graded
   book and is not held (buy at the next open). SELL: it lost its grade.
   TRIM: only on a reset day, when the rebalance trims it back to target.
   HOLD otherwise. No timing gate on BUY has passed a test tonight - the
   price rules and the forecast both lost - so BUY does not wait for a
   level. The operator's question "should BUY mean a good stock at a good
   level" is right in principle and remains open in evidence: the next
   candidate is a *conditional* rule - a dip the forecast says is likely
   to recover (drawdown20 forecast low, price under EMA) - priced the same
   way.
