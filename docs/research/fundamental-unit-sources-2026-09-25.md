# Unit-preserving fundamental sources — September 25, 2026

## Decision and first failing boundary

The current versioned-fact parser chooses the largest unit group in the entire
company-facts snapshot and drops the unit before storing a `Version`. This can
make a later snapshot change earlier inputs even though the downstream selector
uses filing dates correctly. A synthetic reproduction appended only future EUR
rows to four already-known USD quarters: earlier trailing revenue changed from
460 to missing. A second assertion confirmed the stored frame contains no unit.
Both failures are retained; they are not fixed in the legacy path by this change.

`desk._fundamental_opinion`, learned-input and shadow paths use the existing
versioned loader. Some older module/research prose saying it is unused by the
desk is stale. Changing the parser or `VERSION` alone is not a safe migration:
the loader ignores frame metadata, and immutable same-day partitions are not
rewritten by a refresh. A new unit cannot be recovered from an old unitless
number by assuming the issuer's current currency or the stock's quote currency.

The new `fundamental_unit_sources` module is an **isolated research source
boundary**. It is not wired into the live desk, refresh, shadow model or an
automatic loader. It does not alter old frames, source pins or strategy results.
The old two failures remain strict expected-failure regression cases, not passes.

## Contract

- `parse(body, expected_sha256=..., expected_cik=...)` authenticates the supplied
  original JSON bytes against their declared hash and issuer before extraction.
  Duplicate JSON keys, inconsistent envelopes and conflicting same-observation
  facts fail. Recognized valid source rows retain their exact unit, accession,
  filing/acceptance fields, fiscal period and original JSON-pointer position.
- Every valid unit group and filing vintage remains represented, including
  unsupported currencies and identified duplicate extracted observations. Invalid rows and
  absent unit evidence have explicit exclusions. No largest-group choice occurs.
- `project(source)` explicitly admits USD monetary values, `shares` share counts
  and `USD/shares` EPS into the existing `Version` vocabulary. Other units remain
  in the source but are excluded from that projection. No FX rate, reporting
  currency or share conversion is inferred.
- `frame(source)` returns caller-owned columns and separate schema metadata;
  `from_frame(..., source_body=...)` re-extracts the original bytes and compares
  the complete frame, not merely a caller-recomputed frame checksum. Old unitless
  frames and missing/wrong schemas are rejected by this new boundary.

The reserved kind is `edgar_facts_unit_sources`; the existing
`edgar_facts_versions` kind is untouched. There are no store or network calls.
Source bytes are public research evidence, not private account data. Persistence
and retention remain explicit caller operations, outside Git and the public UI.

Missing acceptance time retains the existing conservative `filed + 1 day`
fallback. An explicitly malformed, empty or timezone-naive timestamp must not
become an invented instant. Acceptance before the fiscal period ends and
unrepresentable availability dates are excluded. Malformed instant-period
fields cannot become absent dates through truth-value coercion.
Accepted and filed dates need not be identical:
the retained AAPL 2022 index has acceptance October 27 and filing date October
28. Neither a nearby earnings release nor a matching fiscal quarter supplies
an exact-accession publication clock. Existing cached earnings events cover
8-K item 2.02, not a complete 10-Q/10-K acceptance archive.

## Actual public source measurement

One unauthenticated SEC company-facts request for ASML, CIK 937966, returned
HTTP 200 at 2026-09-25 16:48:09 UTC. It used the existing application's SEC
identification header, no credentials, retries, redirects or paid service.
The 1,837,771 retained bytes have SHA-256
`28be6fd0f5608350ec396ae5d5097e45da95f4f29ad3fbd19aac328a15cce3d4`.
This consumes no authenticated quote/history probe and supplies no prices.

The 647 recognized valid observations contain 487 EUR values, 102 EUR/share
values and 58 share counts. The USD projection admits the 58 share observations
and excludes the other 589 without relabelling them. **This does not mean EUR
margins are inherently wrong:** EUR numerator/EUR denominator can be compatible.
The issue is lost dimensional evidence, particularly when combining company
facts with USD market capitalization. A separate currency-consistent ratio path
or dated FX conversion would need its own declared, tested contract.

The final real-source exercise checked 5,176 source fields/positions, persisted
the JSON frame, reloaded it against original bytes and rejected a saved EUR→USD
relabel. Source and code stayed unchanged. The saved frame matches the first
exercise exactly, SHA-256
`b8889397663e94f3682758df598b97a8bfe25f7428557feb76af4e3d1ff45b07`.
The automated suite separately exercises a synthetic mixed-unit Parquet
write/readback against original source bytes.

**VERIFIED scoped acceptance:** 189 passed, one existing missing-Torch skip,
three strict legacy expected failures and 24 existing empty-slice warnings,
6.41 seconds. The three expected failures are the two reproduced unit defects
and the previously recorded frozen price/share-basis defect; none is counted as
fixed. Independent review has no outstanding findings. Scoped Ruff and format
checks pass, as do all 33 unchanged canonical diagram/page checks. No live model,
UI, provider-coverage or deployment acceptance was attempted for this isolated
helper. The skipped optional model path remains unverified.

Final production SHA-256:
`b1baeec6ac73f4b9e7c8f82ce7b0f13bf6590e78faac1bf9041affb29d79168c`.
Evidence: `/private/tmp/anios-fundamental-units-final.t7P1uR/RECEIPT.md`.
Initial evidence and reproduced failures remain under
`/private/tmp/anios-fundamental-units.pkKxBnJd/`.

## Limits and rollout requirements

This source boundary does not establish publication authenticity, exhaustive
filing coverage, share-class/ADR/split consistency, historical universe membership,
or investment quality. A matching CIK identifies an issuer, not a time-valid
tradable security. Unit labels alone do not make a USD price times a share count
a verified market capitalization.

Before changing a live consumer: retain qualified raw source snapshots for its
full universe; measure supported/unsupported units and exact-accession clock
coverage; use a distinct schema/kind with explicit unavailable states for legacy
data; verify same-date partition isolation and unchanged original bytes; compare
feature and grade differences without trading; then seek the scoped rollout.
No automatic collection, legacy-cache migration, model fitting or strategy
promotion is included here.

Diagram impact: NONE — internal input representation within the existing filing
and research boundary; no live path, store or external dependency added.
