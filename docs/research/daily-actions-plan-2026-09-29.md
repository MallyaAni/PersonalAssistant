# Daily learned positions: frozen first experiment

Status: REGISTERED BEFORE FITTING. Research branch only; no live orders,
policy activation, dashboard change or deployment. Base: main `2262333`.

## Question and boundary

Can daily economic forecasts improve Buy/Add, Hold, Trim, Sell and position
size versus the current `/4` account, after costs? A forecast is not an action:
desired positions are compared with actual research holdings; cash and fills
remain the executor's responsibility. No imitation of hardcoded trade labels.

VERIFIED from source: the existing simulator accepts a custom allocator and
daily rebalance cadence. With `rebalance=1`, every ordinary session supersedes
old deferred/breakout/redeployment paths. Its existing event lifecycle still
owns event sessions. FAILED prior work: the Stage 3 selection/timing candidates
and target-consistency follow-up did not qualify for promotion. UNVERIFIED:
this daily candidate's forecasting, action behavior and economic benefit.

## Frozen data and target

- Existing local daily OHLCV only, adjusted using each row's adj_close/close.
  No SIP bars, intraday cubes, news retrieval, options or new provider requests.
- Same reconstructed desk report and dated membership mask as `/4`. Train
  only on member stock rows with a current A/A+ grade and available past
  features. Membership/current-universe omissions and reconstructed fundamental
  availability limit the evidence; these are not survivorship-free issuer data.
- Target: log(adjusted open[t+6] / adjusted open[t+1]), five executable sessions
  beginning after the decision close. It is a gross forecast proxy, not the
  actual multi-price, green-open-conditioned portfolio return.
- Features: stock log returns over 1/5/20/60 sessions; trailing 20-session
  return volatility; close relative to trailing 20/60-session mean; trailing
  20-session peak drawdown; today's adjusted open gap, log(high/low),
  log(close/open); log(volume / trailing20 mean volume); SPY and QQQ log
  returns over 1/5/20/60 sessions and trailing20 volatility. No ticker identity,
  analyst score or reconstructed fundamentals as model inputs. The grade is
  only the incumbent universe/quality gate, unchanged in every stock arm.
- Invalid/nonpositive OHLC or volume cannot become zero observations. Feature
  row eligibility uses inputs only; missing future labels stay missing. Keep
  genuine extreme observations/labels; no return winsorization. Fold-specific
  standardization for ridge uses only fit rows; no full-sample preprocessing.

## Frozen training and validation budget

First outer year 2019; last 2026 or available data, whichever is earlier.
For each outer year Y, inner training starts 2016 and ends before Y-1,
validation decisions are Y-1, outer decisions are Y. Every label endpoint must
strictly precede the next partition's first date. All stocks on a date share
the partition. No shuffled k-fold. Expand the past-only training window each
year, refitting the selected setting on all matured observations before Y.

One ridge family: alpha 10 or 1000 after train-only standardization. One
HistGradientBoostingRegressor family: learning rate .05, max_leaf_nodes 7 or
15, l2_regularization 10, min_samples_leaf 100, loss squared_error,
random_state 29. Evaluate 25/50/100 boosting iterations on the chronological
validation year (no internal random validation). Select each family's lowest
validation mean squared error, ties in declared order. This is the fixed
early-stopping/checkpoint grid, not a neural epoch search. At most eight
settings/year, eight outer years; no post-result feature/grid expansion.
Record all scores, selected counts/settings, label boundaries, refitted model
state and out-of-sample predictions. A train-only constant-mean forecast is
another control. Fewer than 500 training or 100 validation labels invalidates
that fold; do not silently shorten the history or search another split.

## Frozen action and sizing contract

Start with today's `/4` A/A+ equal-weight targets. For finite forecasts mu,
multiply each eligible target by clip(1 + mu / .02, 0, 1.5), cap each target
at .20, then scale down proportionally only if total exceeds 1. No leverage
or shorting. Missing forecasts retain the incumbent target and are counted
explicitly; they do not count as learned Hold decisions. The .02 scale and
1.5 bound are registered policy parameters, not claimed learned quantities.

All learned/control action arms decide daily (`rebalance=1`), through unchanged
`profit_taking.control_options` and `simulate.run`. Close-sized synthetic
adjusted units; cash-funded next-open buys, next-close ordinary sells,
green-open sell cancellation and current event lifecycle. A blocked/cancelled
sell is not a executed Sell. Costs 10 and 25 bp per traded side, zero cash
yield, no terminal forced liquidation, no real settlement or whole-share claim.
Record desired decisions separately from executed Buy/Add/Trim/Sell and held
balances. Safety tests must prove negative cash and shorting cannot occur,
and target changes cannot be undone by another normal-session buying path.

## Frozen comparisons and evaluation

Eight accounts: original 20-session `/4`; daily unlearned `/4`; daily momentum
forecast (five twentieths of trailing20 log return, same mapping); daily
train-only mean; daily ridge; daily tree; funded buy-and-hold SPY and QQQ.
Use shared calendars, costs and starting capital. Continuous accounts across
all outer years, not annual capital resets. Four start offsets 0/5/10/15
sessions (first screening, not the final 20-offset qualification).

Report net CAGR, total return, drawdown from starting NAV, turnover, cash,
executed action counts, forecast MSE against train-only mean, and paired
daily excess return / Newey-West t (lag 20) against both `/4` controls.
Show each outer year and causal regimes: prior-decision SPY close above/below
its trailing200 mean, and prior-decision 20-session annualized SPY volatility
above/below .25. Also show SPY/QQQ performance without implying they share
the stock strategy's drawdown or risk. Independently reconcile saved journals.

History through September 2026 was examined in prior projects: these annual
outer tests are chronological out-of-sample development evidence, NOT a
pristine untouched final test. New unseen observations are still needed.

## Kill criteria, fixed before observing this run

Any causal, accounting, calendar or action-contract failure invalidates the
economic reading until corrected and rerun under the same specification.
Do not promote automatically, even on success. A candidate advances only if,
at 25 bp, median CAGR exceeds BOTH original and daily `/4` by at least 1
percentage point; paired daily excess t >=2 against both at offset 0; max
drawdown is no more than 3 percentage points worse than either; net daily
excess is nonnegative in 2024+; and at least 3/4 offsets beat each control.
Otherwise RECORD / DO_NOT_PROMOTE and stop this candidate without tuning the
thresholds. SPY/QQQ gaps remain mandatory context, not a guarantee of returns.

Acceptance: causal/action/accounting tests; actual bounded fits and continuous
funded evaluation; saved models/predictions/receipts/journals/results in a new
separate scratch directory; reviewed code/results pushed to Spark research
branch, then GitHub from Spark. This is not completion of live ML integration.
