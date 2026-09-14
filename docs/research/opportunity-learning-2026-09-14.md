# Price-sensitive supervised comparison — September 14, 2026

Implemented and trained at source `b92ca4ff46c60ae92b4b387df460cafeb0b26287`.
After incorporating concurrent documentation updates, this source commit became
published `09cef0e5`. The training CLI, feature builder, accounting, valuation
levels and shared model code are byte-for-byte unchanged by that rebase. The
original artifact manifest retains the actual training revision.
This is a bounded comparison, not a production trading policy or proof of alpha.

## What ran

Eight existing price/volume features plus ten filed-financial ratios: sales,
earnings, book and cash-flow yields, revenue growth, margins, cash and debt.
Ratios use the decision-date price. Date-only filings are withheld until the
following calendar day, including after-close filing cases. Missingness is
explicit; all strategies retain identical stock eligibility rather than silently
dropping names without financials. Sales-yield coverage in the test was 84.29%.

Fixed ladder: ridge alpha 10; histogram boosting with 100 iterations, 15 leaves,
no randomized early-stopping split; one small neural network, seed 0, 15 epochs.
The network ran on RTX 5080. Its epoch was selected from 5/10/15 on 2024 net
log wealth, selecting epoch 10. Training used 2018–2023 with full label endpoint
purging, training-only imputation/scaling, and one training date every five sessions.
Twenty-session labels run from next-close entry to the next delayed execution.
Portfolio evaluation shares cash accounting, 10% name caps, twenty-session
decisions and 10/30 bp per traded dollar. There is no new RL sweep.

The neural model won the 2024 validation comparison. That choice is preserved;
the later test results have not been used to swap in a different learned model.

## Retrospective results

January 2, 2025–September 11, 2026; total returns, not annual returns.

| Policy | Return at 10 bp | Return at 30 bp | Drawdown at 10 bp |
|---|---:|---:|---:|
| Ridge | 61.03% | 53.91% | -45.50% |
| Boosted trees | 121.07% | 109.27% | -46.85% |
| Neural, validation winner | 63.72% | 55.69% | -49.75% |
| Fixed valuation rule | 255.52% | 249.25% | -36.54% |
| Momentum20 | 419.01% | 384.46% | -38.31% |
| Momentum120 | 348.10% | 335.74% | -45.87% |
| Equal weight | 122.35% | 120.89% | -33.88% |
| SPY | 31.19% | 30.93% | -18.76% |

These figures are materially biased by today's thematic membership and an
already examined test period. Historical delistings are absent. Share-count and
split-unit consistency needs further audit. No historical analyst consensus,
release-text model or full adopted-desk replay is included. Adjusted fractional
execution omits historical spreads, settlement and market impact. These results
support withholding this learned policy from production, not a general verdict
against ML. No new model is connected to live grades, orders or the paper book.
No new prospective ML performance has accumulated in this task.

## Ledger corrections and evidence

The separate paper ledger now observes current-session corporate actions through
the existing Yahoo adapter and stores an immutable daily action observation,
independent of completed daily bars. Unavailable actions fail closed. It rechecks
quote freshness after network collection; splits and dividend receivables apply
once. A real AAPL adapter call succeeded at 2026-09-14T21:23:45Z.

Both the HTTP decision view and paper planner use the experimental target for
direction when a matching current research allocation is available. Adopted
eligibility gates remain. The regressions verify 6% held / 2% target sells and
6% held / 10% target buys despite opposing nightly targets. Version 2 records
the writer change and clears earlier pending intents via the policy hash.

VERIFIED: 75 targeted Linux tests including HTTP and persisted account checks;
16 research/accounting tests on Windows (four overlap the Linux selection);
all six saved learned-model cost curves replay; lint; 32 diagrams and published
architecture page synchronized. Diagram impact: NONE — existing data, research,
provider and paper-ledger boundaries are reused. No new prompt or route.

UNVERIFIED: live deployment and public browser acceptance. Existing SSH access
from this desktop to spark1 was denied; the normal scripts/deploy.sh path was not
bypassed. Deployment and its full gates remain for an authorized host.

Artifacts are separate at `E:/AgentWorkspace/opportunity-learning-20260914`:
inputs.npz, manifest.json, results.json, ridge/trees joblib and neural.pt.
Only locally created joblib artifacts are reloaded by the training CLI; do not
substitute untrusted pickle files. The committed JSON summary contains exact
configuration, source, feature/price hashes, selection metrics and results.

Reproduction from the isolated research environment (DEBUG=false):

```text
python -B -m backend.cli.market_opportunity_learning --data-dir E:/AgentWorkspace/growth-pilot-transfer-3dcce629/market --facts-dir E:/AgentWorkspace/PersonalAssistant/data/market --output NEW_EMPTY_OUTPUT_DIRECTORY --asof 2026-09-14 --device cuda
```

Dependencies are recorded in the manifest; sklearn was installed only in the
isolated research venv. Shared environments and Spark model servers were untouched.
