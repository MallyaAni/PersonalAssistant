# Candidate: filing versions refreshed for the research universe

The only bound source that changes is `backend/cli/market_daily.py`: `_refresh_versions` covers the research universe
instead of the book, because the value analyst's levels (and the expectations gap that blends into it) now read the
stored filing versions with a per-session tag choice (`levels_pit.point_in_time_levels`). No allocation rule changes.
Evidence: `~/dsv41/valfix/` (truncation test, spot checks against SEC companyfacts, backtests on the honest universes).
