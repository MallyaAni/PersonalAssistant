# Design panel synthesis (2026-09-25)

Five designs (balancer, 15-minute execution, evidence-first, volatile deployment + risk-off, 15-minute structure entries/exits), each adversarially critiqued against the code, merged into one plan. **Superseded where it conflicts with the approved plan** in [TRADING_VOLATILE_BOOK_ARCHITECTURE.md](../../TRADING_VOLATILE_BOOK_ARCHITECTURE.md): the engine now trades at any completed bar (not only 15:46), and the paper account and personal board share one signal stream.

## Executive summary

- **Where the edge comes from.** Nearly all of the book's measured lead over SPY and QQQ comes from three things:
  - which volatile names are held: about 19 points a year of the lead is hindsight in choosing the universe;
  - how fully the account is deployed in them;
  - five winners.
  Intraday timing contributes almost nothing. Every number is in-sample on a survivor universe. The plan therefore aims to be deployed well in qualifying volatile names and to execute and exit cleanly. It does not chase alpha from timing.
- **Phase 0 is kept small and only unblocks later phases.** It has five parts:
  - one harness that scores every candidate on all 20 reset offsets, at 10 and 25 bp, against the equal-weight book and funded SPY and QQQ, with a yield-credited cash column;
  - the statistics, and a trials registry so DSR and SPA use a counted number of trials;
  - four correctness fixes: the split look-ahead at levels_pit.py:186, the simulator hooks that silently do nothing under the live policy, the FOMC-freeze parity gap, and provenance in the nightly record;
  - qualified delayed-SIP 15-minute history, including SPY and QQQ;
  - recorded buying power and margin, SIP-referenced fill-cost analysis on both buys and sells, and cheap checks that decide whether each later branch is worth building.
- **Phase 1 deploys more of the account into qualifying volatile names.** It tests, each as one registered arm:
  - removing the 0.30 book-volatility target;
  - removing the hype-phase 0.75 multiplier (tightening keeps both its 0.75 and its tilt);
  - capped equal weight across all A/A+ names;
  - a rank buffer plus a hold limit that trims at the close and cannot be cancelled;
  - tranches, measured as four real offset sub-books;
  - sending sale money by rank instead of pro rata, and keeping deferred buys alive longer.
  Leftover cash stays in cash, credited with a T-bill yield in research. SPY and QQQ never absorb it.
- **Phase 2 is the 15-minute chart-structure engine.** A causal reader (structure-read/1) turns completed SIP bars, checked against daily and weekly structure, into five states: ACCEPT, FAILED_HIGH, BREAK, HOLD_LEVEL and NEUTRAL. It drives:
  - entries: buying at the same day's close, or vetoing a failed high. It never waits for a later confirmation, which is the pattern that lost;
  - exits: a partial rotation out of a name only on a volume-confirmed daily break;
  - profit-taking: a 15:45 structure read decides whether a queued trim stands. This replaces the green-day coin flip;
  - execution: same-auction swaps placed from the nightly plan, and gap handling measured as counterfactual fills before any order change;
  - the dashboard: Buy, Add, Trim and Exit, each carrying an episode id so it never repeats.
- **Prior failures are addressed rule by rule.** Every rule differs from what was already measured to lose: confirmation entries, waiting, price stops, partial trims, band exits and the wick rationale. Each has a control designed to falsify it: unconditional close entry, a same-notional overnight position in QQQ or the equal-weight book, random veto or trim at a matched rate, a one-session unconditional deferral, and off-book replication. The expected verdict for most timing rules is "insufficient evidence", and that verdict is accepted as it stands, with no retune.
- **Phase 3 is the crash switch.** It uses the frozen QQQ 200-day brake plus an ensemble signal on a volatile-theme basket (SMH and IGV). Destinations are set in advance by mechanism:
  - a broad trend break moves the cut to cash, credited as SWVXX-like at a sourced T-bill yield;
  - a breakdown in the volatile names only moves it to SPY;
  - QQQ is never a destination, because in the A3q test (brake cut parked in QQQ) it gave back all of the drawdown protection.
  It first runs as an advisory dashboard state. It trades only if it passes long-history, total-return tests and costs no more than the insurance budget you set.
- **Expected effects (INFERRED).**
  - Phase 1 exposure levers: +1 to +3 CAGR in-sample, with drawdowns 5-8 points deeper.
  - Close-auction entries: about 0 to +0.1 CAGR. In the proxy, breakout names earned no extra overnight return beyond the book's average.
  - Same-auction swaps: +0.2 to +1 CAGR, only if the account's margin allows it.
  - Structure exits: 0 to +0.3 CAGR.
  - Crash switch: likely costs 1.7 to 7.4 CAGR for 2 to 11 points less drawdown, so it will probably stay advisory.
- **Adoption follows the path you chose.**
  - A predeclared historical gate, chosen on 2016-2023 with 2024-2026 reported only.
  - Then a 4-6 week dry-run shadow on its own simulated ledger, checking fill and execution fidelity only.
  - Then the paper account switches under a new policy version, with /3 kept running as a shadow with a kill switch.
  - Changes ship as release trains: /4 for balancer changes, /5 for the 15-minute engine, and the crash switch only if it passes. Nothing deploys unless you ask.
- **Not built:**
  - an index residual sleeve, leverage, or any standalone or falsification intraday sleeve;
  - the funded vol and vol_trend allocation path, covariance optimisers, or RL/Kelly sizing;
  - confirmation or pullback entries, stops, fixed profit targets, or a gated run-up trim;
  - VWAP/TWAP slicing or paid real-time data;
  - retunes of anything frozen, or edits to hash-pinned study files.
- **Decisions needed from you:**
  - the insurance budget for the crash switch, and its destination mapping;
  - cash in the paper account;
  - how strict the gate is for execution-only changes;
  - a narrow new class of orders placed at 15:46;
  - the hold-limit level, and whether the green-day skip is retired;
  - whether breakout adds repeat night after night;
  - dashboard behaviour;
  - the extra free data pulls;
  - how the split fix is rolled out;
  - amending the roadmap to match your adoption choice.

