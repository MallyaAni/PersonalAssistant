# A+ pick and execution audit — September 13, 2026

This audit uses the grades actually saved, their recorded publication times,
dated daily prices, historical consolidated SIP candles, and read-only Alpaca
paper order receipts. It does not regenerate last week's grades with today's code.

## What the selection actually earned

Five records contain 34 A+ observations across 11 names. Ten names have at
least one tradable session after their first observed publication; ALAB does not.
Repeated daily grades are not independent picks. The first observed grade is
not proof of a new upgrade: the archive starts on September 4.

The table starts at the first regular-session open after the record was written
and ends at September 11's close. Prices are raw daily observations; returns use
a consistent adjusted basis. Different rows have different observation windows.

| Name | First stored publication (ET) | First tradable open | Open | Sep 11 close | Return |
|---|---|---|---:|---:|---:|
| ADBE | Sep 7, 7:45:29 pm | Sep 8 | $262.81 | $252.23 | −4.03% |
| ANET | Sep 7, 7:45:29 pm | Sep 8 | $196.82 | $199.59 | +1.41% |
| HPE | Sep 7, 7:45:29 pm | Sep 8 | $52.29 | $62.09 | +18.74% |
| SMCI | Sep 7, 7:45:29 pm | Sep 8 | $39.67 | $40.10 | +1.08% |
| SNDK | Sep 7, 7:45:29 pm | Sep 8 | $1,769.43 | $1,633.35 | −7.69% |
| AAOI | Sep 8, 7:34:59 pm | Sep 9 | $110.78 | $105.36 | −4.89% |
| MSI | Sep 8, 7:34:59 pm | Sep 9 | $463.85 | $466.16 | +0.50% |
| NTAP | Sep 8, 7:34:59 pm | Sep 9 | $189.35 | $199.28 | +5.24% |
| LRCX | Sep 9, 7:39:01 pm | Sep 10 | $302.15 | $298.22 | −1.30% |
| PANW | Sep 10, 9:58:01 pm | Sep 11 | $338.49 | $330.65 | −2.32% |
| ALAB | Sep 12, 2:30:56 am | Not observed by cutoff | — | — | Unscored |

Five of ten rose. The equal-weight mean is +0.67% before costs, the median
−0.40%. The matched-window SPY mean is −0.23%; QQQ is −0.39%. These are
selection summaries, not the funded portfolio's return. HPE dominates the mean.
There is favorable selection evidence, but “all of them performed well” does
not hold when the clock begins after publication.

The later cohorts do contain several strong moves. The September 9 close's
record, available that evening, has six positive names out of eight from the
September 10 open through September 11: ANET +5.41%, NTAP +7.87%, SMCI +5.78%,
AAOI +0.82%, MSI +0.74%, ADBE +0.17%; LRCX −1.30% and SNDK −5.34%.
The September 10 record has five positive names out of eight on September 11.
All six grades in the September 11 record were published early Saturday and
have **no post-publication return** in this sample. Friday's rally cannot be
credited to a Saturday publication.

The first three records lack source revisions. September 10 records `3ec55ec`;
September 11 records `5103792`. The stored write time is a conservative
availability bound, not proof of the earliest publication if a record was
rewritten. Record hashes are retained in the audit output.

## What the paper account actually did

The broker returned 34 desk-prefixed orders: 24 filled, eight expired, and two
canceled venue probes. No orders were submitted by this audit.

**HPE was an execution miss.** The order for 201 shares, based on the September
4 record, was submitted September 8 at 4:03 am ET. Its opening-auction order
expired at 9:31:17 without a fill. Eight of the nine original opening-auction
orders expired; SMCI alone filled. Holding 201 HPE shares from the observed
$52.29 open through $62.09 would have earned about $1,969.80 gross, before
costs or the rest of the portfolio's funding decisions. That is a counterfactual,
not earned money. The production client already switched those entries to
queued day orders after this incident; the subsequent day orders filled.

**AAOI showed a material opening-price move before the fill.** The first A+
record appeared September 8 at 7:34:59 pm, but its target weight was zero.
The account eventually bought 31 shares on September 11 at **9:33:06.308 ET**,
average **$107.997097**. The consolidated SIP 9:30 bar opened at **$104.49**;
the daily vendor reports $105.00, illustrating why an opening reference must
name its feed. The 15-minute SIP bar ranged from $104.08 to $108.43. The fill
arrived after a substantial price move. A SIP quote at 9:33:05.763 showed
$107.49 bid / $107.74 ask; it is a nearby historical observation, not proof
of the quote available for every partial fill. The first completed 15-minute
candle was unavailable until 9:45. Using that candle to justify a 9:33 entry
would introduce hindsight.

**Selling later was not uniformly better.** On September 11 the account sold
27 NTAP at 9:30:34 for $186.08; the close was $199.28. Delaying those shares
to that close would add $356.40 gross. The 43 ADBE sold at 9:32:49 for
$246.868605 closed at $252.23, a $230.54 difference. But 14 PANW sold at
9:30:33 for $337.51 closed at $330.65: waiting would lose another $96.04.
These morning sales predate the current ordinary closing-execution policy.

**SMCI's later re-entry was useful.** The first 155 shares were bought at
$40.04 on September 8 and sold at $39.88 on September 9. The account bought
121 at $37.79 on September 11 at 9:31:02. Marked at the $40.10 close, the
two episodes total roughly +$254.71 before costs. Simply retaining the first
155 shares to that close would be about +$9.30. Timing was not uniformly poor.

## Chart-based timing experiments

