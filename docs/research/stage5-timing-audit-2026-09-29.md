# Stage 5 timing audit: which buys can be decided at 15:45 (2026-09-29)

The stage-4 follow-up
([stage4-audit-and-overnight-2026-09-29.md](stage4-audit-and-overnight-2026-09-29.md),
part 2) found that the executor's buy prices rise between the decision close
and the next session. That is +22 bp a buy to the board's fill in 2018-2023
and +52 bp in 2024-2026. The candidate study buys at the decision day's close
instead, with a market-on-close order placed before the 15:50 ET cutoff.

That study is only honest if the buy can be decided at about 15:45 from data
available then. This note establishes:

- which buy decisions are knowable at 15:45;
- how often the 15:45 reading differs from the 19:30 decision;
- how a backtest can reconstruct a 15:45 decision faithfully.

It ends with a recommended design for the registered study.

**Nothing here is priced.** No candidate fill, gain or return was computed.
Every figure compares decisions: grades, band flags and order sets. None
compares prices after a decision, so the registration is not contaminated.

**Provenance.**

- Code: `main` at `2b2f0a6`. The spark1 runs used `~/scratch/wt-s4int` at
  `dabd3f5`, which differs from `2b2f0a6` only by the new
  `backend/market/paper_history.py`.
- Data: the store as of the 2026-09-28 session. The 2026-09-29 nightly had not
  yet run.
- The control: stage 4's `ew-redeploy` executor at offset 10.
  - It reproduces stage 4's model-window orders exactly: 1,433 orders, 1,058
    buys and 375 sells.
  - Replaying its planner with the final inputs reproduces all 2,688 of its
    decisions exactly.

## The answer

**By buy kind.** Share of notional is the per-(session, name) submitted buys at
offset 10, 2018-2023 (2024-2026). "Same order at 15:45" is the share of that
kind's notional that a 15:45 decision places identically, measured on the
control's own book state.

| Buy kind | Share of buy notional | What decides it | Inputs that move with the day's price | Knowable at 15:45? | Same order at 15:45: 2018-2023 / 2024-2026 |
|---|---|---|---|---|---|
| Reset buy | 28% (22%) | The 20-session clock. Targets: every A/A+ member at min(1/count, cap). Band blocker | Grades (only through pending stance confirmations), blocker, sizes | **Yes** | 98.1% / 97.4% |
| Deferred retry | 20% (13%) | Yesterday's unpaid units, re-gated on A/A+, not rotating out and not blocked | Grade, blocker | **Yes** | 98.7% / 99.3% |
| Rotation buy | 3% (4%) | A held name graded below A is sold; its value goes pro rata to held names not blocked | Grades, takers' blocker | **Yes** | 95.4% / 99.7% |
| Band entry | 4% (5%) | Bollinger z of the day's close ≥ 1.10 on an A/A+ name | The z itself (no persistence), blocker | **Partly** | 98.8% / 96.2%; the trigger alone disagrees on 12-14% of fires |
| Redeploy of idle cash | 46% (56%) | Cash beyond 2% after the other legs, put toward targets, including names graded in since the reset. No band gate | Grades (above all new A/A+ names), A/A+ count, cash, prices | **Yes**, with the largest misses | 97.6% / 97.9% |
| FOMC restoration | 17 buys, all in 2026 | The calendar and confirmed event fills | SPY's 5-session weakness at t (for the reduction) | Yes, but next-open by policy | Not replayed; exclude |
| Any buy on a 13:00 early-close session | 18 of 1,873 buys | Any of the above | No 15:45 exists | **No** | Exclude |

- **Almost all buy notional is decided the same way at 15:45.**
  - It is 99.4% in 2016-2017, 97.9% in 2018-2023 and 98.0% in 2024-2026.
  - About 2% of notional would fall back to the next session.
  - The 15:45 decision would also buy extra notional that the 19:30 decision
    does not want: 0.8%, 2.6% and 6.8% of buy notional in those windows.
- **The grade is settled by 15:45 on about 99% of name-days.**
  - The A/A+ set changes on about a third of sessions.
  - The 15:45 reading calls 97.8-99.0% of those changes right.
  - The A/A+ status is wrong on 0.04-0.11% of member-days: 1.0-3.9% of
    sessions.
- **Why it is settled: stance persistence.**
  - A stance changes on session t only when it has already read its new value
    on t−1 and t−2 (`opinions.PERSISTENCE = 3`).
  - At 15:45 the only open question is whether today confirms, and the last
    fifteen minutes rarely flip that.
- **After-close news never enters the same session's decision.**
  - A release accepted at or after 16:00 counts from the next session
    (`edgar.py:154`).
  - Filing facts count from the day after their filing date
    (`fundamentals_asof.py:82`).
  - Only 2 of 3,451 earnings releases were accepted between 15:45 and 16:00.
  - The diagnostic's worry about "decisions caused by after-hours news" does
    not arise: that news moves the decision of the next session, which is
    itself decidable at its own 15:45.
- **The least knowable inputs are the executor's same-day price rules.**
  - These are the band blocker and the band-entry trigger. Neither has
    persistence, and a quarter hour can move a name across either line.
  - They disagree with the close on about 12-18% of their fires.
