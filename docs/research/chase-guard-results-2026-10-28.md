# Chase guard on the installed rule: the honest-universe result — 2026-10-28

**Status: FAILED the pre-registered gate. The guard is not adopted.** This is
the result of `chase-guard-preregistration-2026-10-28.md`, run after the note
was committed. The guard is not added to the rule, the board, or any prompt,
and is not retried without a new pre-registration.

## The question and the gate

Does deferring entries into names that have already run at least 25% over the
trailing 63 sessions improve the installed rule's risk-adjusted return on the
honest S&P 500 point-in-time universe? The pre-registered gate, on S&P 500 PIT
at 25 bp over 2016-2023, is a conjunction:

1. choosing-window Sharpe at least **0.05 above** the installed rule's;
2. choosing-window CAGR no worse than **1.0 percentage point below** the
   installed rule's;
3. choosing-window worst drawdown no deeper than **−35.0%**;
4. the Sharpe improvement above the **95th percentile of 200 random-deferral
   draws**;
5. the perturbation check passes;
6. the off null reproduces the installed book exactly.

## The result

Run on the frozen `~/dsv41/pit2/cache.npz`, `policy_book.simulate` with only
`Rule.chase` changed. The baseline reproduces the risk dial's 0.25/25 line to
1e-9: choosing 10.6747% / −33.3296% / 0.6736; reported 26.2893% / −19.1375% /
1.6743; all 14.2725% / −33.3296% / 0.8842.

S&P 500 point in time, **25 bp** (the gating row):

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all DD | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| installed | 10.67% | −33.33% | **0.6736** | 26.29% | −19.14% | 1.6743 | 14.27% | −33.33% | 0.8842 |
| chase25 | 10.75% | −34.49% | **0.6736** | 23.45% | −18.84% | 1.5861 | 13.71% | −34.49% | 0.8559 |
| chase40 | 10.46% | −34.35% | 0.6585 | 23.55% | −19.27% | 1.5539 | 13.51% | −34.35% | 0.8423 |

S&P 500 point in time, 10 bp (reported):

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all DD | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| installed | 11.54% | −34.69% | 0.7083 | 25.48% | −19.66% | 1.6107 | 14.77% | −34.69% | 0.8970 |
| chase25 | 11.26% | −35.36% | 0.6963 | 23.98% | −18.27% | 1.6250 | 14.22% | −35.36% | 0.8793 |
| chase40 | 11.53% | −34.60% | 0.7120 | 24.37% | −18.73% | 1.6107 | 14.51% | −34.60% | 0.8938 |

S&P 500 IT + Communication, point in time, 25 bp (reported):

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all DD | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| installed | 8.92% | −36.66% | 0.5296 | 49.49% | −26.70% | 1.7897 | 17.44% | −36.66% | 0.8713 |
| chase25 | 8.93% | −36.77% | 0.5367 | 39.90% | −26.69% | 1.6797 | 15.58% | −36.77% | 0.8255 |
| chase40 | 9.16% | −36.68% | 0.5419 | 41.62% | −26.65% | 1.7044 | 16.11% | −36.68% | 0.8368 |

S&P 500 IT + Communication, point in time, 10 bp (reported):

| arm | choosing CAGR | choosing DD | choosing Sharpe | reported CAGR | reported DD | reported Sharpe | all CAGR | all DD | all Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| installed | 11.16% | −35.66% | 0.6324 | 51.04% | −26.44% | 1.8282 | 19.57% | −35.66% | 0.9565 |
| chase25 | 11.20% | −35.83% | 0.6431 | 41.21% | −26.44% | 1.7293 | 17.67% | −35.83% | 0.9164 |
| chase40 | 11.42% | −35.78% | 0.6455 | 43.02% | −26.46% | 1.7530 | 18.21% | −35.78% | 0.9254 |

## The verdict

**Criterion 1 fails.** The choosing-window Sharpe gain at 25 bp is
**+0.00004** (0.6736 to 0.6736), far below the +0.05 gate. At 10 bp the guard
lowers Sharpe (0.7083 to 0.6963). The chase40 sensitivity at 10 bp is +0.0037,
also far below; at 25 bp it lowers Sharpe (0.6585). The guard does not improve
the honest broad universe's risk-adjusted return.

