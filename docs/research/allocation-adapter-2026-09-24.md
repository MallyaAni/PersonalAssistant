# Stock, index and cash research adapter — September 24, 2026

## Purpose and boundary

`backend.market.allocation_replay` implements a separate execution adapter for
explicit stock/SPY/QQQ/cash allocations. It does not forecast red or green days,
fit a model, select stocks, call a broker, modify the dashboard or change
`cash-bounded-breakout-rotation/3`. Its execution version is
`stock-index-cash-adapter/1-research`; adoption is always false.

The existing simulator rejects zero exposure and restores some targets by
dividing by their previous scale. Its planner can retain holdings smaller than
0.5% of NAV even when the target is zero; the other funded planner has a tiny
unit-delta threshold. The new adapter leaves those incumbent paths unchanged.
It computes explicit absolute ending-unit targets and reuses only the generic
`_Book._fill` ledger. Exact zero targets bypass both suppression thresholds.

## Instruction contract

`AllocationInstruction` contains a decision `session`, caller-declared
`information_through`, nonempty `evidence_id`, `stock_scale`, direct `spy_weight`
and `qqq_weight`, optional `stock_weights`, and an explicit `rebalance` flag.
There must be exactly one instruction for every executable close from `first`
through the penultimate source session. Dates must match that source grid, and
declared information cannot come after the decision. These are daily declarations,
not verified publication timestamps; an evidence identifier is not a source audit.

An explicit stock map replaces the retained unscaled composition. `None` means
retain it; `{}` explicitly empties it. A stock allocation before any composition
was supplied fails instead of guessing. Updates made while in cash or an index
remain available on restoration, with their source session recorded.

The target for each stock is its retained equity weight times `stock_scale`.
SPY and QQQ have their separately supplied absolute equity weights. Unused
capacity stays cash; the stock basket is never renormalized. Each fraction is
bounded to [0,1], and actual stock-plus-index target weights must sum to at most
one (1e-12 summation allowance). A 20%-equity stock basket at scale 1 plus 80%
SPY is valid: scale is a multiplier, not itself actual stock exposure.

Replanning occurs only on the first instruction, an explicit rebalance, a stock
composition update, a sleeve change or an actual funding follow-up. Price drift
alone does not trigger daily rebalancing. Composition updates while defensive
also count as declared rebalance events. The future runner must freeze this
cadence before results, not silently switch it between candidates.

## Execution and receipts

Sizing uses the decision close's NAV and prices. Fills are no earlier than the
next supplied session's adjusted open, with proportional costs and one common
cash scale for competing buys. No sale proceeds from that batch fund its buys;
net sales enter cash at batch end. When actual sales leave an unpaid buy target
and positive cash, a funding-follow-up flag survives. The next close replans
using its current instruction, preserved composition and NAV; a changed
instruction supersedes the old allocation, never revives stale quantities.

The result includes every closing NAV, actual cash balance, cash fraction,
positions, fees, per-session turnover, instruction receipts and terminal pending
state. Turnover is traded notional divided by the preceding decision-close NAV.
The initial account row has zero fees and turnover. Terminal holdings are not
liquidated to improve the apparent result or manufacture closing cash.

Receipts say `earliest_execution_session`, which is permission timing, not an
actual fill. `planned: false` holds have `submitted_units: null`. A planned
vector is an absolute intended ending quantity, not a change in shares or proof
that an order reached a broker. Actual fills belong to the optional journal.
Every journal decision retains the exact consumed instruction, full-path hash,
effective stock composition, composition source session and plan triggers.
The existing journal represents holds as carried units with `no_order: true`.

`instruction_path` retains the complete normalized input path and SHA256 of its
canonical JSON payload. The demonstration archives it beside each adapter
journal. Full-path hashes change when a future suffix changes, so causal tests
compare earlier decisions/fills/account states, not whole-archive byte equality.
The accounting CLI does not validate this sidecar hash or regenerate allocation
decisions: it independently verifies cash, units, fills, fees and marks only.