- **The largest avoidable error is the expectations gap.**
  - The 15:45 proxy uses yesterday's gap. 437 of the gap's 531 universe names
    have no intraday bars in the store.
  - With the exact gap, the extra notional in 2024-2026 falls from 6.8% to
    1.5%.

## 1. How the executor decides and fills today

**The live timeline:**

- **19:30 ET, Mon-Fri.** Cron runs `desk_daily.sh` from `~/deploy/anios`:
  `market_daily --refresh --brief-book --paper-trade --challenger ...`.
  - `refresh` (`market_daily.py:163`) pulls the daily bars and the EDGAR
    events and facts, then the filing versions, then the release tone for the
    book (the model, 180-minute budget).
  - It then runs the desk (`desk_report`, `market_daily.py:1962`) and plans
    and submits the paper orders (`_paper_trade`, `market_daily.py:684`).
- **Every 15 minutes, 09:00-16:59.** `desk_intraday.sh` runs `market_balancer`:
  the board's live quotes, the live technical re-read and the entry-timing
  latch.
- **20:30 ET.** The SIP append (`desk_sip.sh`).
- **The paper account's buys** are market DAY orders sent after 19:30. They
  fill at the next session's open (`alpaca_trading.py:250-263`; "opg" until
  2026-09-08).
- **Its sells** are market-on-close orders for the next session's close
  (`market_daily.py:447-459`). The intraday green-day rule cancels a sell
  when the name opens up.
- **The board, the operator's own account.** A BUY fills at the first
  15-minute close 1% under the next open, else at the close:
  `dip_or_close` (`fill_timing.py:561`, `DIP = 0.01`).
  - The board's "close" state starts at 15:30.
  - The market-on-close cutoff is 15:50 (`entry_timing.py:72-74`).
- **The simulator** decides on t's close, buys at t+1's adjusted open and
  sells at t+1's close (`simulate.py:1741-1744`), with the green-day skip at
  `simulate.py:1765`.
- **Stage 4's control fill** for every order is `dip_or_close` in t+1
  (`stage4_labels.py:229-237`).

### The buy kinds and their inputs

Prices below are t's close (`market_daily.py:707-711`; the simulator's
`_paper_inputs`, `simulate.py:132`). Grades are `report.graded.grades[t]`. The
blocker is `exit.evidence(panel).signalled()[t]` (`market_daily._band_blocked`,
`market_daily.py:615`; `exit.py:106-142`). It fires on:

- a bearish candle while the close is in the top 5% of its 20-day band; or
- a band wider than 90% of its own trailing year while the close is in the
  band's upper fifth.

It reads t's open, high, low and close.

**1. Reset buys.** Source: `paper.plan` → `_rebalance_orders`
(`paper.py:835`, `paper.py:537`); the simulator at `simulate.py:1595-1609`.

- Inputs:
  - the reset clock (`REBALANCE_EVERY = 20`, in the paper state);
  - targets from `live_policy.targets` → `policy_v4.targets`
    (`policy_v4.py:47`): every A/A+ member at min(1/count, `HOLD_CAP`);
  - held shares and equity at t's close;
  - the blocker, which vetoes buys and adds only.
- Sizing is `planner.plan` at t's close. What the cash cannot pay is deferred.
- **The clock and holdings are final before the session.** The A/A+ set, the
  blocker and the sizes depend on t's price.

**2. Deferred retries.** Source: `paper._deferred_orders` (`paper.py:611`),
retried first by `plan` (`paper.py:954-980`); the simulator's `_live_midcycle`
(`simulate.py:425-455`).

- Inputs:
  - yesterday's unpaid units, which are final;
  - the gates at t: graded A/A+, not in `finished`, not blocked;
  - the 15% name cap;
  - cash.

**3. Rotation buys.** Source: `paper._rotation_orders` (`paper.py:401`).

- Held names graded below A at t are sold
  (`market_daily._downgraded`, `market_daily.py:550`; `simulate.py:152-154`).
- Their value is bought pro rata into held names that are not leaving and not
  blocked, inside the 15% cap.
- The buys are paid from cash on hand, because the sale fills at t+1's close.

**4. Band entries.** Source: `paper._entry_orders` (`paper.py:475`) and
`market_daily._price_entries` (`market_daily.py:579`).

- Trigger: `entry.bollinger_z(adj_close)[t] ≥ ENTRY_BAND_Z = 1.10` on an
  A/A+ name that is not rotating out and not blocked.
- Size: `entry_size(z) = 0.023 · (z / 1.25)²` (`paper.py:216`).
- The trigger is a same-day price level with no persistence.

**5. Redeploy of idle cash.** Source: `paper._redeploy_orders`
(`paper.py:683`) and `simulate._redeploy_orders` (`simulate.py:304`).

- Cash beyond `REDEPLOY_BUFFER = 2%` of equity, after the other legs, goes to
  targets pro rata to each name's shortfall.
- The candidates are held A/A+ names not leaving, plus names the policy wants
  today that it did not want at the last reset.
