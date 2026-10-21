# Trading-source changes held back for the release approval, 2026-10-21

The learned holding release (`data/market/desk/learned-holding/release.json`)
binds the exact bytes of 41 trading sources (`learned_live_holding.source_identity()`),
and the saved timing distributions bind `backend/market/calendar.py` by hash
(`probabilistic_execution_saved.CORRECTED_CALENDAR_SHA`). A commit that changes
any of those files makes the next nightly raise "Exact reviewed learned holding
release required" and end without a record or a publication, until a new approval
bundle is activated through `backend/cli/market_release_admission.py`.

The dashboard review of 2026-10-20 (`docs/research/trading-dashboard-review-2026-10-20.md`)
first landed four of its fixes inside those files. They were moved out before the
first deploy, so the live approval stays valid; the behaviour the board needs is
provided at the serving layer instead:

| Held-back change (patch here) | What ships instead |
| --- | --- |
| `publication-expired-error.patch` - `strategy_publication.validate` raises `ExpiredError` carrying the verified snapshot after every other check | `backend/api/v1/market_allocation._expired_snapshot` re-reads the snapshot with the clock one microsecond inside its window; a snapshot that verifies then has merely expired, and the API answers `awaiting_nightly` with the last plan |
| `verdict-fields-in-sealed-rows.patch` - the entry engines write `verdict`, `reason_code`, `reason`/`verdict_reason` and a verdict-consistent `size_weight` into their rows, with read-time invariants | `market_allocation._with_verdicts` adds the same verdict fields on the way out from the evidence the rows already carry (`strategy_verdict.annotate`); `size_weight` is left as the engine wrote it |
| `replay-price-basis-and-universe-mask.patch` - `strategy_model_history.replay` prices opens and intraday observations in adjusted close, takes a dated universe mask and exits names that leave it; `strategy_history_publication.read` stamps `sample` and `model_fit_through` | `backend/market/strategy_replay_sample.stamp` stamps the served history in `backend/api/v1/market_simulation.view`. The price basis and the universe mask are producer-side and are NOT shipped: the installed history was produced without them (see the review's defects 7 and 8). They belong in the next approved regeneration of the history artefact |
| `calendar-ends-week.patch` - `calendar.ends_week` | `backend/market/session_weeks.ends_week`, same logic, same callers (`technical.py`, `ticker_chart.py`, `stage5_close.py`) |

Each patch applies to `origin/main` at `95a7710f` with `git apply`. Whoever next
activates an approval bundle for these sources should take the first three
through that process; the fourth needs no approval any more.
