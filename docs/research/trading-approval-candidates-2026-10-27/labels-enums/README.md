# Candidate: trading labels as enums (no rule change)

Every trading label is compared and built as a member of an enum in `backend/market/labels.py`
(frontend: `frontend/src/services/labels.ts`), and model outputs that carry a label are decoded under a
strict JSON schema. Wire values are unchanged. No allocation rule, model, cost or parameter changes.

Evidence (`~/lbl/r2` on spark1): full backend suite 0 new failures against main; tsc clean; full e2e paired
against main with no new failures; policy replay (94 names), curve block, live-rules and funded simulations
and 51 desk API answers byte-identical apart from timestamps and source hashes; FOMC decision-close
restoration dry run (2026-10-28 15:46 ET, fake broker) sends the same 8 orders as main.

Bound sources changed (18):

- `backend/agents/trading/desk/event_execution.py`
- `backend/agents/trading/desk/funded_execution.py`
- `backend/agents/trading/desk/nightly_plan.py`
- `backend/api/v1/market.py`
- `backend/cli/market_daily.py`
- `backend/market/alpaca_trading.py`
- `backend/market/decision_view.py`
- `backend/market/learned_order_observation.py`
- `backend/market/learned_personal_guidance.py`
- `backend/market/live_model_decision.py`
- `backend/market/personal_history.py`
- `backend/market/sequential_shadow_context.py`
- `backend/market/strategy_entries.py`
- `backend/market/strategy_model_history.py`
- `backend/market/strategy_publication.py`
- `backend/market/strategy_reference_book.py`
- `backend/market/strategy_reference_entries.py`
- `backend/market/strategy_reference_transition.py`