- There is no band gate.
- Every target depends on the A/A+ count at t, and the spare cash on t's
  prices.

**6. FOMC restorations.** Source: `event_execution.plan`
(`event_execution.py:29`).

- The restoration starts on the decision date (`reducing = session <
  decision_date`, line 49). It buys back confirmed event sells.
- Whether a reduction starts at all reads SPY's close at t against t−5
  (`event_risk.py:127-133`).
- It is live only from 2026-06-18 (`event_risk.py:18-27`).
- Event orders are next-open by policy.

**Cash, the one structural subtlety.**

- The control's budget at t is the cash after t's close. That includes the
  proceeds of the sells decided on t−1, which fill at t's close
  (`simulate._fill_split`).
- A market-on-close buy at t fills in the same auction as those sells.
  - In the simulation, fill t's closing sells first and then the
    market-on-close buys. The budget is then identical to the control's.
  - Live, the order must pass the broker's buying-power check at 15:45,
    before the sells fill. The account reports `buying_power`
    (`alpaca_trading.py:45`), so a margin account can carry it.
  - The executor should budget the cash now plus today's still-live
    market-on-close sells priced at 15:45.

**Stage 4's labels do not identify the leg.**

- `stage4_orders.classify` (`stage4_orders.py:227`) labels a buy `retry` when
  the previous decision deferred it, `event_buy` in an event cycle, and
  otherwise `entry` or `add` by whether the name was held. Reset, rotation,
  band-entry and redeploy buys all land in entry or add.
- Counts since 2016 (executed basis): 460 entries, 883 adds, 513 retries and
  17 event buys.
- This audit attributed legs by recording the planner's own orders during the
  replay. When a name has two legs in one plan, the priority is retry, then
  band entry, then rotation, then redeploy.

| Submitted buys, offset 10 | Reset | Retry | Rotation | Band entry | Redeploy | All |
|---|---|---|---|---|---|---|
| 2016-2017 | 71 (29%) | 125 (21%) | 63 (3%) | 21 (2%) | 152 (45%) | 432 |
| 2018-2023 | 169 (28%) | 291 (20%) | 182 (3%) | 47 (4%) | 392 (46%) | 1,081 |
| 2024-2026 | 54 (22%) | 66 (13%) | 42 (4%) | 15 (5%) | 204 (56%) | 381 |

Counts, with the share of buy notional in brackets. On the executed basis the
windows hold 423, 1,058 and 392 buys, at a mean of 3.2%, 4.0% and 5.3% of
equity.

## 2. The grade and its timing

### How it is produced

- **The run.** `desk.run` (`desk.py:156`) builds the book panel and five
  analysts, then `assemble` (`desk.py:390`) calls `grading.grade`
  (`grading.py:148`) and the rule `grade_stances` (`grading.py:231`).
- **The vote.** votes = fundamental + technical + sentiment + value + ½ ×
  rotation.
  - A needs votes ≥ 2, or a bullish release with votes ≥ 1, or bullish
    fundamentals and technicals with votes ≥ 1.5.
  - A+ needs a bullish release with votes ≥ 2.
  - Any bearish core analyst caps the grade at B.
- **Each stance.** It is bullish in the top 30% and bearish in the bottom 30%
  of the analyst's cross-sectional rank that session
  (`opinions.STANCE_FRACTION`). It must hold three sessions before it replaces
  the old one (`PERSISTENCE = 3`, `opinions.py:19`; `persist`,
  `opinions.py:108`).
- **The rotation gate.** Rotation's half vote is set to zero on any session
  the regime gates it off (`grading.py:167-173`). The gate applies after
  persistence and takes effect the same day.
- **Two configurations.** The research backtests (stage 3, stage 4 and this
  note) use `desk.run(store, None, inputs=(EXPECTATIONS_GAP,))`, which is
  fundamentals `/2`. The nightly uses `FUNDAMENTALS_CURRENT`: `/3`, with
  stance resets (`market_daily.py:1962-1964`).
- **Run time.** `desk.run` took **321 s** on spark1, most of it the
  expectations gap.

**Each analyst's inputs, and what is final before 15:45:**

