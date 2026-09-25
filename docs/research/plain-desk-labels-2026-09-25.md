# Plain-language price and chart labels

## Scope

The user reported confusing `post-market quote stale`, `snapshot`, `replay`
and `below` labels. The change is confined to `StockBoard.SessionPrice`,
`TickerChart` and their browser expectations; data and trading logic are unchanged.

- An old quote says **No recent quote to display · Last quote: …**, retaining
  its actual quote time, source and recorded session. A stale price is still
  withheld. The wording describes this display, not all trading venues.
- A missing quote also says **No recent quote to display**. Detailed failure
  reasons remain in the tooltip; the chart's repeated diagnostic paragraph is
  replaced by **Price signals use regular-session candles.** Execution checks
  remain separate and unchanged, explained in the tooltip.
- `snapshot` becomes **Saved grade**: the grade comes from a nightly record.
  `replay` becomes **Recalculated grade**: later calculation from historical data.
  `below A` referred to the grade threshold, not price. The exact **A→B** (or
  other) transition remains visible without that redundant fragment.
- Chart recommendation counts use **saved records**, not **snapshots**.
  Pagination, original dates/actions, unavailable history and deleted/expired
  record caveats remain. Grade changes and recommendations are not fills.

Marker calculations, positions, color, size, candle mapping, price expiry,
source selection, chart indicators, account actions and strategy allocations
are unchanged. This is not a global removal of the word "snapshot" from source
or every other interface, and does not fix pre-existing crowded weekly markers.

## Validation and limits

The pinned, network-disabled browser image serves a fresh compiled bundle from
the actual checkout, with intercepted synthetic APIs. Root's quote-only run
passed 66 cases; the two new wording cases failed the original bundle. Agent's
four new chart cases failed the old labels and passed the new labels on desktop
and phone, observing actual canvas paint and preserving recommendation history.
Root separately repeated the two new quote cases at 390 pixels; both passed.
Phone screenshots were inspected. TypeScript, production build and all 33
unchanged diagram/page checks passed. Existing CSS/chunk warnings remain.

The first combined run retained 196 passes and six failures: five tests could
not write their hardcoded screenshot paths through the read-only mount; one
updated test wrongly called a recalculated grade "Saved". The screenshot
directory was made writable and both positive/negative grade expectations were
corrected to match the fixture's `said=false`. No product rule or assertion was
relaxed. Final combined acceptance: **202 passed**, zero failures/skips/flakes,
115.422 seconds. The corrected positive/negative grade-toggle case also passed
separately on the final test source. The two phone quote cases passed in 2.237
seconds. All tests exercised the same final compiled asset below.

Compiled asset: `index-CWPTRnOZ.js`, SHA256
`d7530fc2fd09e0974a083f4a8b40a045a0b34b4349eb146646d7d0b5a2d8d64a`.
Root evidence: `/private/tmp/anios-plain-quotes.i8JEa9/`; chart evidence:
`/private/tmp/anios-chart-wording.94Ei6Q/`.

**UNVERIFIED:** deployed workflow and fresh all-hours feed coverage. No provider
request, account/order operation, runtime setting change or deployment occurred.
An inactive new collector cannot refresh the read-only quote endpoint; deploying
it disabled is not equivalent to the old on-demand collection behavior. Enabling
it remains an explicit approval question and would not establish data entitlement
or guarantee fresh quotes. Ship from Spark only through the gated deploy script.

Diagram impact: NONE — rendering text and optional diagnostic placement only.