## Decisions it asked for

These decisions are needed before implementation starts. Each one has a proposed default.

1. **Insurance budget for the crash switch.** This is the most CAGR you will give up, at the median offset, 25 bp, with cash credited at the T-bill yield.
   - (a) 0: the switch must pay for itself.
   - (b) 1.5 points (default).
   - (c) 3 points.
   Above budget, or failing the long-history test, the switch stays a dashboard advisory only.
2. **Destination mapping.**
   - Default:
     - a broad QQQ trend break moves half the volatile book to cash (credited as SWVXX-like in research);
     - a breakdown in the volatile names only moves half to SPY;
     - QQQ is never a destination.
   - Alternatives:
     - always cash;
     - allow QQQ when only the volatile names break down;
     - move 100% to SPY in a volatile-only breakdown.
3. **Cash in the paper account.**
   - (a) Plain cash, with the research ledger crediting a T-bill yield (default).
   - (b) Hold SGOV or BIL in paper, with distributions accrued in the ledger.
   SWVXX is never ordered.
4. **Gate strictness.**
   - Changes that claim return (exposure, selection) need DSR ≥ 0.95, SPA p < 0.05 and PBO < 0.2, with trials counted.
   - Default for execution and hygiene changes (buffer, tranches, swaps, clock): they may adopt on offsets plus a non-inferiority margin of −0.5 CAGR, with DSR and SPA reported but not required. The alternative is to require DSR and SPA for everything, which will likely reject every timing change.
5. **Margin.** Approve deploying code that parses and journals the account's buying_power and multiplier. The nightly already fetches the account, so no new call is needed. If the account turns out to be a cash account, same-auction swaps are dropped.
6. **New 15:46 order class.** Allow MOC buys, MOC partial sells and trim cancels at 15:46-15:49, behind an activation hash and only for rules that pass. This narrowly reverses the market-open refusal in _submit. If declined, the 15-minute engine is dashboard-only, and green-day and structure holds stay measurement only.
7. **Profit-taking.**
   - Hold-limit level: 20% (default), 25%, or none.
   - Accept that run-up trims are shown as information only.
   - The green-day skip was your requested behaviour. Retiring it or replacing it with the structure hold (S2) is your decision after the tests.
8. **Repeat adds.** Keep /3's nightly pyramiding adds up to the 15% cap, or move to one entry per breakout episode. The second option changes /3 and would run as its own registered arm.
9. **Dashboard.**
   - Show intraday Watch states, with an optional labelled 'Buy at the close' setup.
   - For rules that have not passed: show them labelled 'not validated' (default), or hide them.
   - Keep the personal board on /3 until you confirm, or have it follow the paper switch.
   - Add an 'order placed' input so working orders stop repeat Buys.
   - Your broker's MOC cutoff decides whether a 15:30 snapshot leaves you enough time to act.
10. **Free data beyond the approved Alpaca SIP 15-minute bars.** Each needs a yes:
    - a T-bill series (FRED DTB3, or BIL/SGOV from Yahoo);
    - SMH and IGV added to the nightly refresh;
    - long total-return histories (QQQ, SPY, SMH, IGV, the French market series) for the Phase 3 validation;
    - 1-minute SIP fill windows for fill-cost analysis. The 15-minute bars suffice at lower precision.
    - one same-session SIP probe at 15:46.
11. **Split look-ahead fix.** Run it one week as a record shadow (default), or switch directly after reviewing the diff. It lowers the historical baseline that everything is judged against.
12. **Protocol.**
    - Choose on 2016-2023 and report 2024-2026 only.
    - Drop a structure rule before outcomes if it has fewer than 200 events or clock agreement below 85%.
    - Record a roadmap amendment replacing the season-long shadow with your adoption path (historical gate, then a 4-6 week fidelity shadow, then switch with /3 kept as a shadow).
13. **FOMC overlay.** It stays frozen and unchanged. The 'subsumed while risk-off' composition rule is enabled only if the crash switch ever trades, and it needs a version bump plus your approval.

# Plan: beat SPY and QQQ with the volatile-name book

**Status: read-only review; nothing has been built.** Code was checked at HEAD 990fa981. Every number is in-sample on a survivor, hindsight-picked universe unless it says otherwise. It is development evidence only, and anything marked INFERRED is an estimate.

## 0. Thesis in six lines

1. **Name choice dominates.** The equal-weight book returned 34.2%/yr against 15.6%/yr for off-book S&P names. That is about 19 points a year of name choice before any signal. SNDK, DELL, LITE, MU and NVDA produced 67% of /3's net gain.
2. **Deployment is the next lever.** /3 sets its targets below what it holds, for three reasons:
   - the 0.30 book-volatility target (sizing.py:296-299);
   - the 0.75 regime multiplier (regime.py:49,72; risk.py:189);
   - cash-bound funding: sells fill at the close and buys at the next open (paper.py:639-648).
   Every measured increase in exposure raised CAGR and deepened drawdown.
3. **Timing inside the day is near zero.**
   - The open is as good as any first-hour print.
   - Every confirmation entry lost to the open.
   - Every price exit and every stop lost to holding, and partial trims lost as well (commit 1f33108b).
   - In the proxy, breakout fires earn no extra overnight return beyond the same-night book mean: −2.0 bp, t −1.06, 2016-23.
4. **The one proven execution edge is selling at the close:** 24 bp better than the open, t −2.77.
5. **The 15-minute layer earns its place three ways:**
   - reading chart structure for entries and exits;
   - removing randomness (the green-day coin flip, repeated Buy signals);
   - measuring what fills actually cost.
   It is not a source of alpha by itself.
6. **The crash switch is insurance, not a return source.** In this sample every risk-off condition was followed by above-average returns.

## 1. Ground rules for every item

**Protocol P** is written and committed before any arm runs.