| Analyst | Inputs | Moves with t's price? | Same-day information | Known at 15:45? |
|---|---|---|---|---|
| Fundamental (`fundamental.py:37`) | Revenue growth (YoY, QoQ, acceleration), gross margin, from EDGAR filing versions | No | Versions carry no acceptance time (0 of 174,521 stored rows), so a fact counts from the day after its filing date (`fundamentals_asof.py:82-88`) | **Yes**: fixed before the open |
| Technical (`technical.py:122`, `STRETCH_LEG = "band"`) | Weekly trend (the close against a rising weekly 21 EMA; a Friday's own close enters it), daily trend (21 EMA against 50, slope), residual momentum over t−140 to t−21 (no t), and either the 20-day band position or the 60-day range position | **Yes**: close, high and low at t. The playbook follows the AI basket's 60-session return including t | none | Only the pending confirmations are open |
| Sentiment (`sentiment.py:64`) | The model's tone of 8-K earnings releases | No | The reaction date is the acceptance date if accepted before 16:00 ET, else the next day (`edgar.py:154`). Of 3,451 releases: 2,719 after 16:00, 701 before 09:30, 29 at 09:30-15:45, **2 at 15:45-16:00**. Scored only in the nightly | Yes, except the 2 late releases. Needs daytime scoring for same-day releases, which part G shows is optional |
| Value (`value.py:34`), blended 50/50 by rank with the expectations gap (`challenger.py:94`) | P/S = shares × close at t over revenue, against the side's median, size-neutral (`valuation.py:68`). The gap = a learner's expected revenue growth − the price-implied growth | **Yes**: t's close, in P/S and in the gap's momentum, market cap and implied-growth features | The value levels include facts filed on day t (`edgar.py:599`, non-strict), which can be after the close. The gap's model is fit once a year on labels published before 1 January (`market_expectations.py:878`). Its filings and tone are strict | Only the pending confirmations are open. The gap needs t prices for 531 names |
| Rotation (`regime.py:206`, half vote) | The 60-session AI-minus-software residual return spread, including t's returns | **Yes** | Gated when the AI basket's participation is below its two-year median (`regime.py:264`). Participation is the 20- against 250-session log dollar volume, including t's full volume and the closing auction | Only pending confirmations and the gate |

No consensus estimates enter the grade. There is no free history of analyst
consensus (`market_expectations.py:38`): the "expectations" are the gap's
learner.

### How often the A/A+ set changes

These are point-in-time member-days (`point_in_time.point_in_time`).

| Window | Sessions | Mean A/A+ count | Sessions the A/A+ set changes | Of which by grade (not membership) | Grade entries / exits a session | Sessions the count changes |
|---|---|---|---|---|---|---|
| 2016-2017 | 503 | 7.1 | 166 (33%) | 164 | 0.20 / 0.21 | 143 |
| 2018-2023 | 1,509 | 6.4 | 528 (35%) | 525 | 0.23 / 0.23 | 476 |
| 2024-2026 | 687 | 5.0 | 202 (29%) | 199 | 0.18 / 0.19 | 186 |

Every change of the count moves every name's target 1/count. Under `/5` the
25% cap binds whenever fewer than five names qualify. That is 10.9% of
sessions in 2016-2017, 19.0% in 2018-2023 and 42.5% in 2024-2026.

### Why most of it is known by 15:45

**The rule.** With `persist` (`opinions.py:108`), a held stance on t can only
be its value on t−1 or the raw stance of t−1.

- It changes on t only if the raw stance has read the new value on t−2 and
  t−1 (a run of two that differs from the held stance) and t matches.
- Call such a cell "pending". Everything else about t's stance is fixed
  before the session.

**Checked on the data, all member-days 2015-2026.** Every persisted change
happened on a pending cell.

| Analyst | Pending cells a member-day | Persisted changes a member-day | Changes on a pending cell |
|---|---|---|---|
| Fundamental | 0.73% | 0.68% | 596 of 596 |
| Technical | 6.75% | 5.10% | 4,495 of 4,495 |
| Sentiment | 1.57% | 1.48% | 1,302 of 1,302 |
| Value | 1.35% | 0.99% | 876 of 876 |
| Rotation | 1.78% | 1.42% | 1,253 of 1,253 |

**The one same-day switch is the rotation gate.**

- It changed on 25, 50 and 29 sessions in the three windows, with the book
  gated 32%, 53% and 30% of the time.
- **The upper bound.** Let the pending cells of the three price-dependent
  analysts go either way, and let the gate flip on the sessions where it
  did.
  - The A/A+ status is then open at 15:45 on 1.35%, 1.36% and 0.98% of
    member-days.
  - At least one name is open on 25-34% of sessions.
  - 60-76% of the A/A+ changes happen on open cells: 124 of 207, 473 of 681
    and 193 of 255.
- **The next table measures how many of those the 15:45 reading actually
  gets wrong.**

### Measured: the 15:45 grade against the 19:30 grade

Every analyst is recomputed with row t replaced by its 15:45 reading (§3). The
registered-style proxy uses:

- the close of the 15:30-15:45 bar, and the high and low so far;
- SIP volume through 15:30, scaled by the name's trailing ratio;
- filings strictly before t;
- the gap at t−1.

| | 2016-2017 | 2018-2023 | 2024-2026 |
|---|---|---|---|
| Member-days with a 15:45 bar | 99.2% | 98.8% | 98.1% |
| A/A+ status wrong: name-days (share of member-days) | 5 (0.04%) | 51 (0.11%) | 30 (0.10%) |
| Of which: A at 15:45, not at 19:30 / the reverse | 5 / 0 | 30 / 21 | 19 / 11 |
| Sessions with any wrong A/A+ status | 5 of 503 | 50 of 1,509 | 27 of 686 |
| A/A+ changes called right | 205 of 207 | 666 of 681 | 250 of 255 |
| Rotation gate wrong (sessions) | 3 | 24 | 7 |
| Raw stance wrong, member-days: technical / value / rotation | 3.6% / 0.1% / 0.2% | 3.9% / 2.9% / 0.7% | 2.9% / 4.3% / 0.6% |
| Band blocker wrong on A/A+ name-days (spurious / missed; final blocks) | 25 (15 / 10; 209) | 75 (44 / 31; 549) | 37 (19 / 18; 210) |
| Entry trigger (z ≥ 1.10) on A/A+ name-days: final fires, wrong | 233, 28 | 441, 63 | 184, 24 |

**Sessions with any wrong A/A+ status, by proxy variant:**

| Variant | 2016-2017 | 2018-2023 | 2024-2026 |
|---|---|---|---|
| The registered-style proxy (above) | 5 | 50 | 27 |
| The day's final volume (isolates price) | 4 | 47 | 27 |
| The exact gap at t (an upper bound for a better gap proxy) | 5 | 29 | 9 |
| Same-day filing facts admitted | 5 | 48 | 26 |
| A 15:30 decision (the 15:15-15:30 bar; volume through 15:15) | 9 | 55 | 29 |
| Tone only through the prior evening (name-days; sessions) | 6; 6 | 55; 54 | 32; 28 |

- **The volume estimate costs little.** The gate is wrong on 24 sessions in
  2018-2023, but only 3 more sessions carry a wrong A/A+ status.
- **The gap is the main error.** Recomputing it at 15:45 would roughly halve
  the mismatches in 2018-2023 and cut two thirds of them in 2024-2026.
- **Same-day filings and intraday tone scoring hardly matter.** Persistence
  holds a new input back two sessions anyway.

## 3. Reconstructing a 15:45 decision in the backtest

### The bars

- **The cubes.** `sip_cube.SessionCube` (`sip_cube.py:72`) holds 26 regular
  15-minute bars. Slot k is the bar starting 09:30 + 15k minutes
  (`intraday_sip._slot`, `intraday_sip.py:179`).
  - **Slot 24 is the 15:30-15:45 bar.** Its close is the last trade before
    15:45:00, and it is the bar that closes at 15:45.
  - Slot 25 is 15:45-16:00.
  - The closing cross is kept separately as `auction_open`, the official
    close (`sip_cube.py:84`).
- **Coverage.**
  - Cubes exist for all 94 book names and SPY, plus QQQ, SMH and IGV.
  - 67 names start on 2016-01-04; later listings start later.
  - Everything runs through 2026-09-28.
  - 13:00 early closes are excluded (21 sessions since 2016).
  - Auction prints are present, for example on every NVDA session.
- **The fill basis.** `fill_timing.session_scale` (`fill_timing.py:1006`)
  puts a cube price on the adjusted basis. It multiplies by the panel's
  adjusted close over the cube's official close for that session. The
  official close is `auction_open`, else the slot-25 close
  (`fill_timing.py:480`).
  - So the official close times the scale is, by construction, the panel's
    `adj_close[t]`.
  - **A market-on-close buy at t therefore fills at exactly C_t**, the
    decision close the diagnostic measured from.

### The method: substitute one row, do not re-run the desk

Re-running `desk.run` on a panel truncated at each t is 321 s × 2,700
sessions. It is not needed: every price-dependent input is a causal function of
the history through t−1 and row t.

**What was built** (spark1 `~/scratch/stage5/part_c.py`). For each t it keeps
every row before t final and replaces row t:

- **Prices.**
  - Close: the slot-24 close.
  - High and low: the extremes of slots 0-24 and the day's open.
  - Conversion: to the split-adjusted and adjusted bases by that session's
    scale (the same rule as `session_scale`).
  - A name with no bar that session carries t−1's close, as
    `live_technical.with_live_row` does.
- **Volume.** SIP volume through slot 23: what the free SIP plan serves at
  15:45, given its 15-minute delay. It is times the name's trailing-20
  median of full-day over through-15:30 volume.
- **Technical, one step.**
  - The 21- and 50-session EMAs, from t−1's state (`technical.ema`).
  - The weekly 21 EMA, stepped only when t ends a week, using the backtest's
    own week-end rule (`technical._weekly_ema`).
  - Their 5-session slopes, the 20-session band position and the 60-session
    range.
  - The fill for names the stretch measure cannot read.
  - The AI basket's 60-session trend, which picks the playbook.
  - The four-leg rank blend.
- **Value.** `valuation.multiples` and `cheapness` on the single row at the
  proxy close, with levels strictly before t
  (`point_in_time_levels(strict_publication=True)`). Then the 50/50 rank blend
  with the gap at t−1.
- **Rotation.** The spread with t's basket returns; the participation
  percentile against the final trailing 500 sessions; the gate.
- **Then.** Ranks at t, one step of persistence from the final t−1 state, the
  gate and the grade rule.
- **The executor's own gates.** The blocker (band position, width rank, and
  the candle from t's open with the 15:45 high, low and close) and the band
  z.
- **Finally** (`part_d.py`), the executor's own planner functions on the
  control's book state at t:
  - `_gated_targets` and `_Book.plan` on a reset;
  - `_live_midcycle` with the redeploy variant otherwise.

The per-session cost is milliseconds: all 2,700 sessions take about 3 s.

**Validation.**

- **Null test.** With row t set to the final row, the code reproduces the
  report on every session from 2016-01-04:
  - 0 mismatching cells in the raw technical, value and rotation stances, the
    gate, the grades and the blocker;
  - a maximum difference of 0.0 in the technical score, the value score and
    the band z.
- **Planner replay.** With the final inputs it reproduces the journal's
  submitted units on all 2,688 control decisions.

**The existing live re-grade is not the rule.** `live_technical`
(`live_technical.py:93-233`) and `holdings._live_grade` (`holdings.py:346`)
re-read technical and value at the live price, but:

- they use plain value, without the gap;
- they keep the record's fundamental, sentiment and rotation stances;
- they append a row whose volume is NaN.

The study must not use them as its proxy.

### What cannot be reconstructed exactly, and what it costs

- **The day's full volume and closing auction.** They are estimated. The gate
  is wrong on 3, 24 and 7 sessions, which adds at most 3 sessions with a
  wrong A/A+ status.
- **The expectations gap at 15:45.**
  - It needs 15:45 prices for its 531-name universe
    (`mx._universe_panel`), and cubes cover only the 94 book names.
  - The proxy uses t−1's gap, which is causal and simple. That is the largest
    error source.
  - Two ways to reduce it:
    - backfill SIP for the gap universe;
    - recompute the gap's price terms at 15:45 for book names, with
      non-book names at t−1.
  - For the second, fit the yearly boosters in the morning: `_fit_predict`
    is deterministic.
- **Same-day filing facts.** Facts carry only a filing date, so the proxy
  excludes all facts filed on t. The effect is 50 against 48 sessions with a
  wrong A/A+ status in 2018-2023.
- **Releases accepted 15:45-16:00.** There are two in ten years (MCHP
  2021-02-04 and TRMB 2016-01-21, both 15:56). The proxy must move them to
  t+1.
- **The live price basis.**
  - Live at 15:45, the board's price is the IEX last trade: real time, a
    subset of the tape.
  - The backtest uses the SIP consolidated slot-24 close. This difference was
    not measured.
- **The paper venue's handling of a same-day market-on-close buy** cannot be
  backtested.

## 4. The executor's buys: 15:45 against 19:30

Both plans are made on the control's own book state at t, with the
registered-style proxy.

- **Matched:** both buy the name. The share placed at the close is the
  smaller of the two sizes.
- **Missed:** only the 19:30 decision buys; that part falls back to the next
  session.
- **Extra:** only the 15:45 decision buys, or buys more.

| Window, kind | 19:30 buys | Matched / missed / extra orders | Same order at 15:45 (share of notional) | Falls back | Extra notional |
|---|---|---|---|---|---|
| 2016-2017, all | 432 | 429 / 3 / 1 | 99.4% | 0.6% | 0.8% |
| 2018-2023, reset | 169 | 167 / 2 / 3 | 98.1% | 1.9% | 1.0% |
| 2018-2023, retry | 291 | 289 / 2 / 1 | 98.7% | 1.3% | 0.9% |
| 2018-2023, rotation | 182 | 173 / 9 / 12 | 95.4% | 4.6% | 8.1% |
| 2018-2023, band entry | 47 | 46 / 1 / 11 | 98.8% | 1.2% | 10.2% |
| 2018-2023, redeploy | 392 | 381 / 11 / 9 | 97.6% | 2.4% | 3.3% |
| **2018-2023, all** | 1,081 | 1,056 / 25 / 36 | **97.9%** | 2.1% | 2.6% |
| 2024-2026, reset | 54 | 53 / 1 / 1 | 97.4% | 2.6% | 4.4% |
| 2024-2026, retry | 66 | 65 / 1 / 0 | 99.3% | 0.7% | 2.4% |
| 2024-2026, rotation | 42 | 42 / 0 / 1 | 99.7% | 0.3% | 1.1% |
| 2024-2026, band entry | 15 | 14 / 1 / 1 | 96.2% | 3.8% | 0.2% |
| 2024-2026, redeploy | 204 | 194 / 10 / 14 | 97.9% | 2.1% | 9.7% |
| **2024-2026, all** | 381 | 368 / 13 / 17 | **98.0%** | 2.0% | 6.8% |

- **The size of matched orders barely changes.** The median gap between the
  15:45 and the 19:30 size is 0.2-0.6% of the order.
- **Why orders differ.** Of the 61 mismatched orders in 2018-2023:
  - 14 are the name's own grade;
  - 7 are its blocker;
  - 7 are its entry band;
  - 33 are other, meaning the A/A+ count, cash or a leg near the 0.5% trade
    floor. Across all windows, 80% of these "other" orders are under 1% of
    equity.
- **Early closes change almost nothing here.** None of the mismatches falls on
  one. Without them the tallies are essentially the same: for example, 6.9%
  against 6.8% extra notional in 2024-2026.
- **The large extra buys in 2024-2026 are grade misreads on days with only one
  to five A/A+ names**, where one name is a full 20% target:
  - ADSK 2025-09-29 (B at 19:30, A at 15:45; count 2 against 3), 20% of
    equity;
  - FFIV 2026-02-02, 20%;
  - AVGO 2025-01-28, 20%;
  - AVGO on the 2025-02-24 reset, 19.7% (count 1 against 2);
  - CSCO 2025-01-07, 10.5%.

  With the exact gap, extra notional falls to 0.8%, 1.4% and 1.5%, and
  "same order" rises to 99.4%, 98.7% and 98.7%. Under `/5` each such buy
  would be 25% of equity.
- **A 15:30 decision** keeps 98.7%, 98.3% and 96.2% of notional as the same
  order, with extra notional of 0.9%, 3.1% and 7.1%. It is slightly worse, but
  it leaves 20 minutes to the cutoff.
- **A "locked only" rule is a poor trade.** Buying at the close only when the
  name's A/A+ status cannot flip today would exclude 12%, 18% and 33% of buy
  notional.
  - Most of it is redeploy buys: 29% and 51% of redeploy notional in
    2018-2023 and 2024-2026.
  - 76 of the 88 such buys in 2018-2023, and 46 of 51 in 2024-2026, are names
    crossing into A/A+ that day.
  - The 15:45 reading calls those correctly almost every time. The rule would
    discard a large part of the effect to avoid a rare error.

## 5. Recommended design for the registered study

**Question.** Does buying the executor's eligible buys at the decision day's
close, on a decision made from 15:45 data, beat the board's fill in the next
session?

**Arms.**

- **Control:** stage 4's control executor.
  - Every buy fills by `dip_or_close` in t+1 (`stage4_labels.py:229-237`).
  - Report `next_open`, the paper account's own convention, beside it.
- **Candidate:** the same executor, with eligible buys decided on the 15:45
  proxy and filled at t's official close.
- **Policy:** run it under the policy that will be live, `/5`
  (`trading/policy-v5-cap25`: `HOLD_CAP = 0.25`, otherwise `/4`), or
  register both. The figures above are `/4`.

**Eligible buys.** Reset buys, deferred retries, rotation buys, band entries
and redeploy buys.

**Excluded, filling as the control:**

- FOMC restorations: next-open by policy, 17 buys, all in 2026;
- every buy decided on an early-close session: 18 of 1,873;
- names with no 15:45 bar: 5 more.

**Sells are unchanged.** They are decided at 19:30 on the final data and
filled per the board's rule in t+1. The diagnostic found the delay helps
sells by 16-52 bp.

**The decision proxy**, fixed in advance, is the one in §3:

- row t from the cube through 15:45: the slot-24 close, and the high and low
  of slots 0-24 with the open;
- volume through 15:30, scaled by the trailing-20 median ratio;
- filings strictly before t;
- tone with a 15:45 acceptance cutoff;
- the gap at t−1, unless an improved gap is built and frozen before the run;
- one-step persistence, the gate and the grade rule;
- the executor's blocker and band z on the partial bar;
- the planner on the book at t.

The null test, row t equal to the final row reproducing the report and the
journal exactly, is a registered check before any fill is read. Choose 15:45
or 15:30 by what the live path can meet (see the notes below), not by
results.

**Fills.**

- **Candidate.** The official close of t: `auction_open`, else the slot-25
  close, times `session_scale`. This is `adj_close[t]`.
- **Control.** `dip_or_close` in t+1 on the same basis.
- **Gain.** Per order, g = `stage4_labels.gain` = 1e4 · ln(control /
  candidate), on the executed basis.
- **Costs.** Equal one-way costs on matched notional cancel.

**When the 15:45 decision differs from the final one.** Classify per
(session, name) as in §4:

- **Matched part** (the smaller of the two sizes): candidate fill against
  control fill.
- **Missed part** (19:30 wants more than 15:45 placed): it fills as the
  control, g = 0. This is what the 19:30 run would do: place the rest for the
  next session.
- **Extra part** (15:45 bought what 19:30 does not want): a round trip,
  bought at t's close and sold in t+1 by the board's sell rule, charged two
  one-way costs. Its P&L enters the session's bp.
  - This is conservative. The live executor would sell a below-A name at
    t+1's close through the rotation, but keep an A/A+ name bought too early.

**Robustness.** A full ledger walk of the candidate executor:

- 15:45 buys at t's close;
- at 19:30, the final plan's sells and the remaining buys on the actual book;
- extra positions left to the executor's own rules.

**Cash.** Fill t's closing sells, decided on t−1, before the market-on-close
buys. The budget is then the control's.

**Statistics.** Use stage 4's machinery:

- 20 start offsets, reading the median offset;
- bp of equity a session with a Newey-West t at lag 20;
- per re-timed order, the mean g with t clustered by date;
- the drift-adjusted reading (A/A+ drift μ times the session gained), as a
  diagnostic.

**Windows, the honest part.**

- 2018-2026 is contaminated. The diagnostic already measured this very
  quantity (C_t to the board's fill) on stage 4's orders from 2017-12-27.
- **2016-01-04 to 2017-12-26 is unexamined.** It has 423 executed buys, about
  0.84 a session at 3.2% of equity.
  - At the diagnostic's per-buy dispersion (about 214 bp, from +22.3 bp at
    t 3.4 on 1,065 buys), the naive SE there is about 10 bp.
  - A true +22 bp would read t ≈ 2.1 before clustering.
- The deciding evidence should be that window plus a forward shadow.
  - The shadow records the 15:45 decisions each session without trading,
    like the laggard and fidelity shadows.
  - At about 0.6-0.8 buys a session it adds roughly 150-200 buys a year.
- 2018-2023 and 2024-2026 are reported as in-sample replication, which must
  not reverse sign.

**Criteria: decide before registering.**

- Stage 4's criterion 1 is +2.0 bp of equity a session. The diagnostic's own
  estimate of this effect is about +0.9 bp a session in 2018-2023 and +2.2
  in 2024-2026, so under stage 4's criteria the study would almost surely
  RECORD even if the effect is real.
- The change costs nothing in trading cost. The auction has no spread, and
  the extra round trips are 1-7% of buy notional.
- A per-buy criterion therefore fits better: a positive mean g with clustered
  t ≥ 2 on the deciding windows, with the session-level bp and its NW t
  reported. Stage 4's "real but immaterial" rule is a per-order mean ≥ 25 bp
  at t ≥ 3.
- The cumulative trial count rises from 451 by the number of registered
  variants. Register one primary variant: 15:45 or 15:30, and the gap proxy.

**What the operator would see on the board.**

- **At the 15:45 balancer run**, or 15:30:
  - Every buy the 15:45 plan places reads, for example: "BUY 120 ADBE at
    today's close. Market-on-close, submit before 15:50 ET. Decided on the
    15:45 price $x; tonight's decision confirms".
  - SELLs from last night's record are unchanged: `dip_or_close` today.
- **The 19:30 record reconciles:**
  - confirmed: nothing to do;
  - bought at the close but tonight's grade is below A: a SELL next session,
    through the rotation;
  - not bought at the close but wanted: a BUY next session by
    `dip_or_close`, as today.
- **The board's existing "close" state** (from 15:30, market-on-close by
  15:50; `entry_timing.py:72-74`) is the natural place for the new row.

