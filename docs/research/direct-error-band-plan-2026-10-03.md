# Error-informed changes to learned holdings

Registered after verified direct study e093cd51 and its complete publication
9334fb83, BEFORE this correction's account outcomes. This is one incremental
decision correction to the saved direct model, not another predictor or search.

Objective: preserve the direct learner's stock-conditioned buy/hold/trim/exit
mechanism while reducing unnecessary changes when its historical forecast errors
do not support a precise mean. No fixed entry distance or profit percentage.
Primary acceptance remains compounded net gain versus the matched daily rule,
SPY and QQQ at ALL0/10/25bp; trading/year is a separate key diagnostic. Do not
choose a cost, window, stock or regime to claim success. A smaller trade count
alone is not success. This cannot prove full live-policy or intraday parity.

VERIFIED: source e093cd51, report764e8e6489325bf84d515ae2acc000bdebe41a2b539e59df1dce274950e8fc0a,
proof8c8bbe09871d4e1ae3a87ecf306d135f80c330a111edee4bb1664d3b2ecb7017;
141 monthly receipts/79 numeric heads and three saved accounts,15 older controls.
Zero-cost direct gain749.92% versus rule547.68%, but89.20NAV/year gross trading.
FAILED: positive-cost full-period rule total-gain advantage. UNVERIFIED: whether
an error-informed holding band improves the gain/turnover tradeoff. Positive-cost
shortfalls are not an isolated estimate of fee or turnover effects.

Reuse the exact authenticated direct forecasts, bridge arithmetic labels,
score_mask, symbols and date/endpoint grid. No fitting or rescoring of any model.
At the first exchange session of each calendar month, take only same-stock saved
OOS predictions and finite labels within the preceding756 session indices, whose
endpoint is strictly before min(month's first session,2026-08-17). This mirrors
the registered source lookback/freeze; neither future outcomes nor scoring-time
filtering may enter calibration. Benchmarks have no stock calibration. Missing
future labels do not change current scoring eligibility or denominators.

For each stock, residual e_i=realized arithmetic return_i - saved forecast_i.
Group residuals by their forecast calendar month, preserving serial dependence
inside a model month. N is the number of actual residual observations; G the
number of observed month clusters. If N<2 or G<2, radius is unavailable (NaN),
not zero or a chosen pooled fallback. Otherwise compute mean residual b and
cluster-robust standard error

    se = sqrt((G/(G-1)) * sum_g(sum_{i in g}(e_i-b))**2) / N
    radius = abs(b) + se

The multiplier is exactly1, no tuned alternative. This is an empirical error
resolution statistic, not a calibrated probability, guaranteed confidence
interval or clean measure of epistemic uncertainty. It assumes past errors are
relevant to today's conditional mean; clustering does not cover across-month
dependence or distribution shifts. Zero observed error may yield zero radius.
Do not describe future price moves as confined by this radius.

Freeze the stock radius for that scoring month, retaining every monthly and
stock receipt: sample/cluster counts, maximum endpoint, original typed residual
row hashes, bias, cluster sums, standard error and radius. No estimates from
in-sample fitted predictions, no interpolation, no silent unavailable fallback.
All94stock identities, including missing calibration, remain explicit.

Keep the exact direct forecast mean and one-session covariance/second moment.
Only the incremental convex objective changes, from a scalar cost penalty to

    0.5*w' second_moment w - mean'w
      + sum_j (actual_per_side_cost + radius_j)*abs(w_j-current_j)

The robust interpretation concerns uncertainty in incremental mean utility
relative to the current holding, not a worst-case guarantee on portfolio return.
Radius is NOT a paid fee, cash deduction, execution spread or extra broker cost.
Funding continues to use actual cost only. Covered grade exits/caps remain
mandatory. Unavailable radius is treated as unavailable forecast evidence:
exclude unheld names; preserve held ownership/caps and the existing safe
missing-held-cross-risk fallback, retaining the blocked plan explicitly.
Default callers with no radius must retain exact old targets and receipts.
An explicit all-zero radius must preserve old numeric targets; record its new
contract without pretending it supplies calibrated uncertainty.

Acceptance exposed numerical solver residue at an exact no-change kink before
any new actual account outcome. In the optional band path only, canonicalize
current weights where the declared subgradient lies strictly inside the change
penalty and bounds permit the holding. Reconstruct exact trade/purchase auxiliary
variables; use the canonical point ONLY if a fresh existing feasibility/global
convex certificate passes (strict bounds; declared1e-8 constraint/gap tolerances).
Otherwise keep the original certified point. When
the resulting target exactly equals current weight, preserve original shares
instead of creating a floating round-trip trade. No economic percentage or
parameter is introduced; absent/zero-radius scalar solves remain unchanged.

Keep common NAV1 anchor2020-03-02, first official-open proxy03-03, end09-30,
same prior-close share freezing, pre-sale cash, covered shares, fees/basis/profit,
missing-open expiry,25% operator cap and zero cash yield. Historical current-
vintage grades/universe and synthetic adjusted fractional units stay explicit.
Earlier unavailable calibration is retained as missed cash/holding opportunity;
do not shift the evaluation start to its first successful trade.

Run exactly THREE new error-band books0/10/25bp. Authenticate and reuse all THREE
direct books and FIFTEEN prior controls, no old account replay/audit or model fit.
Publish all/effective2018–20/2021–26/reusedAug17–Sep30 windows, CAGR, positive
drawdown loss, Sharpe, exposure, rolling252 wins, actual fees, gross trading/year,
plan/fill/cash/missing/blocked counts and all stock profit contributions. No
adoption automatically follows a favorable component result.

Before actual new accounts, require causal label endpoint/freeze/month receipts,
typed original lineage, same-month correlation handling, different-stock error
radii, zero-error and missing evidence, future-prefix invariance and declared
NaN counts. Exercise the actual convex solver: uncertain favorable names are
held rather than added; uncertain negative means retain holdings; sufficiently
strong signed advantage causes funded buys/covered exits; safety exits remain.
Actual fees/cash must never include radius. Default controls remain exact.
Then independently audit saved calibration, objective certificates and only new
ledgers with all fixed metric cells, without fitting or strategy replay.

Research-only; production, UI, data and model services unchanged. No new family,
parameter/window mining, paid data, real orders or research-only deploy/gate.
Diagram impact NONE within the existing research/accounting boundary.
