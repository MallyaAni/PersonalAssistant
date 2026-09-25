# Allocation decisions and actual outcomes — September 25, 2026

## Purpose and boundary

The operator wants upside participation and protection ahead of deteriorating
conditions. The existing scorecards measure net wealth, drawdown, turnover and
causal prior-close regimes, but did not systematically connect every allocation
decision with its actual fills and subsequent comparator outcomes.

`backend.market.allocation_attribution.attribution` closes that reporting gap.
It accepts frozen journal snapshots and freshly runs independent accounting
verification. Candidate, matched no-gate adapter, funded SPY and funded QQQ are
required as caller-declared account roles; other controls are retained. The
helper verifies accounting, not that an account called SPY actually implements
a SPY policy. The study owns control construction. Costs and reconstructed
closing-mark dates must agree exactly. Missing dates are never silently
inner-joined away. Each account retains its own ordered symbols, so fill and
position vectors remain interpretable even when account symbol grids differ.

Each interval retains:

- effective desired stock/SPY/QQQ/cash weights, declared stock scale and decision
  identifiers; mixed, missing or ambiguous evidence remains explicit;
- actual fill batches, paid fees, bought/sold notional, cash-budget limitations
  and unfilled quantities, rather than treating a submitted target as a fill;
- actual sleeve weights at the preceding and following closing marks;
- full already-charged close-to-close returns for every matched account;
- positive/negative/tie comparator outcomes, with a fixed absolute `1e-12`
  zero-return tie band, not a fitted threshold.

Disjoint intent/sign cells reconcile to the original account log growth. Empty
cells stay visible. Initial account state and terminal pending declarations stay
separate. A residual batch is not inferred to be an outstanding future order.
An underfilled stock basket can imply cash even when the declared stock scale
is positive; stock scale is neither actual stock weight nor a cash forecast.

**Timing matters:** a close decision followed by a next-open sale cannot avoid
the intervening overnight gap. Following-close cash is not exposure throughout
the preceding return interval. Accordingly this report says “positive comparator
interval while cash was intended,” not “wrong decision” or “loss avoided.”
SPY/QQQ retain equity risk and are never labelled defensive cash. Grouped returns
are retrospective descriptions, not annualized stitched strategies or evidence
of predictive skill.

The existing study now includes this table under each full-sample
`decision_outcomes` field. The frozen model protocol, labels, candidate selection,
account rules and source prices are unchanged. Existing archives can be inspected
without rerunning their producer; derived output must be kept outside the
original archive. No live route, prompt, broker, subscription or dashboard change
is included.

## What the frozen gate evidence says