The study fetched **22,616 SIP bars**, including 45 calendar days of warmup,
with no unavailable symbols. It reuses the desk's causal EMA calculation.
SIP consolidates trading venues; IEX is only one venue. Neither a bar nor a
paper fill guarantees real execution. [Alpaca market-data documentation](https://docs.alpaca.markets/us/docs/market-data-faq)

The following rules were specified before their outcomes were calculated:

- Daily context uses the prior completed session: close above EMA21 above EMA50.
- Hourly confirmation uses complete candles anchored at 9:30 ET: close above
  EMA21. The final 30-minute session segment is explicitly treated as the final
  completed candle. An incomplete current hour is never used.
- Pullback entry requires a 15-minute touch of EMA21 followed by a bullish
  close back above EMA21 and EMA9, with daily/hourly alignment.
- Breakout/retest entry requires a retest and bullish recovery of the prior
  day's high, after that level was exceeded, with daily/hourly alignment.
- Structure exit requires both a 15-minute close below EMA21 and a completed
  hourly close below its EMA21.
- The optional half trim requires an upper-Bollinger-band rejection, a bearish
  candle and a close below EMA9. The remaining position follows the structure exit.

Signals act at the following bar's open. Costs are 10 bp each side, including
the terminal liquidation assumption. No-entry candidates remain in cash and
remain in the average. The sample is the same ten first-observed picks for
every row; Friday's newly published picks remain unscored.

| Entry | Exit | Entered / 10 | Mean net result |
|---|---|---:|---:|
| First tradable open | Hold through sample | 10 | +0.47% |
| First tradable open | EMA structure failure | 10 | −1.31% |
| Confirmed trend pullback | Hold through sample | 4 | −0.34% |
| Confirmed trend pullback | EMA structure failure | 4 | −1.50% |
| Confirmed breakout/retest | Hold through sample | 2 | −0.16% |
| Confirmed breakout/retest | EMA structure failure | 2 | −0.57% |

The band-trim variant produced the same results as the structure exit: no
additional band trim fired before the tested structure exits. This is not
independent evidence for the trim. A synthetic test confirms that the trim can
fire and cannot repeat on the same position.

HPE explains the tradeoff. Its trend-pullback entry waited until September 9
at 3:45 pm, at $58.17, versus the first tradable $52.29 open. The structure
exit then sold at September 10's 2:30 pm bar open, $55.2801, before the next
day's advance. Strict agreement across timeframes filtered some losers but
also delayed the strongest winner. These specific rules do not improve this
sample. That is not evidence that all technical timing is ineffective.

These are **single-position experiments**, not a replacement for the funded
20-session portfolio simulation. They do not model re-entry after a full exit,
position competition, funding, spreads at every fill, or a multiweek holding
outcome. A one-week sample cannot establish the best EMA periods or candle rules.
Fixed percentage controls were also measured initially, but are not a proposed
live exit policy and are not the chart-based conclusion.

## Improvements supported by this audit

1. Preserve publication, submission, and fill timestamps together in the durable
   decision record. The existing journal retains quantities/prices but not the
   complete broker timing evidence this audit had to retrieve again.
2. Measure actual entry drift against both the decision price and an explicitly
   named opening/quote reference. A simulation's opening price differs materially
   from some paper fills arriving one to three minutes later.
3. Treat an A+ grade as selection evidence; separately show whether the name has
   an allocation, is blocked, is waiting for the rebalance, or has a confirmed
   entry signal. ANET, AAOI, MSI and PANW had zero target weight at their first
   observed A+ grade. A favorable grade alone was not a buy order.
4. Evaluate technical exits together with re-entry and funding inside the actual
   portfolio. Selling a pullback and never buying the recovery is a different
   strategy from using that pullback to improve execution.
5. Keep the FOMC policy separate from technical profit taking. It is now enabled
   as a provisional exposure decision; its orders bypass ordinary green-day holds.

The first two require additional production instrumentation. This change ships
the reusable read-only evaluator and its tests; no underperforming timing variant
is promoted to live orders. The predeclared next evaluation should include
re-entry, paired portfolio funding and an untouched forward sample.

## Reproduction and proof

`python -m backend.cli.market_pick_audit --root data/market --since 2026-09-04
--until 2026-09-11 --intraday --broker --feed sip`

Audit source SHA-256:
`519490b25269884dfd254fb69f1c6ed2bd81cf7d3e6db1cbf0e5315297841735`.
Technical evaluator SHA-256:
`3338e577b2ea123a548c77e6996723ca9a6c58d1dafe5ddf309e6322745e38f5`.
The saved output includes every pick, record hash, dated raw candle, tested rule,
and broker receipt. [Compact results](pick-timing-audit-2026-09-13.json) include
every tested pick and per-symbol candle counts/hashes; the full raw candle
artifact is retained in the task's visualization directory. Nine tests passed
in 0.12s. Tests cover publication boundaries, adjusted price basis,
unknown candle ordering, complete hourly candles, no future-price influence,
next-bar execution with costs, and one-time band trims.

FOMC deployment is separately verified at `84d07faf`: 3,450 unit tests passed,
19 skipped; 100 real-model routing cases passed in 482.00s; post-deploy marker
`2026-09-14T01:31:47Z 84d07faf ok (cheap)`. Frontend wording follow-up
`f13cbcfa` also deployed successfully, with post marker
`2026-09-14T01:53:26Z f13cbcfa ok (cheap)`. The public dashboard asset is
`/assets/index-CtXHAenQ.js`; browser replay displayed the policy notice and 93
grades with no page, console or network errors. This replay uses captured real
GET responses and a mocked operator session. No real-money order was submitted.