Missing required decision prices, execution prices or held valuations fail
closed. No absent signal means cash, no missing price means a free exit, and no
missing valuation becomes zero. An unused missing price is allowed, including
an all-cash account. Source matrices must be real numeric arrays: complex,
boolean, string and object matrices are rejected instead of silently coercing
them. A reproduced complex-price input had discarded its imaginary component;
the explicit type boundary now prevents that. Nonfinite or negative ledger
state is refused before a valid account can be reported.
Symbols must be an ordered non-string sequence; sets and mappings cannot define
price-column identity. A reproduced set input reordered ticker identities against
unchanged price columns and is now rejected.

## Evidence and limitations

Acceptance exercises the real adapter and independently replays its journals:
complete microscopic exits, repeated cash, restoration after composition
updates, both indexes, mixed stock/index/cash targets, costs, competing buys,
overnight gaps, explicit cadence, funding retries, superseding instructions,
terminal truth, source-copy isolation, price/source failures and future suffix
perturbation. Changing the next open may affect its fill, never the preceding
close's submitted units; changing a later close may not change an earlier open
fill. Enabled/disabled recording must return identical results.

The saved demonstration compares the adapter's explicit switching path with
its stock-only no-gate path and the existing funded SPY/QQQ controls at 10 and
25 bp on the same nine **synthetic** sessions. All eight account journals and
their **72 marks passed** the actual read-only CLI. These are accounting journeys,
not market-performance results or evidence that a switching rule is profitable.
VERIFIED: **526 tests passed, 1 deliberately deselected** cached-study
reproduction, with five existing synthetic-fixture All-NaN/empty-slice warnings.
The two new test modules contribute **234 passing cases** (76 behavior,
158 boundary). Scoped lint/format and all **32** diagram checks pass; an automated
browser verifies the documentation SVG/page and root inspected its screenshots.
That browser check is not dashboard or live-strategy acceptance.

The tests and demonstration mounted the current checkout read-only at `/app`
using image
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.
Final adapter SHA256:
`c8dfcf93de108f1fbed615a0609470a60590e89dceb4f798237b6483f9841f15`.
The demonstration runner is
`3fc6154cd235212777b70b870f210b063200945cebde4d1e42bf1435964c7601`;
every manifest records exact source hashes, not a claim that uncommitted source
was already the baseline commit `8f124d6`.

Final local evidence: `/private/tmp/anios-allocation-verified.1fg7Mp/`.
Preserved on Spark:
`/home/animallya96/anios/data/market/research/allocation-adapter-20260924.3sVFrv/`.
All **30 files / 135,475 bytes** have matching readback hashes and sizes; the
destination was fresh and no archive was overwritten. Largest demonstrated
reconciliation residuals: cash/NAV **4.44e-16**, units **3.47e-18**.

Adjusted units are not broker shares. There is no market impact, volume limit,
bid/ask execution, order queue or real historical T+1/T+2/T+3 settlement model.
Cash earns zero. A valid daily information declaration does not authenticate a
training set, source vintage, historical membership or point-in-time quality.
The independent journal verifier does not prove the adapter's policy semantics
or predictive skill. No completed study was rerun or retuned for this change.

## Next experiment

The remaining substantive work is a frozen nested chronological runner, not
another hindsight regime switch. It must retain actual training rows and label
maturity/publication bounds, outer/inner ranges, training-only transforms and
calibration, inner-only selection, frozen model outputs and future-perturbation
proof. It can pass one continuous out-of-sample instruction path to this adapter,
so outer boundaries never reset account cash or holdings.

Keep a no-gate adapter control for attribution and preserve exact `/3`, funded
SPY/QQQ and equal weight on the same calendars and costs. The score-based
`harness.evaluate_scores` is not a funded portfolio evaluator and filters by
available future outcomes; it must not replace the actual account curves.
Source-complete historical quality/cohorts remain outstanding. Previously
examined history remains exploratory regardless of new fold geometry.
