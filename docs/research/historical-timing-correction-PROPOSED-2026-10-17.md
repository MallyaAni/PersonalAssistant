# Concrete conditional correction proposal — no replacement run authorized

The original sole account/source27471/container1e8f440a is immutable. Nothing here
rewrites, restarts, republishes or renames it. Its independent accounting audit can
continue only under root's existing direction; full live timing parity remains held.

## Bounded genuine input evidence

Exactly the additionally authorized old-data GETs were made: one SPY quotes page
(limit5), then AAPL quotes and trades (limit1000 each), all SIP, ascending, strictly
2019-03-01T14:45:00Z–14:45:01Z. No retry, redirect, pagination, recent end, paid-plan,
account or order call. Original root probe and all earlier proof roots are retained.

The AAPL pages returned200 with94quotes/69trades and no next page. Actual retrieval
was2026-10-17T11:38:52.482437Z–11:38:52.849132Z. The original raw body hashes are:

- quotes `d72425b3e7715c5d1abb2d2a1751d6e809d797ba4296a59c28481147fb736f77`
- trades `4ee7d11c02ba5d960fee735c83b1c3bdcd6207a1da4015fcccc6e8821bf5eaa1`
- combined acquisition receipt `3343062549278d01ff745325bc85d8603c1941b681f8f1ce88d41ef50a5e9919`

Remote receipt:
`/home/animallya96/scratch/historical-stock-packet-probe-20261017-v1/observations.json`.
The separate SPY after-boundary acquisition receipt has SHA
`8a1e8a241a1b03259b823e59ae83ee6c858abe6789f8f07a4a60abcb29627004`.
SPY remains a benchmark; its data was not renamed into an eligible stock.

Two existing original raw SIP session files were read,4430bytes for AAPL and
4396bytes for SPY. Their authoritative mount resolves `/private/bars_15m_sip`
through `/original/bars_15m_sip` to the deployed data directory. Both report raw
15Min/SIP, complete schema2, with actual Sept27 retrieval clocks. AAPL file SHA is
`cce7a6d1482bc60f99d212a2bb73f56188771b4491fa8ff0ca862f0115a747de`;
SPY is `35428d71724f15fe4b67de28ecee360156baa74bae4fe60b20fab11178963a3b`.
Their eventual match to the original full-run completion input map still requires
the COMPLETE audit; these current reads do not fabricate that missing proof.

AAPL raw9:30 opening is174.34, prior completed-bar close174.015 and9:45 opening
174.01. The first returned trade is174.03 at14:45:00.006Z with conditions `@,I`;
the first returned trade matching the official bar opening is174.01 at.007Z.
Price matching alone does not authenticate official trade-condition eligibility.
Never use the first arbitrary trade as the model's opening anchor.

## Concrete prototype and its limits

`prototype.py` calls exact original selected bodies of the unchanged
`forward_probability_timing._quote/build_reader` and shared funding/utility code.
No source body is changed. Actual bid/ask/sizes/timestamps, session open and
opening-anchor price come from the retained genuine inputs. Numeric inference
is deliberately a declared fixed distribution; funds and the one-share intent
are declared synthetic constants. No real model or account executes.

Historical actual quote receive, anchor publication and inference duration are
**null/unknown**. The prototype requires `assumptions.json`; none of six missing,
negative, Boolean or noninteger latency inputs defaults to zero (9rejections).
Its native clock-shaped fields are an **ephemeral conditional interface view**;
the proof labels that mapping explicitly. They are not stored or authenticated as
actual 2019 receipt clocks and cannot be admitted as production evidence. Without
the assumed receive/publication fields, the unchanged shared guard returns
unavailable. No claim of zero observed latency is made.

Let T be the completed-bar boundary. The explicit illustrative schedule is:

```text
assumed bar available       = T + bar-publication-delay
assumed forecast available  = bar-available + inference-duration
assumed anchor available    = matched opening event + anchor-publication-delay
assumed quote available(q)  = genuine quote event(q) + quote-receive-delay
decision                   = max(forecast/anchor/needed-quote availability)
submission                 = decision + sender-delay
earliest market arrival    = submission + broker-route-delay
```

Only quotes available by decision are eligible inputs. Selection uses integer
nanosecond ordering, not lexical timestamp comparison. The shared reader receives
upward-rounded microsecond availability clocks so precision conversion cannot
move an assumed availability earlier. No forming next-bar high/low/close/volume
enters timing, and the raw next opening is only the already-known transport anchor.

Results, all explicitly illustrative:

| Assumption | Timing calculation | Execution reference |
| --- | --- | --- |
|50ms bar/quote/anchor,100ms inference,20ms sender,20ms route|decision14:45:00.150Z, submission.170Z, arrival.190Z; unchanged forward reader executes the declared fixed negative-mean buy|first qualifying later ask174.03 at.196Z; NOT a broker fill|
|1s bar publication, same other delays|decision14:45:01.100Z, submission1.120Z, arrival1.140Z|unavailable: genuine bounded sample ends before a post-arrival event|

