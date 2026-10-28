# Top-tier swing-trading algorithms: what the evidence supports — 2026-10-28

Status: research note. No live change, no install, no order. The program of
record remains `trading-program-2026-10-28.md`; the installed rule remains
`grade-led-leader-weight/1`, frozen for the forward record.

This note answers three questions the owner asked: what the best external
evidence says actually makes money in swing trading, what the Codex and Claude
implementations got right and wrong, and which concrete algorithmic changes
this desk should test next. It is deliberately about algorithms, not operations.

## 1. The honest starting point

The installed rule selects on grades (fundamental, technical, sentiment, value
at three votes, rotation at half a vote), enters at A, holds while B, sizes
equal A/A+ slots tilted 0.5x-1.5x by trailing 63-session return rank, scales the
book to a 25% realised-volatility target with a 50% exposure floor, caps a name
at 25%, tilts by P/E own-history, and fills at the next open.

On the honest point-in-time universes it earns:

| line | universe | CAGR | worst DD | Sharpe |
|---|---|---:|---:|---:|
| installed rule | S&P 500 PIT, 10 bp | 14.8% | −34.7% | 0.90 |
| installed rule | S&P 500 PIT, 25 bp | 14.2% | −33.3% | 0.88 |
| installed rule | S&P IT + Communication PIT, 10 bp | 19.5% | −35.7% | 0.96 |
| equal weight, no costs | S&P IT + Communication PIT | 19.9% | −34.4% | 0.93 |
| SPY | — | 13.8% | −33.7% | 0.82 |
| QQQ | — | 19.0% | −35.1% | 0.91 |

The 37.6% book number is the choice of names, not the rule. The rule earns
roughly SPY plus one to three points with a better Sharpe; inside technology it
matches equal weight and trails QQQ. That is the bar any candidate must clear.

The objective is forward, point-in-time, after-cost CAGR with worst drawdown no
deeper than about 35%, Sharpe at least 1.0 on the honest universe, long-only, no
leverage, US large caps, turnover no more than about 2x a year, one engine, and
every change pre-registered and forward-shadowed.

## 2. What the external literature says survives

I reviewed the primary papers and the recent replication evidence. The table
keeps only effects that are (a) documented across multiple samples or markets,
(b) implementable long-only in US large caps, and (c) low enough turnover to fit
this book. The citations are the original papers, not summaries.

