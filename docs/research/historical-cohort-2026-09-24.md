# Historical evidence importer — September 24, 2026

The research pipeline can now import a reviewed cohort from retained primary
source bytes and report exactly which evidence is missing. It cannot yet run a
credible historical strategy comparison from this cohort: no price, volume or
grade history has been supplied. Backtest readiness, independent validation and
adoption eligibility remain **false**.

The actual demonstration uses ten public SEC files: five issuer documents plus
their five accession indexes. A fresh archive preserves their original bytes,
SHA256 hashes, URLs, ingestion times, original manifest and reviewed passages.
The command reads that archive back before publishing its readiness report.
Matching a hash and quote proves retained-byte integrity, not that an extraction
is true, that a publication clock is independently authenticated, or that every
historical event was collected.

## Declared demonstration, not a historical universe

The cohort was deliberately selected retrospectively on September 24, 2026 to
exercise three evidence paths. Its period is January 2, 2020 through November 8,
2022. All three names are retained on each of 720 XNYS sessions: 2,160 rows,
including unknown and absent membership. CIK plus share class identifies each
security; ticker is only a display label.

| Security | Declared membership | Primary evidence and its limits |
| --- | --- | --- |
| AAPL common stock | January 2, 2020 onward | The 2019 and 2022 10-K cover tables both identify AAPL common stock on Nasdaq. These two observations do not exhaustively establish everything between them. |
| SNOW Class A common stock | September 17, 2020 onward | The final prospectus states NYSE listing approval. This entry is the first full session after the conservative publication bound, **not** a claim that September 17 was its first trading day. |
| TWTR common stock | January 2, 2020 through October 27, 2022; exit effective October 28 | The 2019 10-K states listing since November 7, 2013. The later merger 8-K states trading suspension before the October 28 opening. That filing is not known to the replay until November 1. |

These are intervals under the supplied demonstration rule, not exhaustive
listing histories or verified trading eligibility. The importer does not drop
SNOW before its source appears, drop TWTR after removal, or rebuild the cohort
from today's surviving tickers. Nevertheless, this tiny, selected cohort is not
a survivorship-free universe and is not independent validation of a strategy.

## Publication, effect and ingestion are different clocks

The SEC accession indexes supply **Filing Date**, retained at day precision.
Availability is conservatively bounded at the following midnight in
`America/New_York`. Exact publication instants are not invented from acceptance
clocks whose timezone is not stated consistently across SEC representations.
The original date and precision remain in the report alongside the derived
`availability_bound_at`. All bytes were ingested in September 2026; this does not
make the historical features recorded observations from 2020–2022.

| Filing | SEC Filing Date | Conservative availability |
| --- | --- | --- |
| AAPL 2019 10-K | October 31, 2019 | November 1, 2019, 00:00 New York |
| TWTR 2019 10-K | February 21, 2019 | February 22, 2019, 00:00 New York |
| SNOW final prospectus | September 16, 2020 | September 17, 2020, 00:00 New York |
| AAPL 2022 10-K | October 28, 2022 | October 29, 2022, 00:00 New York |
| TWTR merger 8-K | October 31, 2022 | November 1, 2022, 00:00 New York |

The TWTR document states the merger was consummated October 27 and suspension
occurred before the October 28 opening, but its index Filing Date is October 31.
The replay must not backdate knowledge of that later filing. October 28 and
October 31 therefore retain the prior known membership with unavailable feature
history; they are not assertions that TWTR remained tradable. Starting November
1, the rows show absent membership and the terminal consideration.

That consideration is the right to receive **USD 54.20 cash per ordinary share**,
subject to the filing's exceptions. It is not a settlement receipt. Settlement
date is null, `cash_is_funded` is false, and six terminal rows explicitly retain
`terminal_settlement_unknown`. No cash, position, price or strategy return is
manufactured from the merger amount.

## Actual imported evidence and remaining gaps

The checked-in [reviewed manifest](../../backend/market/data/historical_cohort_demo_20260924.json)
contains the exact SEC URLs, original filenames, full hashes, ingestion times,
date-level publication evidence and passages. Large original filings stay in the
separate research archive, not Git. AAPL's later filing is retained for manual
corroboration; the 2019 identity/entry evidence drives its membership rows.

The final real-source acceptance run produced:

- 10 source files, 3 stable security identities, 720 sessions and 2,160 rows.
- 1,975 present rows, 179 rows with unavailable identity/membership evidence,
  and 6 absent rows after the known TWTR exit.
- Zero complete-feature rows. Every one of the 8,640 requested feature cells
  (`open`, `adjusted_close`, `volume`, `grade`) is explicitly unavailable.
  Per-feature gap counts are 1,975 because readiness counts feature gaps on
  present-membership rows; the other rows still retain their unavailable cells.
- No live/paper account changes, model fitting, strategy replay or benchmark
  estimates. Source integrity and archive read-back pass; historical-backtest,
  independent-validation and adoption flags remain false.

Still **UNVERIFIED**: exhaustive membership and corporate-action coverage;
original-publication authenticity beyond reviewed SEC evidence; historical
feature values, their adjustments and availability; recorded learned inputs;
cash settlement and independently replayable cash/fill journals. This work does
not alter the completed study or repair its examined-survivor limitations.

## Reproduction and validation

The importer is offline. Place the original source files named in the manifest
beside a copy of that manifest, with the exact retained bytes. With market
research dependencies installed:

```bash
python -m backend.cli.market_historical_cohort \
  --manifest /path/to/source-files/cohort.json \
  --archive /path/to/new-research-archive \
  --start 2020-01-02 --end 2022-11-08
```

The destination must not exist. The importer writes `cohort.json`,
`original-manifest.json`, content-addressed source files, `readiness.json` and
`import-receipt.json`. It uses `exchange-calendars` XNYS sessions and scheduled
session close plus 15 minutes, including early closes. `--required-feature`
can explicitly replace the four default feature requirements. Invalid inputs,
missing or changed source bytes, absent quotes and existing destinations fail
closed. An interrupted or corrupted partial archive cannot receive a successful
readiness receipt and is never overwritten on retry.

VERIFIED against the checked-out implementation based on `8953aee`: **41 tests
passed** across the cohort domain, existing membership and new CLI modules.
The 11 CLI tests cover durable byte/report state, retaining names and unavailable
features, publication-gated entry/removal, holiday and early-close timing,
custom requirements, damaged/missing evidence, corrupt archive read-back and
repeat-import refusal. These fixtures are clearly synthetic and do not stand
in for the separate real-source acceptance run. Scoped Ruff and format checks
pass for all four changed Python files; `git diff --check` passes.

The real command ran in a disposable local `anios-functional-tests` container
with the checkout and source directory mounted read-only and
`exchange-calendars==4.13.2`. A separate stdlib-only audit verified all
14,920,321 original source bytes unchanged, every per-source SHA256, both
persisted artifact hashes, the exact exercised code hashes, all 2,160 retained
rows and 8,640 unavailable feature cells. It asserted SNOW's unknown→present
boundary and TWTR's publication-gated removal and unfunded entitlement directly
from the persisted JSON, rather than merely trusting a successful CLI exit.

Preserved Spark archive:
`/home/animallya96/anios/data/market/research/historical-cohort-20260924/`.
The exact path was confirmed absent before atomic directory creation; copying
used no-overwrite extraction. All **14 files / 16,926,539 bytes**, including the
ten original source bodies, both manifests, readiness report and import receipt,
have identical SHA256 hashes on Spark and locally. No existing research output,
service, model or account was modified.

Local copy: `/tmp/anios-historical-cohort-final.ekJucf/archive/`.
The receipt records `/output/archive`, its path inside the disposable container.

| Preserved artifact | SHA256 |
| --- | --- |
| `readiness.json` | `ca90d58d6eeb8c48e18cf9901e05228e2e21caca73bcae634052b01cca7bf66c` |
| Archived `cohort.json` | `419be2dcc3afc71df2de0decc1179491706e031f7038c2c97936cbf7403aaa74` |
| Original/checked-in manifest | `3505ac0a21811da6b9ce82df7da62918b10c727f02cefd1cea8bdc975a21eabd` |
| Exercised cohort domain module | `516164bda2aa6fb60d4dba63f7634615ad061c753dd582e0d6f0215a59d66b5e` |
| Exercised CLI module | `82499d7471ebb2979fd0818bb6ca36f599eda72296d4589013dc1dbee1d15df2` |

Diagram impact: the [market-data flow](../diagrams/market-data.mmd) now shows
the distinct primary-document → reviewed importer → immutable archive →
readiness path, separate from existing snapshot panels and research accounts.
No deployment occurred.
