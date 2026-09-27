# The CNN's volatility forecast as the sizing input for the graded equal-weight book: pre-registration (2026-09-27)

Written before the run. Nothing in this note is a result. The kill criteria
in the last section are fixed here and the code (`backend/market/vol_sizing.py`)
carries them as constants; a change to either is a new trial.

## Question

Stage 1 of the deep-intraday plan
([deep-intraday-stage1-2026-09-27.md](deep-intraday-stage1-2026-09-27.md))
found one thing a deep model earns: the temporal CNN forecasts the next
session's realized variance with out-of-sample R² 0.27 against the
trailing 20-session baseline, on 2016-2023 and again on 2024-2026. Does
that forecast, used only to *size* the graded equal-weight book
(`policy_v4.allocator(mask)`: every A/A+ member at min(1 / count, 0.20),
the arm the paper account runs), earn anything over the book without it -
and, separately, over the same sizing rule fed trailing volatility, which
is the control that decides whether a gain is "the forecast" or just
"inverse vol"?

## The prior, and what would make it wrong

The book is about eleven names of similar volatility, already equal weight
and already capped at a fifth of equity. Inverse-volatility weighting on
such a book moves weights by a few points either way and is worth 0-2 CAGR
points a year in either direction, most often within a point of equal
weight; the 2026-09-26 point-in-time arms found the `/3` rule's
inverse-volatility tilt and its 0.30 volatility target were part of what
cost that rule fifteen points, though there they came bundled with regime
multipliers and concentration. A volatility target with no leverage can
only cut exposure, and cutting exposure on a book that compounds at 25-30%
a year costs return on most sessions to save it on a few; the prior is that
it lowers CAGR and drawdown together and leaves the ratio about where it
was. The forecast beats trailing volatility by R² 0.27, but the sizing
rule reads the *cross-section* of volatility (which name is calmer than
which) and its *level* (is tomorrow a loud day), and both are mostly in the
trailing number already; the prior is that the forecast adds little over
trailing volatility once it is a weight - well under the half point the
twin rule asks for.

The prior is wrong if a forecast variant clears every floor below,
including the half point over its trailing twin. That would say the CNN
sees next-session volatility the trailing window does not, in a way that
moves money usefully on this book, and the volatility head would then be
the first deep-model output to earn a place in the account's sizing. It is
also wrong, in the other direction, if inverse volatility from *trailing*
volatility clears the CAGR floors on its own: then the finding is that the
equal-weight book leaves an inverse-vol tilt on the table, labelled as
such and not as a forecast result.

## The rule

`backend/market/vol_forecast.export_forecasts` runs the stage-1 CNN
walk-forward (`deep_intraday.walk_forward`: refit every 63 sessions on an
expanding window, first fit after 500 sessions, 5-session purge, one fixed
configuration, no search) on the volatility target alone and writes the
out-of-sample forecast per (name, session t) row with the trailing
baseline and the realized value beside it. The row dated t is made from
bars through the close of t and targets session t + 1; the allocator
decides at t's close and holds t + 1, so it reads the row dated t and no
other (`vol_forecast.align`; the no-lookahead test shifts the matrix by a
session and asserts it differs). Both forecast and baseline are log
realized variance; sigma is exp(x / 2).

Every variant wraps `policy_v4.allocator(mask)`: it calls it for the
session's control weights and rescales them, never choosing a different
set of names. A held name with no sigma that session - before the first
fit (2018-02 on the store), on a session the dataset has no row for (the
day before an early close, when the dataset's "t + 1 complete" rule drops
the row), or a name outside the dataset - keeps the control's weight, and
the share of such positions is counted and reported (`fallback_share`).
The forecast variants therefore *are* the control on 2016-2018 by
construction, and the choosing window's numbers carry that.

- Inverse volatility: the held names' weights proportional to 1 / sigma,
  renormalised to the control's total invested that session, each capped
  at 0.20 with the excess redistributed among the rest (water-filling);
  when every name is at the cap the book is the control.
- Volatility target: the control's weights scaled by min(1, target /
  predicted), where predicted is the exposure-weighted sum of the names'
  sigma (a full-correlation proxy: the book's names move together) and
  the target is the median over 2016-2023 of the same quantity on the
  control's own weights with the *realized* next-session sigma, measured
  once before the run and recorded in the payload (`vol_target`). No
  leverage: exposure never exceeds 1.0.
- Hybrid: inverse-volatility weights, then the volatility target.

## Variants, fixed now (one registered trial each; six and the control)

| name | scheme | sigma from | twin |
|---|---|---|---|
| `ew` | control: `policy_v4` as it is | - | - |
| `inv-vol-forecast` | inverse volatility | CNN forecast | `inv-vol-trailing` |
| `inv-vol-trailing` | inverse volatility | trailing 20 sessions | - |
| `vol-target-forecast` | volatility target | CNN forecast | `vol-target-trailing` |
| `vol-target-trailing` | volatility target | trailing 20 sessions | - |
| `hybrid-forecast` | inverse volatility + target | CNN forecast | `hybrid-trailing` |
| `hybrid-trailing` | inverse volatility + target | trailing 20 sessions | - |

Every variant runs under the plain options (next-open fills,
`use_exits=False`, the live reset cadence) AND under the live execution
policy (`market_pit_scorecard._live_options`: sells at the close, the
green-day skip, the band gate, mid-cycle entries, deferred buys, the FOMC
path and lifecycle). Both are reported; the verdict reads live, because
that is what the account runs.

## Statistics, fixed now

The pit scorecard's 20 start offsets, costs 10 and 25 bp one way, windows
2016-2023 (choosing), 2024-2026 (reported) and all. Per variant, option
set and window: median CAGR, worst and best CAGR and median worst drawdown
across offsets; the ratio CAGR / |max drawdown|; median exposure on
rebalance sessions; the fallback share; the count of offsets above the
control under the same options; the paired daily difference at the median
offset against the control under the same options and against the
trailing twin, with a Newey-West t at lag 20 and the probabilistic Sharpe.

## Kill criteria, fixed now

A forecast variant is **ADOPT (registered)** only if, on 2016-2023 at 25 bp
under the live options, its median CAGR is at least 1.0 point above the
control's with the paired Newey-West t against the control at least 2.0,
AND its median worst drawdown is not worse than the control's, AND it is
not worse than the control on 2024-2026 by paired bp a day, AND it beats
its trailing twin by at least 0.5 CAGR point. A variant that clears
everything but the twin is **RECORD** labelled "inverse vol, not the
forecast": the gain belongs to the sizing rule, which trailing volatility
feeds as well, and is recorded under that name. Anything else is
**RECORD**. The trailing variants are controls and are never adopted from
this trial; if one clears the CAGR floors on its own the note says so and
a separate registration would follow. The ratio is reported for every
variant whatever the decision.

ADOPT authorises a registered change to the live policy (a `/5` with its
own version string, built with tests and gated), not a same-night edit;
the paper account runs `/4` until then.

## Commands

On the RTX (the forecast file; the dataset is the stage-1 export):

    python -m backend.cli.market_vol_forecast --dataset stage1_dataset.npz --out vol_forecasts.npz --device cuda

On the Spark (the trial; needs the store and the desk):

    python -m backend.cli.market_vol_sizing --root data/market --forecasts vol_forecasts.npz --offsets 20 --costs 10 25

Writes `<root>/desk/vol_sizing.json`; prints one table per option set and
the verdict. Seven variants x 2 option sets x 20 offsets x 2 costs is 560
simulator runs, about twice the catastrophe stop's.
