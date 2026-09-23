# Intraday incumbent parity review — independent validation, 2026-09-23

Independent differential validation of the fixed comparison's incumbent
price-entry formula against unchanged production momentum's price rule, run in
the `codex/incumbent-parity-20260923` worktree at base
`18e3cda9edbe0b8b5b5d4c8c4cbb40d002692e53`. No production code was edited, no
Git history mutated, no provider/model/order path touched. This owns three
files: `backend/tests/test_intraday_incumbent_parity.py`,
`docs/research/intraday-incumbent-parity-review-2026-09-23.md`,
`PARITY_HANDOFF.md`. Root reviews.

## What the production incumbent price rule actually is (traced, not inferred)

The API (`backend/api/v1/market.py:525-534`) runs the live read
`live_technical.entry_now(store, quotes)` and feeds each name's returned
`band_z` into `decision_view.build(...)` as the `entries` dict
(`backend/api/v1/market.py:530-534`, `decision_view.py:706-712`). `entry_now`
(`live_technical.py:647`) computes that band through `entry.entries(panel)`
(`backend/agents/trading/desk/entry.py:72`) → `bollinger_z(panel.adj_close)`
(`entry.py:60`), where `panel` is the stored daily history plus the developing
row built by `with_live_row` (`live_technical.py:91`) whose adjusted close is
`raw_live_price × (prev_adj / prev_close)`. The gate is
`decision_view.entry_action(row, band, grade_live, current)` (`decision_view.py:539`)
reading `paper.ENTRY_BAND_Z`, `paper.ENTRY_MIN_GRADE`, `paper.ENTRY_NAME_CAP`,
`paper.entry_size` (`paper.py:155-177`). `grade_live` is refreshed intraday by
`holdings.live_grades` over `desk_freshness.grade_inputs` (a live technical/value
re-read), not the record grade alone (`market.py:552`, `decision_view.py:674`).

The comparison (`backend/market/intraday_comparison.py`) reuses the *same*
`bollinger_z` (`intraday_comparison.py:36,307`) and the *same* `entry_action`
(`intraday_comparison.py:337-342`), with the same conversion: series = last 19
prior adjusted closes + observed intraday close × (latest prior adj/raw ratio).

## Verified parity (26-case suite, `backend/tests/test_intraday_incumbent_parity.py`)

- **Band equals the live read** — `incumbent_band_z` ≡ `entry_now`'s band_z on
  the same causal inputs (production panel built by the real `with_live_row`),
  to 1e-12, at six developing-day closes (235–260). Both are the same
  `bollinger_z` on 19 priors + today's converted close.
- **Developing-day inclusion, not a frozen prior band** — the band moves with
  the intraday close (0.9907 at 245, 1.3784 at 260) while the frozen prior-20
  band sits at 0.8238; the candidate's fixed levels (level 242.07, entry
  244.37, invalidation 219.00) are the prior-20 mapping and never move intraday.
- **Entry threshold equality / just-below / just-above** — comparison readiness
  equals `entry_action`'s Buy decision at every sampled band; `band ==
  ENTRY_BAND_Z` (1.10, raw close 248.6416) fires, a hair below does not; the
  comparison reads the same.
- **Raw/adjusted scale equivalence** — the same economic path in raw and
  adjusted coordinates gives equal band, equal readiness/state for both
  methods, levels that scale by r, and equal production `entry_now` band; a
  missing/ambiguous basis raises before any scoring.
- **Rejecting-band gate** — `entry_action` returns Hold at any band when the
  daily rejects its upper band; the comparison reports both methods
  NOT_ELIGIBLE for the same input.
- **Grade floor / late / unknown eligibility** — grade B is refused by
  `entry_action` at any band and blocks both methods; unknown or late-learned
  eligibility blocks both, known-by-decision-time enables.

Run with `PYTHONPATH=<worktree> /tmp/opencode/fv-venv/bin/python -m pytest
backend/tests/test_intraday_incumbent_parity.py` → **26 passed**. Narrow
neighbors: `test_intraday_comparison.py` 34 passed, `test_intraday_comparison_
review_edges.py` 10 passed, `test_market_live_technical.py` 20 passed (90 total
in one run). Ruff and `ruff format --check` clean on the owned test. The 16
RuntimeWarnings are `levels.level_features` NaN slices on the deliberately short
21-session synthetic panel, cosmetic, not parity-affecting.

## VERIFIED / FAILED / UNVERIFIED

- **VERIFIED** — comparison incumbent band formula equals production's live
  band formula on identical causal inputs; entry threshold boundary, grade
  floor, rejecting-band gate and raw/adjusted scale equivalence match the real
  production helpers; candidate uses the distinct frozen prior-20 mapping.
- **UNVERIFIED** — live intraday grade refresh: the comparison takes a fixed
  `Eligibility.grade` (with availability), while production re-grades intraday
  via `holdings.live_grades`; the single-source diagnostic fixes grade A,
  rejecting_band False at each open for BOTH methods, which is a controlled
  assumption, NOT recorded eligibility (`intraday-single-source-protocol-2026-
  09-22.md`). Account/holdings/cash/name-cap at account level: the comparison
  calls `entry_action(..., current=0.0)` and cannot see a name already at the
  15% cap or any cash constraint (pinned as a named boundary). Execution: a
  close-time signal is historical, never a fill or next-session order; the
  next-bar-open proxy is zero-cost by protocol and unverified as an executable
  fill.
- **FAILED** — none reproduced in this role; no production defect was edited.

## Why this cannot establish live-strategy or portfolio superiority

The single-source diagnostic derives daily reference closes from IEX
regular-session closes (`intraday-single-source-protocol-2026-09-22.md`), not
the live Yahoo/daily bars the incumbent trades; changing the daily source is an
explicit contract change. It fixes common eligibility (A/nonrejecting at open)
rather than replaying recorded availability or the live re-grade, and a cohort
of four corrected names plus two benchmarks cannot estimate universe-wide
strategy performance. Frozen 20/5 horizons and the zero-cost next-open proxy
stand as declared; none of these makes the results an exact live backtest or a
portfolio/performance claim. Parity of the *formula and gates* is what is
verified here — not historical outcomes, not superiority.

Diagram impact: NONE — no component, agent, store or boundary changed; this
adds a review document and a test module only.
