# Price-only nested allocation study — frozen September 24, 2026

## Objective and boundaries

Test whether a past-only, three-target ridge allocation gate improves funded
wealth over the same stock basket without that gate, unchanged
`cash-bounded-breakout-rotation/3`, funded SPY, funded QQQ and equal weight.
This protocol is declared before this runner's first real-market outcome run.
Previously examined history stays exploratory; nested validation cannot make
it an untouched test. No quality, survivorship-free, historical-availability,
deployment or adoption claim is made. No holding or order is changed.

The implementation and acceptance results will be recorded separately from this
specification. A failed run is retained; no tuning after reading outcomes is
permitted under this protocol.

## Pinned inputs

Use the September 18 vintage only. The original report has 2,945 sessions
(2015-01-02 through 2026-09-18), 94 stocks and SPY. Preserve it unchanged for
the incumbent. Add QQQ only to a separate execution panel, mapping by symbol.

- Trusted report SHA256:
  `d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26`.
  Authenticate the complete bytes before unpickling.
- Source manifest SHA256:
  `3e7f398610919674c4f798c4b359811aeac7a2d73d1c91dbf2f0e8446d0db8f6`.
  Its 190 source entries are 95 bars and 95 corporate-action files.
- Additional QQQ bars SHA256:
  `e496f36ebe70fd5ddbe25115cc44883b3c690b2fa71438436468725f37d55cd3`.

Verify every source hash, per-asset records, the exact XNYS calendar and all
570 report/source field comparisons, including missingness. Adjusted opening
prices are `open * adjusted_close / close`, not raw opens. Preserve individually
ragged histories; do not intersect all names, interpolate, backfill or select
names by their future availability. Corporate-action files establish source
integrity, not actual broker-share accounting or then-known adjustment factors.

The report's precomputed grades/regime are reconstructed evidence, not audited
point-in-time features. Historical membership and complete financial-feature
channels are absent. Price-only describes the new gate, not a claim that the
underlying desk basket has no non-price inputs.

## Stock and equal-weight compositions

On global source row `t % 20 == 0`, obtain stock weights from
`simulate._targets(original_report, original_report.panel, risk.BOOK_CONFIG, t)`.
This slices prices through `t` before sizing. Preserve the resulting residual
cash, grade selection, regime multiplier, tightening tilt and caps. Map the
weights into the separate execution panel; SPY and QQQ stock weights are zero.
Hold compositions unchanged between refresh rows. Never renormalize the basket
or apply regime exposure a second time.

Freeze the actual `BOOK_CONFIG` values and exercised source hashes in evidence:
top fraction .1, short fraction 0, volatility lookback 60, minimum volatility .1,
target volatility .3, maximum gross 1, name cap .15, theme cap .4, rebalance 20,
speed .5, minimum trade .005, configured cost 10 bp (study costs override fees).

Equal weight uses the same global-20 adapter schedule. At each refresh, assign
equal weights to non-index stocks with finite positive decision-close prices;
if there are none, retain cash. Eligibility never inspects a future row.
An account starting off cadence seeds the composition effective at its start.

## Twenty-two features, known by the decision close

For SPY, then QQQ, in this order:

1. Trailing adjusted-close log returns at 1, 5, 20, 63 and 126 sessions.
2. Population standard deviation (`ddof=0`) of the last 20 daily log returns,
   not annualized volatility.
3. `log(close / SMA200)`, including the decision close (first available row199).
4. `log(close / max(last63 closes))`, including the decision close (row62).

Then for the current, fixed decision-time stock weights `w`:

1. Four trailing gross log-wealth proxies at 1, 5, 20 and 63 sessions:
   `log(1-sum(w) + sum(w * close[t]/close[t-h]))`.
2. Population standard deviation of 20 daily log-wealth proxies calculated
   with that same current `w` and residual cash for each daily interval.
3. Invested fraction `sum(w)`.

These basket features describe the current composition's past, not returns of
a historically traded basket. A positive-weight member missing any required
endpoint/window makes that feature missing; never renormalize away the member.
Unused zero-weight prices may be missing. All-cash basket returns/volatility
are zero after the feature's ordinary lookback, not artificial prehistory.
Index windows likewise require complete finite positive prices. Finite feature
availability is the decision date; this is a derivation convention, not proof
that vendor-adjusted history was then available.