- **Windows.** The choosing window is 2016-01-04..2023-12-29. It has also been examined before, and is labelled as such. 2024-01..2026-09 and the full window are reported but never used to choose (roadmap: "no tuning on 2024-2026").
- **Offsets and costs.** All 20 reset offsets, at 10 and 25 bp. Also a 0 bp midpoint row, which is a target and not a claimed fill.
- **Cash columns.** Two columns side by side:
  - zero yield, the score of record for paper;
  - "SWVXX-as-cash": cash credited with a sourced, dated T-bill yield (FRED DTB3, or the adjusted return of BIL/SGOV). The ^IRX levels in px.npz are corrupt after 2021 and must never be reused.
- **Controls, all on identical sessions:**
  - the incumbent, reproducing curve_block exactly with `since=None` (market_daily.py:1260-1267);
  - the equal-weight book, the survivorship hurdle, run with every LIVE_POLICY flag off (a plain hold between 20-session resets);
  - equal weight over the A/A+ names;
  - funded SPY and QQQ via benchmarks.load_benchmark at 10 and 25 bp (benchmarks.py:133).
  Diagnostics only:
  - QQQ matched to the arm's exposure;
  - QQQ matched to its beta, computed after the fact because constant_exposure refuses a fraction above 1 (allocation_controls.py:124);
  - a non-adoptable row with idle cash parked in QQQ.
- **Statistics:**
  - paired Δ log growth against the baseline;
  - HAC t;
  - stationary-bootstrap CI;
  - PSR/DSR, with N = the family's declared historical floor plus its registered arms;
  - Hansen SPA and StepM across the family;
  - CSCV PBO.
- **Gate H, for arms that claim return:**
  1. Median-offset Δ > 0 at 10 and 25 bp.
  2. Positive in at least 15 of 20 offsets at 25 bp.
  3. At the median offset, CAGR ≥ the equal-weight book's, and candidate − EW is at least baseline − EW.
  4. DSR ≥ 0.95, SPA p < 0.05 when the family has 3 or more arms, and PBO < 0.2 for selection arms.
- **Gate H-E, for execution and hygiene arms that make no return claim:**
  - gate H items 1 and 3;
  - a non-inferiority margin of −0.5 CAGR on item 2;
  - DSR/SPA reported but not required. This needs your OK (Q3).
- **Always reported, never gated:** drawdown against SPY and QQQ, turnover, maximum weight, and deployed share.
- **Failures.** A failed arm is recorded as "insufficient evidence". It is never retuned on the same sessions. Frozen studies stay frozen: the reclaim comparison, the rank blend, the 10-session ML spec and the FOMC 6-meeting gate.
- **Baselines.** Each step's baseline is the policy adopted at the previous step, never the best-looking arm.
- **Compute.** About 500+ full walks. They run on Spark in the probe clone (/tmp/anios-probe), never during a deploy gate, with one cached report per regrade variant.
- **Code rules.** Every new function carries the required AGENTS.md comment. No prompts are added. If an LLM narrative ever reads the new structure facts, it needs a functional test in backend/tests/functional/.

## 2. Phase 0: foundation (about 2 weeks)

### P0.1 Evaluation harness, statistics and trials registry

**Changes**
- New CLI `backend/cli/market_policy_study.py`. It leaves market_strategy_bench.py untouched, because that CLI publishes strategy_bench.json.
- New `backend/market/balancer_candidates.py`: a frozen registry of named candidates (simulate.run kwargs, allocator, report transform), each fingerprinted.
- New `backend/market/selection_stats.py`, NumPy only:
  - hac_t, which replaces the four copies at market_snapback.py:117, market_bounce.py:203, market_earnings.py:179 and market_allocation_rl.py:285, after bit-equality tests;
  - a stationary bootstrap;
  - PSR/DSR/MinTRL, SPA/StepM and CSCV PBO.
- New `backend/market/trials.py` with the append-only registry `data/market/research/trials.jsonl`, using the os.link append pattern (opportunity_shadow.py:51-62).
- `data/market/trials_floor.json` holds a declared trial floor per family, each sourced from the ledger, for example:
  - execution: Study 1/2 cells, market_execution_rl schedules;
  - exits: 21 triggers, 56 dead-cat variants, 1f33108b trims;
  - brake/overlay: the 48 FOMC windows;
  - sizing: the band sweep, cadence runs, A1-A4.
- Research-only hooks in simulate.run:
  - pass `held` to allocators at simulate.py:1130;
  - a `cash_yield` path accrued before closing marks (:1105, :1120, :1261);
  - `sell_hold` to override the green-day test (:1239-1252).
  All defaults stay byte-identical.

**Reuses:** simulate.run/LIVE_POLICY, benchmarks.load_benchmark, allocation_controls.constant_exposure, neural_study_metrics.scorecard, entry_pilot.paired_interval, research_journal.

**Evaluation:** the harness must reproduce curve_block byte for byte and load_benchmark exactly. The DSR unit test must reproduce the published worked example (0.900 at N=100). SPA must hold its size on synthetic null panels. The incumbent against itself must give a difference of exactly 0. The EW-control convention must be reconciled in writing against the nested study's 43.70%.

**Expected effect:** none directly. It prevents false adoptions and makes start-offset luck visible (a 5.7-point spread, paper.py:63-66).

**Risk:** the trial count may be undercounted. The floor file is mandatory, and opencode and GPT studies count too.

**Status:** research only.

### P0.2 Correctness fixes that change the baseline or unblock later phases

(a) **Split look-ahead.** levels_pit.py:186 applies a split only when `seen < day <= days[t]`, while panel.close is already split-adjusted, so historical cap reads as true cap ÷ ratio. This affects NVDA, AVGO and others across their whole pre-split history.
- Fix: apply every split in the same partition that is later than `seen`.
- Tests: synthetic 10:1 fixtures and the WDC spin-off encoding.
- Leave frozen trailing_levels alone and give non-frozen consumers a split-aware sibling.
- It changes live expectations-gap training, so it runs one week as a record block (the fundamentals-correction precedent) before a switch.
- Every value, expectations-gap and /3 number is marked "superseded: pre-split-fix".

