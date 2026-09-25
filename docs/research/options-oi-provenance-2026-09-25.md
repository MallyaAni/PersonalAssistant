# Dated option OI levels, not a current gamma signal

## Objective and implemented boundary

The [raw-price/isolation fix](options-diagnostic-isolation-2026-09-25.md) did not
establish the provenance of older saved calculations. A fresh stock bar or a
new technical explanation cannot make a separately collected options chain
current. This change makes the distinction explicit without inventing a
freshness threshold or changing a trading rule.

New successful `live_technical` wall calculations retain `calculation` metadata,
version `raw-option-oi-levels/1`: actual raw reference price, raw-panel row date,
original cached source-bar start when known, the date supplied to expiry
selection, and the method parameters. The source bar is captured with the
cached raw row, not copied from a later quote. A changed price on the same
cached bar therefore cannot rebase the options calculation. A rejected quote
supplies no bar. An older source bar may legitimately precede the synthetic
panel row date and remains separately dated.

The expiry-selection date is **not a recorded computation timestamp**. The
panel row date is **not proof of quote freshness**. The immutable chain's
`source_time`/`fetched_at` is local collection time, after parsing and before
storage; it is **not the provider's effective OI time**. These distinctions are
part of the displayed wording rather than assumptions left to the reader.

`options_evidence` supplies a pure read-time projection under the top-level
`options_evidence` field from `desk_freshness.describe`, including `/desk/live`.
It reads but does not modify the saved technical detail or snapshot:

- `recorded`: recognized raw-reference version, consistent method, dates,
  levels, interest counts and distances. This means a dated calculation is
  present, not that OI is fresh or independently authenticated.
- `unverified`: legacy/missing/unsupported/inconsistent calculation provenance;
  displayed numerical levels are withheld, not repaired or inferred from prices.
- `unavailable`: the optional-data failure marker or unsupported stored shape.
- `absent`: no stored diagnostic supplied. This does not assert that no chain
  exists: omission can also mean an empty chain or unusable reference price.

Every state has an assessment timestamp and separate collection status/age.
Missing, malformed and timezone-naive collection times yield no invented time
or age. A future collection retains its normalized timestamp with a `future`
status and no negative age. `oi_effective_at` remains null and `oi_freshness`
remains `unknown` in every case. No collection-age TTL is asserted.

Selection dates are assessed in New York. A historical selection remains
historical even after one or all of its expiries pass; the read does not rerun
selection or silently treat it as current. Invalid/future selection dates,
future panel rows/bars, unsupported methods and internally inconsistent levels
withhold the projection. The producer and projection use the same price-space
range checks, avoiding ratio-rounding errors at an exact boundary.

## User-visible meaning

Both existing wall locations use one shared `Stored option OI levels`
disclosure. They never fall back to raw legacy wall fields. The summary names
unknown OI freshness and flags historical expiry selection before expansion.
Details show collection age **as of the supplied assessment time**, not a
perpetually current age; all instants include year and one ET suffix. Calendar
dates remain date-only and are not shifted through UTC midnight.

The method is explicit: sum OI per strike across expiries 1–60 calendar days
after the selection date, excluding same-day expiry. Among strikes within 25%
of the recorded raw reference, choose the greatest qualifying put OI at/below
that reference and call OI at/above it; ties select the nearest strike. A selected
strike must have at least 500 summed contracts on that side. A computed absence
of qualifying levels is distinct from unavailable data.

Distances are neutral spatial comparisons, such as `5.0% below recorded
reference`, with no price-movement arrows or trading colors. The exact reference,
panel date, original bar when retained, selection date, expiry span and method
version remain visible. A missing bar is explicit. These levels are not dollar
gamma exposure, measured dealer positioning, guaranteed support/resistance or
a buy/sell signal. They need not match a single-expiry Barchart gamma display.

## Acceptance and evidence

Starting clean main: `979cdb738821b0c269d384c588a7f13dbee71fdc`; initial pull
current. The cached Python runtime mounts current source read-only with
networking disabled. The browser serves a specifically built candidate bundle
inside a separate network-disabled container; no laptop access changes needed.

