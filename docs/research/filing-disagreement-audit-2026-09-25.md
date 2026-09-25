# Why the qualified filing inputs disagree

## Decision

Keep the existing research refusals. This audit found no subtraction,
floating-point or fiscal-partition arithmetic defect in the disputed saved
evidence. It did find two different missing qualifications: reporting precision
and compatible reporting basis across filing versions. Neither is fixed by
choosing whichever number reconciles, preferring a reported quarter unconditionally,
or adding an arbitrary tolerance.

No financial calculation, score, record, live strategy or account changed.
This is new source-level evidence about the explicitly separate
`fundamentals-qualified/1` research mode, not another backtest or a promotion.
Starting source: `a1c2a08557fe28fc923d94498b7b0d25fbf93b75`.

## Scope and verified result

The audit reads the already saved qualified record block and only the twelve
affected original company-facts bodies. It does not rerun the 94-source feature
comparison. Original hashes, JSON pointers, source fields, complete intervals
and signed sums are checked independently of production extraction. Agent
verification uses Decimal; root independently checks the original integer sums.

- There are 16 distinct issuer/concept/full-quarter disagreements across
  twelve issuers (fourteen issuer/quarter pairs).
- They occur in 35 distinct feature cells. Twenty-nine have a top-level
  disagreement reason; six also have a missing-current-quarter reason that
  takes display precedence. The nested disagreement evidence remains present.
- All 47 distinct disputed source pointers validate. Every competing residual
  is an interval-correct YTD subtraction, with no arithmetic error.
- Five annual-derived quarters depend on these disputed amounts. Their twenty
  distinct source pointers and exact sums validate; disputed terms have net
  coefficient -1, not a cancelled-term false positive.

The differences separate as follows; amounts are derived minus reported:

| Evidence class | Cases | What is established |
| --- | ---: | --- |
| One observed integer increment | 12 | Five absolute differences of $1,000 and seven of $1,000,000; actual declared precision is absent |
| Changed and unchanged filing versions mixed | 1 | APLD comparative quarter has a $53.56m difference after its half-year input changes |
| Larger unresolved source differences | 3 | APLD current quarter +$35.12m; BE quarters -$79k and +$158k |

An integer increment is a descriptive property of these numbers, not a way to
infer XBRL precision. Small relative error does not establish harmless rounding.

### ORCL: a small unexplained difference, not a newly revised amount

For September–November 2025, the retained rows give reported revenue of
$16.058bn, half-year revenue of $30.983bn and preceding-quarter revenue of
$14.926bn. The subtraction is $16.057bn, a $1m difference. The latest preceding
quarter repeats its original value exactly; its newer accession does not
explain the discrepancy. No selected row includes `decimals`, precision or a
complete XBRL context. The dependent May 2026 quarter remains refused, and this
does not establish an ORCL buy/dip signal or fair value.

### APLD: demonstrably different retained versions

The June–November 2024 half-year changes from $124.572m in the January 2025
filing to $71.012m in the January 2026 filing. The comparative quarter remains
$52.921m and nine-month amount remains $177.493m. Combining the latter two
periods with the newer half produces $106.481m instead of $52.921m.

The older half exactly reconciles the quarter, but that is not evidence that
the older basis is the right one to use now. The company-facts rows alone do
not explain the accounting change. For APLD's current quarter, the implied
reconciling half-year amount is absent from the retained rows. BE's implicated
same-period amounts are unchanged across their retained filing versions, so
latest-version selection does not explain its two differences.

None of the sixteen comparisons has one retained accession containing all
three required spans. That does **not** mean every comparison is invalid:
ordinary quarterly derivation may need multiple filings. Identical accessions
are neither a universal requirement nor proof of equivalent accounting meaning.

## Independently reproduced selection mechanism

The period engine selects each interval's latest eligible version independently.
It then checks dates, units and arithmetic, without proving that the operands
share an accounting basis. A separate eight-case characterization exercises
both annual and YTD construction through the real public feature path:

