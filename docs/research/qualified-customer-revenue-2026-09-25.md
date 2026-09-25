# Source-backed customer-revenue research

## Decision and scope

The explicit `qualified` desk mode connects original-byte filing archives to
the real fundamental analyst, grading path and saved research record. Its source
identity is `fundamentals-qualified/1`; its metric profile is
`customer-revenue-ex-tax-usd-quarter/1`. These identify a calculation contract,
not economic truth, fair value or an adopted trading strategy.

This replaces neither existing mode nor the nightly default. `corrected` remains
`fundamentals-features/2`, `current` remains `/3`, and `market_daily` still selects
`current`. Learned inputs, saved historical records and examined strategy
results keep their original identities. The new mode requires `inputs=()`;
the CLI supplies this explicitly. A learner fitted to another financial profile
cannot be activated merely by choosing the new source mode.

Only the **fundamental analyst** uses the new profile. Other analysts, including
the existing valuation inputs, retain their own paths. A full desk grade from
this research mode is not a claim that every analyst's data is now qualified.

## Accounting contract

Revenue is exactly
`us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`, in literal `USD`.
The profile never substitutes generic `Revenues`, `SalesRevenueNet`,
tax-inclusive customer revenue or a similarly named IFRS concept. Its growth
lags come from this same concept and unit, without historical tag stitching.

There is no defensible universal priority order over those different concepts.
Assessed-tax scope, returns/discounts, and principal-versus-agent gross/net
presentation are separate distinctions. Exact matching historical amounts can
corroborate those particular observations without proving universal aliases.
Literal USD also does not make growth constant-currency or accounting policies
comparable across companies.

The latest valid decision-eligible reported revenue end across recognized
source rows is a **rejection-only frontier**. A newer alternative tag or unit
can withhold an older canonical quarter; it cannot donate an amount. A missing
current quarter does not revive an older shared interval. Annual or YTD evidence
can advance the frontier without proving a quarter is derivable.

Growth remains log-ratio growth. The lag convention is the existing nearest end
within 20 days of `91 * quarters` days earlier, then full-interval ambiguity and
value checks at that selected end. A bad nearest candidate cannot be skipped to
borrow a more convenient one. The convention is explicit, not a guarantee that
every unusual fiscal calendar is economically comparable.

Each margin requires one identical complete USD interval for its numerator and
canonical revenue denominator. Numerators are exactly `GrossProfit`,
`NetIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`, and
`PaymentsToAcquirePropertyPlantAndEquipment`, all in `us-gaap`. The last is
PPE purchases, not a substitute for purchases of productive assets that include
intangibles. Missing gross profit is not inferred from costs and expenses.

Quarter derivation reuses the unit-preserving full-period machinery. YTD
differences retain signed source terms; an annual residual requires contiguous,
unambiguous Q1–Q3 covering the annual prefix. All contributing availability
dates remain explicit. Reported quarters have precedence only when no finite
same-interval derived amount disagrees. A disagreement, or dependence on a
disputed reported component, makes the selected amount unavailable, with both
paths retained. Equal values are not described as proof of source authenticity.
The older period helper and `/2`/`/3` calculations remain unchanged.

## Archive and consumer path

`fundamental_source_store` writes one raw binary response per symbol/as-of date
under `edgar_facts_unit_archives`, with a distinct archive schema. It revalidates
the UnitSource against its original bytes, retains hash/CIK/caller-declared
capture time, and re-extracts on read. POSIX file locking serializes cooperating
writers; same-date imports cannot replace the first stored response. Different
legacy kinds remain untouched. A malformed newest archive is an error, not
permission to use an older archive or a unitless fallback.

The original-byte importer accepts an already acquired local source only,
bounded to 16 MiB. Hash, issuer, symbol, as-of date and aware capture timestamp
are explicit arguments. A capture cannot be assigned to an earlier New York
calendar date. This is not proof that the source was available at that day's
market close, and a caller-supplied capture timestamp is not independently
authenticated acquisition evidence. No provider request is made.

The connected path is:

`original bytes → immutable archive → declared-concept features → fundamental
opinion and vote resets → desk grades → source-labelled research record`

Every accepted or refused metric retains its reason, full selected intervals,
source hash/CIK, original JSON pointers, accession, filing/acceptance dates and
signed derivation components. Missing sources remain explicit. Source-level
parser exclusions are labelled `whole_source_not_point_in_time`; they do not
claim to have been known at each reconstructed decision date.

