# SUE coverage audit on the honest PIT universe: result (adequate)

**Status: ADEQUATE.** The store's filing data supports a SUE rank-IC study on the
honest PIT universe. This is a coverage result, not a performance result: no rank-IC,
return or trading result was read, and nothing changes in the live rule. The audit was
pre-registered in `sue-coverage-audit-preregistration-2026-10-29.md` (committed
`a300f873`) before the first run.

## What ran

- PIT cache: `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time cache used by
  C1-C3 and the risk dial: 532 tickers, 2,970 sessions 2015-01-02..2026-10-23;
  361-456 members per year in the choosing window.
- Filings: the store's `edgar_facts_versions` frames, read with
  `fundamentals_asof.versions_from_frame`. 531 of 532 tickers have a frame; the one
  missing is SPY, the benchmark, not a stock. Primary earnings: `net_income`
  (`NetIncomeLoss` and its fallback tiers); secondary: `eps` (diluted/basic). Quarter
  spans only (80-100 days); the earliest filing per period end is the observation; the
  decision date is `Version.available`, the first session the filing was public.
- Tiers (nested): tier 0 = two quarterly filings; tier A = a seasonal pair (Q_t vs the
  same fiscal quarter a year earlier); tier B = a pair plus at least 2 prior seasonal
  changes; tier C = a pair plus at least 4 prior seasonal changes (the usual 8-quarter
  denominator). A name counts in a year only if it is a PIT member on the decision
  date.
- Read-only; no price data, no model call, no prompt.

## Coverage

| Year | PIT members | Any quarter | Tier 0 | Tier A | Tier B | Tier C | Tier C share |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2016 | 361 | 346 | 346 | 346 | 346 | 342 | 94.7% |
| 2017 | 381 | 365 | 365 | 364 | 364 | 363 | 95.3% |
| 2018 | 389 | 376 | 376 | 376 | 376 | 373 | 95.9% |
| 2019 | 406 | 392 | 392 | 392 | 392 | 391 | 96.3% |
| 2020 | 415 | 409 | 409 | 409 | 409 | 406 | 97.8% |
| 2021 | 425 | 420 | 420 | 420 | 420 | 419 | 98.6% |
| 2022 | 441 | 435 | 435 | 435 | 435 | 434 | 98.4% |
| 2023 | 456 | 448 | 448 | 448 | 447 | 445 | 97.6% |
| 2024 | 471 | 464 | 464 | 464 | 462 | 459 | 97.5% |
| 2025 | 489 | 483 | 483 | 482 | 481 | 480 | 98.2% |
| 2026 | 502 | 499 | 499 | 499 | 496 | 495 | 98.6% |

The choosing window is 2016-2023. Every choosing year clears the pre-registered bar of
at least 150 tier C names and at least 250 tier A names by a wide margin.

## The gap

- Five names have no quarterly earnings under the US-GAAP tags: ASML, FDXF, NBIS, SIMO
  and TSM. All are foreign private issuers (20-F/6-K); TSM files under IFRS in TWD, and
  the others file under foreign tags the store's `net_income` set does not read. They
  are excluded from the SUE sample and stay in the denominator. The rank-IC study must
  fail closed for them, never fill a missing quarter.
- The remaining uncovered members in a year are names with no quarter public in that
  year (recent listings or filings). The tier C share is 94.7-98.6%, and the per-name
  detail is in the payload.
- Sector coverage is proportional to membership over the choosing window: Industrials
  72/75, Financials 67/68, Information Technology 58/61, Health Care 56/57, Consumer
  Discretionary 43/43, Consumer Staples 31/33, Utilities 30/30, Real Estate 30/30,
  Materials 23/24, Energy 18/19, Communication Services 17/19. No sector is
  systematically missing.

## Verdict

- Coverage is adequate. The next step is a separate pre-registration for the rank-IC
  study: SUE rank against 20- and 60-session forward returns, by year, on the honest
  PIT universe, with a placebo and costs. That study must exclude the five foreign
  filers and report the denominator; it makes no live use.
- The audit does not cover the market-cap/value gap for multi-class names (P5). The
  SUE uses earnings only, so that gap is separate.
- No live change follows. The installed rule stays frozen through the 252-session
  forward record.

## Note on the first run

The first run counted the tiers exclusively (A = pair only, B = 2-3 prior changes,
C = 4 or more prior changes), which contradicts the pre-registration's nested
definitions (B includes A; C includes B). That run reported tier A of 1-7 names and
status "inadequate". The script was corrected to the nested definitions and re-run;
the tier C set is unchanged, and the tier A and B counts are now cumulative. The
pre-registration is unchanged. The correction was a definition fix, not a change to
the bar.

## Artifacts

- Pre-registration: `docs/research/sue-coverage-audit-preregistration-2026-10-29.md`,
  committed `a300f873`.
- Runner: `~/dsv41/pit2/sue_coverage.py`; payload `~/dsv41/pit2/sue_coverage.json`;
  log `~/dsv41/pit2/sue_coverage.log`.
- Cache: `~/dsv41/pit2/cache.npz`; filings: `~/deploy/anios/data/market/edgar_facts_versions`.

## The one number

In 2016-2023, 342-445 of 361-456 PIT members per year (94.7-98.6%) have a full-history
SUE observation (seasonal pair plus four prior seasonal changes). The data supports the
rank-IC study; it makes no performance claim.