(b) **Dead hooks.** Under live_midcycle, simulate.py:1193-1195 overwrites the between-reset order, which makes several options silently inert: `trim`, `exits`, `dip`/DipRule, `band_dip_buy` and `trend_gated_exit`. They should raise when combined with live_midcycle, in the style of the refusal list at simulate.py:803-837.

(c) **New-listing residual momentum** (baselines.py:161). Mask only the rows before the first finite return; handle interior gaps with a minimum-known-count rule. This is historical-only today, so it is a class-A fix.

(d) **FOMC-freeze parity.** The simulator's event_paused only caps buys (simulate.py:1205-1213). Live hands the whole night to event_execution (market_daily.py:695-699), which stops rotation and entries and defers the reset. Add an option that reproduces live behaviour, and check it against the 09-11..09-17 paper journal.

(e) **Provenance.** Record paper.POLICY_VERSION, the LIVE_POLICY flags and a hash of constituents.csv in the record (market_daily.py:1024-1050). Fidelity replays need these.

**Status:** (a) is shadow then live; (b)-(e) are correctness changes deployed on your word.

**Expected effect:** the historical baseline will probably fall, by an unmeasured amount. The live effect is about zero.

### P0.3 Qualified delayed-SIP 15-minute data (approved)

**Changes**
- `alpaca.fetch_bars` (alpaca.py:140-172) gains:
  - `feed` and `adjustment` parameters;
  - datetime `start`/`end`, because the current `end=T23:59:59Z` would request the most recent 15 minutes, which the free plan refuses;
  - a comma-joined `symbols` list.
  Defaults keep the live IEX URL byte-identical.
- New kind `bars_15m_sip`, stored raw with metadata {feed, adjustment:"raw", fetched_at, request_sha}.
- `market_intraday` gains `--feed sip --adjustment raw --append`, and a loader that reads appended partitions.
- `qualify_sip()` in intraday_cache accepts a name-session only if it meets all of these:
  - it has contiguous regular bars, using calendar.session_close;
  - the SIP last close times the split factor is within 2% of the store's daily close;
  - the per-name median error is 0.25% or less.
  Failing sessions are counted and never patched.
- Extend the reviewed early-close calendar to 2016-2018, or start SIP-dependent work in 2019. The calendar JSONs are hashed into intraday_research's fingerprint, so declare the reset.
- Do NOT edit the SHA-pinned files market_pick_audit.py or timing_research.py.
- Symbols: 94 book names plus SPY, QQQ, SMH and IGV. About 1,700 requests, roughly 10 minutes, with a nightly append after 16:20 ET.

**Evaluation:** an outcome-free acceptance report covering coverage (at least 98% of sessions, SPY/QQQ complete), scale-gate pass rates, early closes and request counts. No returns are computed.

**Risk:** the entitlement is proven only on samples. A same-session read at 15:46 is unverified, so one probe runs before anything live depends on it.

### P0.4 Execution instrumentation (no new provider call class)

- Parse `multiplier` in alpaca_trading.Account (:40-46, :93-99). Journal `buying_power` and `multiplier` in the nightly record. The nightly already calls client.account().
- execution_quality v3 records, for both buys and sells: the SIP 09:30 first print against the official open, the 15:45 bar close, the official close, gap buckets, a CI on mean slippage, whole-share residuals, and counts of skipped and refused orders.
- The balancer logs each green-day decision with the IEX first-bar open, and next night the SIP and official open, to count parity disagreements.
- Turnover conversion: /3 trades about 13.65x gross a year, about 6.8x NAV in buys, so 10 bp of buy slippage costs about 0.7 CAGR.

**Status:** display and measurement only.

### P0.5 Zero-cost prechecks that decide which later branches get built

All of these run on the existing store and SimResult journals.

1. **Actual idle share of /3.** Taken from SimResult.invested, and split by cause: volatility target binding, hype 0.75, tightening 0.75, and cash-bound timing. The 24-28% figure predates the deferred leg; A1 averaged 82% invested.
2. **Buy notional by order type.** Entry, rotation redeploy, reset, and deferred retry. Also each type's overnight return (close t+1 → open t+2 for same-session-funded buys) measured against the same-night book mean and QQQ.
3. **Overnight return of A/A+ band fires,** measured against the same-night book mean and same-notional QQQ, at 20 offsets. This is the oracle upper bound E-UB for close-auction entries.
4. **How often more than 9 names are A/A+ at a reset,** and how many names get displaced. This decides whether P1.2 and the momentum ordering arm are more than no-ops.
5. **Existing simulate.run(trend_brake=True)** on real grades, 20 offsets, both cash columns (see P3.1).
6. **Daily-data event counts** for each Phase 2 structure rule, as an approximation.

**Stop rules, predeclared:**
- If E-UB is below +0.1 CAGR, or does not beat same-notional QQQ or the EW-book overnight, close the same-close entry branch for the paper account. The 15-minute structure reader still ships for the dashboard and for exits.
- If same-session-funded buy notional is below 0.5x NAV a year, drop same-auction swaps.

## 3. Phase 1: deployment into qualifying volatile names

The baseline is the incumbent on corrected inputs. The arms run in this order.

### P1.1 Exposure levers (gate H; balancer family)

**Changes:** SizingConfig (sizing.py:47-64) gains `target_volatility: float | None` (None skips :296-299), `weighting` and `max_names`. A research allocator passes a RiskBudget.

**Arms:**
- **D1:** incumbent selection with the volatility target removed. The tightening 0.75 and the inverse-vol-squared tilt (risk.py:189-191) are kept, because they have book-level support: Sharpe 1.47→1.65, drawdown −38.3→−34.6.
- **H:** D1 plus the hype multiplier set to 1.0. It has only basket-level evidence (regime.py:49).

**Leftover cash:** stays in cash, labelled `few_qualifiers` or `theme_cap`. Research credits it with yield. SPY/QQQ never absorb it, per your clarification.

