# Selective action advantage around /4 — frozen experiment

Status: registered before labels, fitting or new outcome inspection. Research
only; no live deployment. Parent code: `0f6819384e3676079b7e5435ead795554ddae97e`;
Spark and GitHub main checked at `2262333`. The failed daily-reset experiment
is not rerun. This is a different target and intervention policy, not a claim
that a more complex model must beat /4.

## Question and fixed interventions

Does a holdings-aware estimate of net action advantage improve the existing
cash-bounded /4 strategy without changing its 20-session reset cadence?

The underlying account retains /4's quality/membership gates, next-open buys,
cash funding, next-close ordinary sells, green-open sell cancellation, deferred
retry, midcycle rotation/redeployment and FOMC lifecycle. Event ownership wins.
There is at most **one new intervention per actual reset cycle**, including an
intervention whose fill is cancelled. Consider decisions at cycle ages
0, 5, 10 and 15; event-owned days are skipped, not rescheduled. Actual resets
clear the intervention and any reduction lock. Accepting the incumbent plan
is called **no intervention**, not Hold: /4 may itself place trades.

At each eligible close enumerate current-information-only alternatives:

- Buy/Add: increase the incumbent proposed units by at most 2% of current NAV,
  bounded by available cash after reserving all incumbent buys and their fees,
  and by a 20% decision-close position ceiling. Require current A/A+ membership,
  the incumbent buy block to be clear, and no incumbent sell in that symbol.
  This may exceed its equal-weight target but not the 20% ceiling.
- Trim: reduce to half the currently held units, only if this is below the
  incumbent proposed units. Sell: reduce to zero, only if it changes that plan.
  Never reverse a stronger incumbent reduction. Only currently held names
  qualify; they need not still be A/A+. Ignore changes below /4's 0.5% NAV
  trade floor. Pre-run clarification: require at least 0.5% NAV both versus
  the incumbent proposal and versus current holdings; cancelling a large
  planned add does not authorize a tiny below-floor sell.
- A reduction sets a unit ceiling through the next actual reset. Apply it
  after every ordinary buying path and remove suppressed deferred buys.
  It does not override event execution or force immediate sells when an
  ordinary sell is cancelled. On later ordinary days it retries under the
  same execution rules. Buy/Add is a one-time proposal, not a daily top-up.
  Pre-run clarification: if an ongoing ceiling changes the incumbent order
  into a below-0.5%-NAV trade (including a capped buy), keep the lesser of
  current and incumbent units that day, retaining any incumbent exit plus
  the ceiling and deferred-buy suppression. The
  ceiling is an instruction, not a claim that all reductions already filled.

Select the highest predicted advantage strictly above **0.0005 of NAV**
(5 bp); otherwise accept /4. Ties use symbol then action lexical order.
No future execution/label availability may decide whether a present candidate
exists. Candidate accounts use their own holdings, cash, holding ages and
reset state at inference.

## Exact counterfactual labels

Use one unchanged /4 teacher account starting at the first session of 2016,
with cost **25 bp per side**, no initial offset. At each eligible teacher close
save its pre-planning state and fork the same simulator through **20 subsequent
sessions**: unchanged /4 versus one candidate intervention. Recompute all
future plans from each fork's actual state; never replay baseline orders.

Label = `(intervened_NAV[t+20] - unchanged_NAV[t+20]) / teacher_NAV[t]`.
It includes the actual fills, cancelled sells, fees, cash and subsequent /4
actions. Reduction locks expire at the actual reset, even if before t+20.
Incomplete future endpoints produce missing labels, not deleted feature rows.
Training uses the conservative 25 bp teacher labels at both evaluation costs;
there is no cost-specific model search and no aggregation of offset teachers.

The simulator hook is default-off. Checkpoint/resume must retain book units,
cash, trade/open/paid state, reset weights/clock, deferred orders, event baseline
and sold units, scale/brake state and counters. Cache only market preparation.
Before generating labels, prove no-op continuation and intervention forks
against full-prefix replay, including events, resets, funding and cancellations.

## Features and fit protocol