| Effect | Primary evidence | What it says | Caveat for this desk |
|---|---|---|---|
| Cross-sectional momentum | Jegadeesh & Titman (1993), *Journal of Finance* 48, 65–91 | 3–12 month past winners beat losers; one of the most replicated anomalies. | Crash-prone; the edge is weaker in large caps and after costs; needs a risk overlay. |
| Residual momentum | Blitz, Huij & Martens (2011), *Journal of Empirical Finance* 18, 506–521 | Ranking on beta-adjusted residual returns roughly doubles risk-adjusted profit and halves volatility versus total-return momentum; less concentrated, more consistent. | Requires a stable beta estimate; 6–12 month formation, not 3 months. |
| 52-week-high proximity | George & Hwang (2004), *Journal of Finance* 59, 2145–2176; Bhootra & Hur (2013) | Nearness to the 52-week high dominates past-return momentum; recency of the high adds information. | In a theme book many names are near highs, so cross-sectional dispersion can collapse. |
| Time-series momentum | Moskowitz, Ooi & Pedersen (2012), *JFE* 104, 228–250 | 12-month own past return predicts the next month across futures. | Kim, Tse & Wald (2016) show the result is largely volatility scaling, not the sign rule; single-country equity evidence is weaker. |
| Volatility scaling | Moreira & Muir (2017), *Journal of Finance* 72, 1611–1644 | Scaling exposure by recent realised variance raises Sharpe across factors. | Cederburg et al. (2020) find out-of-sample gains are sparse: 8 of 53 strategies significant. The desk already uses it; do not add more dials. |
| Momentum crashes | Daniel & Moskowitz (2016), *JFE* 122, 221–247 | Crashes are forecastable in panic states; dynamic mean/variance scaling roughly doubles alpha and Sharpe. | Mostly a short-leg phenomenon; this desk is long-only. The long-leg analogue is leader mean-reversion after panics. |
| Value and momentum together | Asness, Moskowitz & Pedersen (2013), *Journal of Finance* 68, 929–985 | Value and momentum earn premia everywhere and are negatively correlated; combining them improves the risk-adjusted result. | The desk already weights value at three votes and tilts by P/E; avoid double-counting value. |
| Quality | Asness, Frazzini & Pedersen (2013), *Review of Accounting Studies* | Quality-minus-junk earns a high information ratio in the long sample. | Post-2016 US QMJ has been weak (Sharpe about 0.15, 2017–2026); the desk's fundamental analyst is also about zero IC since 2018. Do not add it now. |
| Post-earnings-announcement drift | Bernard & Thomas (1989); Livnat & Mendenhall revenue-surprise work; Meursault et al. (2021) text-based PEAD | Returns drift in the direction of the earnings surprise for weeks to months; revenue surprise adds; text-based PEAD has been larger recently. | Magnitude has declined; large-cap edge is smaller; needs clean filing dates and a surprise measure, not today's fundamentals. |
| Analyst estimate revisions | Low (2016), *Journal of Empirical Finance*-adjacent work; revision literature | Forecast revisions have incremental predictive power after momentum and information uncertainty. | The desk has only forward snapshots (P3); no historical point-in-time series yet. |
| Industry/sector momentum | Moskowitz & Grinblatt (1999), *JFE* 73, 525–556; O'Neal (2000); Chen, Jiang & Zhu | Intermediate-term industry momentum is profitable; sector indexes carry price and earnings momentum and can survive costs. | This is a separate mandate from the AI/software book; old samples overstate today's edge. |
| Hierarchical risk parity | López de Prado (2016), *Journal of Portfolio Management* 42, 59–69 | Clustering plus recursive bisection is more robust out-of-sample than mean-variance or naive risk parity. | The desk's skfolio minimum-variance replacement lost CAGR internally; HRP is a different, return-free method but still an allocation bet. |
| Machine-learning cross-section | Gu, Kelly & Xiu (2020), *Review of Financial Studies* 33, 2223–2273 | Trees and neural nets improve monthly cross-sectional return prediction; momentum, liquidity and volatility are prominent. | Internal learned rankers lost to momentum120 and equal weight; the honest PIT universe and label maturity are the binding constraints, not model class. |
| Momentum costs and capacity | AQR live momentum (Israel, Moskowitz et al.); Korajczyk & Sadka (2004) | US large-cap momentum traded at about 6.4 bp per $ traded, 0.117% of NAV a year, 80–90% one-sided turnover; costs do not kill the large-cap version. | The desk's 1% minimum trade already keeps turnover far below this; cost is not the constraint. |

Three conclusions follow directly:

1. **The durable edges are value, momentum, and the combination of the two.**
   The desk already owns value (three votes) and raw momentum (leader tilt). The
   one large, replicated improvement it does not own is **residual momentum**,
   and its close cousin **52-week-high proximity**.
2. **Timing, direction forecasting, and learned rankers have not survived this
   desk's own honest tests**, and the external evidence does not promise they
   would. The Codex record agrees.
3. **Volatility scaling is already installed and is the only risk lever that
   has reliably moved drawdown.** More dials are not the answer.

## 3. What the Codex and Claude implementations established

I read the Codex research branches (`codex/learned-entry-risk-20261002`,
`codex/funded-execution-forward-20261002`, `codex/intraday-personal-20260922`)
and the Claude review in `claude-review-2026-09-23/REVIEW.md`. Their
methodology is strong; their economic conclusions are mostly negative, and that
is useful.

### Claude review (2026-09-23)

- **Look-ahead clean.** Decisions use close t, fills at t+1 open, every window
  sliced at t; the intraday replay drops unfinished bars and respects
  publication times.
- **`vol` / `vol_trend` should not be adopted.** They scale to SPY-level
  volatility, halve exposure and return, and the margin over QQQ at 25 bp is
  about 0.08 points a year. The incumbent stayed.
- **The universe is the biggest caveat.** The 94 names are today's winners,
  hand-picked with hindsight; equal-weighting the book returned about 38% CAGR,
  beating every selection and sizing rule tested. "Beats QQQ on this universe"
  is not evidence of edge.
- **Operational defects found:** the personal board repeated Buy every refresh
  with no same-day memory; the funded whole-share path churned 608 reversals in
  250 sessions; idle cash cost about 5 CAGR points in the proxy; buy/sell
  thresholds were lopsided. These are correctness fixes, not alpha.
- **Recommendation:** keep the incumbent, shelve `vol`/`vol_trend`, shadow idle
  cash deployment and a QQQ 200-day overlay, and measure every result against
  equal weight, not only SPY/QQQ.