- Original coherent amounts agree.
- An identical later Q1 repeat still agrees.
- A Q1-only revision changes the residual while leaving the reported quarter
  unchanged, producing a refusal.
- A complete coherent revision agrees again.

All eight pass in the independent review and root reproduction. These tests
characterize the current mechanism, not an approved replacement behavior or
proof of which disputed amount should be admitted. In particular, the partial
revision mechanism cannot explain ORCL's unchanged-repeat example.

## Primary-standard research

The current XBRL specification index links to
[Calculations 1.1, Recommendation with February 2024 errata](https://www.xbrl.org/Specification/calculation-1.1/REC-2023-02-22+corrected-errata-2024-02-14/calculation-1.1-REC-2023-02-22+corrected-errata-2024-02-14.html),
retrieved September 25, 2026. This is an established reporting standard, not a
new 2026 trading paper.

Sections 5.1–5.2 require appropriate dimensional alignment and compare calculated
and reported value intervals. Section 5.2.3 defines a round-to-nearest interval
from the fact's declared `decimals` value; section 5.2.4 treats truncation
differently, including endpoint inclusion. The processor uses one selected
rounding mode consistently within a report; the filing need not declare that
mode. These rules support recovering actual precision
metadata rather than inventing a percentage tolerance.

This is **not** a claim that AniOS implements Calculations 1.1, or that the
standard automatically validates cross-period YTD subtraction. Its taxonomy
summation bindings use dimensionally aligned facts; separate fiscal periods and
filing bases require their own declared compatibility checks. Interval overlap
can establish numerical consistency under a declared model, not economic truth
or the correct current reporting basis.

## Next evidence and implementation boundary

Before changing admissibility, recover the original inline-XBRL or instance
facts for the exact implicated accessions, preserving raw bytes and hashes,
fact IDs/contexts, entity/consolidation dimensions, units, scale/sign/transforms,
declared precision and publication evidence. For APLD/BE, also establish the
reporting/revision basis from the filing disclosures. Do not replace the retained
company-facts packet or saved research records.

Then define a versioned comparison contract that distinguishes:

1. Unknown precision or unestablished reporting-basis compatibility.
2. A numerically consistent comparison under justified precision and basis.
3. A genuine same-basis numerical discrepancy.

Admission of values is a separate decision from explaining a refusal. Test
partial revisions, identical repeats, coherent revisions, true discrepancies,
negative/zero/truncated values and interval boundaries before changing the real
consumer. Do not globally require one accession or silently fall back to older
values. No new financial-source acquisition or such implementation occurred in
this audit; only public specification pages were fetched.

## Evidence and limitations

The source record block has SHA256
`f08af24259bbf5610f915fc983616e7d8fa8d54b70aa287854c725174abe2dda`;
the original packet manifest has SHA256
`f0b5cc2e0540f35f10c7bf8ecbb6132f8c102af3432f84ef99e4851a0722021b`.
Full original rows, all sixteen comparisons, retained versions and dependent
paths are in `/private/tmp/anios-disagreement-classification.1dH6Do/`.
The independent characterization is in
`/private/tmp/anios-vintage-review.ofASnl/`; root verification and the retained
standard are in `/private/tmp/anios-filing-disagreement-root.WlJyYg/`.
Exact hashes and commands are recorded in the current handoff/root receipt.

VERIFIED: scoped source arithmetic, retained-version differences and the
controlled selection mechanism. FAILED: the initial guessed specification URL
returned 404; the official index supplied the corrected linked URL.
UNVERIFIED: actual rounding cause, current accounting basis, source authenticity
at historical decision times, complete financial coverage, live deployment and
investment performance. This disagreement-only audit does not certify the 430
accepted feature cells; absence of a conflicting path does not establish their
accounting basis. No new behavior is claimed from unchanged source tests.

Diagram impact: NONE — research evidence and a next-step contract, with no
component, data flow, persistent store or deployment change.
