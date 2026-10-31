# Sector exposure cap on the installed rule: the honest-universe result — 2026-10-31

**Status: FAILED the pre-registered gate. The cap is not adopted.** This is the
result of `sector-cap-preregistration-2026-10-31.md`, run after the note was
committed (`8513b31e`). The cap is not added to the rule, the board, or any
prompt, and is not retried without a new pre-registration. Nothing live changed.

## The question and the gate

Does capping the book's target weight in Information Technology + Communication
Services at 50% of equity reduce the worst drawdown enough to justify the
return it gives up? The pre-registered gate, on S&P 500 point-in-time at 25 bp
over the choosing window 2016-2023, is a conjunction:

1. worst drawdown at least **2.0 percentage points shallower** than the
   installed rule's (−33.3296%, so no deeper than −31.3296%);
2. CAGR no worse than **1.0 point below** the installed rule's (10.6747%, so at
   least 9.6747%);
3. Sharpe no worse than **0.02 below** the installed rule's (0.6736, so at
   least 0.6536);
4. the drawdown improvement above the **95th percentile of 200 random-group
   placebos**;
5. the perturbation check passes;
6. the off, cap1 and cap0 nulls pass.

## The result

Run on the frozen `~/dsv41/pit2/cache.npz` with only `Rule.sector_cap` changed.
The baseline reproduces the risk dial's 0.25/25 line to 1e-9: choosing
10.6747% / −33.3296% / 0.6736; reported 26.2893% / −19.1375% / 1.6743; all
14.2725% / −33.3296% / 0.8842.

S&P 500 point in time, **25 bp** (the gating row):

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all DD | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| installed | 10.67% | −33.33% | 0.6736 | 26.29% | −19.14% | 1.6743 | 14.27% | −33.33% | 0.8842 |
| cap50 | 10.67% | −33.33% | 0.6736 | 26.29% | −19.14% | 1.6743 | 14.27% | −33.33% | 0.8842 |
| cap60 | 10.67% | −33.33% | 0.6736 | 26.29% | −19.14% | 1.6743 | 14.27% | −33.33% | 0.8842 |
| cap40 | 10.67% | −33.33% | 0.6736 | 26.29% | −19.14% | 1.6743 | 14.27% | −33.33% | 0.8842 |

S&P 500 point in time, 10 bp (reported): every arm is likewise identical to the
installed book, choosing 11.5355% / −34.6861% / 0.7083, reported 25.4809% /
−19.6572% / 1.6107, all 14.7657% / −34.6861% / 0.8970. The IT-only cap50
sensitivity at 25 bp is also identical.

## The verdict

**Criteria 1 and 4 fail; 2 and 3 pass only because the arm is the baseline.**

- The choosing-window drawdown gain is **0.00 points** (both books −33.3296%),
  against the +2.0-point requirement.
- The placebo's 95th percentile is **0.00**; the gate asks for a gain strictly
  above it, and 0.00 is not above 0.00.
- CAGR delta and Sharpe delta are exactly 0.00, so their floors pass trivially.
- The perturbation, off null, cap1 null and cap0 null pass (see below).

The conjunction fails, so the arm is closed.

## The cap never binds on the honest universe

`bite` against the installed book over all 2,970 sessions: **0 sessions active**,
mean removed weight 0.00, mean IT+Comm weight **16.48%**, maximum **39.67%**.
The 40% sensitivity is also a no-op, which means the target sector weight never
reached 40% on any session, let alone the 50% primary. The cap cannot change a
book whose sector target never reaches the cap.

This is the opposite of the pre-registration's premise. The premise came from
the live book: 58 Information Technology and 2 Communication Services names of
94, and a −5.49% mean return on the GOOGL shock day. But the live book's
*concentration is in what it holds, not in what the rule targets*. From the
2026-10-30 desk record:

- **Held book:** 8 names, all Information Technology, gross **60.69%**
  (SNPS 9.89%, NTAP 9.29%, HPE 8.67%, SMCI 8.48%, STX 8.11%, INTC 7.28%,
  SNDK 7.13%, MU 1.83%).
- **Tonight's target:** 12 names, gross **50.00%** — Information Technology
  **39.46%**, blank label (ALAB, TSM) 7.28%, Industrials (GEV) 3.25%,
  Communication Services 0.00%.

The rule is already trimming the held 60.69% IT book toward a 39.46% IT target;
the 50% cap would not bind on that target at all. A standing cap on the target
cannot address the exposure that produced the shock-day loss, because that
exposure is the held book waiting for next-open fills. The honest PIT universe
is more diversified still: its simulated book holds 109 names across sectors and
its IT+Comm target peaks at 39.67%.

## The IT + Communication sensitivity: the cap does bind there, and still fails

On the all-tech PIT universe the cap binds. 25 bp:

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all DD | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| installed | 8.92% | −36.66% | 0.5296 | 49.49% | −26.70% | 1.7897 | 17.44% | −36.66% | 0.8713 |
| cap50 | 4.96% | −21.97% | 0.4553 | 29.91% | −14.95% | 1.8714 | 10.46% | −21.97% | 0.8358 |
| cap60 | 5.62% | −26.00% | 0.4566 | 34.43% | −18.39% | 1.8083 | 11.89% | −26.00% | 0.8252 |
| cap40 | 4.23% | −17.73% | 0.4696 | 24.11% | −11.69% | 1.9148 | 8.68% | −17.73% | 0.8571 |

