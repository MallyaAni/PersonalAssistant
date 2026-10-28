# Candidate: the Historical simulation box reads the installed rule's replay; nightly plan check; dead code removed

No allocation rule, model, cost or parameter changes. `market_daily.py` loses the old curve block (the box now reads
the 20:40 policy_book replay); `api/v1/market.py` serves `policy_simulation` and `plan_parity`. Planner files unchanged.
Evidence: full backend suite no new failures against main 17dcff8a; tsc clean; 27 desk/paper/chart/strategy e2e specs
paired with main, no pass-to-fail; replay byte-identical on 94 names; plan check OK on 10-22..10-27 (`~/scratch/mapfix`).

Bound sources changed (2):

- `backend/api/v1/market.py`
- `backend/cli/market_daily.py`
