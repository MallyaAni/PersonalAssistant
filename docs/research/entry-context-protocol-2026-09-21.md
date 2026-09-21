# Ten-session entry context ablation — protocol — September 21, 2026

Independent pre-run review: 29 context/pilot tests passed on the desktop,
no skips; targeted Ruff passed. Review corrected the real intraday partition
boundary, added input/model hash verification before model loading, added
paired comparisons against always-wait and the same-mode price-only arm,
and required automatic replay before success. Run once with four CPU threads
and a two-hour process ceiling; do not tune from its output.

An information test, not a profitability claim. The question is whether
correct, point-in-time quarterly fundamental context adds information to
the ten-session entry-timing decision at all, before any GPU training time
is spent. Everything here is retrospective on reused periods and nothing is
promoted to the live desk. A new GPU experiment is justified only if this
feature ablation gives a reason, not to satisfy hardware usage.

## Frozen design

- **Horizon** exactly 10 sessions. `SLOTS` and the top-five momentum20
  candidates are unchanged from `entry_pilot.build`.
- **Training** 2020-01-01 through 2023-12-31 with the existing exit-label
  purge at the boundary (`entry_pilot.split`, labelled). No hyperparameter
  or horizon search.
- **Report periods** 2024, 2025-to-data-end, and pooled (2024-to-data-end),
  reported separately. These are explicitly retrospective/reused periods,
  not untouched validation or test sets; the manifest labels them as such.
- **Models** two paired `HistGradientBoostingRegressor` per feature set, one
  per target column, targets identical to the pilot (immediate reward and
  wait-minus-immediate). Exact parameters, no tuning:
  `max_iter=100, max_leaf_nodes=15, min_samples_leaf=100,
  l2_regularization=10, learning_rate=0.05, early_stopping=False,
  random_state=0`. Raw target units are used consistently in both arms; no
  target scaling is mixed.
- **Feature sets**
  - price-only: the pilot's 28 price features, normalized with training-only
    mean/std and clipped to [-10, 10] exactly as the pilot's trees receive
    them;
  - context: the same 28 normalized price features plus 21 quarterly columns
    — the seven corrected quarterly features, seven missingness flags, and
    seven fiscal-period ages.
- **Baselines** always-enter and always-wait. Costs 5/10/20 bps each side.
  Each model runs in timing-only mode (enter/wait) and in enter/wait/skip
  mode. Every model result carries paired account daily-return intervals
  against **both** baselines, and each context-arm result also carries the
  paired interval against its price-only arm on the same window, cost and
  mode. Net return, drawdown, exposure and turnover are reported. No winner
  is selected automatically.

## Quarterly inputs

- The seven corrected quarterly features are `fundamental_features.FEATURE_NAMES`
  (revenue_yoy, revenue_qoq, revenue_acceleration, gross_margin, net_margin,
  ocf_to_revenue, capex_to_revenue) from `fundamental_features.features`,
  which is point-in-time: values are those public at the session read.
- **All quarterly inputs and ages are read at decision day minus one** (the
  session before the decision). A lookup at day zero (the decision day's own
  first session, or any row with no prior session) must fail.
- Each feature's **fiscal-period age** is the days from the referenced fiscal
  period end (the `period_ends` tensor) to the read session (decision day
  minus one). Ages are clamped to 0..2000 days. An unknown age (feature
  missing) is encoded as 2000, alongside its missingness flag. A negative
  age — a period dated after the read session — indicates invalid data and
  must fail, never be accepted.
- **Missingness flags** are set before any imputation, so a genuinely zero
  economic value keeps flag 0 and an imputed value keeps flag 1.
- Missing quarterly economic values are filled with the **training-only
  median** per column; a column all-missing in training falls back to a
  median of zero.
- No row is filtered out for missing fundamentals; foreign/no-filing names
  remain in the cross-section with their flags and unknown ages.
- Preprocessing (price normalization, context medians) is frozen in the
  artifacts and reused verbatim at verification.

## Artifacts and verification

- New output directory only. Manifest records git revision, source hashes of
  the CLI, `entry_context`, `entry_pilot`, and the imported feature selector
  modules (`fundamental_features`, `fundamentals_asof`), the intraday
  partition the dataset was built from, dataset hash, pinned hashes of every
  saved artifact (dataset, context, preprocessing, predictions, both model
  files), horizon, split counts, library versions, feature names, and
  limitation labels.
- Saved: dataset, preprocessing (price normalization and context medians),
  fitted models, predictions, account results, and a concise summary.
- Verification reloads only its own artifacts: the pinned artifact hashes and
  the dataset fingerprint are checked **before any model is loaded**, so a
  tampered input — even one too small to change a prediction — is rejected
  without being used; it then reproduces predictions at a tight explicit
  tolerance and replays every account path with exact decisions and NAV
  within atol 1e-10. Nothing is recomputed into or overwritten in the
  manifest during verification. No arbitrary external pickle files are
  loaded. CPU threads are capped at four.
- Account baselines are preflighted before any model is fitted, and the CLI
  verifies its freshly written output before reporting success.

## Limits

Survivor universe; retrospective reused periods only; IEX bar-open fills
with no impact or spread history; price-only fixed selection, not the
production desk; zero cash interest; daily-close drawdown only. This is an
information test and does not authorize any live promotion.
