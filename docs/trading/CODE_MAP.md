# Code map: the trading system in plain words

Written 2026-10-27 from main at 2cad22de. Every claim was checked against the code and against
spark1 (crontab, scripts, data folders). All times are New York time; spark1's clock is set to it.
The rules for changing anything are in [RULES.md](RULES.md).

Words used below:
- **Book**: the 94 stocks the desk grades and may buy (AI and software names, two "sides").
- **Paper account**: a practice account at the broker Alpaca. Fake money, real prices.
- **Record**: the nightly file that holds one day's decision (`desk.json`).
- **Shadow**: something computed and written down every night but never traded.
- **Live**: the code runs in a scheduled job or in the web app and can affect what is traded or shown.

## 1. How a trade happens, start to finish

1. **08:45, weekdays. Option chains (display only).** `backend/cli/market_options.py` saves
   option open interest for the book from Cboe's free delayed feed into `data/market/options/`.
   The ticker page shows these as "option walls". They do not change grades or orders.

2. **09:00 to 16:45, every 15 minutes. The balancer.** `backend/cli/market_balancer.py` reads
   15-minute prices from Alpaca's free feed and writes `desk/live.json` and `desk/intraday.json`
   for the screens. It also sends any paper order that is due now
   (`backend/agents/trading/desk/intraday_orders.py`). On an FOMC decision day it sends the
   "restore" buys on the 15:45 candle (`backend/agents/trading/desk/decision_close.py`). If a
   planned FOMC cut was missed, it catches up (`backend/cli/market_event_recovery.py`).
   Since 2026-10-21 ordinary buys and sells go at the next open (step 9), so on most days the
   balancer sends nothing.

3. **19:30. The nightly run starts.** `~/desk_daily.sh` runs `backend/cli/market_daily.py` from
   the deployed copy of the code (`~/deploy/anios`). A lock (`backend/market/nightly_lock.py`)
   stops two nightly runs at once. Tonight's run wrote its record at 19:53.

4. **Prices.** `backend/market/snapshot.py` downloads daily prices from Yahoo
   (`backend/market/yahoo.py`) for about 535 tickers: the book, the S&P 500 research universe,
   SPY, QQQ, and four market series (VIX, 10-year yield, dollar, oil). They go into
   `data/market/bars/`, and splits and dividends go into `data/market/actions/`.

5. **Company filings (fundamentals).** `backend/market/edgar.py` (run through
   `backend/cli/market_edgar.py`) downloads SEC filings: earnings announcements and reported
   numbers, each tagged with the date it became public. `backend/market/fundamentals_asof.py`
   (run through `backend/cli/market_fundamentals_asof.py`) keeps every filed version, so a past
   day only sees what was public on that day. `backend/market/fundamental_features.py` turns
   these into growth and margin figures. `backend/market/levels_pit.py` gives revenue, earnings
   and share counts as known on each day. The value analyst uses those to compute price-to-sales.

6. **Earnings-release tone.** For each new earnings press release of a book company, the local
   AI model on spark1 (DeepSeek, port 8000) scores guidance, demand and pricing as -1, 0 or +1.
   This happens in `backend/cli/market_tone.py`, `backend/market/language.py` and
   `backend/agents/trading/release_tone.py`, and the scores go to `data/market/edgar_tone/`.
   The step has a 3-hour time limit. If the model is down, the old scores are kept.

7. **The analysts.** `backend/agents/trading/desk/desk.py` builds a price table for the 94 names.
   Five "analysts" each give every name a view (bullish, neutral or bearish) plus a strength:
   - fundamental: what the filings say (`backend/agents/trading/desk/fundamental.py`)
   - technical: price trend and position in its range (`backend/agents/trading/desk/technical.py`)
   - sentiment: the release tone from step 6 (`backend/agents/trading/desk/sentiment.py`)
   - value: price-to-sales against peers (`backend/agents/trading/desk/value.py`), plus the
     "expectations gap" from `backend/market/challenger.py`. That gap is a learned estimate of
     revenue growth minus the growth the share price already assumes.
   - rotation/regime: whether the AI side or the software side is leading
     (`backend/agents/trading/desk/regime.py`)

