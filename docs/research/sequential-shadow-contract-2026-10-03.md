# Actual-intent timing observation contract

This read-only collector connects the frozen September continuation model to
actual ordinary unsent paper-account intents. It tests input compatibility and
conditional decisions; it is not a policy promotion, an account simulation,
an execution-attempt journal, or proof of improved returns.

The completed [funded comparison](sequential-execution-results-2026-10-03.md)
does not justify replacing the live gate. The model improves full-period
paired median gain modestly but loses in the recent window. No parameters,
windows, sources or model weights are changed in response to those outcomes.

## Source and clock requirements

- Read the actual paper state and six GET-only account/positions/open-order
  responses. Freeze only ordinary unsent orders under the actual active policy;
  retain every excluded original ID and reason. Refuse changing state, cash,
  holdings or working orders. No writer locks or production writes.
- Require explicit preceding-session desk and Yahoo daily partitions. Use
  actual record `written` and parquet `source_time`, source revision metadata,
  original-byte hashes and complete-through dates. Preserve the full recorded
  EMA origin. Missing reviewed exchange sessions remain NaN; missing names
  never reduce the breadth universe silently.
- Recorded prior-session grades and recorded current-book membership are
  explicitly different from the recomputed grades/current-vintage historical
  membership used in training. No historical grade reconstruction is claimed.
- Capture the original free IEX endpoint responses with `adjustment=raw`.
  Retain page tokens, queries, statuses, body hashes and actual request/receipt
  clocks. Reject duplicates, reordering, disconnected pagination and clock
  rollback. Retain malformed or refused response bytes privately.
- Only completed aligned regular-session bars enter features. Do not replace
  raw prior closes with adjusted prices. A separate `adjustment=split` request
  may supply the previous session's final regular-bar close only when every
  current raw/split OHLCV value and missingness matches exactly. No estimated
  ratio, inferred factor of one, or price-based threshold is fitted.
- That anchor is an IEX prior regular-bar proxy, **not** the training source's
  Yahoo/SIP prior close. IEX/SIP volume and price differences, recorded-grade
  differences, and frozen September carry-forward into October remain explicit
  domain differences. Missing or mismatched anchors produce unavailable model
  observations. [Provider adjustment contract](https://docs.alpaca.markets/us/reference/stockbars).
- Original source and model hashes are recorded. Ordinary heads use the
  previously fitted parameters; no fitting or old account replay occurs.
  Terminal observation is the 15:45 regular-session decision, not an auction.
  Early closes are unsupported by this frozen model.
- Retain market receipt and actual model-completion times separately. Reject
  an observation that crosses a bar boundary during source capture or model
  computation. Recheck the actual intent file before emitting decisions.

## Output and limits

Each invocation writes a new private directory outside every source input.
Directories are mode0700; original pages, intent snapshots and JSON receipts
are mode0600 and exclusively created. No credentials appear in artifacts or
console summaries. A no-eligible-intent observation makes no market request
and loads no model.

Each decision retains original ID, side, quantity and complete order object.
Observed-price whole-share capacity is conditional on the frozen cash/holdings;
covered sells do not create funding for another buy. Current-gate and
first-available states use the same observed prefix. No execution attempt or
fill is committed. No gain, portfolio return, benchmark excess return or
midpoint fill is inferred from this observation.

Run from the reviewed source using explicit original paths:

```sh
python -m backend.cli.market_sequential_shadow \
  --root /market \
  --record /market/desk/asof=YYYY-MM-DD/desk.json \
  --daily-partition /market/bars/asof=YYYY-MM-DD \
  --models /original-research/models \
  --output /private-proof/new-observation
```

The partition date must be the preceding actual exchange session. Production
market data and fitted archives must be mounted read-only. Exact built image
and source revision belong in `ANIOS_RESEARCH_IMAGE_ID` and
`ANIOS_RESEARCH_SOURCE_REVISION`; unavailable identities stay explicit.

This is a one-observation compatibility tool, not a completed full-day
counterfactual study. A fair subsequent performance evaluation must retain the
initial cohort after actual orders disappear, lock first attempts, carry cash
and holdings, retain missing opportunities, measure prices after actual model
completion, and compare unchanged live-policy selection/funding against SPY
and QQQ. No score or adoption claim may substitute these observations for that
evaluation.
