# Code and branch hygiene — 2026-11-04

Status: **canonical hygiene record for milestone 4**. Research and cleanup
only: this note changes no live rule, order, grade, prompt or risk dial, and
prepares no release. The live rule remains `/3`; the forward record continues.

This is the audit and the deletion record for
`docs/trading/PROGRAM-DIRECTION.md` milestone 4. The owner delegated the
deletion decision on 2026-11-04 ("use your best judgment"); every deletion is
reversible from the tag `archive/2026-11-04/pre-hygiene` (the exact tree
before this pass) and from git history. Nothing was force-pushed, reset,
cleaned or rewritten.

## What was measured

- A read-only import graph over the 1,877 Python modules under `backend/`,
  built with `ast` on 2026-11-04 from `main` at `e48cf28b`. Imports inside
  functions and relative imports are included; string-only dynamic imports
  were checked by hand.
- The live entry points are the scheduled jobs and the Desk API, not every
  module the web app loads. The research entry points are the `backend/cli/`
  commands that no cron job runs.
- A module is **live** if it is reachable from a cron job or a Desk API
  router. It is **research** if it is reachable only from a research CLI. It
  is **dead** if no cron job, API router or CLI reaches it and only tests,
  one-off scripts or other dead modules import it.
- The full unit gate was run before and after the deletions; the trading
  admission check was run after. Results are in section 6.

## 1. The live path

The live path is the one described in `CODE_MAP.md`; this audit confirms it
and fixes the counts. 236 trading modules are reachable from the live entry
points: 172 under `backend/market/`, 44 under `backend/agents/trading/`, 16
CLI entry points and 4 Desk API routers.

| job | entry point | what it does |
|---|---|---|
| Nightly 19:30 | `backend/cli/market_daily.py` | data, grades, paper plan, orders, record, briefs |
| Balancer every 15 min | `backend/cli/market_balancer.py` | live prices; due intraday orders; FOMC restore |
| Options 08:45 | `backend/cli/market_options.py` | option open interest, display only |
| SIP 20:30 | `backend/cli/market_intraday_sip.py` | 15-minute bars, data only |
| Replay 20:40 | `backend/cli/market_policy_replay_research.py` | installed-rule replay and plan parity |
| Plan check | `backend/cli/market_plan_parity.py` | re-run one session's plan check |
| Tone | `backend/cli/market_tone.py` | earnings-release tone scores |
| Filings | `backend/cli/market_edgar.py`, `market_fundamentals_asof.py` | SEC facts and versions |
| Economics | `backend/cli/market_economics.py` | inflation notes |
| Desk API | `backend/api/v1/market.py`, `market_simulation.py`, `market_allocation.py`, `market_history_sizing.py` | the screens and ticker pages |

The release identity in `backend/market/learned_live_holding.py` binds 44
source files. No deleted file is in that identity, so the deletion does not
change admission. The retired rules and shadows remain loaded or recorded but
do not size the live book: `policy_v4.py`, `policy_v5.py`,
`shadow_ledger.py`, `risk.py`, `simulate.py` and the one live signal in
`exit.py`. They are not dead code and were not deleted.

## 2. The research path

About 140 `backend/cli/market_*.py` commands are research entry points: no
cron job and no live import. 112 trading modules are reachable only from
those commands. They are the research record and were not deleted. The
research scripts under `~/dsv41/` are outside the repository and were not
touched.

The manual audit commands `backend/cli/audit_original_live_model_history.py`
and `backend/cli/verify_live_model_history.py` are also research entry
points. The live model-history reader and projection they share with the Desk
API remain; the audit-only modules are listed in section 7 as a second-pass
candidate, not deleted in this pass.

## 3. Dead code removed

The dead set is the historical serving-binding audit subsystem and the
intraday research subsystem. Neither is reachable from a cron job, a Desk API
router or a CLI. They are imported only by each other, by their tests and by
27 one-off `scripts/run_*.py` integration runners.

