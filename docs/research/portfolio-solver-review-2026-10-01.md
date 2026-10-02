# Independent covariance solver review

Scope: inspect the captured numerical failure, establish the mathematical
feasible set, and propose an equivalent formulation. No market outcomes,
allocation thresholds, budgets, source data, live policy or services changed.
The original worker correctly stopped after its three unsuccessful hypotheses.

## Reproduced boundary

Captured input: Spark `/tmp/codex-skfolio-first-failure.npz`, 252 completed
returns across seven assets. Gross is 0.9999999999999999, prior selected gross
0.7500000052573383, mandatory exits 0.24999999474266174 and total L1 budget
0.4999999894853233. The selected L1 allowance is 0.24999999474266157; the
required gross increase is 0.24999999474266155. Their difference is 2.78e-17.

At this boundary, the L1 constraint is equivalent to `weights >= previous`:
every change must be nonnegative because their sum already consumes the entire
L1 allowance. The remaining constraints are `weights <= 0.25` and
`sum(weights) = gross`. Some lower bounds lie within 1e-9 of the cap; this
leaves very narrow intervals. No bound was rounded or relaxed during review.

The fitted skfolio Ledoit-Wolf covariance is positive definite. Eigenvalues
range from 8.27548790e-5 to 1.71845036e-3, condition number 20.77. The failure
is not an indefinite or ill-conditioned covariance matrix.

The original skfolio MeanRisk formulation introduces a standard-deviation SOC
epigraph and minimizes its square. Its canonical problem has eight variables,
one equality, 22 inequalities and an eight-dimensional second-order cone.
With the existing CLARABEL absolute gap and feasibility tolerances both 1e-10,
it reproduces `optimal_inaccurate` in 14 iterations despite zero printed primal
violations. The strict status guard must remain.

## Equivalent formulation and independent certificate

Directly minimize `quad_form(weights, covariance)` subject to the same bounds
and equality. This uses the same covariance, CLARABEL and 1e-10 tolerances;
only the redundant SOC epigraph is removed. The captured problem returns
`optimal` in 12 iterations. There is no solver selection based on investment
outcomes, objective scaling or loosened status/tolerance acceptance.

A solver-independent certificate uses convexity. For a feasible candidate w,
the global objective gap is at most
`gradient(w) @ (w - y)`, where y minimizes that linear objective over the
capped simplex. This linear minimization is solved exactly by starting at the
lower bounds and assigning the required remaining gross in ascending gradient
order, capped at 0.25. It does not call another numerical optimizer.

| Formulation | Variance | Convex upper bound on objective gap | Relative gap |
| --- | ---: | ---: | ---: |
| Original SOC | 0.00013887826807165455 | 4.046600817763659e-10 | 2.9137754048573e-6 |
| Direct quadratic | 0.00013887826814673937 | 5.329791749814679e-13 | 3.837743529594709e-9 |
| Independent active-set KKT | 0.0001388782678990718 | 2.710505431213761e-20 | 1.951713160178229e-16 |

The direct candidate has no lower/cap violation and sum error -2.22e-16. An
independent analytic check fixes assets 1, 2 and 6 at their upper caps and asset
3 at its original lower bound, then solves the equality-constrained quadratic
system for free assets 0, 4 and 5. All free reduced gradients are zero at
floating-point precision; upper-bound reduced gradients are negative and the
lower-bound reduced gradient positive, proving the correct KKT signs. The
covariance is positive definite, so the feasible stationary point is the
unique minimizer. These numerical statements are double-precision checks,
not an interval-arithmetic theorem.

## Implemented correction and acceptance

The branch now uses skfolio's fitted EmpiricalPrior/LedoitWolf covariance with a direct CVXPY
quadratic objective. Preserve the declared capped simplex, total L1 constraint
away from the minimum-turnover boundary, exact boundary equivalence, current
CLARABEL tolerances, strict `OPTIMAL` requirement and all post-fit contract
checks. This is a representation correction to the same registered candidate.

