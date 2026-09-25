# Point-in-time quarterly fundamental features — September 20, 2026

**Current reach, checked September 25:** the initial research-only scope below
is historical. `desk._fundamental_opinion` now uses this adapter and
`fundamentals_asof.load_versions` for the corrected live fundamental opinion;
learned-input and shadow paths also read the versioned source. The legacy
version records omit their original units. Whole-snapshot unit selection can
therefore undermine the temporal guarantees below before this adapter receives
its inputs. The new unit-preserving source work is separate, not a silent
migration or a claim that old frames can be labelled USD.

A research-only adapter that turns the already-stored as-of filing versions
(`backend/market/fundamentals_asof.py`) into quarterly fundamental features
with explicit missingness. It is standalone, touches no frozen module, and
is not read by the nightly desk, the shadow ledger, or any model that has
been promoted. Nothing here establishes a profitable strategy or promotes a
model.

## Interface

`backend/market/fundamental_features.py` exposes
`features(panel, versions_by_ticker)` returning a `FundamentalFeatures`
dataclass:

- `values` — a float `(T, N, K)` tensor of the economic columns, NaN where
  a feature is not computable;
- `names` — the ordered `FEATURE_NAMES` tuple:
  `revenue_yoy`, `revenue_qoq`, `revenue_acceleration`, `gross_margin`,
  `net_margin`, `ocf_to_revenue`, `capex_to_revenue`;
- `period_ends` — a parallel `datetime64[D]` tensor: the fiscal period end
  each economic feature references, NaT where the feature is NaN, so a
  consumer can detect an individual ratio that still sits on an older
  quarter while revenue growth has moved on;
- `available` — a `(T, N)` bool mask: has this name published any
  fundamental by this session (independent of whether a specific feature is
  computable);
- `staleness` — sessions since the name's latest newly available filing, a
  filing activity counter, not a freshness flag for every feature (that is
  what `period_ends` is for); NaN when nothing is on file.

The mask and staleness are deliberately separate from the economic columns
so a caller can tell "no data on file" from "data but this feature missing".

## The defect reproduced

The frozen path (`edgar.edgar_features`) zero-fills every non-finite ratio
(`np.where(np.isfinite(series), series, 0.0)`) and sets `has_fundamentals`
from revenue alone. The fundamental analyst
(`backend/agents/trading/desk/fundamental.py`) then ranks those fabricated
zeros as valid inputs. `test_reproduces_legacy_zero_fill_of_a_missing_ratio`
shows, on one panel row, revenue known and gross margin never filed: the
frozen path emits `gross_margin = 0.0` with `has_fundamentals = 1`, and the
analyst's evidence block reads the zero; the adapter keeps the same
situation as NaN.

## Missingness

Missing values stay NaN, never a fabricated zero. A genuinely zero growth
(a year-ago quarter with equal revenue) or a genuinely zero margin (zero
gross profit against positive revenue) is a real zero. A missing lagged
quarter and a zero denominator are NaN.

## As-of semantics

- Only versions with `Version.available <= session` are used; a later
  filing, restatement, or competing tag cannot change any earlier feature,
  including the tag-selection decision (asserted on the full tensor).
- A restatement changes only the features that read the restated quarter,
  and only from the restatement's availability on — after-close and
  date-only filings alike.
- Each name's quarterly values come from the tag the as-of selector chooses
  with the periods available then (deterministic table-order ties), with
  quarters derived from six/nine-month spans and from the year the same way
  `fundamentals_asof._quarters` does. Nothing is filled from a future
  period.
- The per-session state updates only names a newly available filing touches
  and carries the derived quarters forward, rather than recomputing all
  history every session.
- Revenue growth is log growth, matching the incumbent convention: same
  fiscal quarter a year apart for year-over-year, prior quarter for
  sequential, and the difference of the two year-over-year rates for
  acceleration. The lag lookup picks the nearest eligible quarter end,
  deterministic regardless of insertion order, and the growth is computed
  as `log(a) - log(b)` so huge finite operands do not overflow.
- Ratios divide the same fiscal period: the numerator and denominator are
  taken from the latest quarter end where both are known, so an old
  numerator is never divided by a newer quarter of revenue. Each ratio's
  reference period end is exposed in `period_ends`, so a newly filed revenue
  quarter never makes an older, still-lagged margin look fresh; an
  overflowing ratio quotient is NaN, never inf.

## Limits

- Same-day acceptance is suitable for end-of-day decisions only; for
  intraday use the features must be lagged to the previous completed
  session.
- Research only: this adapter is not integrated into the live desk, is not
  evidence of a profitable strategy, and does not promote any model.

## Validation

Independent Codex review on 2026-09-21: all 22 tests passed on the desktop,
including the CLI test skipped in the worker environment; one existing
empty-slice warning remains. Targeted Ruff passed. The stored-data acceptance
run exercised 2,936 sessions and 95 panel columns, with versioned filings for
93 names. Removing every filing available from 2024 onward left all 2,264
earlier sessions' features and reference-period dates identical. No infinity
was emitted, and finite values exactly matched non-missing period dates.
Latest coverage by feature: 88/87/87/67/89/89/88 names respectively, in the
declared feature order. Latest local price session is 2026-09-04; this is not
a claim about current production data. Exact source hash and results:
`E:/AgentWorkspace/entry-timing-pilot-20260920/fundamental-feature-verification.json`.
No production dependency reads this new module; no deployment is needed to
make the research adapter available in the repository.

`python -m pytest backend/tests/test_fundamental_features.py
backend/tests/test_fundamentals_asof.py` — 21 passed, 1 skipped (the
pre-existing CLI test that needs joblib/sklearn/torch, not a pass). Targeted
Ruff check and format check are clean. No live suites or deployment gates
were run.