| cluster | files | lines | why it is dead |
|---|---:|---:|---|
| `backend/market/historical_*.py` (39 modules) | 39 | 17,378 | no cron, API or CLI reaches it; the historical fixture is absent and the gate has ignored `test_historical_*.py` since 2026-10-17 |
| `backend/market/intraday_{cache,comparison,entry,inputs,preflight,replay}.py` | 6 | 3,845 | no cron, API or CLI reaches it; the intraday research branches are closed |
| historical and intraday tests | 59 | 30,041 | they test only the deleted modules; 20 synthetic setup helpers are included |
| `scripts/run_*.py` integration runners | 27 | 4,088 | one-off runners for the deleted historical audit; no cron and no caller |

The full deletion list is 151 files: 45 modules, 59 test files, 20 synthetic
setup helpers and 27 scripts. It is recorded in the commit that removes them.
The deleted modules are:

```
historical_broker_checkpoint, historical_conditional_cycle,
historical_conditional_forecast, historical_conditional_market,
historical_conditional_nightly, historical_conditional_settlement,
historical_final_receipt_capacity, historical_finite_evidence_input,
historical_native_directory_binding, historical_native_metadata,
historical_native_output_capacity, historical_packet_checkpoint,
historical_packet_demand, historical_packet_parser,
historical_packet_registry, historical_packet_spool,
historical_packet_store, historical_paper_component,
historical_physical_checkpoint, historical_post_resolution_marks,
historical_prepared_orders, historical_prepared_results,
historical_prepared_transition, historical_raw_cycle,
historical_raw_cycle_final, historical_raw_nightly,
historical_request_admission, historical_reserved_blob_store,
historical_reserved_cycle_final, historical_reserved_cycle_stages,
historical_reserved_native_io, historical_reserved_native_metadata,
historical_reserved_protocol, historical_reserved_sqlite,
historical_session_completion, historical_static_request_admission,
historical_synthetic_native_write, historical_timing_packet,
historical_timing_resolver,
intraday_cache, intraday_comparison, intraday_entry, intraday_inputs,
intraday_preflight, intraday_replay
```

**Kept, deliberately:**

- `backend/market/historical_cohort.py` — reachable from
  `backend/cli/market_historical_cohort.py`.
- `backend/market/intraday_sip.py`, `intraday_evaluation.py`,
  `intraday_research.py` — live data or research path.
- `backend/market/joint_funded_accounts.py` — its `candidate_grid` is used by
  the tests of the live `joint_funded_policy.py`; `CODE_MAP.md` records this.
- `backend/market/earnings_calendar_report.py`, `event_watch_report.py` —
  imported by the Desk API; descriptive only.
- `backend/market/live_model_history_reader.py`, `_binding.py`,
  `_projection.py` and `backend/market/live_model_history.py` — the Desk API
  history-sizing route and the live reader.
- The retired rules and shadows named in section 1.

The result document
`docs/research/historical-serving-binding-acceptance-2026-10-17.md` remains
the record of what that audit measured and what it left UNVERIFIED. Its code
is now archived, not deleted from history.

## 4. Branches and worktrees

**Local branches.** 66 existed. 28 were deleted: 15 fully merged into `main`
(zero unique commits) and 13 with unique commits whose tips are preserved by
an `archive/2026-11-04/<branch>` tag. 38 remain, and every one is checked out
in a worktree: `main`; the clean `.claude` worktree branch; `research/value-v2`
in the dirty `/tmp/opencode` worktree; `codex/intraday-personal-20260922` in a
dirty worktree (its tag is `archive/2026-11-04/codex/intraday-personal-20260922`);
and 34 merged Codex branches held by dirty worktrees. No unique branch is left
without a tag. The 14 that had unique commits:

| branch | tip | unique | last commit |
|---|---|---:|---|
| `backup/ranker-local-work` | `cc13de0e` | 1 | 2026-09-24 |
| `codex/funded-execution-forward-20261002` | `3b9f0f1d` | 15 | 2026-10-02 |
| `codex/intraday-personal-20260922` | `0f3c167b` | 1 | 2026-09-22 |
| `codex/learned-entry-risk-20261002` | `ee13b97f` | 2 | 2026-10-02 |
| `codex/trading-test-cleanup-20260923` | `84712fab` | 1 | 2026-09-23 |
| `fix/research-gross-execution-20261001` | `c2c69e46` | 6 | 2026-10-01 |
| `fix/shared-strategy-inputs-20260929` | `e7a59e2c` | 1 | 2026-09-29 |
| `master` | `d7c8f8db` | 1 | 2026-08-23 |
| `opencode-market-gate-wip` | `ac644bca` | 1 | 2026-09-19 |
| `research/daily-actions-20260929` | `0f681938` | 3 | 2026-09-29 |
| `research/daily-risk-liquidity-20260930` | `f828f186` | 3 | 2026-09-30 |
| `research/earnings-events-20260929` | `04f3224b` | 7 | 2026-09-29 |
| `research/selective-actions-20260929` | `dc6783b5` | 7 | 2026-09-29 |
| `research/target-consistency-20260929` | `7e70fe16` | 3 | 2026-09-29 |

All 14 are closed experiments, backups or the old `master`; none is a
candidate for merging. A branch checked out in a dirty worktree could not be
deleted and is left in place; it is listed with the worktrees below.

**Remote branches.** 58 on `origin`: 8 merged and 50 with unique commits.
Every one is stale (last activity 2026-09-21 to 2026-10-22) and belongs to a
closed experiment, a Codex work package or the historical audit. Their tips
are recorded here and each is tagged locally as
`archive/2026-11-04/remote/<branch>`; the remote refs were **not** deleted,
because deleting a remote branch is a push and an outward-facing action. The
owner can delete them after reviewing this table. The 50:

