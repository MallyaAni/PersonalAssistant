# Preserve required OI independently of optional collection fields

September 25, 2026. Source checkpoint starts from `main` at
`8b577f9efe4d5bbefb465aa8fb0944acbb6de355`. This corrects stored-data admission
and query semantics; it is not a new options signal or trading strategy.

## First failing boundary

The former collector used the legacy full-chain parser. A malformed volume,
IV or gamma value silently dropped an otherwise valid OI contract; missing
values could instead become zero. A missing/malformed underlying price could
block all storage. A saved incomplete same-date file was then skipped on retry.
The strict query decoder also could not consume nullable optional columns.

**FAILED original desired behavior:** the initial 88-case matrix produced
69 failures and 19 passes before production edits. Expanded acceptance with
query sentinels, explicit zeros and fixed gamma-order oracles produced 99
failures and 19 passes on overlaid original production source. Three failures
in that expanded run concern an intentionally absent new helper, not three
additional original arithmetic defects. Both runs and their actual synthetic
Parquet files remain retained. A separate late eight-case shape test found
one trailing-newline symbol accepted by the candidate; it is retained and fixed
only in the collection path. The final contract has 119 cases.

## Scoped implementation

The collection CLI uses a new explicit `CollectionRow` / `CollectedChain`
contract. It retains the same seven aligned columns in the same
`options/asof=DATE/TICKER.parquet` partition. There is no sidecar or migration.

- Every received eligible contract must have a supported complete symbol,
  positive strike and nonnegative integer OI within signed int64. Missing,
  fractional, boolean, nonfinite or out-of-range OI rejects the whole received
  collection; it cannot silently produce a smaller successful chain. Valid
  symbols outside the existing date window are skipped before field admission.
- Volume, IV and gamma are admitted independently or stored as null. Integer
  volume must be nonnegative and fit int64; IV/gamma must be finite numeric
  values and retain the legacy sign handling. This is numeric admission, not
  validation of an economic model. Observed zeros stay distinct from missingness.
- Bounded metadata records schema `options-collection-v1`, received eligible
  row count, reference-price status, and available/missing/invalid counts per
  optional column. These describe the received rows only. They do not establish
  provider completeness, OI effective time or market freshness.
- An unavailable underlying reference no longer blocks valid OI storage. The
  existing live OI reader may still calculate levels using its independent raw
  reference price. The query CLI has no such substitute and explicitly withholds
  price, levels and gamma. Existing four-decimal stored-price formatting remains.
- Optional-only defects use one fetch attempt. Transport/refusal/required-data
  failures retain the three-attempt boundary and original pacing/backoff.
  Diagnostic logs use fixed reasons, not raw invalid values or exception bodies.

The query CLI validates OI separately from gamma. Missing IV or volume cannot
hide a calculable gamma proxy. If any required stored gamma value is unknown,
nonfinite, or the calculation overflows, the total is unavailable rather than
a partial sum or fabricated zero. The unchanged gamma scope is **all stored
rows**, including rows outside the OI-level expiry window; multiplication and
accumulation order are preserved. This does not validate the assumed dealer
position signs. Neither diagnostic directly changes grades, sizes or actions.

The eleven existing class/function definitions covering full parsing, frames,
symbol parsing, OI arithmetic and the legacy gamma loop remain byte-identical.
Public `parse_chain`, `fetch_chain`, `ChainRow` and `rows_from_frame` are not
relaxed; callers explicitly asking for their old full contract still get it.
Fully valid old/new CLI output is equal. The New York batch date, explicit
`--asof`, 180-day retention endpoints, aware UTC collection time and query-only
latest-unbounded lookup remain unchanged.

Existing files are skipped before fetch and remain byte-identical on same-date
reruns. They are not repaired, annotated complete or rewritten. Previously
discarded rows cannot be recovered from those files. Unknown external strict
consumers of newly nullable frames remain UNVERIFIED; the source inventory
found only the adapted CLI and compatible OI-only live reader in this repository.

## Verification

**VERIFIED agent acceptance:** 119 contract cases plus 399 neighboring cases:
518 passed, zero skips, 16 existing empty-slice warnings, 6.32 seconds.

**VERIFIED root independent acceptance:** the same cases plus the four policy
fingerprint cases and 16 independent synthetic differential cases: 538 passed,
zero skips, 16 existing warnings, 9.43 seconds. The differential cases cover
12 deterministic 36-row chains, each complete and with separate IV/volume/gamma
null variants, plus four unusable underlying references. They compare the
unchanged legacy arithmetic, real Parquet, CLI output and live OI projection.

These tests exercise actual CLI argument parsing/refresh, collection parsing,
storage/readback, both query flags, malformed inputs and existing authenticated
synthetic API/provenance/isolation paths. Query sentinels record attempts at
refresh, both fetch APIs, native transport and writes, even if an exception is
swallowed. Before/after file comparisons prove no query mutation. Independent
IEEE-754 hex oracles pin original gamma operation order. Review-found zero and
query-observability gaps were fixed before final acceptance. Independent final
source review, native Ruff and format checks and `git diff --check` pass.
All 33 unchanged diagrams and the published architecture page pass their
synchronization and syntax-render checks.

Runtime: cached image
`63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`, exact
read-only source, existing dependencies, network disabled and explicit synthetic
test credentials. Root's first standalone differential invocation failed at
settings initialization because a test outside `conftest.py` lacked a synthetic
`SECRET_KEY`; that error is retained. Supplying a test-only environment value
gave 16 passes before the final combined run. No laptop setting changed.

| Artifact | SHA256 |
| --- | --- |
| Options implementation | `e81142caa5a6458c44508bc7d8a6a017c3aedecebc1428a5beef3507d2049fd6` |
| Collection/query CLI | `97e8dc7ba51255dab9558ef2c41711f28d072482eb7482ba365ed99186e1abd0` |
| Permanent contract test | `8d42ba02190b3fa233e0f87bd337aef955d1f63940068f823c901ebeb561a1e6` |
| Agent frozen JUnit | `7197192185a36407b3625e46ab451fcaf2b9090fea2a74809d971f720627a723` |
| Root final JUnit | `c5750d871afb5c6446daa78caef95f1ef022839abeeb385116aabde89efe72d0` |

Agent receipt: `/private/tmp/anios-options-collection-fix.FBD67N/RECEIPT.md`,
SHA256 `4c979131979710a5a2cd15a1c6859d1b3ac19e3775769ab0cbe942d6a5403d2e`.
It retains all failure stages, source snapshots, legacy identity and gamma
oracles. Root evidence: `/private/tmp/anios-options-root.PeCclR/`.

**UNVERIFIED:** deployment/startup, live provider coverage, any repaired old
chain, unknown external decoder compatibility, UI changes and investment
performance. No provider/model/account request, fit, historical strategy replay,
holding/order operation, collector-cadence change or service restart occurred.
Publication is not deployment. **Diagram impact: NONE — field-level admission
and query semantics within the existing provider/CLI/store/reader boundaries.**