### Codex learned entry and risk (2026-10-02)

- The protocol is exemplary: fixed features, three histogram gradient-boosting
  heads, a ridge alternative, Chronos-2 as a pinned challenger, monthly refits,
  label purging, a frozen holdout, funded accounting, 0/10/25 bp, missing data
  retained, no threshold mining.
- The economic result was negative. On the complete common prefix, the learned
  ranker made 48.7% CAGR at −57.9% drawdown and 19.5x turnover, against
  momentum120's 70.5% at −46.6% and 9.3x, and equal weight's 39.5% at −38.6%
  and 0.5x. The learned brake cut return. At 25 bp the ranking was unchanged.
- The adaptive-entry study (457 cumulative trials) found no dip threshold beat
  the fixed 1% rule; the ML entry-level study found volatility is forecastable
  but direction is not (IC about 0.01). This is the same conclusion as the
  desk's 467-trial timing record.
- The funded-execution candidate (`bounded-execution/1`) lost to the incumbent
  in a five-opportunity closing cohort, and the sample is too small to select a
  threshold. The auction-state defect it found was real and was fixed.
- **Lesson:** the bottleneck is not model class or execution cleverness. It is
  the signal. A learned model trained on a hindsight-selected book cannot
  establish edge, and a direction model on 15-minute bars does not have one.

### Codex pretrained challenger

- Chronos-2 was pinned to an immutable revision and passed synthetic inference
  acceptance, but the only eligible economic window was 33 sessions; that is a
  component diagnostic, not evidence. The same is true of the other foundation
  models in the open-source protocol.
- **Lesson:** foundation models are a research comparator, not a shortcut. The
  desk should not spend live capital on them before a forward shadow.

### What the implementations missed

All three lines of work focused on **entry timing, execution, and learned
direction**. None tested the one cross-sectional signal with the strongest
external and internal support that the desk does not already size on:
**residual momentum**. The internal baseline module already computes it and
reports a higher rank IC than raw momentum (0.055, t 2.2, over 60 sessions,
against 0.042, t 1.6, on the book's names), but the installed leader tilt still
ranks raw 63-session returns. That is the gap this note recommends closing
first.

## 4. Concrete candidates, ranked

Each candidate is a research hypothesis. None is a live change. Each must be
pre-registered before its outcome, measured on the honest PIT cache at 10 and
25 bp, walked forward by year, compared with the installed rule, equal weight,
SPY and QQQ, and passed through the account simulator before it can become a
release candidate. The 252-session forward record stays frozen regardless.

### C1 — Residual-momentum leader tilt (highest priority)

**Hypothesis.** The leader tilt's +2.3 CAGR points come from cross-sectional
momentum, but raw trailing return carries time-varying market and factor beta.
Ranking on the part of the return the market does not explain should keep the
tilt's return and cut its crash exposure.

**Exact change.** The residual score needs about 273 sessions of history, more
than the 64 closes `point_in_time.TILTS` receives, so the score is computed on
the full panel and passed to `grade_led_leader_policy.leader_weights` as an
optional `scores` vector that replaces the trailing-return rank when given.
`policy_book.simulate` gains the matching optional `leader_scores` array; both
default to `None`, and the production nightly never passes them. The score is
the trailing sum of `own return − rolling beta × market return` over 120–252
sessions, skipping the most recent 21, divided by the residual's own
volatility (`baselines.residual_momentum`, unchanged), ranked with the
installed 1±0.5 mapping. Keep the same strength 0.5, the same 25% cap, the
same volatility target and floor.

**Evidence.** Blitz, Huij & Martens (2011): about twice the risk-adjusted
profit at half the volatility, more consistent, less concentrated. Internally,
the baseline's residual momentum already scores higher rank IC than raw
momentum on the book's names (0.055 vs 0.042 over 60 sessions). The installed
leader tilt was worth +2.3 CAGR at the same drawdown; the question is whether
the residual version keeps that gain with a shallower crash.

**Expected effect.** Same or slightly better CAGR, 2–4 points less worst
drawdown, better Sharpe. If it only matches raw momentum, it is still a
defensible replacement because it is less exposed to a factor unwind.

**Risks.** Beta estimation noise; residual momentum can underperform in sharp
market reversals; a 63-session window is too short for the effect (Blitz uses
6–12 months), so the window must be fixed at 120 or 252 before the test, not
swept. The tilt is a sizing change, not a selection change, so it cannot add a
name the grades reject.

**Measurement.** Honest S&P 500 PIT and IT+Comm PIT, 10/25 bp, 20 start
offsets, yearly walk-forward, shuffled-rank and random-tilt placebos, account
simulator with whole shares and the 1% minimum trade. The operative gate is
fixed in `residual-momentum-preregistration-2026-10-28.md`: choosing
2016-2023 at 25 bp, Sharpe at least +0.05, CAGR no worse than −0.5 points,
worst drawdown at least 2.0 points shallower, and the placebo's 95th
percentile exceeded. The reported 2024-2026 window and IT+Comm are reported
and do not gate.

### C2 — Value × residual-momentum composite sizing

**Hypothesis.** Value and momentum are negatively correlated and complementary
(Asness, Moskowitz & Pedersen 2013). The desk's value analyst is the only
analyst with positive rank IC every year since 2020, and the P/E-history tilt
already adds return. Blending a value rank with a residual-momentum rank in the
sizing slot should improve risk-adjusted return more than either alone.

**Exact change.** Replace the single leader multiplier with a fixed 50/50 blend
of two percentile ranks: residual momentum (C1) and P/E own-history cheapness
(the existing `valuation.own_history_rank`, reversed so cheap is high). Use the
existing `baselines.rank_blend` helper. Keep strength 0.5, cap, target and floor.
Do **not** change the grade weights; value already has three votes in selection,
and this candidate is about sizing only.

**Evidence.** Asness et al. (2013); the desk's own value ×3 study (17.1% vs
15.3% on the S&P 500 PIT at 25 bp); the P/E tilt study (37.6% vs 34.9% on the
book, 8 of 11 years, about 3.5 standard deviations above placebos).