The captured failing covariance/prior geometry and independent analytic KKT
comparison are pinned in the portfolio acceptance module. The real immutable
252-by-seven returns fixture also passed, with convex objective gap at most
1.062379418920352e-13 and maximum weight difference from the analytic optimum
2.5092066948534386e-9. Its SHA256 is
`2ce65f6dbf5fab131d3aea26a47fcd487fd78daeea37f6c121b758b360160385`.

The portfolio, policy-v5, allocation replay/validation/controls and research
journal/replay/integration/scale suites passed: **497 tests, 3.00 seconds**.
The inaccurate-status test still refuses an explicit `optimal_inaccurate` at
the actual CVXPY solve boundary. Both changed modules passed Ruff; no acceptance
assertions were weakened. Source exercised:

- `open_source_portfolio.py`: `4e2c7e8ded7b31e41a16a9909f476d0606ebdab06598a7678d931bc0a2c58219`
- `test_open_source_portfolio.py`: `94d701a048b3034a39f6252cd66e89a0bd377b99743e7e594accb15cd228900f`
- unchanged CLI: `b2a5cac76b9f744eddd14539f41db56b0e97909e45b2476de232214fc31542ba`

The fixed full-history run completed once in 2.01 seconds into a **new** artifact
`/home/animallya96/scratch/open-source-inputs-20261001/portfolio-results-qualified-qp.json`.
All **101** numerical fits returned `optimal`; maximum original primal
constraint violation was **1.3455903058456897e-13**. Analytical unique/zero-change
resets bypass numerical fitting. Numerical evidence is alongside it in
`portfolio-qp-numerical-proof.json`; the earlier provisional artifact remains
unchanged. Qualified result SHA256:
`55bc6f4ba9f3ed4db4249f8d98753b64528e10921065223a213f6d5eaa5bf8f2`.

Runtime versions: skfolio 1.4.10, cvxpy-base 1.9.3, CLARABEL 0.11.1,
NumPy 2.5.2, SciPy 1.18.1.

## Qualified conditional results: do not adopt

The continuous funded account begins 2016-01-04; 2,700 measured return sessions
run 2016-01-05 through 2026-09-30. The common calendar has 136 target resets.
Three candidate resets retain unavailable covariance baskets as cash:
2026-05-19, 2026-06-17 and 2026-07-17. Grade availability in the supplied member
grid is complete, but grades are reconstructed current-vintage evidence,
not original historical advice. Eligibility/provenance restrictions in the
registered study still apply. This is sizing evidence, not live-strategy parity.

All percentages below are percent per year for CAGR and positive drawdown loss;
turnover is actual one-way traded account fraction per year. Account state is
continuous across reporting splits. The first split has 1,258 return sessions
ending 2020-12-31; the second has 1,442 from 2021-01-04 through 2026-09-30.

