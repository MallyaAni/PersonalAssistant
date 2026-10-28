# Trading rules: read before touching any trading code

Applies to `backend/market/`, `backend/agents/trading/`, `backend/cli/market_*`,
`backend/api/v1/market*`, `frontend/src/components/DeskPanel/`, and research under `~/dsv41/`
on spark1. Every rule here is mandatory. If a rule blocks you, stop and ask the owner. Do not
work around it. What each part does is in [CODE_MAP.md](CODE_MAP.md).

## 1. Labels are enums, never free text
- Every trading label is a member of an enum: actions, sides, signals, grades, sessions, timing,
  states and verdicts. Backend: `backend/market/labels.py` (StrEnum, one enum per wire
  vocabulary). Frontend: `frontend/src/services/labels.ts` (`as const` tuples and union types).
- Never compare to a string literal (`== "BUY"`, `== "hold"`) and never build a label from text.
  Read stored or API values with `labels.parse(Enum, value)`, so an unknown value fails loudly.
- Each wire field keeps its existing value and casing (`OrderSide.BUY == "buy"`,
  `TradeAction.BUY == "BUY"`). New vocabulary means a new enum, not a new string.
- Frontend switches over a label must be exhaustive (`assertNever`).
- Files whose bytes are fingerprinted for stored evidence still hold raw literals (listed in
  `docs/research/trading-approval-candidates-2026-10-27/labels-enums/`). Convert them only
  together with a reviewed re-issue of those fingerprints, never silently.

## 2. LLM answers are structured
- Any model call that produces a label or a number the code acts on sends a strict JSON schema
  (`response_format` json_schema, enums/const, `additionalProperties: false`) and reads the answer
  with `json.loads` plus the enum. No regex or keyword parsing of model text.
- Use a discriminated union when fields depend on the label (e.g. a limit order must carry a price).
  Put the analysis field before the label so the model reasons first.
- The local model is DeepSeek-V4.1-Flash-1017 at `spark1:8000`. It reads images and serves the
  vision role.

## 3. One engine
- `backend/market/policy_book.py` `simulate()` is the only implementation of the account. It is
  used by the backtest, the chart replay and the live parity check. Never write a second one.
- Charts show the installed policy's own decisions, with no hindsight. They must agree across every
  ticker, timeframe and zoom level.

## 4. No future data
- Anything evaluated at time T reads only data known by T: filings by their filed date, bars by
  their end time (`visible(bars, T)`), daily pivots only once confirmed.
- Every new feature that reads time series ships with a perturbation test: change everything after
  T and the output stays byte-identical; change the last bar before T and it changes.
- Charts shown to a model carry no ticker and no date, and prices are rebased.

## 5. Research before anything goes live
- Write the pre-registration (question, sample, gate, placebo, what passing buys) and commit it to
  `docs/research/` BEFORE the first run. Amend it only before any result exists, and say so in it.
- Test on the honest point-in-time S&P 500 universe (`~/dsv41/pit2/`), not only the hand-picked
  book. Costs are 10 and 25 bp.
- A new signal must beat a placebo built by shuffling its information across stocks.
- Corrections to data must not degrade results (non-inferiority). New signals must win (superiority).
- A failed idea is written down with its evidence and not retried without a new pre-registration.
- Passing a research gate leads to a forward shadow first, never straight to a live change.

## 6. Data
- Free sources first. API keys live in files with permission 600 and are never printed.
- Research never writes to the deploy store (`~/deploy/anios/data/market`). Use overlays and
  scratch roots.

## 7. Releasing changes
- 44 "bound sources" (`learned_live_holding.source_identity()`) need the release ceremony: a
  candidate folder under `docs/research/trading-approval-candidates-<date>/`, then
  `~/dsv41/cand-release/install_leader_release.py` from the merged tree. Never backdate `approved_at`.
- If `market_daily.py` or `live_model_decision.py` change, recompute the AST pins in
  `test_reconciliation_release_admission.py`.
- Proof before merge:
  - The full backend suite has no new failures against main's list.
  - tsc is clean.
  - The e2e specs run paired against main show no new failures.
  - Replay and simulation outputs are byte-identical when behaviour should not change.
  - Any change near order execution gets a dry run of the next scheduled orders with a fake broker.
- Deploy with `scripts/deploy.sh`, then confirm `check-trading-admission.sh` reports ADMITTED and
  `.post-deploy-status` reads ok. Don't deploy while the 19:30 ET nightly is running.

## 8. Working on spark1
- Reach it from the Windows PC: `ssh animallya96@172.16.8.3`.
- Write scripts with `cat > file <<'EOF'`, never with quotes nested inside `ssh '...'`.
- Never `pkill -f` a pattern that matches your own command. Kill by PID.
- Long jobs run under `setsid nohup ... &` and are polled.
- Files written by containers come out owned by root. A root-owned partition under `data/market`
  makes the nightly prune fail.

## 9. Reporting to the owner
- Plain words. State what is live, what is not, and what failed.
- Never call something done until it is verified.