**Expected effect.** +1–2 CAGR points and a better Sharpe than either tilt
alone, with similar drawdown.

**Risks.** Double-counting value: the grade already gives value three votes and
the sizing already tilts by P/E. The test must include a value-only arm and a
momentum-only arm so the blend's incremental effect is identifiable. If the
blend is not better than the best single arm, keep the single arm.

**Measurement.** Same protocol as C1, with three arms: residual only, value
only, blend. The blend must beat both single arms at 25 bp to be a candidate.

### C3 — 52-week-high proximity tilt

**Hypothesis.** Nearness to the 52-week high is a more robust momentum signal
than past return, and it is less prone to the "extended leader" reversal.

**Exact change.** Add a `high` tilt: score = current close / trailing 252-session
high, ranked cross-sectionally; blend with residual momentum at a fixed weight
(50/50) or test it alone. Same strength, cap, target and floor.

**Evidence.** George & Hwang (2004): the 52-week-high strategy dominates JT
momentum; Bhootra & Hur (2013): recency of the high adds information.

**Expected effect.** Similar return to raw momentum with lower crash risk;
possibly better than residual momentum in a theme book where betas are similar.

**Risks.** In a book where most names are near their highs, the cross-sectional
rank has little dispersion and the tilt becomes noise. The test must report the
cross-sectional spread of the score each session and refuse the tilt when the
spread is too thin.

**Measurement.** Same protocol as C1; include a dispersion diagnostic and a
placebo that ranks by distance from the high in the opposite direction.

### C4 — Post-earnings surprise (SUE) selection overlay

**Hypothesis.** The market underreacts to earnings surprises; a standardized
unexpected-earnings measure built from consecutive filings predicts 20–60
session excess returns, and it is a different signal from tone.

**Exact change.** Compute SUE as the seasonal change in reported earnings per
share (or net income) divided by the trailing standard deviation of seasonal
changes, using filing dates only. Add it as a sixth analyst with a fixed vote
(0.5 or 1.0) or as a sizing tilt on the eligible A/A+ set. Do not use today's
fundamentals for a historical decision; the filing date must be the decision
date.

**Evidence.** Bernard & Thomas (1989); Livnat & Mendenhall revenue-surprise
work; Meursault et al. (2021) text-based PEAD; the decline literature (Kettell,
McInnis & Zhao 2022) says the edge is smaller but not gone, and revenue
surprise and text measures have held up better.

**Expected effect.** Incremental selection edge around earnings, especially in
names where the grade is borderline; likely small in large caps, but the desk
has no earnings-surprise signal at all today.

