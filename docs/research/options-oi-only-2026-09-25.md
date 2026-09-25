# OI-only stored-chain diagnostics

September 25, 2026. This corrects diagnostic availability, not a trading signal,
gamma model, provider subscription or strategy-performance result.

## Contract and first failure

The live options display uses open-interest concentrations, yet its stored-row
reader required volume, implied volatility and gamma, then rejected nonfinite
aggregate gamma. The frozen 33-case diagnosis reproduced valid $95 put / $105
call OI levels being withheld because of unrelated gamma, including gamma on
expired or outside-horizon rows. Simply removing the finite check would allow
nonfinite raw JSON and is not the correction.

Live stored-row validation now requires only expiry, side, raw strike and OI,
plus the existing metadata mapping. Explicit `OIRow` and `OILevels` types carry
no gamma. One shared `oi_levels` function contains the unchanged original OI
selection algorithm; the legacy `walls` wrapper calls it before its original
all-stored-row gamma calculation. Newly produced live walls omit `net_gamma`;
zero is not substituted. Required malformed data still yields the local
unavailable state, and unexpected programming errors still propagate.

The legacy `ChainRow`, `Walls`, full-row parser, collector and CLI contracts are
unchanged. Collection-time optional-field parsing can still reject a row before
it is stored; this change does not recover such rows or qualify collection.
Legacy nonfinite gamma behavior is preserved, not scientifically validated.

OI expiry/strike bounds, aggregation, minimum OI and tie rules remain identical.
The `raw-option-oi-levels/1` method and actual raw reference, original cached bar,
selection date and collection time retain their previous meanings. OI effective
time/freshness remains unknown. Old saved snapshots and archives are not
rewritten. Versioned old records with gamma remain readable; unversioned records
still withhold numerical display evidence.

Removing the unused raw field changes full-detail cache/archive identities for
new observations. It does not revise old hashes. Repository UI consumers read
the separate OI projection, which never used gamma. Compatibility with unknown
external consumers of raw `technical_detail.walls.net_gamma` is **UNVERIFIED**.

## Acceptance

**VERIFIED:** root's wider eight-module suite passes 418 tests, zero skips,
16 existing neighboring empty-slice warnings, 3.63 seconds. The implementing
agent's six-module suite passes 399, with the same warning category. Actual
synthetic Parquet, technical production, balancer/board persistence and 60
authenticated cached ASGI read cases exercise real source. They verify finite
JSON, expected OI/projection states, unchanged technical inputs/grades, quote
evidence and source/saved bytes. Only clocks, opinion/provider/account boundaries
and the unrelated search-metering account lookup are synthetic or excluded.
This is not a listening server, real account database or deployed acceptance.

All 32 prior malformed fixtures remain: 17 concern irrelevant optional fields
and now retain valid OI; 15 concern required OI/storage data and remain
unavailable. Seven new required-column shape cases and 17 optional-data cases
cover all four required columns, OI-only frames and eligible/expired/far gamma
corruption. Unequal-length shapes are injected at readback because a Parquet
table cannot itself represent them. No assertion was weakened to tolerate
malformed required OI data.

**FAILED original:** the final new-contract matrix on preserved original source
has 223 failures / 51 passes. These include new type/helper absence and explicit
raw-field-removal assertions; they are not 223 distinct arithmetic defects.
The earlier old-contract baseline passes 248. The frozen causal diagnosis is
retained separately.

**VERIFIED independent review:** exact AST comparisons preserve the OI body,
legacy gamma loop, types and parser. A separate reviewer passes 2,500 seeded
synthetic differential cases, 36 adversarial live checks and seven CLI
output/error comparisons without repeating the main suite. Root read the full
diff and tests; source hashes match the reviewed/run artifacts. Scoped
Ruff/format and all 33 unchanged diagram/page checks pass.

**UNVERIFIED:** deployed prevalence, current provider/Barchart agreement, true
OI effective time, dealer positioning, predictive value and improved returns or
drawdown. No model fit, historical strategy replay, holding/order operation,
data migration, collector setting, laptop access or deployment changed.

## Evidence

- Original diagnosis: `/private/tmp/anios-options-gamma-isolation.ktCqjz/RECEIPT.md`,
  SHA256 `9c83f0082877d5b351d2cc203e6156f8170eb024d33614bc16f595cabf2d09bf`.
- Implementation: `/private/tmp/anios-options-oi-split.chAktS/RECEIPT.md`,
  SHA256 `1a871726160377cf1705b97c8b9122387b753af39bc4dc70904f04632de0e2a6`.
- Independent review: `/private/tmp/anios-oi-independent-review.45AM7g/RECEIPT.md`,
  SHA256 `b8ab0bc17b5d61a8a688447621a811d863574df7d1f19c425cb72a1a40437bcb`.
- Root JUnit: `/private/tmp/anios-quote-rl-root.pM9CLO/oi-wide.xml`,
  SHA256 `dde9a98d7f64a11b1935a07253cc7c2bdaf9f5421bf3dd670a4eabef064ec4a2`.

Source hashes: `options.py`
`9a303276f6d9367ce0fde7e1a7587268a264fd6e143d59b91a81d52fd7441d44`;
`live_technical.py`
`961c54c4f6d35a1cfade7856d743d8e94859fe3a646ceefe75aa80372091f94d`.
The receipts retain all five owned-source hashes and separate original/candidate
tests, produced Parquet, snapshots and journals. Runs use the pinned cached
backend image, read-only checkout/dependencies, network disabled and synthetic
credentials; no installation or external request is required.

**Diagram impact: NONE — internal input contract/shared arithmetic only.**
