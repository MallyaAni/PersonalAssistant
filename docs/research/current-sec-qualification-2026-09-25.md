# Current SEC source qualification — September 25, 2026

## Purpose and source boundary

Qualify original company-facts responses before replacing the current desk's
unitless financial inputs. This is a current-data correctness exercise, not a
strategy backtest, valuation estimate or recovery of historical source bytes.
The starting implementation is `c42ace690ac960750acaa5c70e12981a9ea8d673`.

The current book resolves to 94 stocks and 94 distinct CIKs. One public ticker
map and one company-facts request per issuer produced 95 HTTP 200 responses,
without retries, redirects, authenticated market-provider calls or account
operations. Acquisition ran September 25, 21:13:32–21:15:12 UTC, after the
regular session. All original response bytes were retained and independently
checked against their sizes and SHA256 hashes.

Received bytes total 279,738,506; the largest body is 6,172,548 bytes. Minimum
request-start spacing was 1.050756 seconds. The 25-MiB response and 512-MiB
packet limits were post-response rejection thresholds, **not streaming caps**.
HTTP success establishes retrieval, not usable financial coverage.

Packet: `/private/tmp/anios-current-sec-snapshot.XRErYJ4u/`.
Manifest SHA256:
`f0b5cc2e0540f35f10c7bf8ecbb6132f8c102af3432f84ef99e4851a0722021b`.
Readback SHA256:
`0bbca0d81409625ee6a59b6e09ff45eeff327bba0c5587c11af343876e12d58b`.
Acquisition receipt SHA256:
`b6b4dfa4a0aabfd9c0733e6c5380796401885434468190282dfcd4b82c2d294b`.
This is retained session-local evidence, not a deployed ingestion/archive service.

## Observed parser defect

Every response identifies the expected issuer numerically. However, 12 bodies
use a ten-character, zero-padded ASCII string for `cik`; the other 82 use JSON
integers. The original unit-source parser's strict integer check rejects all 12
strings before reading any financial fact. APLD, ALAB, CRWV, CRDO, GLXY, CEG,
IREN, HUT, ARM, GEV, SNDK and Q are therefore parser refusals, not missing
downloads or mismatched issuers.

The correction accepts either the integer representation or exactly ten ASCII
decimal characters, still requiring equality to the caller's strictly positive
integer CIK. It does not accept arbitrary numeric coercion, alter raw response
bytes or weaken hashes, duplicate-key checks, unit checks or fact conflicts.
Existing schemas and frame metadata remain unchanged. In particular, a CIK
identifies an issuer, not a historically valid ticker or tradable share class.

Original parser coverage was 82 accepted / 12 refused. Accepted sources retained
169,996 facts and projected 168,856 into supported USD/share dimensions, with
172 schema exclusions and 1,140 unsupported-unit exclusions. ASML has no
supported monetary projection. The original `coverage.json` field
`unavailable_tickers: []` means no **download** was missing; the separate
`qualification-summary.json` explicitly distinguishes parser eligibility.
Original diagnostics and raw bodies must not be overwritten by corrected runs.

## Current desk features: what the original source actually produces

The unchanged legacy parser accepted all 94 bodies. One `ff.features` call on
a real September 25 `Panel` evaluated all 94 stocks plus SPY. Price arrays were
NaN because this feature adapter reads dates and tickers only. No price, live
grade or trade was evaluated. Each selected concept, tag and largest-unit group
was frozen for comparison; no alternate tag or currency was substituted.

| Current feature | Finite | Missing concept | No shared quarter end |
| --- | ---: | ---: | ---: |
| Gross margin | 68 | 24 | 2 |
| Net margin | 90 | 1 | 3 |
| Operating cash flow / revenue | 90 | 1 | 3 |
| Capex / revenue | 89 | 2 | 3 |

The 376 current cells contain 337 finite ratios and 39 missing values. This
specific snapshot showed no selected-unit mismatch, unequal/ambiguous matched
current interval, or invalid current annual partition. Annual-partition checks
covered 134 operand occurrences. That does not remove the synthetic known-defect
tests or prove that source-labelled fiscal amounts are economically correct.

The original unit-source parser allowed 307 same-tag/unit helper comparisons:
296 finite values agreed exactly, and 11 were missing. Its 12 issuer refusals
left 41 current margin cells unqualified; another 28 lacked selected concepts.
This comparison does not adopt the helper's older-full-interval fallback as
the desk's `/2` selection policy.

**Material next boundary:** 96 of the 337 finite margins reference periods at
least 365 days old; 93 are at least 730 days old and 80 at least 1,825 days old.
Those are descriptive ages, not new eligibility cutoffs. The current selector
chooses the tag with the most available quarterly periods. That can keep an
old concept after a different candidate starts carrying current data:

- AAPL's four margins reference June 30, 2018.
- ORCL's selected `Revenues` ends May 31, 2022; its gross margin references
  March 1–May 31, 2018, despite other operands carrying August 31, 2026 facts.
- AMZN's gross margin references September 30, 2009.

Independent source tracing identifies why the older revenue tags win:

| Issuer | Selected tag: quarter count, latest end | Alternative customer-revenue tag: quarter count, latest end |
| --- | --- | --- |
| ORCL | `Revenues`: 44, 2022-05-31 | Excluding assessed tax: 37, 2026-08-31 |
| AAPL | `SalesRevenueNet`: 40, 2018-06-30 | Excluding assessed tax: 35, 2026-06-27 |
| AMZN | `SalesRevenueNet`: 40, 2018-06-30 | Excluding assessed tax: 38, 2026-06-30 |