**VERIFIED backend:** 235 relevant checks passed, zero skips, 16 pre-existing
empty-slice warnings, 3.03 seconds. The task's own 186-case matrix (88 new plus
98 prior isolation cases) passes without warnings. It exercises real Parquet,
actual cached-row/technical calculation, balancer/board persistence, independent
collection clocks and authenticated ASGI cached reads at two instants. All
task-owned files, technical evidence and grades remain unchanged by reads;
missing bearer gets 401, wrong owner gets 403. Only the unrelated search-metering
account lookup and external/model/account boundaries are supplied synthetically.
This is not a listening/deployed HTTP server or real account database check.

**VERIFIED neighboring behavior:** 54 intraday-candidate, research-storage,
decision-view and RL-readiness tests pass, zero skips, six existing warnings,
1.25 seconds. This is regression evidence, not a new fit or economic backtest.
Independent pure review passes 149 checks with networking disabled. Scoped
Ruff/format and all 33 unchanged architecture diagrams/page checks pass.

**VERIFIED browser:** 152 scoped tests passed, zero skips/flaky/unexpected
results, 67.847 seconds; all 46 strict six-category diagnostic records are
empty. Both options suites and the desk, analyst-semantics and history-accuracy
neighbors ran against the identified production bundle, excluding live-provider
cases. The focused 17 cases cover both locations, clock changes, reload,
historical selection, old bars, all availability states, neutral distances and
the precise method wording. TypeScript/production build pass, with existing
CSS/chunk-size warnings retained. Root reviewed both historical screenshots.
The preserved original bundle failed all 13 initial semantic cases with clean
browser diagnostics; the final suite adds the reviewed wording and older-bar
case rather than presenting a different suite as the same original comparison.

**FAILED before correction:** final original-boundary replay has 160 failures /
26 passes: 80 missing-helper failures, six missing-producer-metadata failures,
two missing-projection failures, and 72 strengthened exact-shape assertions.
This is not 160 regressions in the previous isolation fix. Independent review
also found one genuine candidate arithmetic defect: raw 3.92 / call 4.90 is
accepted at the producer's 25% boundary but its ratio exceeds 1.25 by rounding.
The eight-case boundary matrix gives one failure/seven passes before correction
and eight passes afterwards. Both original failures and a mistaken baseline
overlay that briefly exercised candidate code are retained and labelled.

Backend receipt: `/private/tmp/anios-options-provenance.0HcrH4/RECEIPT.md`,
SHA256 `3a2fd936e3c7f6b2556add5ceeaec2aef21072a6af6047199312fbda027500b7`.
Root wider JUnit SHA256
`3b51dd3a7789659d58bf09afc2052f2d5c3e898a5e56d163bff01b567ba05074`.
Independent receipt:
`/private/tmp/anios-options-provenance-review.sB31jz/RECEIPT.md`, SHA256
`3176c1ea1cc40618cb824d73af00c0bbd46ca63f9e77dc484e6f474f3b730b0e`.
Browser evidence: `/private/tmp/anios-options-provenance-ui.XsDaDF/RECEIPT.md`.
Reviewed asset `index-BoqubrLW.js`, SHA256
`8cb5034ec179fd3b0ea6a0a1e88438586362a15f4f21fa82522f27cf78d44c2a`.
Final source and receipt hashes are recorded in the root handoff.

## Limits

No source OI effective time is recovered. Provider coverage, current AAOI or
Barchart levels, source accuracy, deployed behavior and economic value remain
**UNVERIFIED**. No options feature is adopted into grading, allocation or
execution. No historical study, source chain, holding, account or order is
rewritten. New diagnostic metadata can naturally be retained by future ordinary
research snapshots; that is not a changed forecast or allocation.

The existing `/desk/live/read` explanation still interprets technical feature
lines, not options levels. The read-time assessment stays outside its
detail-based model-cache signature. No prompt/model behavior is changed or
claimed verified. The CLI's default collection calendar is corrected in the
separate [New York date fix](options-collection-date-2026-09-25.md); legacy
UTC-labelled partitions are not migrated. The unused gamma proxy's assumptions
remain separate source-audit work.

No deployment or service restart was performed. Full deployment gates and
postchecks remain required through Spark's `scripts/deploy.sh --wait-post`;
collector activation remains unanswered. Older saved calculations stay
unverified until a normal authorized producer creates versioned evidence;
the API does not refresh providers or run the balancer to manufacture it.

**Diagram impact: NONE — internal diagnostic provenance and read-time field
projection within existing snapshot/API/dashboard boundaries.**