## Three economically comparable gross proxy labels

Order: stock, SPY, QQQ. Decision at close `t`; entry at adjusted open `t+1`,
exit at adjusted open `t+6` (five open-to-open sessions). Stock target:

`log(1-sum(w[t]) + sum(w[t] * adjusted_open[t+6]/adjusted_open[t+1]))`.

Index labels are the corresponding log price ratios. Preserve residual cash
and require both endpoints for every positive stock weight; missing endpoints
yield a missing label. Cash earns zero. Actual endpoint and declared availability
are both the exit session. The fitter requires both strictly before each fit.
Last six decisions have no observed label. Keep the complete raw labels and
endpoint arrays in the archive; exclude rows `t < 200` from training by an
explicit label mask. The mask is fixed before fitting and does not filter accounts.

Labels are idealized, uncharged buy-and-hold proxies, **not** the adapter's
close-sized, delayed-funded P&L. Cash forecast is zero. No calibrated probability
or prediction of tomorrow's color is claimed.

## Fitting, selection and accounts

Keep the existing nested runner unchanged: first outer row1260; outer blocks126;
three inner blocks126; minimum504 eligible training rows per target; ridge
penalties1/100; switch margins0/.005; all four candidates in declared order.
For outer start S, inner decisions `[S-379,S-1)` end at mark S-1. Each inner
block fits expanding past only; selected parameters refit at S. Separate
train-only transforms and unscaled missing indicators are fitted per target.
Selection maximizes worst-cost terminal log wealth at 10/25 bp; stable ordered
ties. One continuous outer account carries intent, cash, holdings and pending
funding through all refits; no account resets or cost-dependent forecasts.

At both costs, include six accounts over exactly the same decision/mark dates:

- Candidate and matched stock-only `no_gate_adapter`, from the nested runner.
- Unchanged `/3`: original report, `since=outer_start`, `BOOK_CONFIG`, current
  `paper.REBALANCE_EVERY` (20), `use_exits=False`, `event_risk.live_path`,
  `event_lifecycle=True`, and every current `simulate.LIVE_POLICY` flag. Preserve
  the FOMC reduction's 2026-06-18 policy-era boundary. No allocator override.
- SPY and QQQ using canonical funded `constant_exposure(fraction=1)`: daily
  close-sized, next-open decisions, not normalized price curves.
- Equal weight through the same stock/index/cash adapter.

All start from cash and NAV1, no leverage, 10/25 bp per traded dollar, zero
cash yield, no terminal liquidation. This is a simplified funding convention,
not real settlement or a market-impact/capacity simulation. `/3` has different
execution/deferral rules and an account-start cadence; candidate versus `/3`
is a whole-policy comparison. Only candidate versus the matching no-gate adapter
isolates the allocation gate under the same execution conventions.

## Evidence, reporting and acceptance

Before market outcomes, verify mathematical feature/label reconstruction,
cadence, ragged eligibility, original-report preservation, future-prefix
non-interference, all six comparator accounts, archive readback and independent
journal CLI reconstruction using synthetic inputs. Source tests must reject
mismatches before unsafe deserialization. Then run the frozen historical study
once, retaining every candidate and failure rather than choosing a favorable run.

Archive in a new directory without overwriting: original-input fingerprints,
normalized arrays, raw and masked labels, complete protocol/config/code hashes,
all fits/transforms/coefficients/predictions, inner selection scores, every inner
and outer journal, independent proof and scorecards. No private holdings,
credentials or personal account data are allowed in these unencrypted archives.

Build metric curves from independently verified account marks, using each
journal's own session indices and cumulative traded dollars. Require exact
calendar equality; never silently join/trim dates. Retain full, rolling, actual
outer-fold and prior-close SPY trend/volatility regime tables, including unknown
regimes. Fold intervals `[start,stop)` use marks `[start,stop]` and differences
in cumulative traded dollars, with carried holdings intact. Regime evidence is
the complete source SPY price series, not funded SPY NAV. Do not use hypothetical
fold reports as evidence of actual nested fitting. A losing result stays losing.

Integrity and accounting success do not establish predictive edge, historical
availability, financial quality or adoption readiness. A successful exploratory
comparison still requires independent validation before any live policy change.
