# Historical opportunity-set coverage, 2026-09-25

## Decision boundary

**Not ready for unbiased historical strategy qualification.** The inspected
archives cover prices for today's selected book, but do not establish which
securities and classifications were available for selection in each past session.
Changing chronological folds, adding a model, or correcting earnings feature
timing cannot supply that missing evidence. No new fit or performance run was
performed for this audit.

Source inspected: `9d9fb6372c13e4bc5b75c16b3d1e9cc234394dcd`. The parallel
dashboard edits did not change the audited market implementation. The audit
used existing local archives, mounted read-only with network disabled in image
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.
This is not a survey of uninspected Spark storage or external subscriptions.

A subsequent bounded Spark inventory is recorded below. It found additional
fundamentals, not the missing historical opportunity set; external source access
and quality are still unverified.

## Verified local coverage

| Evidence | Observed coverage | Limit |
| --- | --- | --- |
| Frozen input archive `/private/tmp/anios-nested-market-inputs.nsm4Sm/` | Report/manifest match their pins; 190 declared source hashes plus QQQ match. Report has 2,945 sessions, 2015-01-02–2026-09-18. | Hash agreement is not historical availability or price correctness. |
| Broader `market/` cache in that directory | 537 bars and 537 action files, September 18 snapshots. All 94 current book names present: 62 have all 2,945 dates; 32 start later. No internal date gaps for those 94 names. SPY and QQQ each cover 2,945 dates. | Date coverage does not prove valid OHLC or historical eligibility. 883 files are outside the frozen study's 191 source pins. |
| `/private/tmp/anios-historical-cohort-final.ekJucf/archive/cohort.json` | Ten source hashes and three artifact hashes match. Three reviewed identities; readiness spans 720 sessions, 2020-01-02–2022-11-08. | Retrospective demonstration; zero complete-feature rows. No cached TWTR prices; merger consideration is not funded cash. |
| Current constituents and overlay | 503 constituent rows dated September 5, 2026; 68 overlay entries; 94 resulting book names. | No historical membership, GICS/classification or overlay-eligibility archive for the full study span. |

The bars contain date/OHLC/adjusted-close/volume plus snapshot metadata, not
stable security IDs or membership/publication clocks. The action files contain
`action_date`, `kind`, `value`: 17,895 dividend and 171 split rows. They do not
provide delisting outcomes, successor identity or settlement evidence. QQQ's
action file exists in the broader cache, but was not authenticated/consumed by
the frozen study.

The inspected market/cohort archives contain no comprehensive historical
membership/master/classification file or raw facts/tone/events collection.
This does not establish that no free source exists or that paid access is
required; sources and existing access must be evaluated before choosing one.

Archive identity: the source manifest SHA-256 is
`3e7f398610919674c4f798c4b359811aeac7a2d73d1c91dbf2f0e8446d0db8f6`;
its report pin is
`d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26`.
The cohort SHA-256 is
`419be2dcc3afc71df2de0decc1179491706e031f7038c2c97936cbf7403aaa74`.

## Verified Spark follow-up

Observed through **2026-09-25T15:00:55Z**, with shared source at
`565988a28d9939acc6c15d65899e4f5fe3ff3dea` before and after. Shared and deploy
market roots resolve to the same `/home/animallya96/anios/data/market`, not two
independent archives. Public market partitions and provenance-shaped research
files were inspected read-only; no private desk, paper-account or receipt data,
credentials, live services, models or source pins were touched.

| Evidence | Observed coverage | Limit |
| --- | --- | --- |
| Bars/actions | 5,556 files of each kind across 16 September 5–24 snapshots; 550 ticker stems. Latest-existing bars have 1,532,754 rows, aggregate dates 2015-01-02–2026-09-24. | Mixed latest vintages: 128 September 24, 409 September 23, 13 September 5. Aggregate extrema are not continuous per-security coverage. The 13 extra names are ETFs, not recovered exited stocks. |
| Latest-existing actions | 18,436 dividends and 179 splits; only `action_date/kind/value` fields. | No delisting, successor, entitlement or settlement fields. No other action kind occurs. |
| September 24 EDGAR events/facts | 531 files per kind: 42,236 event rows (five empty foreign-issuer files), 304,476 fact rows. | Additional filing evidence absent from the local frozen archive; not historical membership, classification or share-class transition evidence. |
| September 24 versioned facts | 174,512 rows for 94 names, filing dates spanning 2009-06-03–2026-09-24 in aggregate. | Every `accepted` value is blank. The implementation conservatively falls back to `filed + 1 day`; separate event acceptance timestamps exist. This is limited timestamp coverage, not a reproduced application defect. |
| Latest-existing tone | 267 files, 11,461 rows; mixed September 5, 14 and 24 vintages. | Model-generated hindsight tone is not contemporaneously archived investor knowledge. |
| Constituents/cohort | Current constituents remain 503 rows dated September 5, 2026; no `membership_history.csv`. The same AAPL/TWTR/SNOW cohort has ten matching source hashes, 720 sessions and zero complete-feature rows. | Retrospective demonstration only. No newly recovered historical opportunity set. |

The extra ETF stems are IGV, IWM, SMH, SOXX, XLC, XLE, XLF, XLI, XLK, XLP,
XLU, XLV and XLY. File counts include overlapping snapshots; no atomic all-store
snapshot or full-file hash certification was performed. The initial CSV count
mistakenly included its leading source comment; the corrected parser establishes
503 rows, not 504. Missing date strings were distinguished from malformed dates.

Evidence, exact scope, corrected outputs and hashes:
`/private/tmp/anios-spark-public-market-inventory.LzgDUd/RECEIPT.md`, SHA-256
`d5d46b9d96b6d6e4d2c3ace3287f2139baf60c9c3f59630f42d8a7ac80140282`.
This inventory does not certify vendor accuracy, historical filing completeness
or all uninspected storage, nor establish that paid data is required.

## First failing implementation boundary

[`book_panel`](../../backend/agents/trading/desk/desk.py) always calls today's
`build_universe()`. Its `asof` argument bounds stored data vintages, not historical
constituency. [`universe.as_of`](../../backend/market/universe.py) exists, but is
not used by that path and its default membership file is absent.

[`nested_market_sources`](../../backend/market/nested_market_sources.py)
correctly leaves `historical_membership_verified` and
`precomputed_report_causality_verified` false. The stock baskets and equal-weight
comparison in the frozen study inherit its reconstructed selected columns; the
price-only gate does not make that opportunity set independently historical.
The existing nested chronological machinery cannot repair this upstream boundary.

## Next bounded task

Locate or obtain, under existing authorized access, dated evidence covering
2015–2026: stable identities, listing/removal and membership events, historical
classifications, effective/public availability clocks, and exited securities'
prices and corporate-action outcomes. Produce a coverage manifest with retained
source hashes and explicit missing intervals before wiring a new adapter.

Today's discretionary overlay has no historical membership to recover. Keep
the existing result labelled a retrospective selected-cohort study. A mechanical
historical eligibility rule would be a separately named, preregistered experiment,
not a silent reinterpretation of the existing book.

**Unverified:** complete historical selection, full financial-input provenance,
delisting accounting, and superiority of `cash-bounded-breakout-rotation/3`
against SPY or QQQ. No source pins, historical studies, holdings, orders or live
strategy were changed. Diagram impact: NONE — evidence audit only.
