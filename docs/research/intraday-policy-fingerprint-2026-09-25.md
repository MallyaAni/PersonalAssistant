# Include the consumed regime source in the research fingerprint

September 25, 2026. Starting source: `main` at
`07c1f97958a046b64679109be71692ae5c86d1c0`. This is a research-identity fix,
not a strategy change or a new backtest.

## Failure and acceptance

`intraday_candidate` imports `TIGHTENING_EXPOSURE` from the regime module,
but the research builder's selected source digest omitted that module.
Two fresh processes with source caps 0.75 and 0.25 produced total target
weights 0.1125 and 0.0375 under identical synthetic inputs. Their versions,
input/record hashes and policy hashes were identical. The real forward report
therefore pooled observations from the two implementations into one group.

**FAILED original contract:** the exact final permanent regression has four
failures on the original builder: omitted dependency, indistinguishable policy
hash, and pooled groups with and without corporate-action coverage. These are
behavior assertions, not missing imports. Earlier diagnostic artifacts have
three failures and remain separately retained.

**VERIFIED correction:** append `agents/trading/desk/regime.py` after all 17
existing ordered source inputs. No calculation, production cap, strategy
version, collector, archive identity or account behavior changes. Removing
that one line restores the original builder bytes. Across six synthetic
decisions, all non-policy-hash fields are identical before/after the fix.

The permanent test loads each source variant before the candidate's by-value
import, checks actual module paths and imported constants, then invokes the real
builder at fixed clocks. Only the historical panel boundary is synthetic;
economic JSON, candidate/risk/entry calculations and hashing are real. A fixed
clock prevents provider fetching. The sole variant source difference is the
cap literal; input and record hashes remain equal while allocations and policy
hashes differ.

The real publisher consumes those built results. Republishing the same candle
preserves the first archive byte-for-byte, including its original policy.
Later candles are admitted. The real report then has two groups with counts
one and two, in both action-coverage modes, with zero pending daily validations.
Coverage uses actual local synthetic Parquet files, not vendor observations.
Reporting leaves every archive byte unchanged.

## Checks and identity

- Agent: 4 original failures retained; corrected focused/neighbor suite
  27 passed, zero skips, 6 existing warnings, 4.17 seconds. Expanded suite:
  76 passed, zero skips, 46 existing warnings, 5.58 seconds.
- Root independent run: 39 passed, zero skips, 30 existing empty-slice
  warnings, 4.55 seconds. It runs the new regression plus candidate, research,
  forward-evidence and entry-evidence tests. Fresh-process warnings are also
  retained in each subprocess stderr artifact.
- Independent source review accepts the two-file change and all acceptance
  assertions; that reviewer did not claim an additional test run.
- Scoped Ruff and format checks and `git diff --check` pass. All 33 unchanged
  diagrams and the published architecture page pass synchronization checks.
  Diagram impact is NONE: a selected digest input is an internal detail, with
  no new component/store/boundary.

Both runtime runs use cached image
`63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`, current
read-only source mounts, network disabled, fixed test mode and fresh temporary
directories. No installation or laptop permission change is needed.

| Artifact | SHA256 |
| --- | --- |
| Builder | `d5e8b93add7efa0e9090c914d6d46a1e3577ac75f4260cb49c2cb025536ba00e` |
| Permanent test | `01d403cda60f067c564511bd23b7b31a06d33190ba7f928f9f9f311343a282c2` |
| Original final-contract JUnit | `2b14806eab5455c7aaee1c35f82976247c09b3c19bf0dc2b7481ab38805c4d73` |
| Corrected final-contract JUnit | `9e1af46133bb8242f09b6691418d43c40dc1ec3cad504c44c008f7076343496a` |
| Root JUnit | `b8f5f19aa1ea72a7ddb2f1c29b39bbb7bd1a52c8395de65ca24be6b2a42a2463` |

Agent receipt: `/private/tmp/anios-policy-fingerprint.9rd4yu/RECEIPT.md`,
SHA256 `558c74898cc1151a0832fa261e0a17c7ff373aae6723f2881dfbac705ea36cd4`.
Original source variants, raw decisions, reports, logs, commands and unchanged
test bytes are retained beside it. Root evidence is under
`/private/tmp/anios-policy-root.nGCj9m/`.

## Limits

This closes one demonstrated source omission. It does not establish complete
dependency closure, package/environment identity or runtime attestation. Source
files read from disk are not proof that a long-running process loaded those
same bytes. Whether real historical archives contain a mixture is UNVERIFIED;
no such archives were inspected or modified for this fix. Existing hashes do
not retroactively attest to the omitted source, and existing groups are neither
migrated nor relabelled. All new builds acquire a different policy hash, also
because the builder hashes its own source.

Deployment, provider correctness and investment performance remain UNVERIFIED.
This does not supply the missing full-policy state, phase prices, executable
fills or common intraday marks needed for a funded `/3` versus SPY/QQQ replay.
No fit, historical strategy rerun, provider/model request, holding/order action,
service restart or deployment was performed. Publication is Mac → Spark →
GitHub from Spark; publication is not deployment.