| Cost bp | Window | Policy | CAGR | Drawdown loss | Sharpe | Turnover/year |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 10 | All | Covariance | 23.10% | 41.71% | 0.913 | 10.49 |
| 10 | All | Rule /5 | 31.66% | 44.58% | 1.079 | 10.22 |
| 10 | All | PIT equal weight | 27.40% | 37.82% | 1.040 | 2.49 |
| 10 | All | SPY | 15.07% | 33.72% | 0.881 | 0.09 |
| 10 | All | QQQ | 20.30% | 35.12% | 0.943 | 0.09 |
| 10 | 2016–20 | Covariance | 21.03% | 32.69% | 0.878 | 10.89 |
| 10 | 2016–20 | Rule /5 | 29.06% | 33.26% | 1.081 | 10.43 |
| 10 | 2016–20 | PIT equal weight | 32.78% | 31.72% | 1.221 | 2.17 |
| 10 | 2016–20 | SPY | 15.38% | 33.72% | 0.854 | 0.20 |
| 10 | 2016–20 | QQQ | 24.38% | 28.56% | 1.103 | 0.20 |
| 10 | 2021–26 | Covariance | 24.93% | 41.71% | 0.942 | 10.14 |
| 10 | 2021–26 | Rule /5 | 33.97% | 44.58% | 1.082 | 10.03 |
| 10 | 2021–26 | PIT equal weight | 22.89% | 37.82% | 0.891 | 2.77 |
| 10 | 2021–26 | SPY | 14.79% | 24.50% | 0.912 | 0.00 |
| 10 | 2021–26 | QQQ | 16.85% | 35.12% | 0.807 | 0.00 |
| 25 | All | Covariance | 21.14% | 42.34% | 0.853 | 10.52 |
| 25 | All | Rule /5 | 29.65% | 45.24% | 1.026 | 10.21 |
| 25 | All | PIT equal weight | 26.93% | 37.98% | 1.026 | 2.49 |
| 25 | All | SPY | 15.05% | 33.72% | 0.881 | 0.09 |
| 25 | All | QQQ | 20.29% | 35.12% | 0.943 | 0.09 |
| 25 | 2016–20 | Covariance | 19.07% | 32.78% | 0.814 | 10.88 |
| 25 | 2016–20 | Rule /5 | 27.06% | 33.33% | 1.023 | 10.43 |
| 25 | 2016–20 | PIT equal weight | 32.35% | 31.73% | 1.208 | 2.17 |
| 25 | 2016–20 | SPY | 15.35% | 33.72% | 0.852 | 0.20 |
| 25 | 2016–20 | QQQ | 24.34% | 28.56% | 1.101 | 0.20 |
| 25 | 2021–26 | Covariance | 22.97% | 42.34% | 0.885 | 10.21 |
| 25 | 2021–26 | Rule /5 | 31.95% | 45.24% | 1.034 | 10.03 |
| 25 | 2021–26 | PIT equal weight | 22.38% | 37.98% | 0.876 | 2.77 |
| 25 | 2021–26 | SPY | 14.79% | 24.50% | 0.912 | 0.00 |
| 25 | 2021–26 | QQQ | 16.85% | 35.12% | 0.807 | 0.00 |

Full-window fee totals below use starting NAV = 1 and sum actual account-unit
fees over the expanding account. Rolling win rates use the same 2,449 complete
252-session windows; they are not independent trials or confidence intervals.

| Cost bp | Policy | Total fees | Win rate vs SPY | Win rate vs QQQ |
| ---: | --- | ---: | ---: | ---: |
| 10 | Covariance | 0.375016 | 81.01% | 66.07% |
| 10 | Rule /5 | 0.587432 | 85.26% | 80.93% |
| 10 | PIT equal weight | 0.145639 | 85.34% | 81.87% |
| 10 | SPY | 0.000999 | 0.00% | 23.36% |
| 10 | QQQ | 0.000999 | 76.64% | 0.00% |
| 25 | Covariance | 0.840572 | 76.68% | 60.64% |
| 25 | Rule /5 | 1.304654 | 82.07% | 76.97% |
| 25 | PIT equal weight | 0.353961 | 84.48% | 80.20% |
| 25 | SPY | 0.002494 | 0.00% | 23.36% |
| 25 | QQQ | 0.002494 | 76.64% | 0.00% |

Covariance beats the rule in only 20.29% of rolling windows at 10 bp and 19.68%
at 25 bp. It reduces full-window drawdown loss by about 2.9 percentage points
while reducing CAGR by about 8.5 points; turnover increases slightly. The
registered return-maximization objective does not support replacement. No
candidate parameter is retuned from these results and the live strategy stays
unchanged. The numerical repair is reusable engineering; this sizing policy
remains research-only.

Review ran on the isolated CPU research runtime, with OPENBLAS/OMP threads
limited to one. The scratch review program is
`/tmp/review-portfolio-solver.py` on Spark; no production files were edited.