All three alternatives have USD observations available under the existing daily
cutoff. This establishes a selection problem, not universal tag equivalence.
For example, AMZN's two capex candidates tie on 35 quarters, but their concept
descriptions differ: productive assets include software and other intangibles.
The same 2016 annual period carries 6.737 billion for property/plant/equipment
and 7.804 billion for productive assets. A freshness fix must not silently
substitute one definition for the other.

ORCL also has a same-accession ambiguity requiring filing-context verification:
`0001564590-22-023675` reports `Revenues` of 42.440 billion over
2022-03-01–2022-05-31 and customer revenue of the same amount over
2021-06-01–2022-05-31. Equal amounts over different durations are not alone a
mathematical contradiction. Neither an economic correction nor a new period
can be inferred merely from the amount, and no raw field was changed here.

Trace receipt: `/private/tmp/anios-current-tag-trace.ABw9iXdy/RECEIPT.md`,
SHA256 `54689273d9c3533eaa7d07062b48d3446a252fceacd100f1c17160e8b5dbe1af`.
The compact result, including exact source observation paths, has SHA256
`f4262adda1e37c95e78c0f1529550e84171001525fd4aeb251fa22710e7ebf54`.

AAOI's gross, net and operating-cash-flow ratios reference April 1–June 30,
2026; capex/revenue references January 1–March 31, 2026. Matching those amounts
does not establish fair value, a good entry price or a buy instruction.

Diagnostic: `/private/tmp/anios-current-fundamentals.YM4BqO/diagnostic.json`,
SHA256 `f29d11849c346f6c6c120b926aa665ff3414237602b9e3408d457e3c92e0f0d9`.
Its receipt SHA256 is
`889c9f451d3fabd677ce8cfe3b798799bf9a4062c5b331e59753ab05f5f6b02e`.
Before/after hashes confirm the input packet and six production modules stayed
unchanged. The initial harness CIK-type failure is retained; correcting the
harness did not change either production parser.

## Corrected parser acceptance

The independent exact-predecessor comparison accepts **94/94 issuers** under
the corrected parser, without a subsequent whole-source refusal. The original
82 have identical typed facts, exclusions, projections, frame columns/metadata
and availability values. All 12 newly admitted issuers, and all 94 in total,
pass JSON serialization, deserialization and frame restoration against the
unchanged original bodies. This is not a deployed storage-persistence check.
Hashes, raw CIK types and all pinned dependencies remained unchanged.

The corrected source retains 174,828 facts and projects 173,688. There are 181
schema exclusions: the original 172, plus two from IREN and seven from HUT.
The 1,140 unsupported-unit exclusions remain unchanged. Exact acceptance
timestamps remain absent; all retained rows use the existing filing-date
fallback. Parser completeness is not financial-feature completeness.

Root's eight-suite acceptance: **318 passed**, one optional missing-Torch skip,
four strict known-defect xfails, 24 existing warnings, 2.70 seconds. The new
synthetic identity tests originally had 25 intended failures and 64 passes on
unchanged source. An earlier test attempt also had five incorrect expected row
orders; both original reports are retained. Correcting fixture order did not
change the extraction order or weaken product assertions. Agent acceptance:
241 passed and four known strict xfails, no skips.

Scoped Ruff/format, independent source/document review and all 33 unchanged
diagram/page checks pass. No frontend or model behavior changed, so this is not
a new UI or model acceptance claim. Root receipt:
`/private/tmp/anios-cik-root.EPWw1D/ROOT_RECEIPT.md`; root JUnit SHA256
`74b14b8325e5f6fb9a96720695f75f2eeb5688611a95343ac59eee080d149983`.
Full retained-source differential: `/private/tmp/anios-cik-differential.GuNzdH/`.
Its receipt SHA256 is
`35a2fb8228ab962395e771cb519cf0d7fcbb7381430bdf159d9982e9dbce3d71`;
candidate report SHA256 is
`e424bb99ef20f39a168675fb30f1b1f4c289e19cdcf96cdd999ee19d4b823479`.
Corrected production module SHA256:
`3cb4be7ccac3d20fc79f354cc4449ff4bdb4922d0314bcdfde112d2dfe4c7404`.

## Remaining requirements for the connected desk migration

A unit-aware helper alone will not make these old metrics current. The next
source-backed path must define concept comparability and current-period
selection, preserve unit/interval/derivation lineage, and expose unavailable
reasons for rejected names as well as scored names. A recent filing activity
counter is not proof that each cited metric is recent. The existing nightly
writer omits fiscal-date metadata when a name has no finite fundamental score;
that is insufficient for a future rejection-evidence contract.

Do not globally change `fa._quarters`, learned inputs or frozen studies. Do not
strip `UnitSource` back to unitless versions and label the result unit-aware.
Preserve valid reported-quarter precedence, reject incomplete annual partitions
without reviving an older ratio, and retain distinct old/new source identities.
Selecting the newest date indiscriminately is not enough: tax treatment,
financial-statement scope and reporting conventions can differ between tags.

All 175,009 recognized raw rows lack an exact acceptance timestamp. Filing-date
fallback is not historical publication authentication. The current packet does
not recover the missing September 18 raw sources, establish share/price basis,
validate `/3` against SPY/QQQ, or justify promoting any trading policy. No
deployment or live input switch is part of this parser correction.

Diagram impact: NONE — representation compatibility within an existing isolated
research input boundary; no new live dependency or collection path.
