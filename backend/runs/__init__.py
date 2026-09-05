"""Durable runs: an agent's loop hosted by a worker over leased rows.

`repository.py` owns the rows, `controller.py` drives `run_steps` over them
with idempotent resume and bound approvals, `worlds.py` is the contract an
agent implements to be run this way, and `backend/workers/run_worker.py`
hosts the loop. Design in docs/AGENT_PLATFORM_PLAN.md (D1, D3, D4, D8).
"""