**Risks.** Data coverage: the store's fundamentals are patchy and the multi-class
names already have no market cap. The measure must fail closed when the prior
quarter or the filing date is missing. The tone-surprise study failed; this is a
different measure and must not be presented as a retry of it. The study must
report coverage by year and name, and the denominator must include missing
names.

**Measurement.** First a data audit: how many of the honest PIT names have two
consecutive quarterly filings with usable earnings and a filing date, by year.
Only if coverage is adequate, a rank-IC study by year at 20 and 60 sessions,
then a pre-registered selection overlay. No live use before the forward record.

### C5 — Sector-rotation sleeve (separate mandate, owner decision)

**Hypothesis.** Intermediate-term industry momentum is profitable and is a
different exposure from the AI/software book. A separate sleeve can answer the
owner's sector question without contaminating the live mandate.

**Exact change.** A new research sleeve, not a change to `grade-led-leader-weight/1`:
rank 11 sector ETFs (or sector baskets) by 6–12 month return, hold the top 2–3
equal-weight, rebalance monthly, scale to a volatility target, cap each sector.
Cash when fewer than two sectors have positive momentum. Keep it separate from
the AI book and report it as a separate account.

**Evidence.** Moskowitz & Grinblatt (1999); O'Neal (2000); Chen, Jiang & Zhu on
sector-index momentum surviving costs.

**Expected effect.** Modest diversifying return, low correlation to the AI book,
and a genuine answer to "oil versus tech." It will not beat QQQ on its own.

**Risks.** This is a mandate change, not an algorithm tweak; the owner decides.
Sector momentum has weakened since the original samples, and ETF costs and
monthly turnover are real. It must not be spliced into the live book's returns.

**Measurement.** PIT sector ETF history, 10/25 bp, monthly rebalance, 20 start
offsets, compared with SPY and equal-weight sectors. Report correlation to the
live book and the combined 80/20 result separately.

### C6 — Correlation-aware sizing (low priority)

**Hypothesis.** The book is concentrated in correlated AI names; hierarchical
risk parity can reduce concentration and tail loss without forecasting returns.

**Exact change.** HRP on the eligible A/A+ set with a 252-session covariance,
then the existing volatility target and 25% cap. No expected-return input.

**Evidence.** López de Prado (2016). Internally, skfolio minimum variance lost
CAGR; HRP is a different method but still an allocation bet.

**Expected effect.** Lower drawdown and concentration, likely lower CAGR. The
volatility target already handles most of the drawdown problem, so the expected
net gain is small.

**Risks.** Correlation estimates are noisy; in a theme book HRP may collapse to
equal weight; the 25% cap already limits single-name risk.

**Measurement.** Same protocol; require a drawdown improvement of at least 2
points with no more than 0.5 CAGR points given up, at 25 bp, in both windows.

## 5. What this note refuses

- It refuses to reopen timing. 467 registered trials, the Codex adaptive-entry
  study at 457 cumulative trials, and the ML entry-level study all found no
  edge; the measured differences are basis points and do not survive costs.
- It refuses another learned ranker on the current data. The Codex learned
  ranker lost to momentum120 and equal weight; the honest PIT universe and
  label maturity are the constraints, not the model.
- It refuses stops, trend gates, sector caps, conviction top-decile, tone
  surprise and the chase guard. All were measured and failed.
- It refuses to add quality now. The post-2016 US QMJ record is weak and the
  desk's fundamental analyst is about zero IC since 2018.
- It refuses more volatility-target dials. The out-of-sample evidence for
  volatility management is mixed, and the desk already uses the one setting
  that paid for itself.
- It refuses to quote the 37.6% book number as the system's return, or to
  select a signal on the names that were chosen with hindsight.

## 6. Recommended sequence

1. **Now (live):** install the FOMC retirement after the 15:45 ET restoration
   and after the last balancer tick, deploy, confirm admission, run the one-time
   6-K reclassify before the 19:30 ET nightly. Freeze the rule for 252 sessions.
2. **C1 (closed):** the residual-momentum leader tilt was pre-registered and
   run on the honest PIT cache at 10 and 25 bp. It failed: R120 lost 0.0129
   choosing Sharpe and deepened the drawdown by 2.1 points
   (`residual-momentum-results-2026-10-28.md`). The arm is not retried.
3. **C2 (closed):** the value × residual-momentum blend was pre-registered
   with value-only and residual-only controls. Value-only was the best single
   arm at 0.6903 choosing Sharpe, but the blend landed at 0.6748, below the
   +0.05 bar and deeper than the drawdown bar; the arm is closed
   (`value-momentum-blend-results-2026-10-28.md`). **Research next:** C3, the
   52-week-high tilt, with the dispersion diagnostic.