**Live implementation notes. These are not part of the study, but they decide
15:45 against 15:30.**

- **A 15:45 plan cannot be made today.** It would:
  - be refused while the market is open (`_submit`,
    `market_daily.py:439-445`);
  - be routed away from `paper.plan` whenever any order is pending
    (`market_daily.py:757-760`); at 15:45 last night's market-on-close sells,
    when there are any, still are, and `event_execution.plan` then plans
    nothing (line 36);
  - collide with `paper.plan`'s once-per-session guard
    (`paper.py:877-878`).
- **It must not run `desk.run`**, which takes 321 s. Precompute the t−1 states
  in the morning, and do the one-step update on the live quotes at 15:45:
  milliseconds.
- **Price and volume sources.** Price from the IEX quotes. Volume from SIP
  through 15:30, which the free plan allows at 15:45. Measure the path's
  latency; if it cannot submit by 15:50, register 15:30.

## 6. Uncertain or not measured

- **The book state.** The divergence figures are measured on the control's
  book at t. On the candidate's own path the book differs slightly, through
  earlier fills and extra positions. That is second order.
- **Order-level against full walk.** The round-trip accounting for extra buys
  is a convention; the full walk may differ.
- **The IEX-against-SIP basis** at 15:45 was not measured.
- **The research report's fundamentals (`/2`) differ from the nightly's
  (`/3`, with stance resets).** Resets come from filings, so they are known
  before the open, but the two reports' grades are not identical.