**Entry funding:** must be declared before the run. When fully deployed, entries are funded first from leftover cash, then by same-auction trims of holdings above 1.25× target (P2.5). The entry cap stays ENTRY_NAME_CAP 0.15 (paper.py:167).

**Expected effect (INFERRED):** D1 +1 to +3 CAGR, with drawdown 5-8 points deeper (the 0.40 target measured −43% vs −35%, risk.py:42-47). H ranges from 0 to +1. Forward: extra exposure × the names' excess return over cash, not the hindsight 40%/yr.

**Risk:** deeper drawdowns. The 2025 drawdown already ran at 89.6% stock exposure.

**Status:** shadow, then paper switch in /4.

### P1.2 Breadth arm (one registered arm, low prior)

- **D2:** capped equal weight over every A/A+ name, up to 20 by conviction, name cap 10%, theme cap 40%, with the tightening tilt switched off so it stays equal-weighted.
- Evidence against it (in-sample): /3 made 59.2% against 43.7% for the equal-weight book, and momentum120 top-10 made 70.5% against 39.5%. Evidence for it: 1/N and Bessembinder's median-outcome argument.
- Run only if P0.5.4 shows material breadth. Expected effect: sign unknown. It will likely fail DSR.

### P1.3 Portfolio profit-taking and reset hygiene (gate H-E)

**Changes**
- **Rank buffer.** A held A/A+ name stays while it ranks inside the top 2K by conviction. It is applied inside desk_targets to the final targets after the multipliers. This is new logic: passing the existing `held` would compare account weights against pre-exposure targets.
- **Hold limit.**
  - A holding above 20% is trimmed to the band edge at the close. The level is Q6.
  - A new `PaperOrder.green_day_exempt` field keeps the trim on MOC. `priority` cannot be used: it routes to the next open (market_daily.py:437-452).
  - _green_day_skip_locked honours the new field.
  - simulate.py gets a matching per-name exemption mask.
  - A daily mid-cycle check lives in paper.midcycle_orders and simulate._live_midcycle.
- **Tranches.** Measured as the average of four offset sub-books (0/5/10/15). Not as speed 0.25: cadence 5 measured 29.7% against 31.6% for cadence 20.

**Evaluation:** gate H-E. Also:
- the spread across offsets must fall by at least 40% relative to real tranches;
- maximum weight must stay at or below the limit plus one session of drift;
- turnover must not exceed the baseline's.

**Expected effect (INFERRED):** median CAGR within ±1.5, turnover 20-40% lower, maximum weight held near 20%, and an in-sample cost from trimming extreme winners, which is reported.

**Risk:** it trims the winners that produced 67% of the gain. That is a deliberate concentration control, not a return claim.

**Status:** shadow, then /4.

### P1.4 Faster, rank-routed redeployment (gate H-E)

- `_rotation_orders(route='rank')` (paper.py:348-418) sends proceeds to the highest-conviction A/A+ names below target, within the cap, instead of pro rata to current holdings.
- Deferred buys persist while the name stays A/A+ and unblocked, up to 5 sessions, via `PaperState.deferred_age` (a dataclass default, so old state still loads).
- Both are mirrored in simulate._live_midcycle and _deferred_leg (simulate.py:116-218).
- Correction to earlier drafts: DELL's 31.6% came from drift plus skipped trims, not from pro rata routing, which is capped by `room` (paper.py:402).
- Expected effect: +0.3 to +1 CAGR (INFERRED).

### P1.5 Selection arms (gate H plus off-book replication; last, expected "insufficient evidence")

- **V: value leaves the veto, but still votes.** grading.py:267-273 gains `veto_analysts`. The earlier +2 to +4 CAGR was for switching off the whole veto, and was only +0.8 at matched volatility, so the prior is near zero.
- **Rot: rotation tie fix.** Each side's stance becomes sign(score) (regime.py:243 ties).
- **M: 12-1 momentum** added to summed conviction only, leaving grades and veto untouched. Run only if P0.5.4 is material.
- **ML rankers stay closed.** harness.evaluate_scores first gains a `long_top_k` / next-open mode, because it currently scores a long-short, beta-adjusted objective (harness.py:159-218).

## 4. Phase 2: the 15-minute chart-structure engine

### P2.1 Causal structure reader `structure-read/1`

**What it is:** a new module, `backend/agents/trading/desk/structure.py`. `snapshot(symbol, session, sip_bars, panel_t−1, record_t−1, as_of)` returns dated facts and one state.

**Inputs**
- Completed contiguous bars only (intraday_entry._completed_bars :209). Any gap returns UNAVAILABLE, and the incumbent rule applies.
- The provisional daily candle (live_quotes.quote_from_bars; live_technical.with_live_row, which uses the prior-row adjustment factor).
- The provisional band z and buy blocker (entry.bollinger_z; exit.evidence).
- The grade is simplified: night t−1's grade plus the provisional band and blocker. Agreement with the final 16:00 grade is measured.

**Your method, as facts**
- Location: support and resistance from levels.level_identity at t−1.
- Timeframe agreement: weekly and daily trend at t−1, read against the 15-minute EMA9/21 seeded over 3 sessions.
- Holding the 9: hold9, the number of the last 4 bars that closed above EMA9.
- Session VWAP on consolidated volume.
- Day-range position, wicks, and projected day volume against a same-slot 20-day median.
- Reward-to-risk and support distance are kept as risk and sizing facts only. They never filter entries, because the relationship measured inverted: RR<1 gave +0.7%, t 2.3.
- Swing highs and lows are for display only; they measured nothing (market_structure.py:48-57).

**States** (round thresholds, frozen, never searched)

| State | Conditions |
|---|---|
| ACCEPT | P ≥ VWAP, P ≥ EMA9₁₅, hold9 ≥ 3, range position ≥ 0.60 |
| FAILED_HIGH | new 20-day high, P < VWAP, range position ≤ 0.50 |
| BREAK | P < 0.99 × support(t−1), projected volume ≥ 1.5×, P < VWAP, range position ≤ 0.33 |
| HOLD_LEVEL | a pullback that holds a rising daily EMA21 or support |
| NEUTRAL | anything else |