At 10 bp the same pattern: installed 11.16% / −35.66% / 0.6324; cap50 6.12% /
−21.81% / 0.5449; cap60 7.16% / −25.40% / 0.5590; cap40 5.23% / −17.69% /
0.5665.

Cap50 at 25 bp buys a **14.69-point shallower** drawdown for **−3.95 points of
CAGR** and **−0.074 of Sharpe**. Even if this universe had been the gating one,
the arm would fail the gate's CAGR floor (−1.0 point) and Sharpe floor (−0.02);
only the drawdown criterion would pass. Cap60 and Cap40 fail the same two
floors. The reported window's Sharpe improves (1.7897 to 1.8714) because the
cap is in cash through part of the 2024-2026 rally while the reported CAGR falls
19.59 points; the full period's Sharpe falls 0.0355. No cap level in this study
is a risk-adjusted improvement.

## The placebo

Two hundred random-group draws, seeds 20261031..20261230. Every draw removes
Cap50's per-session removed weight, which is **zero on every session** because
the cap never binds; all 200 draws are therefore identical to the baseline.
Mean gain 0.00, 95th percentile 0.00, maximum 0.00. The placebo is vacuous here
by construction, and the gate's strictly-above comparison fails. On the IT+Comm
universe the placebo was not run, because that universe is reported, not gated,
and the economic floors already fail there.

## The null and perturbation checks

- **Off null.** `Rule(sector_cap=None)` reproduces the installed book exactly:
  equity, weights and trades byte-identical, and the baseline matches the risk
  dial's 0.25/25 line to 1e-9.
- **Cap1 null.** `Rule(sector_cap=1.0)` is byte-identical to the installed book;
  the cap cannot bind at unit capital.
- **Cap0 null.** `Rule(sector_cap=0.0)` makes **0** sector buys and ends at
  **0.00** sector weight. The cap mechanism works when it is allowed to bind;
  the honest universe simply never asks it to.
- **No future data.** Changing every close after the 60% session (2022-01-31)
  leaves the book and its early trades identical (`future_identical: true`). The
  check is vacuous on this universe (`cap_active_before_cutoff: false`) because
  the cap is never active; the unit test
  `test_sector_cap_reads_only_past_closes` asserts it on a synthetic panel where
  the cap binds.
- **Unit tests.** 22 tests pass, including the off/one byte-identical checks,
  the zero-cap behavior, the placebo's equal removed weight and fixed seed, the
  configuration errors, and the perturbation check on a binding panel.

## What this means

The arm asked whether a standing sector cap reduces the honest universe's worst
drawdown enough to pay for itself. The answer is that the honest universe never
reaches the cap, and where the cap does bind it costs far more return than the
gate allows. The live concentration is a held-book transition being trimmed to
an already-diversified target, not a target-state concentration a static cap
could prevent.

So the sector cap is not the instrument for the owner's concern. The remaining
candidates are the event-window step — knowing an earnings release is imminent
and de-risking before it — and intraday reaction. Neither is pre-registered
yet, and the first is blocked on data: the store has no forward announced
earnings dates (`market_earnings.py`: "the next is not in the store until it is
filed"), so it needs either an external announced-date source or a pre-registered
seasonal proxy built only from past filing dates. That is a separate arm with
its own pre-registration; it is not started here.

## Caveats

- The cache is frozen at 2026-10-24; grades, band, tilt and membership are the
  desk as it stood then. Only `Rule.sector_cap` changes, so the comparison
  across arms is clean, but the absolute levels are not a fresh backtest of
  today's desk.
- The store holds bars only for names it carries today; the membership is dated
  but the price history is survivor-biased. The absolute levels are flattered;
  the comparison across arms is the point.
- The PIT grades cover the broad S&P 500, so the simulated book is diversified
  in a way the live 94-name AI/software desk is not. That is exactly why the cap
  does not bind, and it is the study's central finding rather than a defect in
  the run.
- The live held/target figures are one session's record (2026-10-30) and move
  nightly; they are cited to explain the mechanism, not as a time series.
- `policy_book` is the account simulator, not a bound live-sizing source. The
  new `Rule` fields default off and are not deployed; the live nightly plan
  still sizes through `grade_led_leader_policy.size_report`. A pass here would
  have needed a shared helper in both paths, the release ceremony and a
  252-session forward shadow, not a live change.

## Artifacts

- Pre-registration: `docs/research/sector-cap-preregistration-2026-10-31.md`,
  committed `8513b31e` before the first run.
- Runner: `~/dsv41/pit2/sector_cap.py` (outside git, research only).
- Payload: `~/dsv41/pit2/sector_cap.json`; log `~/dsv41/pit2/sector_cap.log`.
- Simulator parameters: `backend/market/policy_book.py` (`Rule.sector_cap`,
  `Rule.sector_cap_sectors`, `Rule.sector_random`, `simulate(sector=...)`,
  `cap_sector_target`); tests in `backend/tests/test_policy_book.py`.

**Closed.** Not retried with a different cap level, sector set, universe or
window without a new pre-registration saying what changed and why.