4. **Data audit:** C4, the SUE coverage audit. If coverage is adequate, run the
   rank-IC study; if not, record the gap and do not force the signal.
5. **Owner decision:** C5, the sector-rotation sleeve. It is the honest answer
   to the sector question, but it is a separate mandate and must not be spliced
   into the AI book.
6. **Only if a candidate passes:** prepare a release candidate, forward-shadow
   it, and install it only after the 252-session forward record and the release
   ceremony. The forward record is the only out-of-sample evidence this desk
   will ever have; changing the rule to chase a backtest would destroy it.

## 7. The one-sentence answer

The desk already owns the two edges the literature says survive — value and
momentum, sized by volatility. The missing edge is **residual momentum**, not
more timing, more models, or more execution cleverness. Test that first, then
the value-momentum blend, then the 52-week-high cousin; leave the live rule
frozen while the forward record runs.

## References

- Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling
  losers. *Journal of Finance* 48, 65–91.
- Blitz, D., Huij, J., & Martens, M. (2011). Residual momentum. *Journal of
  Empirical Finance* 18, 506–521. https://repub.eur.nl/pub/22252/ResidualMomentum-2011.pdf
- George, T. J., & Hwang, C.-Y. (2004). The 52-week high and momentum investing.
  *Journal of Finance* 59, 2145–2176.
- Bhootra, A., & Hur, J. (2013). The timing of 52-week high price and momentum.
  *Journal of Banking & Finance*.
- Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). Time series momentum.
  *Journal of Financial Economics* 104, 228–250.
- Kim, A. Y., Tse, Y., & Wald, J. K. (2016). Time series momentum and volatility
  scaling. *Journal of Financial Markets* 30, 103–124.
- Moreira, A., & Muir, T. (2017). Volatility-managed portfolios. *Journal of
  Finance* 72, 1611–1644.
- Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. (2020). On the
  performance of volatility-managed portfolios. *Journal of Financial
  Economics*.
- Daniel, K., & Moskowitz, T. J. (2016). Momentum crashes. *Journal of
  Financial Economics* 122, 221–247. https://www.kentdaniel.net/papers/published/jfe_16.pdf
- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). Value and momentum
  everywhere. *Journal of Finance* 68, 929–985.
- Asness, C. S., Frazzini, A., & Pedersen, L. H. (2013). Quality minus junk.
  *Review of Accounting Studies*.
- Bernard, V. L., & Thomas, J. K. (1989). Post-earnings-announcement drift:
  delayed price response or risk premium? *Journal of Accounting Research*.
- Meursault, R., et al. (2021). PEAD.txt: post-earnings-announcement drift
  using text. *Journal of Financial and Quantitative Analysis*.
- Kettell, L., McInnis, J., & Zhao, W. (2022). Why has PEAD declined over time?
  The role of earnings news persistence.
- Low, R. K. Y. (2016). The role of analyst forecasts in the momentum effect.
  *Journal of Empirical Finance*-adjacent.
- Moskowitz, T. J., & Grinblatt, M. (1999). The profitability of sector momentum
  strategies. *Journal of Financial Economics* 73, 525–556.
- O'Neal, E. S. (2000). Industry momentum and sector mutual funds. *Financial
  Analysts Journal* 56, 37–49.
- López de Prado, M. (2016). Building diversified portfolios that outperform
  out of sample. *Journal of Portfolio Management* 42, 59–69.
- Gu, S., Kelly, B., & Xiu, D. (2020). Empirical asset pricing via machine
  learning. *Review of Financial Studies* 33, 2223–2273.
- Korajczyk, R. A., & Sadka, R. (2004). Are momentum profits robust to trading
  costs? *Journal of Finance*.
- Internal: `docs/research/trading-program-2026-10-28.md`,
  `docs/research/claude-review-2026-09-23/REVIEW.md`,
  `docs/research/open-source-integrations-2026-10-01.md`,
  `docs/research/value-weighted-grading-2026-10-22.md`,
  `docs/research/pe-history-tilt-2026-10-24.md`,
  `docs/research/account-simulator-rule-2026-10-24.md`,
  `docs/research/adaptive-entry-results-2026-09-30.md`,
  `docs/research/learned-price-results-2026-09-24.md`.
