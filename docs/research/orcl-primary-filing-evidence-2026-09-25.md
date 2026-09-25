# Oracle's original filing: observed precision, incomplete comparison

## Result

Keep the existing research refusal. Oracle's original FY2026 Q2 filing now
establishes the precision and accounting scope of two disputed inputs, but the
preceding-quarter primary filing is still missing. Applied Digital's original
filing request failed. Neither case justifies changing arithmetic, admitting a
value or restoring a fundamental score.

This advances the [disagreement audit](filing-disagreement-audit-2026-09-25.md),
which had only company-facts rows without declared precision. It is a bounded
public-source investigation, not a backtest, valuation or strategy promotion.
Starting clean `main`: `e44ddd6663b085df2b710f23cb8d06b5eb4405e5`.

## Original source and exact matches

The [SEC filing index](https://www.sec.gov/Archives/edgar/data/1341439/000119312525315925/0001193125-25-315925-index.html)
identifies sequence 1, `orcl-20251130.htm`, as the 10-Q for November 30, 2025.
Its displayed filing date is December 11, 2025, and its displayed acceptance
text is `2025-12-11 16:07:47`. The index does not display a timezone; that text
has not been converted into a historical decision-time input.

The [primary document](https://www.sec.gov/Archives/edgar/data/1341439/000119312525315925/orcl-20251130.htm)
was retrieved September 25, 2026 at 23:04:31 UTC. Its complete received body has
SHA256 `337896d345d5e4873e896b6fce82887b90892c88c62bfe3f2e0e8975776b46f0`.
Printed page 2 is the unaudited **Condensed Consolidated Statements of
Operations**, for the three and six months ended November 30, 2025 and 2024,
with units stated as **in millions, except per share data**.

Both current-period values occur in the same **Total revenues** row:

| Full period | Literal text | Declared scale / decimals | Corresponding retained company-facts amount |
| --- | --- | --- | ---: |
| September 1–November 30, 2025 | `16,058` | `6` / `-6` | $16,058,000,000, row 101 |
| June 1–November 30, 2025 | `30,983` | `6` / `-6` | $30,983,000,000, row 100 |

The original rows are under
`/facts/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/units/USD/`
in the previously retained ORCL body. Its unchanged SHA256 is
`65523545f040abaea1dfcf321da2a5aec85e7f34387244b0ffcb26e4c8707f7d`.
Both accession/date/value matches were independently checked.

The primary statement facts are:

- Quarter: `F_23f40c56-a7ac-4cab-8418-48da10f82a9d`, byte range
  `[429166, 429437)`, context `C_e2121f4b-28ae-4556-bd98-451b676d1bda`.
- Half-year: `F_9017526c-9fe6-4ea5-8a48-61414de6a5ea`, byte range
  `[432800, 433071)`, context `C_657d904d-ca53-46a5-9515-07d241e6ee75`.

Each is `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` in
`http://fasb.org/us-gaap/2025`. Each context identifies CIK `0001341439` and the
complete period above, with no segment, scenario or dimensions. `U_USD` resolves
to `iso4217:USD`. The format is `ixt:num-dot-decimal`, namespace
`http://www.xbrl.org/inlineXBRL/transformation/2022-02-16`. Neither fact declares
`sign`, `precision`, `nil` or a continuation. Each repeats identically in a
geographic table's Total revenues row; those repeats are not extra observations.

Note 1, printed page 6, says revenue reclassifications conformed the presented
periods but **did not affect total revenue, income from operations or net
income**. That disclosure does not explain the $1m residual. No explicit
round-to-nearest/truncation rule was located. The separate MD&A statement that
percentage changes use actual, unrounded results does not establish such a rule.

## What remains unknown

The preceding quarter's $14.926bn remains supported here only by the previously
retained company-facts rows. A later filing index was acquired successfully:
accession `0001193125-26-389274`, report period August 31, 2026, primary document
`orcl-20260831.htm`. Its comparative Q1 document was **not** acquired. An index
does not establish that document's fact precision, dimensions or reporting basis.

Thus $30.983bn minus $14.926bn still differs from $16.058bn by $1m, and complete
three-input precision/basis compatibility remains unverified. Observing
`decimals="-6"` on two operands is not permission to infer it for the third,
select a rounding mode, apply a global epsilon or declare the difference benign.
The dependent May 2026 quarter remains refused. No general inline-XBRL transform
or Calculations 1.1 processor was implemented.

For APLD, accession `0001144879-25-000006` returned HTTP 503 with a **SEC.gov |
File Unavailable** page. It is retained as error evidence, not a financial
filing. Neither APLD's $53.56m comparative-version difference nor its $35.12m
current-quarter difference has a newly established accounting explanation.

## Acquisition and independent verification

Four sequential requests produced statuses **200, 200, 200, 503**: ORCL Q2
index, ORCL Q2 document, ORCL later-Q1 index, APLD original index. Acquisition
stopped at that failure, without retry, redirect, mirror request or access
workaround. No further SEC request was made. Three responses were usable, but
only **one was a primary filing**. Total retained bytes: **3,799,931**.

The temporary collector used the existing committed contact header, without
loading settings or credentials; exact allowlisted accession directories; at
least 1.05 seconds between request starts; a 30-second timeout; and streamed
retained-body limits of 1 MiB/index, 12 MiB/document and 64 MiB/packet, with at
most ten requests. These are retained-byte limits, not proof of a transport
buffer-memory ceiling. All original bodies and request metadata passed readback
hash checks. The primary's received size differs from the index's declared
document size; the received bytes, including the trailing script element, were
preserved, not edited or executed.

The temporary offline inspector uses strict XML parsing, without recovery,
custom/external entity expansion or fetching external resources. **11 tests pass**, zero
failures/skips, in the root repeat. An initial root test invocation failed
before collection because the read-only container had no writable temporary
directory; adding a container-local `/tmp` resolved it without test changes.

The inspector extracts 60 canonical revenue occurrences, 56 referenced contexts
and one unit. A separate ElementTree pass independently checks all **117**
original-byte element ranges and parsed identities/text. Four current-total
occurrences agree. Root additionally verifies the two original statement cells,
their common row, exact entity/period structure, units, declared metadata and
company-facts pointers. A network-disabled execution proves the existing 503
stop prevents another request or evidence write. No runtime application behavior
is claimed from these research checks.

Evidence root: `/private/tmp/anios-filing-primary.NIogyK/`:

- `requests.jsonl`: `3509f0dc04fd06dde7b847f4598ce1f75b82ac5d93ec03372c2a14ace3bc097c`.
- `orcl-q2-root-inspection.json`: `c0c56ef2433d2261fd62326c905021b131d5ff8650ba7f7eb05f96ebae961c97`.
- `root-verification.json`: `a68d3adefe88628a4a034b1e4c5f4e3b76384ed33fc8893012aee47b626282ea`.
- Independent inspector/proof: `/private/tmp/anios-filing-inspector.2pDu06/RECEIPT.md`,
  `35fa9d59b743394f7285f9936a15027e699c4dc763e611c01af589f3e08d127e`.

These temporary paths are local research artifacts, not a durable source-ingestion
service. Hashes establish agreement with the retained bytes, not signed SEC
provenance or authentic availability at a historical trade decision.

VERIFIED: two ORCL original statement inputs' scope/declared precision and exact
source matches. FAILED: APLD original-index acquisition; initial temporary-test
environment. UNVERIFIED: full ORCL comparison, discrepancy causes, APLD accounting
basis, historical authenticity, fair value, full financial coverage and returns.
Backend, frontend, archived records, strategies, learned inputs and accounts are
unchanged; no fit, historical strategy rerun, deployment or service change.

Next source step: complete the missing exact primary-filing evidence after
source availability changes or a separately verified public issuer source is
identified. Do not automatically retry the failed endpoint, repeat the completed
company-facts audit, or construct a tolerance to manufacture acceptance.

Diagram impact: NONE — retained public research evidence only; no implementation,
component, store, trust boundary or deployment relationship changed.
