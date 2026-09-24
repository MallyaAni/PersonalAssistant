# Fixed next-strategy protocol — September 24, 2026

## Decision

The strongest strategy supported today remains the adopted
`cash-bounded-breakout-rotation/3`. It is the winner among the candidates AniOS
has actually compared, not a universal optimum. The completed price-only neural
candidate and the gradient-boosted ranker both lose to their fixed momentum/rule
comparators. Neither may be retuned, relabelled, or promoted.

The next challenger is
`incumbent-neural-rank-blend/1-research`: an equal blend of the incumbent and
price-only neural cross-sectional percentile ranks. It is research only. It does
not change recommendations, the personal position view, the paper broker, or the
adopted policy.

## Why this is the next test

Recent 2026 work supports a disciplined portfolio-level test, but no paper
establishes a generally superior trading architecture:

- Zhu and Cai's review finds no public evidence that one AI architecture
  delivers persistent, cross-regime, capacity-aware net alpha. It calls for
  point-in-time inputs, decision-aligned objectives, portfolio/execution
  evaluation, and prospective evidence
  ([arXiv:2609.04917](https://arxiv.org/abs/2609.04917)).
- Pollok and Robik find that their lower-turnover transformer survives costs
  better than an LSTM, but only matches rather than significantly beats equal
  weight in the pooled comparison. Their model ensemble falls between its
  components, and a rule that switches to the recent winner does not help
  ([arXiv:2607.00475](https://arxiv.org/abs/2607.00475)).
- Wade finds that the best volatility forecaster, best cross-sectional ranker,
  and best portfolio are three different models. The study also identifies its
  current-constituent survivorship bias and construction dependence
  ([arXiv:2605.19278](https://arxiv.org/abs/2605.19278)).
- Sanderink finds that inverse-uncertainty sizing can reduce the strongest rank
  signals. Its model-specific trust gate and tail cap are promising, but were
  evaluated on one concentrated AI universe and require realized model efficacy
  before acting
  ([arXiv:2603.13252](https://arxiv.org/abs/2603.13252)).
- Fonseca formalizes look-ahead freedom as temporal non-interference, reinforcing
  the repository's separate reference-time and availability-time checks
  ([arXiv:2607.04958](https://arxiv.org/abs/2607.04958)).
- Fernandes and Desell show that direct portfolio objectives can outperform
  simple controls in one 2022–2023 test, but the two-year test and one universe
  do not establish portability to this desk
  ([arXiv:2605.28853](https://arxiv.org/abs/2605.28853)).

The equal rank blend is therefore an attribution test, not an assertion that two
weak signals become strong together. It asks one clean question: does neural
ordering add incremental information to the rule that already wins? Equal
percentile ranks avoid fitting a post-outcome scale or blend weight. A learned
regime selector, uncertainty weight, direct portfolio loss, and extra feature
search are deliberately outside this candidate.

## Frozen implementation

- Policy ID: `incumbent-neural-rank-blend/1-research`.
- On each decision session, retain the common set of names for which both
  scores exist, percentile-rank each score across that exact set, and average
  the two ranks 50/50. Ties receive their mean rank. A neural score cannot add
  a name outside the incumbent's evidence coverage.
- Keep the adopted grades, eligibility, risk caps, twenty-session reset,
  midcycle entry/exit behavior, FOMC lifecycle, cash funding, deferred buys,
  next-open/close execution rules, and name limits unchanged.
- Do not add a market-regime selector. A future model-specific trust gate needs
  a predeclared history of genuinely forward forecast errors; the completed
  reconstructed study cannot supply it.
- Do not use the known defective frozen fundamental/share-unit path. A forward
  run must use the separately named price-only model and preserve its exact
  model, normalization, features, forecast, and input hashes.

The code path is implemented in `backend.market.neural_policy_comparison` and is
ineligible for adoption by construction. It does not itself start a run or score
the already examined neural study.

## Evaluation gate

Freeze the model artifact and begin only with decisions created after this
protocol. Retain every missing forecast and failed observation. Review after 252
completed exchange sessions; do not stop or select a date from interim results.

Run candidate and incumbent through the identical funded account at 10 and 25
basis points per traded dollar. Compare the candidate, unchanged incumbent,
SPY, QQQ, and equal weight on exactly the same sessions and costs; do not inner
join away a missing observation or substitute an uncharged index price series.
Total return is the primary objective. Also report CAGR, maximum drawdown,
zero-risk-free Sharpe, bought-plus-sold turnover divided by mean NAV, exposure,
fees, concentration, and rolling 63/252-session wins against the incumbent, SPY,
and QQQ.

Decompose all one-session net account returns with the already-fixed causal
regimes. For the return ending on session `t`, use information available only
through the preceding account session `t-1`: compare that point-in-time SPY
adjusted close with the arithmetic mean of the 200 adjusted closes ending at
`t-1`, assigning equality to above; compare the population standard deviation of
the 20 close-to-close log returns ending at `t-1` with the median of 252 such
volatility observations ending at `t-1`, assigning only a strictly higher value
to high volatility and equality to low. Report all four above/below-trend ×
high/low-volatility combinations. Insufficient or invalid history remains an
explicit `unknown_or_unavailable` bucket, so every return interval reconciles
and none is dropped. Report log-growth contributions, mean daily excess,
observed months and contiguous episodes without treating those periods as
independent trials. Do not annualize stitched regime segments. These are
attribution tables, not permission to switch strategies by regime.

The primary hurdle is higher net total return than the unchanged incumbent,
SPY, and QQQ at both costs. Drawdown, turnover, and rolling consistency diagnose
whether that result is usable; they cannot be hidden by a higher return. Passing
supports an adoption review, never automatic promotion. Until then the adopted
strategy and all dashboard labels remain unchanged.

`backend.market.neural_study_metrics` enforces the fixed comparison set and
provides the fail-closed full-sample and regime scorecards. Any forward runner
must feed it actual funded-account curves plus point-in-time SPY adjusted closes
with enough pre-evaluation warm-up; it must not derive regimes from the SPY
account NAV or from candidate outcomes.