Reuse the 22 causal daily OHLCV/SPY/QQQ features in `daily_action_model`.
Append held weight, cash/NAV, current /4 target minus held weight, holding age
in sessions, sessions until scheduled reset, signed intervention notional/NAV,
incumbent proposed weight and four one-hot action columns (Buy/Add/Trim/Sell).
No ticker identity, future grades, forward return, future availability, revised
fundamental level or test-period statistics as model inputs. Grades remain
eligibility gates. Missing current features mean no ML proposal. Do not clip
labels or delete financial outliers; ridge scales from fit rows only. Tree
splits handle extremes without fitting a full-sample preprocessing transform.

Eight annual outer folds: 2019 through available 2026. For each year Y, train
from 2016 to before Y-1, validate in Y-1, then refit through before Y. Both
fit and validation admit only labels whose t+20 endpoint is strictly before
their respective stopping boundary. The final refit also uses only endpoints
strictly before Jan 1 of Y. No random k-fold. Require 500 fit and 100 validation
labels; otherwise mark the experiment invalid, never silently shorten the purge.

Ridge alpha {10, 1000}; histogram boosted tree max leaves {7, 15}, learning
rate .05, L2=10, minimum leaf rows=100, random seed=29, iterations {25,50,100},
no random internal early stopping. Choose minimum validation MSE, with listed
order breaking ties; then refit with that fixed setting. Iteration checkpoints
are tree training rounds, not neural-network epochs. Save actual models,
hashes, fold bounds, settings, feature names and predictions. Past-only mean
control uses each action's mean label; absent action uses zero. No DL/RL in
this bounded first action-value experiment.

## Funded evaluation and rejection criteria

Seven arms: unchanged /4; selective unlearned momentum; past-only action mean;
selective ridge; selective tree; SPY buy-and-hold; QQQ buy-and-hold.
The momentum control uses signed incremental weight times (stock 20-session
log return minus SPY 20-session log return) as its score, with the identical
5 bp selection floor, opportunity schedule, sizing, locks and account engine.
It is deliberately untrained, not an oracle. The mean control uses the same
policy mechanics. Start accounts in 2019 at session offsets {0,5,10,15};
carry capital continuously, including across model-year changes. Evaluate
10 and 25 bp per-side costs: 56 accounts total. No leverage or shorting.

Report net CAGR, total return, max drawdown, daily excess returns with HAC(20),
yearly results, turnover, cash, proposed/submitted/executed actions and
cancellations separately. Regimes use prior-close SPY vs its 200-session mean
and 20-session annualized volatility at a fixed 25% threshold. Discontinuous
regime slices have growth contributions, not fictitious standalone CAGRs.
Independently reconcile all cash/fill journals and reopen saved samples.

At 25 bp, each learned candidate must beat both unchanged /4 and matched
momentum: median CAGR improvement >=1 percentage point, offset-zero paired
HAC t>=2, max drawdown no more than 3 percentage points worse at every offset,
nonnegative offset-zero recent (2024+) mean daily excess, and positive CAGR
excess at >=3/4 offsets. Failure of any screen means DO_NOT_PROMOTE.
Passing means RESEARCH_PASS_ONLY, never automatic deployment. Report mean
and index comparisons regardless of screening. No settings or thresholds may
be changed after outcomes. All implementation corrections and deviations are
recorded before re-running; failed runs are preserved.

## Limits and acceptance

The 2016–2026 history has already been examined in prior research, so this is
chronological validation, **not a pristine final holdout**. Reconstructed
historical grades, membership gaps (including 15 unavailable former names),
late admission of modern names, adjusted-price revisions, no spread/impact
model beyond fixed costs, and synthetic continuous units remain limitations.
The teacher visits only /4 states; distribution shift under intervention must
be reported, not treated as proven off-policy coverage. A negative result is
useful evidence but not proof that ML cannot help.

Finish means actual label generation, chronological fitting, funded backtests,
saved evidence, independent checks, and an honest result note—not just an API
or test scaffold. No provider purchase, broker action, laptop permission,
runtime/model-server setting or live dashboard change. CPU-only scratch work
on Spark, two BLAS/OpenMP threads per process. Push the research branch to
Spark and to GitHub **from Spark**. No merge or deployment of this candidate.

Diagram impact: NONE — implementation remains within the existing offline
market-model, simulator, benchmark and research-journal boundaries.