8. **Grades.** `backend/agents/trading/desk/grading.py` adds up the votes. Value counts 3,
   rotation 0.5, and the others 1 each. The total becomes a letter: A+, A, B or C. Any bearish
   core analyst caps the grade at B. (This file is in the desk folder, not in backend/market.)

9. **Target weights and orders (the live rule).** The installed rule is
   **grade-led-leader-weight/1** (`backend/market/grade_led_leader_policy.py`; the contract is
   `docs/research/grade-led-leader-weight-contract-2026-10-21.md`). In plain words:
   - It buys a name graded A or A+. It keeps a held name while it is B or better and sells it below B.
   - Each eligible name gets an equal slot. The slot is tilted from 0.5x to 1.5x by the name's
     last-63-day return rank. It is also tilted by where its P/E sits in its own last 3 years
     (cheaper than usual means a bigger slot).
   - The whole book is shrunk if its forecast volatility is above 25% a year. It never goes
     below half of full size, and it never borrows. What is left over stays in cash.
   - No name gets more than 25%. A change smaller than 1% of the account is not traded.
   - A buy is skipped on a night when the "band reversal" price signal fires for that name
     (`backend/agents/trading/desk/exit.py`, the only part of that file still in use).
   - FOMC rule (`backend/agents/trading/desk/event_risk.py`, version fomc-3-session-weakness/2):
     in the 3 sessions before a Fed decision, if SPY fell over the last 5 sessions, held shares
     are cut by half. They are bought back at 15:45 on decision day
     (`backend/agents/trading/desk/event_execution.py`, `decision_close.py`).

   `market_daily.py` first checks that the rule is properly released (see section 6,
   `backend/market/learned_live_holding.py`). Then it reads the Alpaca account and settles last
   night's orders. It plans with `backend/agents/trading/desk/nightly_plan.py`,
   `backend/market/joint_funded_policy.py`, `backend/agents/trading/desk/funded_execution.py`
   and `backend/agents/trading/desk/paper.py`. Buys only use cash already on hand. Orders are
   sent at about 19:50 (19:49 on 2026-10-21, 19:48 on 2026-10-22). FOMC restore buys are not
   sent at night; they wait for the balancer (step 2).

10. **Orders go to Alpaca.** `backend/market/alpaca_trading.py` sends whole-share market orders
    after the close. Alpaca holds them until the next open. The code refuses any broker address
    that is not the paper one, and refuses to send if it cannot read the market clock.
    The account's memory (pending orders, the order journal, targets) is
    `data/market/paper/state.json`.

11. **Fills, next morning about 09:30.** Alpaca fills the orders at the open. Recent fills landed
    between 09:30 and 09:33. The next nightly run reads back what filled and writes it into the
    journal in `state.json`. In the meantime the screen reads the broker directly through
    `/desk/paper`.

12. **The record.** Also during the nightly run:
    - `backend/market/grade_parity.py` regrades tonight from scratch the way the backtest would,
      and says OK or MISMATCH. Tonight it said OK for 94 names.
    - The record is saved to `data/market/desk/asof=DATE/desk.json`
      (`backend/market/deskrecord.py`). The run refuses to overwrite a day that already has one.
    - Per-name history for the charts is written to `data/market/history/`.
    - Old download partitions are pruned (30 days).
    - The AI model writes short briefs into `prose.json` beside the record
      (`backend/market/prose.py`, 45-minute limit).
    - Inflation notes go to `desk/economics/` (`backend/cli/market_economics.py`).