| branch | tip | unique | last |
|---|---|---:|---|
| `origin/codex/learned-entry-risk-20261002` | `a382af87` | 257 | 2026-10-06 |
| `origin/codex/entry-exit-zero-cost-attribution` | `0c37eb16` | 17 | 2026-10-05 |
| `origin/research/text-surprise` | `1fce9f01` | 15 | 2026-10-02 |
| `origin/codex/historical-provenance-20261017` | `991b4394` | 15 | 2026-10-17 |
| `origin/codex/funded-execution-forward-20261002` | `3b9f0f1d` | 15 | 2026-10-02 |
| `origin/research/llm-statements-a2b` | `e758c72f` | 13 | 2026-10-02 |
| `origin/test/decisive-e2e` | `522e2c7a` | 12 | 2026-10-01 |
| `origin/research/universe-expansion` | `73a91687` | 9 | 2026-09-30 |
| `origin/research/structure-rules` | `579801e2` | 8 | 2026-09-30 |
| `origin/research/tone-validity` | `d5a1cf12` | 7 | 2026-09-29 |
| `origin/research/selective-actions-20260929` | `dc6783b5` | 7 | 2026-09-29 |
| `origin/research/earnings-events-20260929` | `04f3224b` | 7 | 2026-09-29 |
| `origin/research/regime-gross` | `7ee01cd0` | 6 | 2026-10-01 |
| `origin/research/kronos` | `15f65ce3` | 6 | 2026-09-30 |
| `origin/fix/research-gross-execution-20261001` | `c2c69e46` | 6 | 2026-10-01 |
| `origin/codex/specialist-contributions-20261001` | `cadec094` | 6 | 2026-10-01 |
| `origin/codex/historical-timing-correction-20261017` | `2487b5d5` | 6 | 2026-10-17 |
| `origin/trading/volatile-book-15m` | `b9c2e371` | 5 | 2026-09-26 |
| `origin/research/llm-statements` | `db014bd6` | 5 | 2026-10-02 |
| `origin/codex/historical-connected-cycle-20261017` | `95510855` | 5 | 2026-10-17 |
| `origin/research/sector-sells-shared` | `ceb95096` | 4 | 2026-10-01 |
| `origin/research/insider-stance` | `853f0118` | 4 | 2026-10-01 |
| `origin/research/cluster-cap` | `952b127e` | 4 | 2026-10-02 |
| `origin/codex/historical-physical-checkpoint-20261017` | `79bd37c2` | 4 | 2026-10-17 |
| `origin/research/vol-target` | `e6ff1ee2` | 3 | 2026-10-01 |
| `origin/research/target-consistency-20260929` | `7e70fe16` | 3 | 2026-09-29 |
| `origin/research/sector-sells` | `46e61992` | 3 | 2026-10-01 |
| `origin/research/daily-risk-liquidity-20260930` | `f828f186` | 3 | 2026-09-30 |
| `origin/research/daily-actions-20260929` | `0f681938` | 3 | 2026-09-29 |
| `origin/value-weighted-grading` | `24694733` | 2 | 2026-10-22 |
| `origin/codex/historical-conditional-settlement-20261017` | `8788d03d` | 2 | 2026-10-17 |
| `origin/codex/historical-nightly-context-integrity-20261017` | `1498c830` | 2 | 2026-10-17 |
| `origin/codex/historical-packet-acquisition-20261017` | `4c382640` | 2 | 2026-10-17 |
| `origin/codex/original-audit-streamed-history-20261017` | `6d4729c3` | 2 | 2026-10-17 |
| `origin/codex/entry-exit-timing-20261002` | `6b24a180` | 2 | 2026-10-02 |
| `origin/codex/trading-test-cleanup-20260923` | `84712fab` | 1 | 2026-09-23 |
| `origin/fix/shared-strategy-inputs-20260929` | `e7a59e2c` | 1 | 2026-09-29 |
| `origin/desk/sector-sells-live` | `8c3afd11` | 1 | 2026-10-01 |
| `origin/desk/stance-table` | `e67213d1` | 1 | 2026-10-01 |
| `origin/fix/close-orders` | `58d0745f` | 1 | 2026-10-02 |
| `origin/codex/historical-broker-current-profile-20261017` | `7847efc2` | 1 | 2026-10-17 |
| `origin/codex/historical-conditional-nightly-20261017` | `796a7d88` | 1 | 2026-10-17 |
| `origin/codex/historical-current-settlement-cycle-v2-20261017` | `b9f5d7cd` | 1 | 2026-10-17 |
| `origin/codex/historical-packet-rate-20261017` | `ecf30f6e` | 1 | 2026-10-17 |
| `origin/codex/historical-packet-spool-20261017` | `3b6c70d9` | 1 | 2026-10-17 |
| `origin/codex/historical-packet-store-20261017` | `28e00c5b` | 1 | 2026-10-17 |
| `origin/codex/historical-retained-forecast-20261017` | `0c80a67f` | 1 | 2026-10-17 |
| `origin/codex/original-audit-source-floor-20261017` | `9020d8c2` | 1 | 2026-10-17 |
| `origin/codex/trading-dead-frontend-cleanup-20261017` | `a5e977a7` | 1 | 2026-10-17 |
| `origin/vol-floor` | `c82ffc01` | 1 | 2026-10-22 |

The 8 merged remote branches (`origin/trading/nightly-fixes`,
`origin/codex/learned-live-release-20261006`,
`origin/codex/fresh-stock-assessment-20261014`,
`origin/codex/live-decision-contract-20261017`,
`origin/sizing-candidate-20261021`, `origin/entry-grade-b`,
`origin/fomc-decision-close`, `origin/main`) contain no unique commits and
need no archive.

