# Independent funded-account proof

## Current fixed-calendar prefix, October 4

VERIFIED saved arithmetic: two v1 candidate accounts, the first v2 candidate
account and the first five controls. At their proof reads, 58/60 v1, 59/60 v2
and 295/300 control accounts remain pending. This is the registered first
start, not the best start. All three producers remain unchanged and active.

First start2018-02-01 through2026-09-30,2177 sessions,0bp per-side costs,
$100,000 initial cash, carried whole shares and matched corporate actions:

| Method | Total gain | CAGR | Maximum loss | Sharpe | Cumulative turnover |
| --- | ---: | ---: | ---: | ---: | ---: |
| Incumbent rule | 763.51% | 28.34% | 43.09% | 0.993 | 184.21x |
| Boosting timing control | 787.70% | 28.76% | 43.30% | 1.006 | 182.56x |
| Ridge timing control | 711.32% | 27.42% | 43.59% | 0.970 | 182.84x |
| Joint funded v1 | 283.76% | 16.84% | 36.30% | 0.777 | 530.60x |
| Joint funded v2 | 337.21% | 18.62% | 36.30% | 0.813 | 551.10x |
| SPY | 190.50% | 13.14% | 32.59% | 0.772 | 1.00x |
| QQQ | 350.63% | 19.04% | 34.54% | 0.862 | 1.00x |

Boosting and ridge retain the incumbent selection, equal-weight sizing and
grade/reset/FOMC exit plans; they change forecast-driven execution timing.
They are distinct from the joint funded sizing replacement. Boosting's
first full-period result is slightly higher than the incumbent, with slightly
larger maximum loss. It does not dominate: the reused32-session recent window
returned4.24% versus5.37% for the incumbent. Nonzero costs and other starts
are still missing. No parameter change, model refit or live adoption follows
from this first prefix.

Mean end-session exposure is 48.10% for v1, 49.49% for v2 and 85.43% for the
incumbent. The revised model improves on v1 but still trails QQQ and the
incumbent over the full period, with substantially higher turnover. Exposure
and turnover identify differences to investigate; they do not establish that
increasing leverage would recover the lost gain. No live replacement is
justified by these results.

| Method | 2018-20 CAGR | 2021-26 CAGR | Reused recent total gain |
| --- | ---: | ---: | ---: |
| Incumbent rule | 29.35% | 27.83% | 5.37% |
| Boosting timing control | 29.60% | 28.33% | 4.24% |
| Ridge timing control | 28.41% | 26.92% | 4.00% |
| Joint funded v1 | 5.08% | 23.34% | 3.75% |
| Joint funded v2 | 5.08% | 26.18% | 5.77% |
| SPY | 11.89% | 13.78% | -1.42% |
| QQQ | 24.41% | 16.39% | 1.26% |

Source/producer/verifier e396841bb5bdb4218491e0bc3adba96cb804635b. Existing
watcher independently verified original saved bytes, funding, shares, fees,
valuations, calendars and every missing comparison; no accounts were rerun.
Artifact /home/animallya96/scratch/funded-calendar-20261004-e396841b/proof/independent/saved-prefix1.json
SHA b1c5ac41001ad4d5c5b981347ca427b3eca01cb5c3990c4a9abf61949b755c3a.

V2 source/producer/verifier 4daa3bab18a44010d53dd845005678b427bc2cb1.
Its saved-only prefix verification ran once, without simulations or fitting.
Artifact /home/animallya96/scratch/risk-qualified-20261004-4daa3bab/proof/independent/saved-prefix1.json
SHA aa9152a8ea571dcd5ce4d6e23f702ac5034afb28dc515456f5fdded90af06571.
Every first-book window has zero missing NAV marks. V2's reused recent gain
of 5.77% accompanies 7.75% maximum loss and 7.32x turnover, versus the rule's
5.37%, 5.68% and 3.60x. The recent 32-session window is not fresh unseen data;
its higher gain cannot select a regime, threshold or replacement policy.
Later optimizer and persistence fixes are absent from these producer sources
and cannot be credited to their saved economic results.