13. **Charts, 20:30 and 20:40.** At 20:30, `backend/cli/market_intraday_sip.py` adds the day's
    15-minute bars to `data/market/bars_15m_sip/`. At 20:40,
    `backend/cli/market_policy_replay_research.py` replays the installed rule over the whole price
    history with the account simulator `backend/market/policy_book.py`, and writes
    `data/market/research/policy-replay/leader_ewma_minB_floor50/DATE/`. The folder name is old;
    the run uses the current rule's settings. The stock charts draw their buy/sell markers from
    this, and the paper account's real fills come from the record and history files. The chart
    endpoint is `/desk/chart/{ticker}` and the replay endpoint is
    `/desk/strategy-simulation/{ticker}`.

## 2. What is live vs research

"Live" below means the code is loaded by a scheduled trading job or by the web app. I measured
this by following every `import` from the live entry points (nightly, balancer, options, SIP,
web app): 169 of the 304 files in `backend/market/` are loaded that way. Being loaded does not
always mean the file affects trades, so the table says what each part actually does.

| Area | Main files | Live? | What it does |
|---|---|---|---|
| Nightly job | `backend/cli/market_daily.py` | yes | Runs steps 3 to 12 |
| Prices | `backend/market/snapshot.py`, `backend/market/yahoo.py`, `backend/market/store.py` | yes | Daily prices from Yahoo, stored by date |
| Filings | `backend/market/edgar.py`, `backend/market/fundamentals_asof.py`, `backend/market/fundamental_features.py`, `backend/market/levels_pit.py` | yes | SEC numbers, only as known on each day |
| Release tone | `backend/cli/market_tone.py`, `backend/market/language.py`, `backend/agents/trading/release_tone.py` | yes | AI model scores earnings press releases |
| Analysts and grades | `backend/agents/trading/desk/` (desk, fundamental, technical, sentiment, value, regime, grading) | yes | The five views and the A+/A/B/C letter |
| Expectations gap | `backend/market/challenger.py` | yes | Extra input to the value analyst |
| Sizing rule | `backend/market/grade_led_leader_policy.py`, `backend/market/joint_funded_policy.py`, `backend/market/learned_live_holding.py` | yes | Target weights for the paper account |
| Order planning | `backend/agents/trading/desk/nightly_plan.py`, `funded_execution.py`, `paper.py` | yes | Turns weights into whole-share orders |
| FOMC rule | `backend/agents/trading/desk/event_risk.py`, `event_execution.py`, `decision_close.py` | yes | Half-size before weak Fed meetings |
| Broker | `backend/market/alpaca_trading.py` | yes | Paper account only |
| Balancer | `backend/cli/market_balancer.py`, `backend/agents/trading/desk/intraday_orders.py` | yes | 15-minute prices; sends due orders |
| Grade check | `backend/market/grade_parity.py` | yes | Live grades vs replayed grades, nightly |
| Labels | `backend/market/labels.py`, `frontend/src/services/labels.ts` | yes | Fixed word lists (BUY, A+, ...) instead of free text. Merged on main (913cf9f0, 5a8f8305); being deployed tonight |
| Web API | `backend/api/v1/market.py`, `market_simulation.py`, `market_allocation.py`, `market_history_sizing.py` | yes | Feeds the Desk screens |
| Screens | `frontend/src/components/DeskPanel/`, `frontend/src/services/api.ts` | yes | The Desk panel |
| Account simulator | `backend/market/policy_book.py`, `backend/cli/market_policy_replay_research.py` | research, run nightly | Backtest figures and chart markers for the installed rule |
| Old simulator | `backend/agents/trading/desk/simulate.py` | live but out of date | Draws the "Historical simulation" box. That box still shows the older graded-equal-weight/5 rule with older fill timing, not the installed rule (checked in tonight's record) |
| Policy shadow | `backend/agents/trading/desk/shadow_ledger.py`, `live_policy.py`, `policy_v5.py`, `policy_v4.py` | shadow | Runs the previous rule (graded-equal-weight/5) on paper every night; never sends orders |
| Other shadows | `backend/market/fundamentals_shadow.py`, `backend/market/reversal.py`, `backend/market/opportunity_shadow.py`, the "challenger" block in `market_daily.py` | shadow | Written into the record for comparison only |
| Old sizing | `backend/agents/trading/desk/risk.py` | recorded, not traded | The older "/3" book, still computed and saved |
| Exit analyst | `backend/agents/trading/desk/exit.py` | retired except one signal | Only its band-reversal signal is used, to block buys |
| Options | `backend/cli/market_options.py`, `backend/market/options.py` | yes, display only | Option open interest on the ticker page |
| 15-minute SIP bars | `backend/cli/market_intraday_sip.py`, `backend/market/intraday_sip.py` | yes, data only | Bars for the 15-minute chart |
| Laggard shadow | `backend/cli/market_laggard_shadow.py`, `backend/market/laggard_shadow.py`, `backend/market/stage3_*.py` | research only | Nightly forecast test. Runs from a separate copy pinned at 901c6824 (`~/shadow/anios`) |
| Research studies | About 120 other `backend/cli/market_*.py` and 135 `backend/market/` files (families: historical_*, live_model_history_*, stage3/4/5, nested_*, open_source_*, nonlinear_*, retention_*, intraday_*) | research only | Run by hand; no cron job and no live import |
| Research scratch (not in git) | `~/dsv41/` on spark1: forward/, llm_shadow/, estimates/, pit2/, universe/, cand-release/ | research only | Forward and AI-model shadows, estimate snapshots, S&P 500 point-in-time tests, release installer |

**Retired rules (code still present):** grade-led-learned-sizing/1 (replaced 2026-10-21).
graded-equal-weight/4 and /5 (now only the shadow). The "dip-or-close" order timing (since
2026-10-21 ordinary orders go at the next open). The IEX 15-minute cache `data/market/bars_15m/`
(blocked for scoring after a split-price fault, last written 2026-09-20). The balancer's
"green-day skip" only touches closing-time sells, and the current rule never makes those.
The installed release still carries and hash-checks older learned-model files
(`desk/learned-holding/model`, `risk`), but the leader rule does not use them to size.

**Dead modules (safe to call unused).** These 9 files are imported only by their own tests.
Nothing in `backend/`, `scripts/`, the crontab, the `~/desk_*.sh` wrappers or `~/dsv41`
imports or names them, and none can be run as a command:
`backend/market/daily_forecast_diagnostics.py` (542 lines), `historical_packet_acquisition.py` (539),
`historical_retained_forecast.py` (691), `intraday_single_source.py` (1,108),
`joint_funded_accounts.py` (173), `learned_archive.py` (471), `recorded_timing_inputs.py` (300),
`rl_readiness.py` (54), `timing_audit.py` (207), all under `backend/market/`.
How I checked: a script parsed every Python file's imports (including imports inside functions),
followed them from every entry point, and searched for each name as text. Apart from their tests,
only docs under `docs/` mention some of them.

**Unused screen calls.** `frontend/src/services/api.ts` defines these functions, but no screen
calls them: `getDeskEntries`, `getDeskStrategySimulation`, `getDeskLiveModelHistory`,
`getDeskFundingPreview`, `acknowledgeDeskHistory`, `deleteDeskPersonalReceipt`.
`getDeskIntraday` is imported by `DeskPanel.tsx` but never called. Their backend endpoints still
exist.

## 3. The screens

Everything lives in `frontend/src/components/DeskPanel/DeskPanel.tsx`. The main data call is
`GET /api/v1/market/{user}/desk`, which returns the newest record plus many extras. Live prices
refresh every 20 seconds.

**Header:** Stocks, Paper account, Archived research, an "i" help button, and "Analyze my trading".

**Stocks view:** `SignalBoard.tsx`, the current buy and sell signal and model size for each name.
It is fed by `/desk` (the record), `/desk/live` and `/desk/session-prices` (current prices), and
`/desk/model-allocation` (the published percentages).

**Paper account view, top to bottom:**
- Status lines: whether last night's record and briefs exist, and the market regime banner.
- Grade-check banner (from `grade_parity` in `/desk`), then notes on changed earnings data,
  unread earnings releases and expired tone readings.
- `TradeBoard.tsx`: tonight's plan, one row per name with action, grade, shares and timing.
  Fed by `/desk`, `/desk/live` and `/desk/paper`.
- "Personal portfolio": your own positions, typed in by you (`/desk/holdings` to read and save,
  `/desk/mine` for advice on them). Your real brokerage account is never traded from here.
- "Strategy details": the rule's name, the fundamentals data version, the FOMC box, what changed
  since yesterday, and planned cash. All from `/desk`.
- "Paper account": the account value over time (`PaperAccountHistory.tsx`, `/desk/paper/history`),
  plus positions, open orders and fills as the broker reports them now (`/desk/paper`).
- "Historical simulation": the curve saved in the record. It is labelled research, and it is the
  old simulator and old rule (see section 2).

**Ticker page (click any name):** latest grade, how each analyst voted, and the evidence.
- The model's plain-words technical read: `/desk/live/read/{symbol}`.
- The latest earnings release read: `/desk/earnings/{symbol}`.
- Grade changes and recent sessions: `/desk/history/{ticker}`.
- The installed rule's replay for this name: `/desk/strategy-simulation/{ticker}`.
- The chart (`TickerChart.tsx`): prices, decisions and fills from `/desk/chart/{ticker}`, saved
  recommendations from the `strategy-simulation/{ticker}/recommendation(s)` endpoints, and your
  saved advice from `/desk/personal-history`.

**Archived research view:** inflation notes (`EconomicContext.tsx`), `ForwardEvidence.tsx`,
`NeuralStudy.tsx`, `StrategyBench.tsx`, `FomcGate.tsx` (the FOMC rule against not using it),
`ExecutionQuality.tsx` (fill price vs decision price), the frozen-ML comparison and the board
simulation (from `StockBoard.tsx`). All of it comes from `/desk`, and none of it trades.

**Analyze my trading:** `/trading/autopsy` reads your own trading notes and names patterns.

## 4. Where the data lives

The live store is `~/anios/data/market`. `~/deploy/anios/data` is a link to `~/anios/data`, so
both paths point to the same files.

| Folder (under data/market) | What is in it | Written by | When |
|---|---|---|---|
| `bars/`, `actions/` | Daily prices; splits and dividends | nightly (`snapshot.py`) | 19:30 |
| `edgar_events/`, `edgar_facts/`, `edgar_facts_versions/` | SEC filings and every filed version | nightly | ~19:40 |
| `edgar_tone/` | AI tone scores of earnings releases | nightly (`market_tone.py`) | ~19:45 |
| `desk/asof=DATE/desk.json` (+ `prose.json`) | The day's decision record (+ AI briefs) | nightly | ~19:53 |
| `paper/state.json` | Paper account memory: pending orders, journal, targets | nightly; balancer when it sends | 19:50; market hours |
| `history/TICKER.json` | Per-name grades and decisions for charts | nightly | ~19:53 |
| `learned_inputs/` | Frozen copy of the inputs each night | nightly | ~19:53 |
| `desk/grade_parity.json`, `fomc-gate.json`, `execution.json`, `shadow/`, `ml-forward/`, `strategy-recommendations/` | Checks, shadows and published recommendations | nightly | ~19:50 |
| `desk/learned-holding/` | The installed release: config, release, evidence | by hand or by deploy (section 6) | at a release; last 2026-10-27 21:38 |
| `desk/live.json`, `intraday.json`, `intraday.log`, `event-live.json`, `entry-timing/`, `board-paper/` | Current prices and plan for the screens | balancer | every 15 min, 09:00-16:45 |
| `forward_actions_from_DATE/` | Splits and dividends for the board simulation | balancer | ~09:45 |
| `desk/session-prices/` | Display price snapshot | the web app's collector (`backend/services/session_price_collector.py`) | while the app runs |
| `options/` | Option open interest | `market_options.py` | 08:45 |
| `bars_15m_sip/` | 15-minute bars (consolidated feed) | `market_intraday_sip.py` | 20:30 |
| `research/policy-replay/` | The installed rule's replay | `market_policy_replay_research.py` | 20:40 |
| `research/forward-shadow/` | Forward test of rule variants | `~/dsv41/forward` | 20:50 |
| `estimates/` | Analyst estimates (Yahoo; Alpha Vantage backfill) | `~/dsv41/estimates` | 21:15; 06:20 |
| `research/llm-shadow/` | AI-model "analyst" calls, record only | `~/dsv41/llm_shadow` | 22:10 |
| `research/laggard_shadow/` | Laggard forecast ledger | `market_laggard_shadow.py` | 23:30 |
| `desk/strategy-model-history/`, `strategy-reference-book/`, `strategy-entries/`, `strategy-simulation/` | Audited history published once | one-off installs | last 2026-10-13 to 10-21 |
| `bars_15m_ext_sip/` | Extended-hours 15-minute bars | no repo code; research scripts | not on cron |
| `bars_15m/`, `edgar_insiders*/`, `edgar_statements/`, `models/`, `bar_reconciliations/` | Old one-off downloads | nothing current | last Sep 5 to Oct 2 |

The research cron jobs (forward shadow, AI shadow, estimates, laggard) write into this live store,
but only into `research/` and `estimates/`. Their crontab comments call them research-only and
say they write nowhere else. Rule 6 in RULES.md says research never writes to the deploy store,
so the owner may want to decide whether these count as exceptions.

## 5. Scheduled jobs (spark1 crontab, weekdays unless noted)

| Time | Line | In plain words |
|---|---|---|
| 08:45 | `backend.cli.market_options --refresh` (from `~/anios`) | Save today's option open interest for the book. Display only. |
| every 15 min, 09:00-16:45 | `~/desk_intraday.sh` → `market_balancer` | Refresh live prices and the plan for the screens; send any paper order due now. |
| 19:30 | `~/desk_daily.sh` → `market_daily --refresh --brief-book --paper-trade --challenger --prune-days 30 --top 30` | The nightly run: data, grades, paper orders, record, briefs. The only job that decides trades. |
| 20:30 | `~/desk_sip.sh` → `market_intraday_sip` | Add today's 15-minute bars and check them against the daily bars. |
| 20:40 | `~/desk_replay.sh` → `market_policy_replay_research` | Waits for tonight's record, then redraws the installed rule's chart replay. |
| 20:50 | `~/desk_forward.sh` → `~/dsv41/forward` | Research: forward test of rule variants on the book and on the S&P 500 tech/communications universe. |
| 21:15 | `~/desk_estimates.sh` → `~/dsv41/estimates/archive.py` | Research: save analyst estimates and valuation multiples from Yahoo. |
| 22:10 | `~/desk_llm_shadow.sh` → `~/dsv41/llm_shadow` | Research: ask the AI model for a call on each name; record only. |
| 23:30 | `~/desk_shadow.sh` → `market_laggard_shadow nightly` | Research: laggard forecast ledger, from the pinned copy `~/shadow/anios`. |
| 06:20 daily | `~/desk_estimates_backfill.sh` → `~/dsv41/estimates/backfill_av.py` | Research: fill in past estimates from Alpha Vantage, 24 names a day, until done. |

Every job runs from `~/deploy/anios`, the copy that passed the deploy gate, except two: the
options job runs from `~/anios` and the laggard shadow from `~/shadow/anios`. `~/desk_recover_0914.sh` exists but is not in the crontab; it was a one-off fix for
2026-09-14. A disabled `@reboot` line for an old model server is unrelated to trading.

## 6. Safety rails

- **Release admission and the 44 bound sources.** `learned_live_holding.source_identity()` takes
  a fingerprint (SHA-256) of 44 files: 41 code files that prepare, size and send the plan, plus 3
  contract documents. The fingerprints must match `data/market/desk/learned-holding/release.json`.
  If any of those files change without a new reviewed release, the nightly refuses to trade.
  Because the release is installed, it then also stops before writing that night's record. The
  log shows this happened three times ("Exact reviewed learned holding release required").
  *Protects against:* a code change quietly changing how real orders are made.
  New releases are prepared as a folder under `docs/research/trading-approval-candidates-DATE/`
  and installed with `~/dsv41/cand-release/install_leader_release.py`, or with
  `backend/cli/market_release_admission.py activate` during a deploy. Tonight's release
  (approved 21:38) covers the labels change (18 of the 44 files changed).
- **Admission check.** `scripts/check-trading-admission.sh` runs
  `market_release_admission check` both on spark1 and inside the app container. It prints
  ADMITTED only if both agree. *Protects against:* the cron jobs and the app running different code.
- **AST pins.** `backend/tests/test_reconciliation_release_admission.py` stores a structural
  fingerprint (of the parsed code, ignoring layout) of `backend/cli/market_daily.py` and
  `backend/market/live_model_decision.py`. Any change to those files fails this test until
  someone recomputes the pin on purpose. *Protects against:* a narrow "fill reconciliation" review
  being used to approve other changes to the nightly.
- **Deploy gate.** `scripts/deploy.sh` is the only deploy path. In order, it:
  1. tests the new commit in a separate copy (full unit suite, then `scripts/gate.sh`);
  2. checks the trading release;
  3. only then moves `~/deploy/anios`, rebuilds, installs the reviewed trading release, and restarts;
  4. runs the admission check and writes `data/.post-deploy-status`.

  It will not start between 19:20 and 19:55, and it waits for a gap between balancer runs.
  A frontend-only change skips the tests. *Protects against:* untested code reaching the cron jobs.
  (A deploy of 5a8f8305 was running while this was written; the last finished deploy is 54908830.)
- **One engine for tests of the rule.** `backend/tests/test_policy_book.py` checks that the
  simulator's defaults equal the installed rule and that its FOMC cycle matches the live one.
  Note: the live account is planned by different code (`joint_funded_policy.py` and `paper.py`)
  that shares the same sizing function (`leader_weights`). No nightly job compares the account
  with `policy_book.simulate()`. The "live parity" is these tests, not a runtime check.
- **Nightly grade check.** `backend/market/grade_parity.py` (see step 12). The screen shows a
  banner when it fails. *Protects against:* the board showing grades the backtest would not give.
- **Smaller guards.** Paper broker address only (`alpaca_trading.client_from_env`). No orders if
  the market clock cannot be read. One nightly at a time (`nightly_lock.py`). A day's record is
  never overwritten without `--force`. Prose and model calls run under time limits, so a hung
  model cannot block the record.

## Could not determine

- (Resolved after writing.) Tonight (2026-10-27) the nightly stopped after "history: 94 names
  written" because the 30-day prune hit root-owned partitions from September (`bars_15m/asof=2026-09-19`,
  `-20`, `edgar_facts|edgar_events/asof=2026-09-26`, written by a container). The record and orders were
  already written; only the prune, the briefs and the economics note were skipped. Ownership was fixed
  the same night.
- What writes `data/market/bars_15m_ext_sip/`. No repo code or cron job names it, yet it changed
  at 08:41 today.
- Whether anyone still runs the ~120 research `market_*.py` commands by hand. I could only show
  that no cron job and no live code uses them.
- I did not run `scripts/check-trading-admission.sh`, because a deploy was in progress in
  `~/deploy/anios`. So I cannot say whether the new release reads ADMITTED.
- I traced imports, not run-time calls. A file that the live jobs load may still do nothing on a
  normal night.