**Evaluation**
- Causality: a later bar never changes an earlier snapshot.
- Parity: the live and replay paths are byte-identical on the same archived bars.
- An outcome-free census of states per name and year on 2016-2023.

**Status:** display-first. A new versioned capture `recorded-structure-opinions/1` leaves the frozen `recorded-entry-opinions/1` untouched.

### P2.2 Simulator same-day close phase

**Changes**
- `simulate.run(close_phase=callable, close_funding='cash_only'|'same_auction')`. It is decided from precomputed (T,N,K) snapshot arrays and filled at closes[t+1].
- The cash_only budget is a snapshot of cash taken after the open buy leg and before incumbent MOC sale proceeds are credited. The current _fill_split ordering (simulate.py:1619-1637) would otherwise leak same-auction funding.
- `taken` and `vetoed` propagate into the next session's entries.
- Close-phase sells bypass the green-day skip.
- The phase pauses while the FOMC cycle, the event baseline or the brake is active.
- There are no entries on reset nights, which mirrors simulate.py:1196.
- Journal fills use phase='close' with a leg label (research_journal.py:260-263 accepts only open and close). A per-event ledger records MFE/MAE and forward returns at +1, 5, 10 and 20 sessions.

**Evaluation:** with close_phase=None the output is byte-identical. Property tests cover non-negative cash, the 15% cap and exemption handling.

### P2.3 Entry family (one primary hypothesis, gate H-E, SIP-dependent)

**Primary hypothesis H-E**
- E1 = every A/A+ band fire (bz_prov ≥ 1.10, blocker off) bought at the same day's close from the 15:30 snapshot, unless the state is FAILED_HIGH.
- A FAILED_HIGH veto skips the incumbent next-open entry for one session.
- Sized with paper.entry_size and capped by bound_orders.

**Controls**
- INC, the incumbent.
- C1: an unconditional close entry. E1 vs C1 isolates the veto.
- C2: a random veto at FAILED_HIGH's measured rate, 50 seeds.
- E-beta: the same notional in QQQ or the EW book from close t to open t+1. E1 vs E-beta asks whether the gain is only overnight exposure.
- E-P without fallback.
- The FAILED_HIGH count is taken net of fires the existing blocker already stops.

**Stratification:** release nights, because an after-close earnings print is a different bet. Declare in advance whether release-night fires fall back to the next open.

**Statistics:**
- per-order paired bp, clustered by session;
- the portfolio gate H-E.
The expected verdict ("insufficient evidence" at about 0-0.1 CAGR) is stated before running.

**E3 pullback add (HOLD_LEVEL on held names)** is optional. It runs only with an exposure-matched arm, because adds earn by exposure (market_structure.py:70-79). It is likely dropped at step 0, which drops any rule with fewer than 200 events or clock agreement below 85%.

### P2.4 Exits and profit-taking family S (answers "how to take profits")

What the evidence says:
- Profit comes from rotating out on a downgrade: +3.42 CAGR against holding, and −24 CAGR if the downgrade is sold to cash instead.
- Price exits all lost: the band exit cost −3.0%/yr, stops were worst, partial trims 1f33108b lost, and the full exit on 15-minute EMA structure made −1.31% against +0.47%.
- On a survivor book, holding always looks best. So every sell rule is also run off-book on non-book S&P names, where survivorship does not reward holding.

**Arms**

| Arm | Rule |
|---|---|
| S0 | incumbent green-day skip (IEX open) |
| S-par | the same rule on the SIP 09:30 open; fidelity only |
| S1 | P1.3's hold limit and rank buffer at the close; portfolio-level profit-taking |
| S2 | structure hold of queued trims: at 15:46, cancel a pending non-risk MOC trim when the name is in ACCEPT, otherwise let it execute |
| S3 (X2) | structure-break partial rotation: in BREAK, sell half at the same close, once per break episode; re-entry only after a close back above the level |

S2 replaces the opening coin flip with an end-of-day structure read. S3's proceeds go by rank (P1.4).

**Controls**
- no skip;
- a one-session unconditional sell deferral;
- a random skip at the matched rate (10 seeds × 20 offsets, to fit the compute budget);
- X2-U (a close below support with no 15-minute condition);
- X2-R (random halves, matched count).

**Dropped as a gated rule: X1 run-up trim.** There are only about 10-30 dev-window events, far below the 200 floor, and the priors are negative. The dashboard shows "Extended; trimming has no measured edge; hold".

Your decision: the green-day skip was operator-requested, so retiring it is your call (Q6).

**Expected effect (INFERRED):** S3 0 to +0.3 CAGR; S2 unknown against S0; S1 a small in-sample cost, bought as concentration control.

### P2.5 Execution clock

**(a) Same-auction swaps, placed from the nightly plan.** Unfunded remainders and rotation redeploy buys are tagged `execution_timing='close'`. _submit routes them to submit_market_on_close, which already accepts buys (alpaca_trading.py:279-296), for the same t+1 auction as the funding MOC sells.
- No market-open exception is needed.
- The green-day job cancels the linked buy whenever it cancels the funding sell.
- The haircut is calibrated to a high quantile of the relative close-to-close move between the sold and bought names.
- The invariant (end-of-day cash ≥ 0, no leverage) is tested on a whole-share, fixed-quantity replay. The simulator's `max(0, …)` (simulate.py:1565-1571) would make the test vacuous.
- It runs only if P0.4 shows margin and P0.5.2 clears the stop rule.
- The ceiling: the legacy recycle measured 43.64% against 39.23%, but only by using leverage down to −1.22x, which is not allowed here.