The opening174.01 at.007Z is consumed evidence in both schedules and is rejected
as a possible post-submission execution. It must never be reused as the fill.
The first schedule's reference is6ms after assumed arrival; no sub-millisecond
order of the original millisecond-resolution records is asserted. A production
historical adapter must freeze timestamp precision/uncertainty and require the
execution event's lower bound to exceed submission/arrival's upper bound.

The quote reference means only that a genuine quote at a later event offered that
side/price. It does not prove queue position, accessible size, routing, impact,
fill probability, partial fills or our order's execution. Do not equate raw size
fields with shares until documented feed units/lot sizes are bound. With one
declared share at174.03, unchanged10bp per-side fee arithmetic is0.17403. No cash
or holdings are changed. AAPL's first traded price174.03 is a separate earlier
event, not the later quote's fill provenance.

Proof: `prototype-proof.json`, SHA
`d118e9422b1bbca6b8ebb4c36e60a31b46de44ea21f702eefd4efb191cda1d5a`.
Script SHA: `741d67c512ee5c3be52f06efb596043228bce8ad08efc9f1e194cbd7fd0e1c0c`.
The two preparation errors are retained in `preserved-failed-preparation.txt`.

## Proposed faithful correction, subject to explicit human direction

1. Preserve the original run and its failed parity boundary. A different account
   is necessary if timing changes earlier submissions/fills; a post-hoc verifier
   cannot repair its later carried cash/share path. The ONE-run restriction
   therefore requires explicit direction before any replacement or replay.
2. Freeze a distinct retrospective execution/availability contract and artifact
   identity before scoring. Keep the exact current holding/timing heads, residual
   and risk banks, grades/cohort/calendar/units, costs10bp per side, cash-only
   funding, covered sells, original whole-share intents, reservations, missing
   data and corporate-action rules. No base fits, model substitution, new grade
   rule, tuning or numerical risk floor. Latencies are declared scenario inputs,
   not estimated from the favorable backtest outcome.
3. Acquire a separate immutable historical quote/trade snapshot with full page
   completeness, exact symbol/feed/time/source and actual present-day retrieval
   clocks. Validate raw units, official eligible-opening construction and quote
   size units using frozen provider specifications. SIP availability is now
   evidenced for this bounded interval, not proven for every name/date or quota.
   The installed acquisition path uses IEX; using archival SIP is a distinct,
   disclosed feed assumption even though the shared forward guard supports SIP.
4. Keep a mandatory outer retrospective-assumption receipt. Never write assumed
   clocks into an archive called actual receive/publication evidence. An isolated
   retrospective adapter can derive an ephemeral conditional view for the exact
   shared feature/model/transport/utility/sender functions; production admission
   must continue requiring real source/quote/receive/account receipts unchanged.
5. Use only daily information through the prior close and completed raw intraday
   prefixes for21features. Reuse original authenticated numeric inference at the
   original frozen model-availability clock, while separately applying declared
   historical observation availability. Account basis comes from the independent
   causal ledger before any batch; receivables do not become spendable cash and
   this batch's sell proceeds cannot fund buys. Preserve missing forecasts and
   explicit final deadlines/early closes. No unsupported fallback to a 1% rule.
6. Apply the exact shared forward quote qualification and midpoint/open transport
   before deciding. Require all relevant assumed packet/inference/account times
   before decision and before expiry. Price execution only **after** assumed
   routing. A recommended candidate convention is the first qualified later
   executable-side quote with declared size/impact assumptions and unchanged10bp
   fees. That changes the original raw-bar-open fill basis and must be registered
   explicitly; it cannot be called unchanged original economics. If evidence is
   absent, too coarse, incomplete or too late, preserve an unavailable/refused/
   unfilled state. Never borrow the already consumed opening or later candle close.
7. Audit every original saved timing input/forecast/verdict/allowed quantity and
   the resulting independent ledger, with assumption/source/model hashes and
   actual versus assumed clocks distinct. Test future-prefix poisoning, wrong
   opening trade, future quote, missing latency, stale/wide book, benchmark trade,
   early/oversized order, cash/coverage/refusal, same-clock pre-batch causality,
   earlier-open reuse and insufficient post-routing samples. Shared-observation
   parity can then mean equality under the declared same conditional packet,
   not a claim that actual historical local receipts were recovered.

Only a newly authorized, separately named conditional simulation could use that
contract. Its results would remain retrospective/current-model/assumption-based,
not historically published, not actual fills, not adoption or investment proof.
The current original run cannot be silently promoted to that meaning.
