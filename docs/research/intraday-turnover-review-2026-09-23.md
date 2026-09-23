# Intraday turnover & missed-opportunity validation — independent review — 2026-09-23

Status: independent synthetic acceptance only. No real data, no orders, no
filesystem/broker writes, no model or provider calls. Base source:
`18e3cda` on `codex/turnover-validation-20260923`. Owned files only:
`backend/tests/test_intraday_turnover_acceptance.py`, this document,
`TURNOVER_HANDOFF.md`. No existing file was edited.

Read repo guidance (AGENTS.md, `docs/NEXT_SESSION.md`, `docs/ARCHITECTURE.md`,
`docs/DEVELOPMENT_GUIDE.md`), the frozen comparison protocol
(`docs/research/intraday-comparison-protocol-2026-09-22.md`), and the real
implementation before defining assertions:
`backend/market/intraday_entry.py`, `intraday_comparison.py`,
`intraday_replay.py`, `decision_view.py`, plus their focused tests. The
acceptance suite exercises exactly those reviewed modules through their public
interfaces.

## What the implementation actually guarantees (VERIFIED)

`python -m pytest backend/tests/test_intraday_turnover_acceptance.py` — 11
passed. Ruff/format clean. Focused neighbors unchanged and green: 163 + 26
passed across `test_intraday_comparison`, `test_intraday_replay`,
`test_intraday_entry_structure`, `test_intraday_entry_freshness`,
`test_decision_view`, `test_personal_guidance_isolation`,
`test_personal_guidance_api`, `test_intraday_candidate`,
`test_intraday_replay_clock_edges`, `test_recommendation_personalization`.

### 1. Repeated polls of one completed prefix — one event, stable identity
40 polls of the same completed prefix through `compare`+`record_event` produced
exactly **1 event, 1 ledger row**, and an identical candidate identity on every
poll and on a fresh ledger. `replay_session` over 26 bar-end observations
recorded exactly **1 event per method** (2 total), byte-identical on a repeat
run. Dedupe key is (method, symbol, session); identity is a hash of method,
symbol, session, rule, `ENTRY_BAND_Z`.

### 2. Cross-session repeat entry is UNCONSTRAINED (finding, not a pass)
Three consecutive sessions each replaying the same reclaim path produced
**3 candidate events** (one per session) in the ledger. This particular case
checks compare/record_event; it does not run a three-session portfolio replay.
Nothing in the ledger, replay or decision view
limits how many consecutive sessions may enter or adds a cooldown. **A
one-event-per-day ledger does not prove low portfolio turnover.** This is the
core honest boundary the review must report.

### 3. Missed-waiting attribution and common denominators
4-session set (both=1, incumbent-only=1, candidate-only=1, neither=1):
`session_count 4`, counts sum to the denominator. `missed_opportunity_count ==
1` (the incumbent-only session only), carrying the incumbent's own non-zero
outcomes: primary mean **0.0769** (280/260 − 1), secondary mean **0.0385**
(270/260 − 1). The candidate-only session is reported as a separate diagnostic
(`missed_opportunity_candidate_primary.mean 0.0366`, 255/246 − 1), never as
what waiting missed. `paired_entry_count 1` (both-executed sessions only).

### 4. Missing/immature labels are never coerced to zero
One missing-next-bar session (execution_unknown), one immature-horizon session,
one missing-endpoint session: `missing_execution_count 1, missing_outcome_count
1, immature_outcome_count 1`. The conditional primary mean over those sessions
is `count 0, mean None` — an empty set is None, never a fabricated 0.0 — while
the one complete secondary label yields a real mean (0.0569 = 260/246 − 1) over
an exact count. `forward_return` is None, not 0, on every non-complete label.

### 5. Personal funding, liquidation and proceeds (real `decision_view`)
- Two firing entries with cash 3000: aggregate Buy `move_weight × equity ==
  3000` exactly — one account-wide cash bound, each Buy ≤ `ENTRY_NAME_CAP`.
- An uncovered personal holding (ZZZ, not graded) is Hold, move 0 — never a
  liquidation — with and without known cash.
- A covered downgrade is an explicit Sell (executable, full position) while a
  firing buy on another name is Hold / "no available cash" at cash=0: **sale
  proceeds are never assumed to fund a buy**.
- Simulated confirmed fills update EVERY purchased name and deduct aggregate
  spend from cash7000; recomputed additions are no greater than remaining cash
  and below the original proposed buy total. Root corrected the worker test,
  which deducted both purchases but only updated one holding. The add-on is
  bounded only by remaining cash and the name cap; there is **no holding-period
  or cooldown rule**, so after-fill add-on remains policy-unconstrained.
- Unknown cash: strategy Buy preserved, action Hold, executable False, "available
  cash is unknown"; the paper account's 50000 cash never becomes personal.
- Paper variants (cash 999999 + S99 position; cash 0 empty) leave personal rows
  identical; the paper-held S99 creates no personal row.

## Missed-opportunity metric interpretation

`missed_opportunity_count` is a count of sessions where the incumbent entered
and the waiting candidate did not; the incumbent's own outcome labels are what
waiting missed. It is a **conditional signal-frequency and attribution
measure**, not executed turnover, not portfolio alpha, and not a profitability
claim. Full strategy turnover (holdings/cash ledger over multi-session
positions) is not computed anywhere in the reviewed modules; a one-event-per-day
ledger is the only event record and cannot stand in for it.

## Counterexample surfaced

The 3-session candidate-only streak is the counterexample to any reading of
"one event per day" as low churn: the same rule enters every session of the
streak, so the dedupe that prevents repeated alerts within a session does not
constrain repeat entry across sessions.

## Status summary

- VERIFIED: stable identity and one event per method/symbol/session; correct
  missed-waiting attribution with shared denominators and non-zero outcomes;
  missing/immature labels explicit and never zeroed; personal additions cash-
  bound; uncovered holdings not liquidated; no assumed sale proceeds; after-fill
  recomputation cannot spend the old balance; zero/unknown cash blocks buys;
  paper never alters personal recommendations.
- UNVERIFIED / UNCONSTRAINED: cross-session repeat entry cadence (no cooldown,
  no position policy); after-fill add-on frequency (only cash/name-cap bound);
  full portfolio turnover; any real-data outcome; any superiority claim.

Root review corrected the incomplete fill fixture and removed an unsupported
three-session replay result from this report. Where the code is silent (cross-session and
add-on policy) it is reported as such, with a minimal proposed correction for
root's decision: a position/holding-period ledger or a decision-view cooldown
would be required before claiming low portfolio turnover — none is implemented
and none is asserted here.

Diagram impact: NONE — validation evidence only; no component, agent, store or
data flow changed.