**(b) Guarded 15:46 close-auction path** (only for arms that pass: E1 buys, S3 sells, S2 cancels).
- New `backend/cli/market_close_auction.py`, modelled on market_event_recovery (activation hash, reconcile).
- It runs at cron `46 15`, with an early-close variant, inside the window [close−14, close−11 min] under paper.transaction.
- One multi-symbol SIP fetch; every live-fetched bar is archived for replay parity.
- Pending rows are written before submitting, with client ids from state.order_seq.
- _submit gets a narrow keyword permitting only these order classes; everything else keeps the refusal at market_daily.py:428-434.
- Nothing is submitted after 15:49. It pauses during FOMC and brake states. Same-name buys are netted against pending trims.
- Fills get a distinct reference_source ("15:45 bar, MOC"), because execution_quality.py:56-62 would otherwise book the drift as zero.
- Deploys add re-activation of event recovery to the checklist, because its execution hash covers market_daily.py and paper.py.

**(c) Gap handling.** It is measured, not built:
- counterfactual columns: ≥2% gap-up deferred to the 10:00 bar open, against the unconditional 10:00 control;
- thresholds fixed from Study 1;
- judged on SIP 2016-2020 (untouched by Study 1), with the same sign required in 2021-2026.
An order path, needing limit orders or 10:00 submission, is built only if t ≥ 2.

### P2.6 Hardening the 15-minute loop

- The cron starts 75 s after the quarter-hour.
- One multi-symbol request per tick.
- A bounded in-run re-poll for missing _expected_bar.
- Degradation per name for execution consumers.
- The fingerprinted research candidate is untouched.

**Gate:** at least 99% of ticks see the just-completed bar for at least 98% of names over 20 sessions, and p95 tick time is under 60 s.

### P2.7 Dashboard: Buy / Add / Trim / Exit that never repeat

- **A presentation layer** over decision_view that leaves `entry_action`'s return untouched. It feeds the frozen capture, and changing it would rewrite that study.
- **Each actionable row carries** a `signal_id` = sha(symbol, setup, episode start, rule version), `decided_at`, `valid_until` and a deterministic structural reason. Example: "Accepted breakout: 2.3 on its 20-day band at 15:30; above VWAP 1.2%; held the 15-minute 9 EMA 4/4; top 18% of range".
- **During the session,** states show as "Watch".
- **Suppression.** Each episode is issued once, and suppressed after a recorded fill or a working order. The frontend needs a new "order placed" input, because it never sends pending_buys today.
- **Midpoint** is labelled "IEX single-venue midpoint: target, not a fill", and is never shown on close-auction rows.
- **Unvalidated rules** are labelled or hidden (Q8).
- **The 09-22 rule holds:** intraday 15-minute triggers stay on the personal board, and the paper clock is never coupled to personal instructions.

## 5. Phase 3: crash-avoidance switch

### P3.1 Precheck

Run P0.5.5 on the adopted /4 book. Report all three earlier measurements of the frozen brake:
- −1.7 CAGR in the proxy, whose T-bill column is corrupt after 2021;
- −3.4 CAGR / −5.7 drawdown on the repo simulator (commit 08ac4d89);
- −7.4 CAGR / −1.9 drawdown on momentum120.

The switch is expected to cost more than a 1.5-point budget.

### P3.2 `risk_state` module (composition only; advisory from day one)

**States**
- **M:** the frozen trend_brake on QQQ (0.97/1.02, trend_brake.py:19-21).
- **V:** a majority vote of risk_off_path over L ∈ {100, 150, 200} on an equal-weight SMH+IGV total-return basket, with the same frozen bands. SMH and IGV are added to the nightly bar_tickers.
- **T:** tightening, handled as today (0.75 plus tilt).

**Rules:** scale 0.5, composed by minimum, re-entry only at the upper band. The state and exit level are written to `record['risk_state']`, and a display-only banner is shown. While the state is advisory it never filters personal Buys.

**Evaluation:** causality tests. The definitions are frozen before any outcome is seen.

### P3.3 Predeclared destination mapping (by mechanism, not fitted)

| Condition | Where the cut goes |
|---|---|
| M binds (broad trend break) | cash. Research credits "SWVXX-as-cash" at DTB3/BIL yield. Paper holds plain cash, or SGOV/BIL with distributions accrued in the ledger (Q2). |
| V without M (volatile names only) | SPY |
| Any | never QQQ: it falls with the book, and A3q gave back all the protection |

SWVXX is never ordered or simulated as an instant fill (paper_allocation.py:62-69).

### P3.4 Long-history validation (needs approval for the free public data pulls)

- **Data:** total-return series: QQQ from 1999, SPY from 1993, SMH, IGV, the French market series with dividends from 1926, and DTB3. Price indices are used for signals only.
- **Gate at 25 bp, per volatile asset:**
  - switch CAGR ≥ always-in − 0.5 pt/yr;
  - maximum drawdown reduced by at least 10 points;
  - results reported per decade, with an episode table (false switches, missed rally, re-entry delay);
  - block bootstrap with blocks of at least 250 sessions.
- **Book gate:** the median-offset CAGR cost stays within your insurance budget (Q1).

### P3.5 Integration, only if both gates pass

- **Simulator:** a `defense` path (scale, destination) with SPY held in separate sleeve units, never in book.shares. Held in the panel, SPY would be rotated out (simulate.py:103-105) and zeroed at resets (simulate.py:451).
- **Paper:** paper.plan gets a target-ceiling-plus-buy-pause branch, not event_execution, which would freeze all trading for months. SPY is stripped from held before the planner, rotation and deferred logic.
- **FOMC composition:** the latent double cut is real (simulate.py:1114-1125; event_execution.py:40-45). The fix treats an FOMC cycle as "subsumed" while defense ≤ 0.5. That needs an event_risk.VERSION bump, an amendment to the fomc-gate doc and your approval. Otherwise the FOMC overlay is unchanged.

## 6. Confronting the prior negative evidence

