# Independently replayable research accounts — September 24, 2026

## Scope and result

The optional `research-journal/1` observer is implemented for the desk simulator,
fixed learned-research replay and funded SPY/QQQ controls. It records what those
ledgers actually did; it neither chooses allocations nor executes orders.
Existing results are identical with recording disabled or enabled. No completed
market study was rerun, no candidate was retuned and `/3` remains unchanged.

VERIFIED: **292 tests passed**, one cached-study reproduction deliberately
deselected. Five synthetic archive/CLI journeys independently reconstruct all
**32 closing valuations**. These are accounting checks, not market returns or
evidence that a new strategy beats SPY or QQQ. Deployment remains UNVERIFIED.

## Contract

`backend.market.research_journal.ResearchJournal` copies the entire supplied
calendar, symbol order and adjusted open/close matrices. Optional raw open,
close and adjusted-close arrays are retained as supplied; the independent
verifier checks their adjustment arithmetic when the required arrays exist.
The observer refuses attachment to different prices, dates, symbols or costs.

Events retain opening cash/positions, close-time intent, phase-specific order
adjustments, actual fills, fees, unfilled residuals, every closing mark and the
terminal holdings/pending state. `submitted_units` means absolute intended
ending units, **not a buy/sell delta**. Decision events include hold/no-order
observations, so counting them does not count submitted or executed trades.
An unfilled batch residual does not itself mean a queued order.

Split execution retains the original close-time decision, the opening buy leg
and the closing sell leg. Open-price sell suppression is an explicit adjustment.
Deferred funding and FOMC event state remain the producer's actual terminal
state; finishing a run never invents liquidation or pays fictitious cash.

`archive(fresh_path)` writes `prices.json`, `events.json`, then `manifest.json`,
and checks the bytes read back. Existing destinations, symlink components and
parent traversal are rejected. Canonical hashes bind retained source/event
bytes. They are not a signature: somebody able to replace an archive can
replace its hashes too. Provenance is caller-supplied, not externally attested.

`backend.market.research_journal_replay` imports no producer ledger or planner.
It independently carries cash and units from account opening to termination,
validating chronology, declared funding budgets, fills, fees, turnover, price
references and each NAV. It never resets its balances to the producer's reported
before-state. Missing held prices and missing close marks, altered accounting,
bad chronology and failed/unclosed recordings cannot pass.

Comparisons allow `1e-10` relative and `1e-12` absolute rounding. A reproduced
fully invested, zero-cost ETF path made a dimensionless buy-scale ratio unstable
on sub-ULP cash. The verifier allows this scale-only discrepancy only when both
observed and independently reconstructed requested buy spend are at most
`1e-12 * max(1, NAV)`. Cash/units/fee checks remain, and the report exposes the
count plus maximum reconciliation residuals. Material scale alteration and
accumulated ledger drift have regression tests; there is no ledger reanchoring.

## What successful replay does not prove

- Prices imply synthetic adjusted units, not broker shares. Do not add separate
  dividends/splits or raw per-share merger payments to these units without a
  separately sourced conversion model.
- One cash balance and each batch's recycling convention are preserved.
  `recycle_sells=False` spends pre-batch cash and credits sales at batch end.
  This is **not historical T+1/T+2/T+3 settlement**. Cash yield is zero.
- A complete recording can contain an unavailable NAV as `null`; the affected
  held symbols remain listed and independent verification fails. `complete`
  means the recorder ended, not that accounting or economics passed.
- Pending queue declarations are validated and retained, not independently
  regenerated from strategy rules: `pending_semantics_verified` stays false.
- Hashes, session dates and phase order do not establish point-in-time data
  availability, security identity, universe completeness or execution capacity.
  Historical availability, settlement and adoption flags remain false.
- This research-only JSON is unencrypted. It must contain public/synthetic
  research inputs, never private holdings, credentials or personal receipts.
  There is no new API, model prompt, broker integration or live collection job.

## Reproducible evidence

Tests used the actual checkout mounted read-only at `/app`, not the backend
source baked into a stale image. Runtime image:
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.
The full applicable command is in the development guide. Its five warnings
are existing All-NaN/empty-slice synthetic-fixture warnings, not skipped checks.
Scoped lint and formatting pass. Host Ruff is absent; validation used the image.

Fresh demonstration: `/private/tmp/anios-journal-final.H5k0NF/`, using the real
`constant_exposure` and stock-book split-fill implementations. The four control
archives are explicitly named `synthetic-spy-10bp`, `synthetic-spy-25bp`,
`synthetic-qqq-10bp`, `synthetic-qqq-25bp`; the fifth is `synthetic-split`.
Both ETF labels deliberately use the same artificial gap series. They are not
historical SPY/QQQ observations. All five real CLI invocations exit **0** with
`ok` and `accounting_verified` true, and adoption false. Largest residuals:
cash **2.60e-16**, units **1.74e-18**, NAV **4.44e-16**.

The archives and runner are also retained on Spark at
`/home/animallya96/anios/data/market/research/accounting-journal-20260924.0fgNNN/`.
All **16 files / 54,258 bytes** were read back with matching SHA256 and sizes.
The destination was newly created; no existing research artifacts were replaced.

The runner's SHA256 is
`dc09dab1299abc530d6c7589f3a5cd8fa602313de3b0825db7117a5fb3ec5f36`.
Every manifest records the baseline `128a5d51e41af23dd23f22fd9cfcb993ce19ed8b`
and these exact exercised source hashes, rather than calling uncommitted code
that baseline revision:

| Source | SHA256 |
| --- | --- |
| `desk/simulate.py` | `9405aebed6ace31d28f606d9b0e000749245ff4e0eca5b7b3f25b49dd3327c4a` |
| `learned_research.py` | `ccdf179ebc0d119290b181f5a4ed260aa292b21129d028b05f5b690f1b0aa7cf` |
| `allocation_controls.py` | `df9e8cddba62b345a03914b6304c21471d8ef7c39c14c62a5f26b550d7dedb86` |
| `research_journal.py` | `31bc5f983108875fbabbfca03ef2a9c4e24e2afa39102f12d49167c112f5c122` |
| `research_journal_replay.py` | `bb2ce0ed7ce32df369a1852249a27a3b1e89cada00ece1c3884f13f6db197bcd` |
| `market_verify_journal.py` | `74c94b9e647ca7b29d633d7f9148c4983b9900ccaaceb206850367d49ba1e50a` |
| Integration tests | `ec79d688d7cbb544a630efbd96b090143b5f7bfb047b3628087111e0643cee8f` |

## Next boundary

The journal removes an accounting-audit gap, not a strategy-validation gap.
The [isolated stock/SPY/QQQ/cash adapter](allocation-adapter-2026-09-24.md) now
explicitly liquidates to zero and preserves unscaled composition for restoration.
Next freeze bounded nested chronological experiments and execution sensitivities. Keep an
identical no-gate adapter control and exact `/3` alongside funded SPY/QQQ at
10/25 bp. Already examined history stays exploratory; historical quality/cohort
inputs and genuinely independent validation remain outstanding.
