# Plain-language price and chart labels

## Initial wording checkpoint

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

## Follow-on chart meaning and source checks

The next bounded change keeps the chart calculations, source observations,
recorded actions and marker placement rules intact while making their meaning explicit:

- Daily EMA labels name 9/21/50/200 trading-session spans; weekly labels name
  9/21-week spans. An EMA weights recent closes more heavily, rather than taking
  a simple average over only the named number of closes.
- Bollinger labels say upper/lower explicitly. Their definition is the mean of
  20 adjusted session closes plus/minus two population standard deviations.
- The old `52-week` line names become `252-session high/low`, matching the actual
  trailing adjusted-high/low window, including its newest candle. This is not a
  literal calendar-year interval.
- Each percentage says **Price distance** and explains its denominator:
  `(chart price - indicator value) / indicator value * 100`, rounded to one
  decimal, not investment return. The formula is unchanged. Zero-denominator or
  overflowing results say **Distance unavailable**. Rounded signed zeros do not
  assert equality; a negative band retains its negative denominator.
- **15-minute bar close** retains the original interval-start date/time. A stored
  fallback says **Newest stored candle price**, with the existing forming or
  incomplete qualifier. Neither label establishes wall-clock freshness.
- Mixed grade transitions name each endpoint's source, such as **Saved A →
  Recalculated B**. Only exact true/false source flags establish those origins;
  missing or malformed flags say **Source unverified**. Grade transitions remain
  distinct from recommendations and fills. Marker eligibility, candle mapping,
  colors, direction and size rules are unchanged.

Price basis and the forming-week caveat are visible without opening the original
research records. Definitions expand separately; indicator rows wrap on phones.
Weekly chart EMAs can include the forming week and therefore differ from the
completed-week inputs of a saved grade. This is an explanation of that existing
behavior, not a change to the saved analyst.

An independent source/payload review ran 45 existing backend and authenticated
in-process chart HTTP tests, all passing with no skips. A separate scalar probe
checked EMA recurrence, population versus sample deviation, the exact 252nd/253rd
boundary and inclusion of a forming week. Backend files were unchanged. Receipt:
`/private/tmp/anios-chart-contract-review.DUT5vy/RECEIPT.md`, SHA256
`616d8fdfc6ce9779e1671b98070a076024a9dfb576e3ac0dc8002e55fc9c48f6`.

Root reproduced three browser failures on the preceding committed bundle,
including a visible `+Infinity%` at a zero band. Its independent eight-case
matrix checks the denominator, negative bands, overflow, signed rounding and
preservation of the endpoint's old dated candle despite a newer independent
board quote. Missing-indicator regression assertions now target the renamed
readings and explicitly check that an incomplete weekly candle has no price.
Final browser counts, exact bundle and publication are in `NEXT_SESSION.md`.

Final root acceptance: **328 passed**, zero failures/skips/flakes, 181.575 seconds;
all 140 attached browser-diagnostic records are clean. This includes all eight
independent numerical cases and broader saved-history, source-warning, account
and session-price regressions. The focused agent suite passed 56 cases. Root
independently rebuilt the frozen source and matched `index-DVSPpamk.js`, SHA256
`f75ce3b9f1e22b2d6d06a390935a0f9d53d4d42fcda3b1e496599921af435e36`.
TypeScript/build, diff review and 33 unchanged diagram/page checks pass. The
final desktop/phone captures were inspected; tall element captures have
scroll-occluded context and are not full-dialog viewport-fit evidence.
Root receipt: `/private/tmp/anios-chart-meaning-root.sYANmh/ROOT_RECEIPT.md`.

This does not resolve crowded weekly markers, qualify market-data coverage or
establish strategy performance. There is no provider/model request, account
change or deployment in this scope. Diagram impact: NONE — text rendering and
display-only handling of nonfinite ratios within existing UI paths.

## Follow-on saved-signal results

`ForwardEvidence` now says **Results from saved signals**, distinguishes reported
daily-file coverage from validation, and names unusable outcomes without assuming
they merely need more time. Saved signal counts are not trades or completed
outcomes. Updated-grade comparisons no longer claim to be technical-only.
Account columns explicitly describe simulated returns, drops at observed prices,
and gross trading relative to the starting balance. Expandable methodology
explains date weighting, costs, the $100,000 denominator, prior-peak losses,
unpaid dividends and the absence of passive SPY/QQQ accounts in this panel.
One visible warning retains the unverified price/action basis. Calculations,
every numerical mapping, archives, API contracts and accounts are unchanged.

**VERIFIED locally:** 184 browser cases, zero failures/skips/flakes, 84.280 seconds;
all 50 attached diagnostic records are clean. Ten focused cases cover wording,
unchanged values and desktop/phone disclosure/reload workflows. Seventy-four
existing backend tests pass with 22 existing all-NaN warnings. TypeScript, build
and all 33 diagram/page checks pass. Final asset `index-ZcOdBGAb.js`, SHA256
`38e9fe50ac6c9c4433a24f1f8dea11f8ae38a5200a58c38bf4f5a6649f469c96`.

Retained baseline: eight intended wording failures plus a test-helper toggle
error. The split absent/unavailable controls pass the old bundle. An intermediate
182-pass/two-failure run mistakenly counted non-recording POST previews as writes;
the original trace proves `record_history=false`. Correcting only that request
audit preserves the prohibition on actual writes; the full final rerun passes.
Evidence: `/private/tmp/anios-forward-meaning.s0adVc/ROOT_RECEIPT.md` and
`verified.json`. Desktop/phone captures were inspected; the tall phone element
capture is scroll-occluded, while the controls were exercised by browser tests.

The previously reported quote/chart phrases were already replaced in commits
`5516bc8` and `f9dd2e1`; this turn also reconfirmed their browser paths. Their
presence on the user's dashboard is not a new source defect established here.
**UNVERIFIED:** deployed artifact, fresh all-hours data and investment performance.
No deployment occurred; the existing collector decision still holds release.
Diagram impact: NONE — wording and disclosure placement only.