Immutable ticker/date anchors bind feature rows to the requested panel. The
loader compares hash and strict integer CIK to its actual loaded archives.
The analyst checks declared profile/units/periods and numerical evidence;
the record writer checks the final row's ticker and decision date again.
Source-bearing records require matching archive provenance, not only a hash
copied into a result. Loss of an admitted scored leg restarts vote confirmation,
as in `/3`; an absent score cannot retain an old fundamental vote.

## Operating the research path

The importer requires `--data-dir`, `--source`, `--sha256`, `--cik`, `--ticker`,
`--asof` and `--captured-at`. The last two identify the source archive, not the
fiscal period. Its JSON receipt reports the actual stored hash separately from
the requested hash when an existing same-day response is kept.

Run the desk with `python -m backend.cli.market_desk --fundamentals qualified`,
an explicit `--data-dir` and `--asof`. A complete desk also needs its normal
cached price and other analyst inputs; importing financial sources does not
create those. `--research-record-root` optionally saves through the real record
writer into a separate directory. Resolved root/desk and final dated-record
destinations cannot lie inside the input market store, including existing
directory symlinks. These are accidental-path checks, not hostile-race protection.
The existing record writer refuses a sequential overwrite; unlike source archive
imports it has no exclusive concurrent-create guarantee. Run one record writer
per destination. No order, holding, paper-account or runtime setting is changed.

The CLI refuses `--backtest`, `--book-backtest`, `--calibrate` and `--history`
for this mode: the last flag also runs return calculations in the existing CLI.
Current snapshots do not establish an original historical archive. Low-level
study APIs remain unchanged; their existence is not permission to call an
unqualified historical result verified. Deployment remains a separate Spark-only
gated operation, not part of importing or running this comparison.

## Verification

The final retained-source comparison imports all 94 already acquired original
responses into a temporary real archive, reads their exact bytes back, compares
the actual current and qualified fundamental consumers, and round-trips all
94 names through the real record block and strict JSON. The original manifest
and response hashes remain unchanged. This is a one-date feature/score
comparison, **not a backtest or a full combined-grade comparison**; the complete
desk/grade/save path is separately exercised with synthetic integration inputs.

| Measurement | Current `/3` | Qualified research |
| --- | ---: | ---: |
| Finite feature cells | 424 | 430 |
| Finite fundamental scores | 64 | 64 |

The small net difference hides a substantial contract change: 139 feature cells
become available, 133 are withheld, and 24 of the 291 jointly finite cells change
value. Twenty names gain a score and twenty lose one. This is not a blanket
coverage improvement. Rejections among 658 cells remain explicit: 73 lack a
complete quarter at the required end, 109 lack the declared concept, 24 have
reported/derived disagreement, seven lack the declared unit, five depend on
disputed components, one has nonpositive growth input, two lack a lagged quarter
and seven have no revenue period; 430 are accepted.

Named observations, not investment recommendations:

- AAOI's six June 2026 inputs are identical; capex stays unavailable. Its score
  changes from 0.70473 to 0.70343 through peer reranking, not improved business
  data or a new valuation result. Negative net margin remains negative.
- AAPL gains seven June 27 inputs and an F score of 0.26037. AMZN gains five
  June 30 inputs and a score of 0.50084, without inventing gross profit or
  substituting intangibles-inclusive purchases for PPE capex.
- ORCL gains August 31 YoY and three margin/ratio inputs. QoQ and acceleration
  remain withheld for a disputed derivation component, gross profit is absent,
  and its fundamental score remains unavailable. Four available features do
  not imply enough eligible scored legs; capex is context, not a scoring leg.

Current company-facts bytes contain historical observations but do not establish
their original historical availability. Full accounting comparability,
contemporaneous source coverage, investment superiority and deployed behavior
remain unverified. Existing defaults must not be changed on these numbers alone.

Final acceptance counts and exact source/artifact hashes are recorded in the
session handoff after the connected and retained-source checks finish. Original
absence failures, independent boundary findings and corrected runs are retained.
No performance advantage is inferred from improved coverage or changed scores.

Diagram impact: NONE — the existing filing/store/analyst/record relationships
are unchanged; this is an explicit data representation and calculation profile
within those boundaries, not a new service, agent or external dependency.