| Prior result | New rule | Why it differs | How it could be falsified |
|---|---|---|---|
| Confirmation entries lost to the open (Study 2) | E1 same-close entry | Buys earlier, never later; the veto only removes entries | E1 ≤ C1, or C1 ≤ E-beta |
| Waiting 1-10 sessions costs 0.29-1.43% | FAILED_HIGH veto | One-session skip only, counted | E1 − C1 ≤ random veto C2 |
| Open is as good as any first-hour print | No first-hour buys | Gap deferral stays a counterfactual | G ≤ unconditional delay U on 2016-20 SIP |
| Band exit −3%/yr; stops worst; partial trims lost (1f33108b); 15m EMA full exit −1.31% | S3 partial rotation on a volume-confirmed daily break | Proceeds redeployed by rank; relies on rotation arithmetic, not a timing forecast | S3 ≤ X2-U or X2-R; fails off-book |
| Green-day +11.7 CAGR looks like an exposure artefact | S2 structure hold of queued trims | Decided on the completed day's structure, not the first tick | S2 ≤ unconditional deferral or random skip |
| Wick and close through support look the same (actions.py:17-26) | BREAK state | Needs a daily-level close plus volume plus a weak close | BREAK events ≈ X2-U |
| Breakout overnight premium absent in the proxy | E-beta control and stop rule | Kills the branch early | E-UB < +0.1 CAGR |
| Swing HH/HL structure and RR measured nothing or inverted | Display and sizing only | Not used as filters | n/a |
| Brake costs 1.7-7.4 CAGR | Insurance budget | Advisory unless it passes | P3.4 or budget fails |
| vol/vol_trend halved CAGR | Not wired | n/a | n/a |

## 7. Adoption rule and release trains

**Adoption rule**

1. **Historical gate.** Gate H or H-E as in section 1, with the registry counting trials.
2. **Forward fidelity shadow, 4-6 weeks.** It runs on a synthetic dry-run ledger with its own positions and cash, filled on daily and SIP bars, from a guarded hook next to _reversal_shadows (market_daily.py:880). A copy of PaperState would never hold the candidate's positions, so it cannot be used. Fidelity checks:
   - at least 20 sessions, including at least one reset, and at least 10 of each new order class, or else forced-state rehearsals;
   - order-level agreement of at least 95% with a simulator replay on the archived inputs;
   - 100% code parity on the archived live-fetched bars;
   - tracking difference of 5 bp/day or less after slippage decomposition;
   - zero negative-cash sessions and zero stranded legs;
   - a defect alarm if the cumulative paired net falls below −3 SE.
   This window makes no alpha claim.
3. **Switch the paper account.** Bump POLICY_VERSION and update LIVE_POLICY so curve_block publishes the policy the account runs. /3 keeps running as a dry shadow with a kill switch.

**Constraints**
- Deploy only when you ask.
- The personal board follows the switch only on your confirmation (Q8), because report.book drives the real Buy list (market_balancer.py:280-288).
- Record a roadmap amendment, because TRADING_ROADMAP stages 3/5 still say "season shadow".

**Release trains**
- **/4:** whatever passes in Phase 1.
- **/5:** whatever passes in Phase 2.
- **Risk switch:** advisory at once; traded only if P3.4 and the budget pass.

## 8. What we will NOT build, and why

| Not built | Why |
|---|---|
| QQQ/SPY residual sleeve for idle cash (default) | Your clarification. Kept only as a diagnostic row. |
| Leverage, conditional beta, leveraged ETFs | Your risk stance. |
| Standalone or falsification 15-minute sleeves (Gao, noise-area, ORB) | Your clarification. Everything measured was negative at 3 bp. |
| The funded vol/vol_trend path as the balancer | Targets volatility twice at a min(SPY,QQQ) budget; halved CAGR. |
| HRP, minimum-variance, mean-variance optimisers; better vol forecasts; RL/Kelly sizing | Lower variance, not return; noisy information coefficient; zero-gradient REINFORCE. |
| Confirmation or pullback entries; learned timing models | Measured negative or null. |
| Fixed profit targets, trailing or price stops, gated run-up trims (X1) | Measured worse; too few events; you want structure, not fixed numbers. |
| Moving ordinary sells to the same-day close; opg/MOO orders | Loses the overnight and the t+1 close advantage; 8 of 9 opg orders expired. |
| VWAP/TWAP/Almgren-Chriss slicing; paid real-time SIP; websocket daemon; 5-minute bars | Negligible impact at this size; no-paid-source rule; you call it noise. |
| Daily green/red rotation, vol-spike or VIX triggers, CPPI, learned brake | Measured negative. |
| Retuning the band 1.10, the brake bands, the FOMC gate or thresholds on 2021-2026 | Frozen or already examined. |
| Editing the SHA-pinned market_pick_audit.py and timing_research.py, or the fingerprinted intraday candidate | Would break reproduction and reset archives. |
| Simulating SWVXX as a tradable instrument | Repo rule. |
| Reopening the ML ranker now | The objective mismatch has to be fixed first. |

## 9. Sequencing and effort (INFERRED)

| Weeks | Work |
|---|---|
| 1-2 | P0.1-P0.5 in parallel. P0.3 fetch about 1 day plus 10 minutes. Split-fix record week starts. |
| 3-4 | P1.1-P1.4 on corrected inputs, one joint registered family. P2.1-P2.2 built on fixtures, then SIP. P3.2 advisory ships (display). |
| 5 | Phase 2 step 0 (outcome-free counts, clock agreement), then a single frozen run of H-E and family S. P1.5 arms. P3.4 if data approved. |
| 6-11 | /4 fidelity shadow (4-6 weeks), then paper switch on your word. The P2.5(b) path is built only for passed arms, then its own fidelity window (/5). |

Effort: P0 about 2 weeks; P1 about 1.5 weeks; P2 about 3-4 weeks; P3 about 1 week for advisory, plus about 1.5 weeks for integration if it passes.

**Overall expectation (INFERRED):** most of any in-sample gain comes from exposure (+1 to +3 CAGR, with deeper drawdowns). Timing and structure rules are likely "insufficient evidence", but they add determinism, no repeated signals and measured costs. Beating QQQ going forward still depends on the volatile names continuing to lead, and no plumbing can prove that.