**Worktrees.** 53 existed. 10 clean stale worktrees were removed: nine
detached or merged worktrees and the clean `funded-execution-forward`,
`learned-entry-risk` and `trading-test-cleanup` worktrees whose branch tips
are tagged. Their commits are preserved by `archive/2026-11-04/detached-<sha>`,
the branch tags, or `main`. One removal,
`/home/animallya96/codex-worktrees/trading-evidence-20260923`, deleted the
worktree registration but left the directory because `frontend/node_modules`,
`frontend/dist` and `frontend/test-results` are owned by `root`; 5.8 MB
remains and needs an owner with sudo to remove. `anios-base` and the `.claude`
worktree were left alone. 43 worktrees remain: 2 clean (`anios-base` and the
`.claude` worktree) and 41 dirty. The dirty ones are the Codex
comparison/dashboard/intraday/trading-mac families,
`trading-portfolio-exposure`, `learned-live-release`,
`learned-live-held-release`, `research/value-v2`, and the `/tmp` gate worktree.
They belong to closed experiments but contain uncommitted state; removing them
is a separate owner or Codex decision.

## 5. Stale documents

These are already marked and need no body rewrite:

- `docs/research/trading-program-2026-10-28.md` — status header says
  superseded for direction and live state by `PROGRAM-DIRECTION.md`.
- `docs/TRADING_ROADMAP.md` — status header says superseded by
  `PROGRAM-DIRECTION.md`.
- `docs/ROADMAP.md` — the trading milestone says direction is superseded.
- `docs/NEXT_SESSION.md` — long historical handoff; the current section is at
  the top and the direction pointer is present. History is not rewritten.

Changed in this pass:

- `docs/research/historical-serving-binding-acceptance-2026-10-17.md` gets a
  status header recording that its code was archived on 2026-11-04.
- `docs/trading/CODE_MAP.md` gets a hygiene pointer and its research-family
  list no longer claims the deleted historical and intraday modules are
  runnable research.
- `docs/trading/PROGRAM-DIRECTION.md` milestone 4 is marked done, with this
  note as the record.

Not deleted: `docs/research/trading-approval-candidates-*` (release
provenance), the bound contract, live `evidence.json`, and the result notes
for closed experiments. They are the audit trail, not stale code.

## 6. Gate and admission

Baseline before deletion on `e48cf28b` (with only these docs changed):
11,947 passed, 94 skipped, 10 xfailed, 508 warnings and 48 subtests in
1,052.53s; exit 0. After deletion: 11,729 passed, 94 skipped, 10 xfailed, 492
warnings and 48 subtests in 1,110.21s; exit 0 (`==> Gate passed`). The 218
fewer passing tests and 16 fewer warnings are exactly the removed suites; no
remaining test failed and none was silently skipped.

The trading admission check after deletion printed `ADMITTED` on host and
container, with config `88c269c7...`, evidence `17c291ad...`, release
`4966fd7d...` and the same 44-source identity. No live rule, order, grade,
prompt or risk dial changed.

## 7. Remaining review list

1. **Dirty worktrees (41).** They contain uncommitted files from closed Codex
   experiments. Removing them needs the owner or Codex to confirm nothing is
   wanted; they are not on the live path.
2. **Remote branches (50 unique).** Deleting them is a push. The tips are in
   the table above; the owner can approve a remote prune later.
3. **Live-model-history audit cluster.** Eight audit-only modules and two
   manual CLIs are a closed audit. They are reachable from
   `audit_original_live_model_history.py` and `verify_live_model_history.py`,
   so they are not dead by this pass's definition, but the gate already
   ignores their stale binding tests. A second pass can archive them after
   confirming the live reader/projection does not need them.
4. **Orphan research CLIs.** About 140 research commands remain. They are
   runnable and are the research record; no deletion is proposed without a
   separate decision.

## Change log

- **2026-11-04:** created. Import-graph audit, 151-file dead-code deletion,
  15 merged and 13 unique local branches deleted (the unique tips are tagged),
  50 unique remote tips tagged locally and left on `origin`, 10 clean stale
  worktrees removed, stale docs marked. No live change.
