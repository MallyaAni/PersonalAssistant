# The volatile book and the 15-minute signal engine

Written 2026-09-26 on branch `trading/volatile-book-15m` (worktree
`../anios-trading-volatile-15m`, cut from `origin/main` at `990fa981`).
Decision record: [ADR 0024](adr/0024-one-signal-engine-for-paper-and-personal.md).
Review material, specs and the design-panel synthesis:
[docs/research/volatile-book-review-2026-09-25/](research/volatile-book-review-2026-09-25/).

**Status: PLANNED.** Nothing here is live. The paper account runs
`cash-bounded-breakout-rotation/3` until a release train (`/4`, `/5`) passes
its gate and the operator asks for the switch.

## Status table

Kept current as parts land. `PLANNED` → `BUILT` (merged on the feature branch,
tests green) → `VERIFIED` (acceptance run with numbers) → `LIVE` (deployed on
the operator's word). A research verdict is recorded as `PASSED` or
`INSUFFICIENT EVIDENCE`, never retuned.

| Item | Wave / agent | Owner files (disjoint) | Status |
|---|---|---|---|
| Design, ADR, specs, roadmap amendment | 0 / integrator | this doc, `adr/0024`, `research/volatile-book-review-2026-09-25/`, `TRADING_ROADMAP.md` | BUILT |
| Main-only nightly fixes: ML-ledger continuation (the Spark ledger's latest row, seq 7 on 2026-09-25, is under df47189d; main's identity is 95a54c58 and its unit test fails until declared) and a New York-date `asof` (before 2026-11-01) | 0 / integrator, branch `trading/nightly-fixes` @ `78a7b3c8`, merged into this feature branch (`4413218d`); reaches main only with the whole branch, once proven | `data/opportunity_shadow_migrations.json`, `market_daily.py` (`_nightly_asof`), `test_market_daily.py` | BUILT (42 tests pass) |
| P0.3 SIP 15-minute history + 2016-2018 calendar | 1 / A | `alpaca.py`, `intraday_sip.py`, `market_intraday.py`, calendar JSON, nightly script | PLANNED |
| P0.1 Candidate harness, statistics, gates, trials registry | 1 / B | `candidate_bench.py`, `candidate_stats.py`, `candidate_gate.py`, `trials_registry.py`, `market_candidate_bench.py`, `macro.py`, `allocation_controls.py` | PLANNED |
| Simulator/balancer API (P1 arms, defensive destination, tranches, fill log, cash yield, dead-hook refusals, FOMC parity) | 1 / C | `simulate.py`, `paper.py`, `planner.py`, `risk.py`, `sizing.py`, `entry.py`, `book_sizing.py`, `defensive.py`, `tranches.py`, `fill_log.py` | PLANNED |
| P0.2 Correctness (split basis, residual momentum, early closes, correction shadow) | 1 / D | `share_basis.py`, `correction_shadow.py`, `levels_pit.py`, `fundamentals_asof.py`, `fundamentals_shadow.py`, `market_expectations.py`, `challenger.py`, `desk.py`, `baselines.py`, `technical.py`, `intraday.py`, `tape.py`, `record_status.py` | PLANNED |
| P2.1-P2.2 Structure reader and event engine (pure) | 1 / E | `structure.py`, `signals.py` | PLANNED |
| P0.4-P0.5 Execution instrumentation and prechecks | 1 / F | `alpaca_trading.py`, `execution_quality.py`, `market_execution_clock.py` | PLANNED |
| P3 Crash-switch research (long histories) | 1 / G | `risk_state.py`, `market_risk_state_study.py` | PLANNED |
| P2.3 Intraday funded ledger | 2 / H | `intraday_ledger.py` | PLANNED |
| Phase 1 arm runs (registered family, gate H / H-E) | 2 | gate files, research notes | PLANNED |
| Phase 2 outcome-free census, then one frozen run per rule family | 2 | gate files, research notes | PLANNED |
| P2.4 Live wiring (balancer, executor, in-session order class, nightly events, personal board) | 3 / serial | `market_balancer.py`, `market_daily.py`, `market_signal_executor.py`, `decision_view.py`, `DeskPanel.tsx` | PLANNED |
| Fidelity shadow → paper switch `/4`, `/5` | 4 | — | PLANNED |
| Learning-layer design (supervised / deep / RL research, then choice) | 1b / 3 research agents | design notes only | IN PROGRESS |
| Pilot P1 (13 dashboard names + SPY/QQQ/SMH/IGV): SIP data, learned models trained before 2026-06-01, decision audit 2026-06..09 | 2 | — | PLANNED |
| Full universe (only if the pilot meets its criteria) | 2+ | — | PLANNED |

## Parameter provenance

Every number the design uses, and where it came from. "Default" means chosen
round and frozen before any outcome is seen; it is not a measurement.

| Parameter | Value | Provenance |
|---|---|---|
| Crash-switch insurance budget | ≤ 1.5 CAGR/yr at median offset, 25 bp | Operator decision, 2026-09-25 |
| Risk-off destinations | QQQ trend break → cash (SWVXX modelled as cash + dated T-bill yield); volatile-only break → SPY; never QQQ | Operator decision 2026-09-25, on the A3q measurement (brake cut parked in QQQ kept return, gave back the drawdown protection; claude-review 2026-09-23 run5) |
| Hold limit | 20% of equity, trimmed at the next bar whenever breached | Operator decision 2026-09-25; DELL reached 31.6% under the green-day skip (fixed-strategy-attribution 2026-09-25) |
| Engine decision cadence | every completed 15-minute bar 09:45-15:45, plus the nightly plan | Operator decision 2026-09-25 ("the max gain for that day can be reached at any point") |
| Closing-auction cutoff | orders submitted before 15:50 ET | Alpaca rule (cls rejected 15:50-19:00); inherited, not a choice |
| QQQ brake | 200 sessions, 0.97 / 1.02, scale 0.5 | Inherited and frozen (trend_brake.py:19-21, 2026-09-23); not retuned |
| Volatile basket vote | risk_off_path at 100/150/200 on equal-weight SMH+IGV | Default (ensemble of lookbacks instead of one tuned value) |
| Breakout trigger | provisional band z ≥ 1.10 | Inherited from /3 (paper.py:160), frozen |
| Structure-state thresholds | round values listed in Phase 2 | Default, frozen before the census |
| Event floor / IEX-SIP agreement floor | ≥ 200 dev events; ≥ 90% agreement (live disable < 95%) | Default |
| Costs | 10 bp and 25 bp per side; 0 bp midpoint row as a target | Inherited repo convention (nested study, neural study) |
| Reset offsets | all 20 | Mechanical (every phase of a 20-session clock) |
| Choosing window | 2016-01-04..2023-12-29; 2024-2026 reported only | Roadmap rule "no tuning on 2024-2026"; intraday rules primary 2016-2020 (2019-20 partly seen via the IEX cache), 2016-2018 sensitivity |
| Gate H | median Δ > 0 at 10 and 25 bp; ≥ 15/20 offsets at 25 bp; ≥ EW book; DSR ≥ 0.95, SPA p < 0.05, PBO < 0.2 | Default, from the methodology survey (Bailey & López de Prado; Hansen) |
| Gate H-E | offsets + non-inferiority −0.5 CAGR | Default, operator-chosen adoption path 2026-09-25 |
| Fidelity shadow | 4-6 weeks; ≥ 95% order agreement; ≤ 5 bp/day tracking; zero negative cash; ≥ 10 fills per new order class | Operator decision (duration) 2026-09-25; thresholds default |


## Learning layer, pilot first, and the decision audit (added 2026-09-26)

**Operator direction (2026-09-26):** "develop this intelligently not rule based
or hard coded. Maybe ML, DL, RL ... whatever works best"; "are you going to
backtest it on 2026 recent weeks of data and then verify that the decisions
were right?"; "test it with a few tickers that the dashboard uses first then
test all if it looks promising".

- **Learned decisions, rules as the baseline.** Selection, entry, add,
  profit-taking/exit and risk-off are decided by learned models behind two
  protocols: `DecisionModel` in `signals.py`, and `RiskModel` in
  `risk_state.py`. The frozen rules become `RuleBaselineModel` and the
  frozen brake. Each learned model must beat its baseline in the harness, and
  the baseline is also the fallback when a model's inputs are unavailable.
- **Fixed constraints are not learned.** The operator's limits stay fixed:
  the 20% hold limit, no leverage, and anti-overtrading (one action per name
  per episode, a cooldown, no same-day reversal, a daily cap).
- **Which learner wins is decided by evidence.** Three designs are in
  research: supervised gradient-boosted trees with meta-labelling, deep
  sequence models on 15-minute bars, and reinforcement learning for position
  management. Each is judged on the same data, the same costs and the same
  gates. Every model trains on the same feature code the live engine runs
  (training/serving parity).
- **Pilot universe P1, frozen 2026-09-26 before any result.**
  - The tickers the dashboard uses on 2026-09-25: book targets NVDA, NTAP,
    FTNT, SNOW, MDB, HPE, LITE, SNDK, AAOI; paper holdings ANET and SMCI
    (plus the overlapping names); and the operator's focus names CRWV and
    IREN. That makes 13 names.
  - The benchmarks and baskets: SPY, QQQ, SMH and IGV.
  - Caveat: these names are today's grades and holdings, so the pilot tests
    timing, exits and risk decisions on names already chosen. It says nothing
    about selection skill. The pilot is a smoke test and a first read, not
    proof.
- **Decision audit on recent weeks.**
  - Models train strictly before 2026-06-01, then the engine is replayed bar by
    bar over 2026-06-01..2026-09-25.
  - For every decision it logs what it did and why (features and scores), and
    its fill.
  - Each decision is graded at +1 day, +5 days and +20 days against: not
    acting, simply holding, the incumbent `/3` decision on the same name, and
    buy-and-hold SPY and QQQ.
  - The audit is also run per decision type: entries, adds, trims or profit
    taking, exits, and risk-off.
  - 2026 has already been examined by earlier studies, so it is graded and
    never tuned on.
  - The truly unseen test is every session from now on, graded the same way
    each night in the forward shadow.
- **Going from the pilot to all names.** These criteria were written before
  the pilot runs. The full universe is run only if all of them hold:
  1. The data acceptance passes for all P1 names, and causality and
     live/replay parity tests are green.
  2. In the decision audit, each learned decision type has a mean graded
     outcome at or above both "no action" and the rule baseline on the same
     names at +5 days and +20 days.
  3. No single name supplies more than half of the gain.
  4. The funded replay on P1 over 2016-2023 (dev) is not worse than the rule
     baseline at 25 bp.
  If any criterion fails, the result is recorded as "not promising yet" and
  the design is revised without retuning on the audited weeks.

## The approved plan

The plan as approved on 2026-09-25, kept verbatim so later changes are visible as diffs.

### Context

- **What you asked for.** Review the trading code, research strategies, and plan (not yet build) improvements that raise total return over buy-and-hold SPY and QQQ. The two levers you named are:
  - choosing the right stocks, like a portfolio balancer;
  - timing entries and exits on 15-minute bars, like an HFT engine at a slower timescale.
- **How this plan was built.**
  - 10 read-only agents mapped the code and the research record: 140 past experiments, and every constant in the live policy `cash-bounded-breakout-rotation/3`.
  - 5 designers each drafted an approach, and an adversarial critic checked each draft against the code.
  - 4 spec agents wrote implementation-ready specs.
  - Code was checked at HEAD `990fa981`.
- **The goal, restated with your clarifications.**
  - Buy volatile names when they meet the conditions we develop, reading daily and weekly structure together with how the 15-minute candles build the daily candle.
  - Take profits and exit on the same kind of structure read.
  - When a crash is expected, step aside into cash or SWVXX (on a broad break) or SPY (when only the volatile names break down).
  - SPY and QQQ are otherwise only benchmarks, never a parking place for idle cash.
- **What the evidence says, honestly.** All of it is in-sample on a universe picked with hindsight; treat every number as a screen, not proof.
  - Returns come from three things:
    - which volatile names are held: about 19 points a year of the lead comes from hindsight in picking the universe;
    - how fully the account is invested: it is only 72-76% deployed today (`sizing.py:296-299`, `regime.py:49,72`, `paper.py:639-648`);
    - a few big winners: SNDK, DELL, LITE, MU and NVDA produced 67% of the gain.
  - Earlier intraday timing, confirmation entries, stops and price exits all measured at zero or negative.
  - The 15-minute engine is therefore built for three things: deterministic, structure-based entries, trims and exits that fire on any completed bar; no repeated or overtrading signals; and measured fill costs. It is not expected to be a big source of alpha on its own.

### Decisions you have made

- **Risk.** Total return first, with no leverage. Drawdown is reported but never blocks a change.
- **Risk-off destination.** A broad QQQ trend break moves money to cash or SWVXX. SWVXX is modelled as cash earning the dated T-bill yield, and is never ordered, because Alpaca cannot trade it. A breakdown in the volatile names alone moves money to SPY. QQQ is never a destination.
- **Insurance budget.** The crash switch may cost at most 1.5 CAGR points a year, measured at the median offset and 25 bp. If it costs more, it stays a dashboard warning only.
- **15-minute engine.** It trades at any completed bar it sees fit, for entries, adds, trims and exits. There is no standalone intraday sleeve and no leverage.
- **One engine for the paper account and your board.** Both show and act on identical Buy/Add/Trim/Exit signals, because you place real trades from the personal board. This replaces the 2026-09-22 rule that kept the paper account and your personal instructions separate; that change gets recorded in the roadmap.
- **Profit-taking.**
  - A hard 20% hold limit, trimmed back whenever it is breached.
  - Structure-based profit-taking checked on every completed bar, not only at 15:45.
  - Whether the green-day skip is retired is decided after the tests.
- **Data.** Free delayed-SIP consolidated history is approved. There is no paid real-time plan.
- **Adoption.** A change must pass a historical gate written before any results are seen. It then runs a 4-6 week forward shadow that checks only whether its fills match the simulation. Then it switches in the paper account, with `/3` kept running as a shadow. Nothing is deployed unless you ask.
- **Workflow.** All work goes on a branch in a separate worktree, never on `main`, because another agent pushes to `main`. Parallel agents move the work faster.

### Phase 0: foundation (week 1, runs in parallel)

- **P0.1 One evaluation harness, its statistics, and a trials registry.** Built as new files:
  - `backend/market/candidate_bench.py`, `candidate_stats.py`, `candidate_gate.py` and `trials_registry.py`;
  - `backend/cli/market_candidate_bench.py`.
  - Every candidate runs at all 20 reset offsets and at 10 and 25 bp, against these controls:
    - the incumbent `/3`, reproducing `curve_block` byte for byte;
    - a calendar-only control;
    - the equal-weight book, which is the hurdle for survivorship;
    - funded SPY and QQQ via `benchmarks.load_benchmark`;
    - QQQ matched to the candidate's exposure, and QQQ matched to its beta (both diagnostics only).
  - Cash is reported in two columns: zero yield, which is the score of record, and "SWVXX-as-cash" at the ^IRX/DTB3 rate.
  - Statistics, in NumPy only: stationary block bootstrap, PSR/DSR/MinTRL, Hansen SPA/StepM and CSCV PBO. A single `hac_t` replaces the four duplicate copies.
  - A gate file is hashed and committed before each run, and a rerun of a committed gate is refused.
  - Reuses `strategy_bench`, `neural_study_metrics`, `entry_pilot.paired_interval` and `research_journal`.
- **P0.2 Correctness fixes.**
  - **(a) Split look-ahead in historical market cap.** `levels_pit.py:186` divides pre-split cap by the split ratio (true cap / ratio), which flatters the value and expectations-gap history.
    - A new `share_basis.py` handles spin-offs encoded as splits.
    - The fix runs one week as a record shadow before it switches.
  - **(b) Dead simulator hooks** under `live_midcycle` (`simulate.py:1193-1195`) must raise an error instead of doing nothing silently.
  - **(c) Residual momentum for new listings** (`baselines.py:161`) must use known returns only, instead of treating pre-listing days as zero.
  - **(d) FOMC-freeze parity.** The simulator only caps buys during an FOMC cycle, while live stops all trading. Add an option that reproduces live.
  - **(e) Policy provenance** goes into the nightly record.
  - **(f) Early closes** must be handled in `intraday.py`, `tape.py`, `record_status.py` and `execution_quality.py`.
- **P0.3 SIP 15-minute history.**
  - `alpaca.fetch_bars` gains `feed`, `adjustment`, `timeframe` and multi-symbol parameters. The defaults keep the live IEX request byte-identical.
  - A new store `bars_15m_sip` is kept on a raw basis, with provenance. It must be raw because `adjustment=all` cannot support appends: it rescales history, which is what caused the AVGO ~10x error.
  - An acceptance gate reconciles the SIP data against the daily store.
  - The NYSE calendar gains 2016-2018 sessions and early closes.
  - A nightly append job keeps the store current.
  - Coverage: the 94 book names plus SPY, QQQ, SMH and IGV. That is about 1,900 requests for the 15-minute history and about 5,600 for the 1-minute fill windows.
  - Do not touch `live_quotes.py`, `market_pick_audit.py` or `timing_research.py`, which are SHA-pinned.
- **P0.4 Execution instrumentation.**
  - Parse and journal the account's `buying_power`, `multiplier` and pattern-day-trader status from the existing account call.
  - Upgrade `execution_quality` to v3: fill cost against the SIP first print, official open, 15:45 bar and official close, split by gap bucket, for both buys and sells.
- **P0.5 Zero-cost prechecks** (new file `backend/cli/market_execution_clock.py`). These decide which later branches are worth building:
  - the actual idle share of the book, split by cause;
  - buy notional per order type, and the overnight return of each type;
  - the oracle upper bound for A/A+ breakout entries;
  - how often more than 9 names are A/A+;
  - the existing `trend_brake`, rerun on real grades at all 20 offsets;
  - event counts per structure rule.

### Phase 1: deploy more of the account into qualifying volatile names (weeks 2-4)

- **Leftover cash stays in cash.** Research credits it with yield; it never goes to SPY or QQQ.
- **Each arm is registered once and must pass gate H.** All arms are expressed through `simulate.run` options whose defaults reproduce today's curve byte for byte (spec `simulator-api`). New files: `book_sizing.py`, `defensive.py`, `tranches.py`, `fill_log.py`.
- **P1.1 Exposure.**
  - D1 removes the 0.30 book-volatility target.
  - H also sets the hype-phase 0.75 multiplier to 1.
  - Tightening keeps its 0.75 and its tilt.
  - INFERRED: +1 to +3 CAGR, with drawdowns 5-8 points deeper.
- **P1.2 Breadth.** D2 holds capped equal weight across every A/A+ name, up to 20 names at 10% each. It runs only if the P0.5 precheck shows enough names are qualifying.
- **P1.3 Profit-taking at portfolio level, and reset hygiene.**
  - A rank buffer: a held name stays while it ranks inside the top 2K.
  - The 20% hold limit, trimmed on a new `green_day_exempt` path.
  - Four tranches offset by 5 sessions, which cuts the 5.7-point spread across start days.
- **P1.4 Faster redeployment.**
  - Rotation proceeds go to the highest-ranked A/A+ names below target, instead of pro rata to current holdings.
  - Deferred buys stay alive for up to 5 sessions.
- **P1.5 Selection arms.**
  - Value keeps its vote but loses its veto.
  - The rotation-tie fix.
  - 12-1 momentum as one rank inside the conviction sum.
  - The expected verdict is "insufficient evidence". ML rankers stay closed until the harness scores the long-only top-K objective.

### Phase 2: the unified 15-minute signal engine `desk-signals/1` (weeks 2-6)

- **P2.1 Structure reader** (new file `backend/agents/trading/desk/structure.py`).
  - It uses completed, contiguous bars only; any gap returns UNAVAILABLE.
  - It builds the developing daily candle from those bars (`live_technical.with_live_row`).
  - It reads context from night t-1: grades, levels (`levels.py`), weekly and daily trend, and daily EMAs.
  - Facts it records:
    - "holding the 9": how many of the last 4 bars closed above the 15-minute EMA9;
    - the 15-minute EMA21;
    - session VWAP;
    - position within the day's range;
    - wicks and rejections;
    - relative volume against the same 15-minute slot's history;
    - gap context.
  - It returns one state per bar: ACCEPT, FAILED_HIGH, BREAK, HOLD_LEVEL, EXTENDED or NEUTRAL. Thresholds are round numbers and frozen.
  - Reward-to-risk and swing structure are shown for display and used in sizing only, because they measured as inverted or null.
- **P2.2 Event engine** (new file `backend/agents/trading/desk/signals.py`, pure logic). It runs on every completed bar from 09:45 to 15:45 and also takes the nightly plan: resets, downgrade rotations and deferred buys.
  - Each event carries:
    - `signal_id`, which identifies the episode;
    - an action: BUY, ADD, TRIM, EXIT or WATCH;
    - the change in target weight as a percent of equity;
    - a structural reason in words;
    - a reference price and a midpoint target (a target only, not a claimed fill);
    - `valid_until`;
    - the rule version;
    - whether the rule is validated.
  - Rules against overtrading:
    - one action per name per episode;
    - a cooldown in bars after any action;
    - no same-day reversal, except for BREAK or the hold limit;
    - a cap on actions per day.
  - **Entries.**
    - An A/A+ name whose provisional band z is at least 1.10 on the developing daily candle, in state ACCEPT and not FAILED_HIGH, buys at the next bar.
    - If it fires on the 15:45 bar, it buys in the closing auction instead.
    - A FAILED_HIGH veto skips the entry for one session.
    - Optionally, a HOLD_LEVEL pullback add on held names, which must be run with an exposure-matched control.
  - **Profit-taking and exits, checked on every completed bar.**
    - The day's high is only known after the fact, so rules react only to completed bars.
    - Hold limit: a holding above 20% is trimmed at the next bar.
    - Blow-off trim: when the name is extremely extended and the 15-minute read is FAILED_HIGH or shows rejection, trim 1/3, once per episode.
    - BREAK: sell half on a volume-confirmed break below support. Re-entry is allowed only after a close back above the level.
    - Downgrade rotation stays nightly.
    - Sells that aren't urgent default to the closing auction, which measured 24 bp better than the open.
    - A structure hold of queued trims replaces the green-day coin flip. It is judged against no skip, a one-session unconditional deferral and random skips at the same rate.
- **P2.3 Intraday funded ledger** (new file `backend/market/intraday_ledger.py`, extending `intraday_evaluation.evaluate`).
  - Runs on SIP 15-minute bars over 2016-2023.
  - Fills at the next bar's open, plus a half-spread taken from the 1-minute SIP windows, plus one bar of latency. Closing-auction orders fill at the official close.
  - Also models missed fills, whole shares, cash limits and dividends.
  - A per-order journal pairs each order against the incumbent's clock.
- **P2.4 Live wiring. This is the only work that touches the hot files, so it runs one agent at a time.**
  - `market_balancer.py`:
    - start 75 s after each quarter-hour;
    - fetch all symbols in one request;
    - degrade per name, not per candle;
    - run the engine on each tick;
    - log parity for the green-day rule.
  - New `backend/cli/market_signal_executor.py`, modelled on `market_event_recovery`:
    - an activation hash, reconciliation under the `paper.transaction` lock, and a kill switch;
    - it submits the engine's events during the session as a marketable limit (midpoint plus a cap) that falls back to market, or as a closing-auction order before 15:50.
  - `market_daily._submit` (`:428-434`) gains one narrow in-session order class. Every other order keeps the market-open refusal.
  - The nightly writes its plan into the same event stream.
  - Only validated rules trade. Rules not yet validated show as "not validated" and never trade.
  - Your personal board:
    - it reads the same event stream through a presentation layer over `decision_view`;
    - sizes are shown as a percent of your own equity;
    - a new "order placed" input stops repeated Buys (`DeskPanel.tsx`; today the frontend never sends `pending_buys`).
  - Live data: live decisions run on real-time IEX bars. Volume features compare IEX against IEX history. Every day, the decisions are compared next day with a replay on SIP bars, and a rule whose agreement falls below 95% is disabled.
- **P2.5 Execution clock.**
  - Same-auction swaps: rotation buys go out as closing-auction orders funded by the same auction's sells. Only if P0.4 shows the account has margin.
  - Gap handling: buys that gap up at least 2% are recorded only as counterfactual fills, compared with an unconditional delay to 10:00 on 2016-2020. It is built as a live rule only if t ≥ 2.
- **How the engine is judged.**
  - Each order is compared with the incumbent's clock.
  - At portfolio level it must pass gate H-E.
  - Controls: unconditional same-bar entry; the same notional held overnight in QQQ or the equal-weight book; a random veto or trim at the same rate; the X2-U and X2-R exit controls; and an off-book replication, because a survivor book makes holding always look best.
  - Any rule with fewer than 200 events in the development window, or less than 90% agreement between IEX and SIP decisions, is dropped before outcomes are looked at.
  - Windows: 2016-2020 is primary (2019-2020 was partly seen through the IEX cache), 2016-2018 is a sensitivity check, and 2021-2026 is reported as already examined.

### Phase 3: crash-avoidance switch (research in weeks 1-3; trades only if it passes)

- **Precheck.** Rerun the frozen QQQ 200-day brake (`trend_brake.py:19-21`, bands 0.97/1.02) on the adopted book at all 20 offsets, in both cash columns.
- **`risk_state.py`**, with three states:
  - M, the frozen QQQ brake;
  - V, a majority vote of the same brake over lookbacks of 100, 150 and 200 days on an equal-weight SMH+IGV basket;
  - T, tightening, handled as today.
  - Scale 0.5, combined by taking the minimum, and re-entry only at the upper band.
  - From day one it is an advisory banner in the record and on both dashboards.
- **Destinations.**
  - M → cash, credited as SWVXX (paper holds plain cash).
  - V without M → SPY, held as a separate sleeve, never in `book.shares`.
  - QQQ is never a destination.
- **Long-history validation** on QQQ from 1999, SPY from 1993, SMH and IGV, the French market series from 1926, and DTB3, at 25 bp.
  - Gate: CAGR no more than 0.5 below always-invested, and max drawdown at least 10 points smaller.
  - Blocks of at least 250 sessions, and an episode table.
  - Book gate: a cost of at most 1.5 CAGR.
- **FOMC overlay.** It stays frozen. The rule that the FOMC cut is "subsumed while risk-off", which prevents a double cut, is enabled only if the switch ever trades, and it needs a version bump and your approval.

### The gates

- **Gate H, for changes that claim more return:**
  - the median-offset improvement is above 0 at both 10 and 25 bp;
  - it is positive in at least 15 of 20 offsets at 25 bp;
  - it beats the equal-weight book;
  - DSR ≥ 0.95, SPA p < 0.05 and PBO < 0.2, with trials counted across the repo.
- **Gate H-E, for execution and hygiene changes:** the same offset tests, with a non-inferiority margin of −0.5 CAGR. DSR and SPA are reported but not required.
- **Windows and baselines.** Candidates are chosen on 2016-2023 only, and 2024-2026 is only reported. A failed arm is "insufficient evidence" and is never retuned. Each step is judged against the policy adopted at the previous step.
- **Fidelity shadow, 4-6 weeks.** It runs on its own dry-run ledger and passes when:
  - order-level agreement with a replay of the simulator is at least 95%;
  - tracking difference is at most 5 bp a day;
  - there are zero sessions with negative cash;
  - each new order class has at least 10 fills.
- **Release trains.** `/4` carries what passes in Phase 1, `/5` carries the engine, and the crash switch trades only if it passes. Each switches the paper account only on your word.

### Doing it fast: branch, worktrees and parallel agents

- **Wave 0 (me, half a day).**
  - Create a worktree at `../anios-trading-volatile-15m` on branch `trading/volatile-book-15m`, cut from `origin/main`.
  - Commit `docs/research/volatile-book-15m-design-2026-09-26.md`, which holds the full design, the specs and your decisions, plus protocol P, `docs/research/gates/TEMPLATE.gate.json` and the legacy trial count.
  - Two fixes belong on `main` because the nightly pulls `main`. They sit on `trading/nightly-fixes`, merged into the feature branch; per the operator (2026-09-26) nothing is merged into `main` until the whole branch is proven:
    - the `opportunity_shadow` migration row, due by Mon 2026-09-28 19:30 ET, or the frozen ML ledger stops recording;
    - a New York date for the nightly `asof`, due before 2026-11-01, when the clocks change to EST.
- **Wave 1 (7 agents in parallel).** Each works in its own worktree on a sub-branch and owns disjoint files:
  - **A, SIP data:** `alpaca.py` (all of it, including `sessions()`), new `intraday_sip.py`, `market_intraday.py`, the 2016-2018 calendar JSON, and the nightly script.
  - **B, harness:** the `candidate_*` modules, `trials_registry.py` and its CLI, `macro.py` (^IRX), and `allocation_controls.py` (the `cash_yield` keyword).
  - **C, simulator API:** `simulate.py`, `paper.py`, `planner.py`, `risk.py`, `sizing.py` and `entry.py`, plus new `book_sizing.py`, `defensive.py`, `tranches.py` and `fill_log.py`. Covers cash yield, the dead-hook refusals and FOMC parity.
  - **D, correctness:** new `share_basis.py` and `correction_shadow.py`, plus `levels_pit.py`, `fundamentals_asof.py`, `fundamentals_shadow.py`, `market_expectations.py`, `challenger.py`, `desk.py`, `baselines.py`, `technical.py`, `intraday.py`, `tape.py` and `record_status.py`.
  - **E, structure and events:** new `structure.py` and `signals.py`, pure logic driven by fixtures, against A's loader interface.
  - **F, instrumentation:** `alpaca_trading.py` (account fields), `execution_quality.py` v3, and new `market_execution_clock.py`.
  - **G, crash-switch research:** new `risk_state.py` and `market_risk_state_study.py`.
- **Wave 2 (research runs).**
  - H builds `intraday_ledger.py`, which needs A and E.
  - The Phase 1 arms run through B and C on the Spark probe clone (`/tmp/anios-probe`), never during a deploy.
  - Then outcome-free event counts, and then one frozen run of each Phase 2 rule family.
- **Wave 3 (live wiring, one agent at a time).**
  - `market_balancer.py`, `market_daily.py` (the narrow in-session order class, emitting events, provenance, the corrections block), the new `market_signal_executor.py`, `decision_view.py` and `DeskPanel.tsx`.
  - Frontend end-to-end tests, and the diagrams.
- **Integration (me).**
  - Merge the sub-branches into `trading/volatile-book-15m` in the order A, B, C, D, E, F, G, then H.
  - Merge `origin/main` into the feature branch regularly, with no rebase and no force push; the pre-push hook refuses non-fast-forward pushes.
  - After every merge, run `scripts/gate.sh --unit` in the probe clone.

### Not building

- An index residual sleeve for idle cash.
- Leverage or leveraged ETFs.
- Standalone intraday sleeves: Gao momentum, noise-area, or opening-range breakout.
- The funded vol/vol_trend allocation path.
- HRP, minimum-variance or mean-variance optimisers, RL sizing, or Kelly sizing.
- Confirmation or pullback-wait entries, and learned timing models.
- Fixed profit targets and price or trailing stops.
- VWAP/TWAP slicing, paid real-time SIP, or 5-minute bars.
- Retunes of anything frozen: band 1.10, the brake bands, the FOMC gate, the reclaim comparison, the rank blend, or the 10-session ML spec.
- Edits to the SHA-pinned files.
- Simulating SWVXX as an instrument that fills instantly.

### Defaults I will use unless you say otherwise

- The paper account holds plain cash. Research reports a T-bill column alongside, but zero yield stays the score of record.
- Nightly pyramiding adds stay as they are in the baseline. "One entry per breakout episode" is tested as its own arm.
- Rules that are not yet validated show on both dashboards labelled "not validated", and never trade.
- The free public data pulls are approved within these request caps: DTB3/^IRX, SMH/IGV, the long index histories, and the 1-minute SIP fill windows. The S&P-member SIP runs are deferred.
- The split fix runs one week as a record shadow, then switches.
- A roadmap amendment records your adoption path and the paper/personal coupling.

### Verification

- **Code checks.**
  - Every item's unit tests pass, and every new function carries its required comment.
  - The simulator defaults are byte-identical, checked by reproducing `curve_block` and `load_benchmark` exactly.
  - A diff guard confirms that the frozen and SHA-pinned files are unchanged.
  - `scripts/gate.sh --unit` passes in the Spark probe clone.
- **Harness acceptance.**
  - The incumbent scored against itself gives exactly 0.
  - The DSR worked example returns 0.900 at N = 100.
  - SPA holds its test size on null panels.
- **Data acceptance.** An outcome-free SIP report showing at least 98% session coverage, SPY and QQQ complete, and the scale-gate pass rates.
- **Causality and parity.**
  - A later bar never changes an earlier structure snapshot.
  - The live and replay paths give identical output on archived bars.
  - The daily IEX-versus-SIP decision agreement is at least 95%.
- **Dashboard.** Browser end-to-end tests cover event rows, the "order placed" suppression and the risk banner.
- **Adoption.**
  - A gate report states every criterion as VERIFIED, FAILED or UNVERIFIED, with the numbers.
  - The 4-6 week fidelity shadow must meet its criteria before any paper switch, and the switch happens only on your word.