Criterion 2 passes: choosing-window CAGR rises 0.073 percentage points
(10.6747% to 10.7476%), above the −1.0 point floor. Criterion 3 passes: the
choosing-window worst drawdown is −34.49%, inside the owner's −35.0% tolerance,
though 1.16 points deeper than the installed rule. Criterion 4 fails: the
guard's gain is below the placebo's 95th percentile (+0.0082). Criteria 5 and 6
pass (see below). The conjunction fails on criteria 1 and 4, so the guard is
closed.

The reported and full-period results are worse. At 25 bp the reported window's
CAGR falls from 26.29% to 23.45% and its Sharpe from 1.6743 to 1.5861; the full
period falls from 14.27% to 13.71% and its Sharpe from 0.8842 to 0.8559. The
guard defers entries that would have participated in the 2024-2026 rally. The
IT+Comm book shows the same pattern: at 25 bp the reported CAGR falls from
49.49% to 39.90% and the full period from 17.44% to 15.58%. Its 10 bp choosing
Sharpe is slightly higher (+0.0107), but the reported and full periods are
worse, so it is not a candidate there either.

## The placebo

Two hundred random-deferral draws, seeds 20261028..20261227, each deferring the
guard's count of entering names uniformly at random. **Mean gain −0.0055, 95th
percentile +0.0082, maximum +0.0172; the guard's gain is +0.00004.** The
guard's gain is below the placebo's 95th percentile, and below the best random
draw. The Sharpe criterion had already failed, so the placebo cannot rescue the
arm; it is reported for the record.

## The null and perturbation checks

- **Off null.** `Rule(chase=None)` reproduces the installed book exactly: the
  baseline matches the risk dial's 0.25/25 line to 1e-9, and the explicit
  `chase=None` run is byte-identical in equity, weights and trades.
- **All-defer null.** `Rule(chase=-1.0)` defers every entry: the installed
  book's 2,284 buys become 0, and equity stays at 100,000. Its Sharpe is 0.0 by
  construction (a flat curve), not a valid score and not a neutral reading.
- **No future data.** Changing every close after the 60% session
  (2022-01-31) leaves the deferral flags before it identical
  (`future_identical: true`); changing the newest close on or before it moves
  APA's flag (`newest_changes: true`).
- **Random count.** A unit test asserts the random arm defers exactly the
  guard's count per session and only names that are entering.

## What this means

The audit's book-PIT result was real on the book: the no-chase guard lifted the
minB arm's Sharpe from 1.07 to 1.13 and today's book from 1.10 to 1.21, with
CAGR flat. It did not transfer to the honest S&P 500 PIT universe. On the broad
universe the guard is flat on the choosing window and worse on the reported and
full periods; the book's entries are not the broad universe's entries. The
no-chase guard is not adopted, and it is not the next candidate. The program's
honest baseline stands, the 252-session freeze is unchanged, and the forward
record remains the priority.

## Caveats

- The cache is frozen at 2026-10-24; grades, band, tilt and membership are the
  desk as it stood then. Only `Rule.chase` changes, so the comparison across
  arms is clean, but the absolute levels are not a fresh backtest of today's
  desk.
- The store holds bars only for names it carries today; the membership is
  dated but the price history is survivor-biased. The absolute levels are
  flattered; the comparison across arms is the point.
- The choosing leg starts at the cache's first sizable session (2015-04-07),
  not 2016-01-01. The desk's grades are effective from 2016, so the first
  months are mostly cash; the program's 2016-2023 label is approximate.
- The guard is not in the live sizing path. `policy_book` is the simulator;
  the live nightly plan sizes through `grade_led_leader_policy.size_report`.
  A pass here would have been a candidate for a shared helper in both paths, a
  release ceremony and a 252-session forward shadow, not a live change.
- The all-defer book's Sharpe of 0.0 is a flat-curve artifact, not evidence
  that the guard is neutral.
