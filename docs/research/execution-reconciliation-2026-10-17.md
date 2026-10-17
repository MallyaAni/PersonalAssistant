# Saved execution reconciliation — 2026-10-17

VERIFIED bounded reconciliation of the genuine Oct13 decision and later Oct14
broker GET capture. This does not establish fresh ordinary acceptance, a learned
intraday decision, present API owner isolation, or investment quality. No model,
sender, planner, broker client, history publisher or production writer is called.

The isolated implementation starts at production-based
`a2378e9565e6a557fbc3782ac1a5536bae961a75`. Original decision source remains
`42b11a76cbbdfd0e329f6e47ca2e532f369e2eba`; it is not relabelled as today's
source. Original capture:
`/home/animallya96/scratch/grade-led-first-ordinary-20261013-v1`, proof
`b5f086853ebbdf432e61eef8046ab2b066def48ba6d4c17fce951e6311cd33d9`.
Later capture:
`/home/animallya96/scratch/grade-led-ordinary-source-failure-20261014-v1`, proof
`6628f809b42949761ed574e70a548d3b365063d52e724c4b7476bb50290b1441`,
broker JSON `d87799e262b24902601f1e1d6e3877a30cab08a307480e454945a33b80922b39`.

## Original decisions and observed outcomes

The original record `37d7541f5ce12a080a4c0538939b95f99367fc9b5318e21eba03d96963927c32`
contains 94 saved grade signals/targets and two funded whole-share exits:

| Original client order | Quantity | Original created UTC | Actual broker completion UTC | Aggregate fill price |
| --- | ---: | --- | --- | ---: |
| `anios-2026-10-13-sell-stx-135` | 12 | `2026-10-13T23:46:44.596904903Z` | `2026-10-14T13:32:46.922719Z` | 739.236667 |
| `anios-2026-10-13-sell-swks-136` | 130 | `2026-10-13T23:46:44.630871025Z` | `2026-10-14T13:33:32.086665Z` | 76.181923 |

Both are grade exits routed `next_open`. They were accepted and unfilled in the
original capture. Later broker receipts preserve IDs, requested quantities and
created instants within the broker's changed timestamp precision. Their later
`submitted_at` clocks are Oct14 at08:00Z. The audit retains both original and
later timestamp strings separately. Aggregate order completion is not the time
of every partial fill and is not proof of an exact09:30 fill.

The share delta is VERIFIED across the saved captures: STX12 and SWKS130 leave
the account, and the other eight positions retain their quantities. Cash12.65
plus aggregate sale proceeds gives18787.139994 before unobserved fees or other
activity; later cash18787.14 differs by0.000006, consistent to broker cents.
Fee, transfer and corporate-action completeness is UNVERIFIED without an account
activity ledger. That comparison does not invent a zero-fee assumption.

The later preserved paper state is still the original hash
`28d3e8ed8c09b1611c57ee0133ae620e430b4b57973b9d28634030d8b80d16fd`.
It retains both pending legs without a later durable journal settlement.
Subsequent ordinary jobs failed source admission before reconciliation. Live
broker resolution and a later durable nightly settlement are distinct facts;
no state is rewritten to make a missing nightly appear to have succeeded.

## Price and plan boundaries

The sizing receipt's original equity is98609.09 and cash12.65. Original saved
positions conserve share quantities, but their later within-run marks sum with
cash to98606.0804. HPE's approximately3-dollar mark change and SNDK's0.0036
precision difference must not replace the original sizing inputs. The audit
derives each held sizing mark from `current_weights * observed_equity / qty`.

Submitted original legs are `record.paper.orders`; unsent legs are
`record.paper.planned` (empty in this record). The original pending rows retain
decision/reference clocks and execution routing. Receipt
`execution_timing.orders` binds their client IDs to routing; receipt `execution`
contains projection/blocker metadata, not an order-quantity map. Projected cash
or equity is not a fill. ALAB27/SNPS12 are retained despite raw proposals of zero;
SNDK6 is retained with unavailable joint-risk support. MU's prospective increase
is below one funded whole share and its saved execution reason says so.

The original embedded and journalled parity failure remains false with eight
target mismatches. The parser initially rejected the valid parity journal's
`rows` wrapper; that failed local attempt is preserved in the task/tool record.
The corrected reader selects the original dated row and never recomputes or
relabels parity. No production execution defect was established by these two
exits. The separate target-checker correction and UI source correction belong
to their reviewed release paths.

## Reproduction and limits

Run `python -m backend.cli.market_execution_reconciliation` with
`--original-root`, `--later-root`, the two independently recorded
`--original-proof-sha256`/`--later-proof-sha256` values, and a fresh `--output`
outside both captures. It authenticates every original capture file before and
after reading, authenticates later broker/state bytes, and writes only the new
proof. It never reads credentials or performs network requests.

VERIFIED native acceptance:21 tests,0skips,0failures (0.61s); Ruff and whitespace
checks pass. The actual saved-capture CLI also passes, retaining failed parity,
pending state and explicit learned-timing gaps. Local proof:
`/tmp/anios-execution-reconciliation-20261017/audit-final.json`, SHA
`bc0648eaea361efe1661424dc5d959e548ba2b9e2a6b0e3b235cf543bba09e31`.
All inputs are copied read-only observations; none is a synthetic replacement
for original live evidence. Synthetic unit fixtures establish only their tested
invariants, not source authenticity or genuine model decisions.

UNVERIFIED: learned intraday wait/execute and its authenticated shared forecast,
sender/fill/UI journey; next fresh ordinary nightly; present source-bound owner
API isolation; full numerical re-inference; complete account activities. The
saved close expired at2026-10-14T09:30-04:00 and cannot be presented as current.
Oct12/14/15/16 missing records remain missing; only Oct12/14 absence is directly
covered by the selected later capture. No missing session is replayed or created.
The full retrospective, model services and production state remain untouched.
Diagram impact: NONE — this saved-only research audit adds no runtime boundary.