- **The leg attribution** uses a priority when a name has several legs in one
  plan. Stage 4's own `entry` and `add` labels do not map to legs.
- **Power.** The unexamined 2016-2017 window alone is marginal for an effect
  the size of the diagnostic's. The forward shadow is needed.

## Files

The scripts and outputs are on spark1 in `~/scratch/stage5/`: read-only
against the store, not committed. sha256 prefixes:

- **Part A**, the report arrays: `part_a.py` `98839318`, `part_a.npz`
  `4b222cd9`.
- **Part B**, grade changes and pending cells: `part_b.py` `c834aab0`,
  `part_b.npz` `06a9850b`.
- **Parts C and C2**, the one-step proxies and their comparison: `part_c.py`
  `d4909541`, `part_c2.py` `9f8a517e`, `part_c_m1545.npz` `c0f800c8`,
  `part_c_m1530.npz` `35760e2f`.
- **Parts D to D4**, the planner replay and the order tallies: `part_d.py`
  `b7b843bf`, `part_d2.py` `a8842e9c`, `part_d3.py` `43ce2bec`, `part_d4.py`
  `b4b20498`, `part_d_rows_m1545.npz` `107299a9`.
- **Part E**, release and filing acceptance times: `part_e.py` `f3bbbee0`.
- **Part F**, event buys and early closes: `part_f.py` `d26805aa`.
- **Part G**, tone without same-day scoring: `part_g.py` `382699f1`.
- **Part H**, small-count sessions and names crossing into A/A+:
  `part_h.py` `d936123c`.
