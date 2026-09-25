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

## Public-source shortlist, checked September 25

This is a **documentation comparison, not validated vendor data or confirmed
access**. The first decision is what authorized access already exists. No
purchase, signup, market-dataset download, adapter or source-pin change occurred.

| Candidate | Primary documentation supports | Still required / caveat |
| --- | --- | --- |
| CRSP US Stock | Permanent PERMNO/PERMCO identifiers, dated security/issuer histories, delisting outcome/reason/successor/missingness fields and distribution declaration/ex/payment dates in the July 31, 2026 CIZ guide. | Strongest inspected documentation for identity and terminal returns, not proof of delivered September 2026 coverage, original publication clocks, GICS or PIT fundamentals. Licensed-use and retention rights unverified. |
| Compustat via WRDS | Public catalog lists PIT, Snapshot, Preliminary History and Unrestated Quarterly as separate products. | Standard Compustat entitlement is not PIT access. Historical classifications, first-filed/revision semantics and time-valid security joins need entitlement-specific schemas and samples. Detailed documentation required sign-in. |
| Norgate US Platinum | Delisted US prices and daily historical index membership; advertised USD 630/year. | Explicitly lacks historical fundamentals/classifications, index-announcement dates, historical ticker/name mapping, delisting returns/reasons and correction versioning. Temporary index inclusions are excluded. Windows updater and license limits affect collection, redistribution and retained raw evidence. A partial price/membership source, not a complete solution. |
| Public reconstruction | Existing SEC cohort shows filing-based identity/merger evidence; Nasdaq documents current symbol fields. Community `fja05680/sp500` README advertises membership history since 1996. | Current directories are not historical archives. Community event completeness/provenance, latest coverage and licensing remain unverified. None establishes a complete price, identity, classification and terminal-accounting source. Public reconstruction remains worth investigating. |

Primary sources: [CRSP product](https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases),
[July 2026 guide](https://indexes.morningstar.com/docs/guide/crsp-us-stock-databases-guide-for-flat-file-format-2-0?isRdp=true),
[WRDS S&P catalog](https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/sp-global-market-intelligence/),
[Norgate coverage](https://norgatedata.com/data-content-tables.php),
[limitations](https://norgatedata.com/data-package-faq.php),
[license](https://norgatedata.com/subscribe/eula.php),
[Nasdaq directory definitions](https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs),
and [community README](https://raw.githubusercontent.com/fja05680/sp500/master/README.md).
Several SEC/S&P pages returned HTTP 403; no access controls were bypassed.

Two accounting distinctions cannot be omitted: CRSP assigns a delisting return
to the next trading date by convention, not as proof cash settled then; CIZ
aggregate returns may already include it, so do not double-count it. Norgate's
suggested final-available-bar exit is not an ex-ante executable decision. Neither
can silently become spendable cash in the funded simulator.

Full bounded comparison, source URLs, failed checks and excerpts:
`/private/tmp/anios-historical-source-options.1E5gSX/RECEIPT.md`, SHA-256
`d48102e18db8c39606aaec495a57db67cc6cedf8cbc0e74fc1dacad6e2607708`.
The 97-page primary CRSP guide is retained with SHA-256
`e42f452207d4a30ef05de542a2dac9522f240100cec99a0309b1b3ab20699ec6`.
This is not an exhaustive source survey and does not establish that paid data
is necessary. Request an entitlement-specific coverage/sample packet before
wiring an adapter; no one source reconstructs today's discretionary overlay.

## Bounded public reconstruction audit

The shortlisted [`fja05680/sp500`](https://github.com/fja05680/sp500) source was
subsequently inspected directly on September 25. **Qualified as a reconstruction
seed; rejected as ready-to-use point-in-time membership.** Six raw files were
retained with content hashes (5,647,284 bytes). No authenticated data endpoint,
purchase, adapter, fit or strategy replay was used.

- The updated history contains 2,720 dated membership rows from 1996-01-02 to
  2026-08-18. From the 2014-12-24 seed for the 2015 study start, 607 rows contain
  771 distinct ticker strings; 268 are absent from the final 503-name snapshot.
  Those 268 strings are not necessarily delisted securities.
- All 125 recorded 2019–2026 add/remove rows reconcile internally; the final
  history matches the bundled current 503 names exactly. This does not establish
  independent event completeness. The last event is 38 calendar days before
  inspection, not proof that an intervening change was omitted.
- The root license is MIT. The inherited book/Wikipedia data's upstream rights
  were not established; a repository license alone does not resolve them.
- Historical schemas are only `date,tickers` and `date,add,remove`: no separate
  announcement clocks, source citations, stable share-class identities or
  historical classifications. Current CIK/GICS fields do not fill these gaps.
- The notebook strips `SYMBOL-yyyymm` suffixes, and the README proposes selling
  on symbol changes. Neither is a valid substitute for security continuity or
  funded corporate-action accounting. The notebook was inspected, not executed.

GitHub metadata requests timed out; successful raw files are content-hash pinned,
not commit-pinned. Do not set announcement equal to effective date, carry current
classifications backwards, or treat the download date as historical availability.
`backend/market/membership.py` requires cited entry/exit announcement evidence;
these files cannot legitimately populate that contract as supplied.

Receipt: `/private/tmp/anios-sp500-source-audit.hMbyyQ/RECEIPT.md`, SHA-256
`2361703c0e6b135a77dfd0a39c2b4932f405260d1e89e20588d63bb42e4e7b4d`.
Machine-readable audit SHA-256:
`9da64c866ec63f91a00eb5812a8d38f48ce5c09fe69b3d78d1d67ba05bff8565`.
It retains exact URLs, raw-file hashes, schemas, all event comparisons and failed
requests. Source correctness, upstream rights and September completeness remain
unverified. No source pins or eligibility rules changed.

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