The [earlier full scorecards](nested-market-validation-2026-09-24.md#recovered-exploratory-result-reject-this-gate)
already rejected the gate: at 10/25 bp its CAGR is **23.32% / 20.50%**, versus
**36.29% / 34.65%** for the matched no-gate adapter. Its closing drawdown is
worse and its annual bought-plus-sold notional over mean NAV is
**14.71 / 14.87**, versus **8.21 / 8.23**. These are the same saved results,
not a new strategy test.

A separate read-only audit of retained predictions finds negative squared-error
skill versus each target's eligible **pre-fit training-label mean**:

| Gross five-session log-return proxy | Skill, `1 − model SSE / training-mean SSE` |
| --- | ---: |
| Stock basket | −6.46% |
| SPY | −14.89% |
| QQQ | −15.35% |

These use **1,679 overlapping observed labels**. The five final decisions lack
completed label endpoints and are explicitly excluded from forecast diagnostics,
not from the **1,684 account return intervals**. The baseline is an unfitted
diagnostic using saved training observations, not a newly executed strategy.
It establishes neither independent statistical significance nor calibrated
downside probabilities. The model labels are gross open `t+1` to open `t+6`
proxies, not funded net account returns.

The audit also records 750 stock, 561 QQQ, 348 cash and 25 SPY **declared-mode**
decisions. Actual average closing exposure at 10 bp is about 30.80% stocks,
33.06% QQQ, 1.14% SPY and 35.01% cash, including the initial cash mark.
Seventy-five mode switches are recorded. Desired modes and realized holdings
are not interchangeable. Higher trading and funding limitations accompany the
underperformance; these observations do not isolate their counterfactual costs.

Audit receipt: `/private/tmp/anios-gate-failure-audit.tlH2PrUu/RECEIPT.md`, SHA-256
`2cec24bf759278e5f3f2fdea640f5058bc0eba33dbcae9a9dcf7c8b8b18713d1`.
`analysis-01.json` SHA-256:
`2682a824af1f77ed2e2352fd5e59495114cef790e7c64ddf298062335f3e35b7`.
The separate arithmetic proof has **5 known-value self-tests and 672 scalar
comparisons across 48 metric sets**, maximum residual `4.44e-16`; all **63
consumed files** were rehashed unchanged. The argmax “best mode” statistic is
not used to choose a policy or make a causal conclusion.

## 2026 research informing the measurement

- [Zhu–Cai, sections 9.2–9.4](https://arxiv.org/html/2609.04917v1) distinguish
  signal quality from fill quality and call for identifying which holdings and
  states produce gains. This motivates the separate intent/fill/exposure fields.
- [Pollok–Robik, sections V-C–V-D](https://arxiv.org/html/2607.00475v1) report
  that positive returns did not establish significant market-timing ability and
  that model switching added noise. Their target-weight turnover convention
  differs from this funded-account convention; their cost numbers are not
  transferred into AniOS.
- [Fonseca](https://arxiv.org/html/2607.04958v1) motivates temporal
  non-interference and explicit availability boundaries. Finite perturbation
  tests are useful evidence, not universal proof of leakage freedom.
- [Jensen et al.](https://doi.org/10.1093/rfs/hhag022): publisher DOI metadata
  and abstract confirm the March 15, 2026 online paper and its decision-aligned,
  transaction-cost-aware evaluation focus. Detailed empirical findings were not
  verified in this review.

No cited paper proves a generally best architecture or qualifies this desk's
strategy. The measurement change does not improve any strategy's realized return.

## Acceptance

The new integration acceptance first failed on the unchanged implementation
with `KeyError: decision_outcomes`; the original result is retained in
`/private/tmp/anios-allocation-attribution.oq0PQQnA/baseline.xml`.

**VERIFIED:** **1,178 tests passed**, one deliberately deselected cached historical
reproduction, five existing empty-slice warnings, **41.14 seconds**. This includes
38 focused attribution cases and the actual synthetic study/archive path;
all source/input/nested-fitting, producer, independent journal, serialization
and metrics tests remain green. Scoped Ruff lint/format and diff checks pass.
All 33 unchanged canonical diagrams and the published architecture page check
pass using locked Mermaid 11.16.0. No frontend behavior or prompt changed;
live-model, production-browser and deployment gates were not run for this slice.

The actual helper additionally processed **12 frozen outer journals** at both
costs, freshly verifying their accounts without any policy fit or simulation.
Each table retains **1,684 intervals**, all reconciled; **36 input files** were
hash-checked against the old observer inventory and remained unchanged.
Independent **50-digit Decimal** calculations checked **74,096 values** spanning
every interval's account returns, candidate sleeve weights and fill fees/notional.
Maximum absolute residual: **4.56e-15**. The original root manifest remains absent.

Among the 348 cash-target intervals at either cost, funded QQQ is positive in
185 and negative in 163; funded SPY is positive in 187, negative in 159 and tied
in two. These are descriptive outcomes after cash intent, not 348 independent
trials or a count of wrong decisions. The complete table retains losses incurred
before cash sales fill, avoiding the false claim that subsequent cash escaped
an earlier gap.

Acceptance used source mounted read-only in network-disabled container image
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`,
Python 3.12.14, NumPy 2.5.3, pandas 3.0.6, PyArrow 25.0.0 and
exchange-calendars 4.13.2. The historical observer uses only the standard library
plus the new helper/independent verifier, with no optional research dependency.
Neither path contacts a provider, model, database or account.

Retained receipt and exact commands:
`/private/tmp/anios-allocation-attribution.oq0PQQnA/RECEIPT.md`.
JUnit SHA-256: `247f8460913c19a88e8cbf21313411e07f98b90396e1b73063d495b0d629efdf`.
Observer proof SHA-256: `cf172e306b01bca07aeeeefb8bce1ac30bf4b44820f14bccd948f97a38bf2148`.
Observer reports `frozen-10.json` and `frozen-25.json` have SHA-256
`d6df28a7f1d7afbcc7d72dde7c36fd79b58929c4313dc7d8d3ba9185fb343006` and
`da6f20f9dfd1e395d817411778874127d97d503b75efb378fec285c766d7460d`.

Exercised source SHA-256:

- helper: `54be6aea2c7a9ca6f79af412b92f82638303cfe3061e96eb1eb7b2826786d0a4`;
- helper tests: `334e39848a255ecb05cb850d6a3c4e3d1ff93141fa2dcdc2c3df8b727d8665b1`;
- study integration: `de0226f87bdb58d168fce5670d3e6a5b79f5238176a0889252f8e5c9513d1bfb`;
- study tests: `ea593cfc4de4835c202a3f067f30fc1b4c4bb2cc50a1364895fe81d5c9198e63`.

The original historical producer remains **FAILED** (archive OOM), with its
root manifest absent. Its individual journals and recovered results are
independently verified; this observer is not a replacement producer manifest.
Historical membership, stable identities, then-known fundamentals/adjustments,
delisted payouts, real settlement and capacity remain **UNVERIFIED**. Today's
survivor/discretionary stock basket prevents a claim of unbiased `/3` superiority.

**Diagram impact: NONE — internal research reporting within the existing
journal/account/scorecard flow; no changed component, store or trust boundary.**