These are conditional current-vintage/proxy books, not exact historical live
reconstruction or proven broker/midpoint fills. Dividend claims contribute
to NAV but remain unspendable and unreinvested; ETF results follow that same
account convention. Arithmetic verification is not forecast calibration or
adoption evidence. The full objective remains ACTIVE.

## Earlier checkpoint, different producer source

The earlier figures below belong to their original source/proof, not the
current fixed-calendar cohort above. They remain as historical evidence.

The live replacement remains UNVERIFIED. This checkpoint verifies saved-account
arithmetic and receipt consistency, not predictive accuracy or adoption.

Exact verifier source: e7df67e778d59d470bae6d0fef9ed11287b3b7f6, pushed on
codex/learned-entry-risk-20261002. Starting tree bd3dcced; original main204689db
remains an ancestor and unchanged. Neither active producer was changed/restarted.
No production, UI, model, prompt, schema or deployment changes; diagram impact NONE.

VERIFIED:128 native tests24.93s;149 pinned-source tests19.09s, no skips.
The31 new cases use actual private-account artifacts and reject altered funding,
shares, valuation, fees, grades, policy, clocks, optimizer metadata, projections,
gains, selected/reordered partial indexes, incomplete final reports, future labels,
image/mount substitution and missing benchmark entry. Saved verification succeeds
with simulations and forecasts forbidden. Ruff and diff checks clean.

The existing independent ledger verifier retains its original policy default and
all raw-source/cash/share/fee/corporate-action assertions. An explicit keyword
admits the named candidate; silently relabelling it as the incumbent still fails.
The new saved-only CLI verifies full original producer trees, actual pinned images,
read-only source mounts, original input maps and compressed account bytes. It
rebuilds funded metrics independently and retains every pending start/cost/window.
Unknown wealth paths and unsupported benchmark openings cannot become complete
comparisons. An original control runtime receipt says image_id=unavailable;
actual Docker image identity is separately authenticated, without rewriting it.

First saved-prefix proof VERIFIED seven original accounts, zero candidate accounts;
60 candidate/293 control-method accounts remained pending at this proof's read.
The first0bp/start0 conditional full-period funded gains were rule856.4248%,
boosting827.5677%,ridge833.9933%,SPY190.4951%,QQQ350.6341%; two further start1
policy accounts were checked. These are partial/current-vintage research results,
not a finished cost/start comparison or exact historical live performance.
Every checked account retained all2177/2176 sessions and zero missing held marks.
No candidate gain or advantage has yet been established by this prefix.

Artifacts:
/home/animallya96/scratch/joint-funded-proof-20261004-e7df67e7/proof/
saved-account-proof.json SHA256cf46283333b9c0c2b1cc1b308f0a28ab0a390725d3071e4630ec9d5702442c9f;
tests.log SHA256fc874315296481a43ec4007e05c088c98b6999b8fb519c349c3e34800ad72805.
command.json/evidence.json bind actual producer IDs and mounts. The first launcher
attempt rejected the wrong control manifest path before reading any accounts;
the launcher was corrected to the original manifest.json location. No assertion,
producer source, result or original byte was altered. Successful second evidence
SHA25680d3a80853d5fd9a52189b5b3b4c6a3bfeee392d9fb01c15f7ceac0b1a09d81f;
command SHAb00100bfc23089e9e00fce1ac8414dcf4943081186b795e1e5898dc6a8e52f13.

NEXT: check compact process completion first; independently verify newly completed
candidate/control prefixes from saved bytes in fresh proof outputs, without
account reruns, model fits, threshold/window/start mining or active-source edits.
Compare all original20starts and0/10/25bp against unchanged rule,SPY,QQQ. Preserve
missing metrics and source identities; inspect any first failing boundary rather
than relaxing proof. Complete-book, complete-study and live adoption are separate.
Current-vintage grades/universe, reused recent outcomes, manually reviewed action
declarations, unspendable dividend claims and conditional raw-opening proxies
remain limitations. Neither broker/midpoint fills nor a calibrated confidence
advantage is verified. The full user goal remains ACTIVE.
