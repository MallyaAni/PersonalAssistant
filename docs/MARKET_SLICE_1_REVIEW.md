# Review of `b38c64e2` — stock-analysis foundation, slice 1

Reviewed 2026-09-04 against the live tree. Every claim below was checked by
reading the code, running the tests through the spark1 tunnel, or querying
the live database. Written to be handed to the agent that continues the work.

## What was verified

| Check | Result |
| --- | --- |
| 15 new tests | 15/15 pass with the DB tunnel up (12 pass without it; the 3 repository tests need Postgres) |
| Migration `20260905_0018` on the live DB | applied; `alembic_version` = `20260905_0018`; `market_daily_bars` exists and is empty |
| Real Yahoo fetch | still 429 from both this desktop and spark1 at 22:10 EDT; a successful fetch+store has never happened |
| `range=730d` accepted by Yahoo | unverified (blocked by the 429). Yahoo's documented ranges are `1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max`; `period1`/`period2` epoch params are the safe form |
| torch on spark1 | not installed (host python and backend container); no training environment exists |
| Diagram / catalog registration | none. The change adds a persistent store and an external dependency, which AGENTS.md says requires a diagram update |

## Verdict

The slice is competent plumbing pointed at the wrong data source, stored in
the wrong place, framing the wrong learning problem. Nothing in it touches
the actual ask (structure-driven buy/sell on CRWV/IREN/SNDK, position sizing,
sector rotation), and the parts that exist would have to be rebuilt before a
serious model could be trained on them. Keep the shape of the code (universe,
fetch, store, windows, CLI, tests), replace the substance.

## Defects in what shipped

1. **The reproducibility claim is false.** `adjusted_close` is back-adjusted:
   every dividend on MSFT, ORCL, CSCO, ETN, AVGO, STX or WDC rescales that
   ticker's entire history on the next fetch, and the upsert overwrites the
   old rows and their `retrieved_at`. A snapshot taken today and one taken
   next month produce different return series for the same dates, and
   nothing records that they differ. Fix: store raw OHLCV plus split and
   dividend *events*, adjust at read time, and keep an immutable as-of
   dimension (a parquet directory per fetch date is the simplest).

2. **The live partial bar is stored as a closed session.** During market
   hours Yahoo's last bar is the in-progress day. `fetch_daily_bars` stores
   it; nothing drops a bar whose session is not complete. A refresh at 2pm
   writes a fake close; a window built before the next refresh trains on it.

3. **The fetch is what earns the 429.** Twenty-three back-to-back requests,
   no delay, no backoff, no `Retry-After`. Also synchronous `urllib` inside
   an `async` function, which blocks the event loop if this is ever called
   from the backend rather than the CLI.

4. **Research data was put in the production AniOS database.** That DB has
   nightly dumps only and no PITR. Market bars are bulk, immutable,
   re-fetchable data with no relationship to anything the assistant stores.
   spark1 has 2.9 TB free on its NVMe. Leave the empty table alone (no
   destructive DDL on that DB) and do not extend it.

5. **Rule misses.** No `Diagram impact:` line and no diagram for a new store
   and external dependency. `build_parser`, `_run`, `main`, `_at`,
   `_int_or_none`, `_row_count` and every test helper lack the required
   function comment. `_log` imports `math` inside the function with a
   comment claiming this makes it "bit-for-bit reproducible"; it does not do
   anything. `status` loads every bar for a ticker just to count them.
   `test_windows_have_expected_shape_and_channels` says it checks the
   market-relative channel and asserts nothing about it.

## Why the design cannot reach the goal

**Not enough data, and the wrong kind.** 23 hand-picked tickers over 730
calendar days is roughly 11,000 overlapping daily windows. CRWV has traded
since 2025-03-28 (about 360 bars) and SNDK since 2025-02-24. A neural
network trained on that learns noise. The universe is also today's winners
(SMCI, VRT, ANET), which is survivorship bias built into the training set.

**The wrong learning problem.** `windows.py` frames this as per-ticker
regression of a 20-day forward return from a 20-day window of three channels.
Signal-to-noise on 20-day single-name returns is close to zero, the labels
overlap 20:1 with daily stride so any naive split leaks, and the three focus
names contribute a few hundred samples. "Structure" (bases, breakouts,
consolidation, gap behaviour) lives in open/high/low and volume, and the
builder throws O/H/L away.

**Rotation is defined but never measured.** The theme baskets exist in
`universe.py` and are used by nothing. The only relative channel is versus a
single benchmark. Sector rotation is a cross-sectional phenomenon: money
moving between baskets on a date. It has to be a feature and a label, not a
tag.

## What top tier looks like

1. **Data.** A keyed provider with split and dividend events per row and the
   whole liquid US universe: Tiingo (free key, EOD with `adjClose`,
   `divCash`, `splitFactor`, near-complete US coverage) or Polygon Starter.
   Store as parquet on spark1 (`asof=YYYY-MM-DD/` partitions, immutable),
   query with DuckDB. Universe: every US common stock above a cap and ADV
   floor, industry from the provider, plus ETF baskets (SMH, SOXX, IGV, XLK,
   XLU, and the memory/networking/power names as explicit overlays). The
   three focus names are *targets for sizing*, not the training set.

2. **Framing.** Cross-sectional ranking, not per-ticker regression. On each
   date the model scores every name; the loss is rank-based (pairwise or
   IC-maximising), the label is decomposed into market + theme + residual so
   the model learns rotation (theme component) and stock selection
   (residual) separately. Horizon 5 to 20 sessions, weekly rebalance.
   Daily bars are correct for this; intraday is a different system.

3. **Harness before model.** Walk-forward with purge and embargo equal to
   the horizon. Baselines that must be beaten out-of-sample: 12-1 momentum,
   20-day relative strength versus SMH, equal-weight theme momentum, and
   the hand-coded sector report. Metrics: rank IC, IC decay, turnover,
   cost-adjusted PnL at realistic spreads. If the network does not beat the
   baselines net of costs, it is not used.

4. **Inputs.** Own log return, gap (`log(O/prevC)`), range (`log(H/L)`),
   close position in range, log dollar volume, return relative to market,
   return relative to own theme basket, theme-basket return relative to
   market, realised vol. Emit `label_end_date` beside the label so the
   harness can purge. Emit benchmark and theme forward returns beside the
   own forward return.

5. **Position sizing.** Volatility-targeted: size = target risk / realised
   vol, scaled by model score, capped per name and per theme, with a
   drawdown throttle. The three focus names get a theme-exposure budget so
   "rotation out of AI infra" reduces all three, not one.

6. **DeepSeek V4 Flash's role.** Not the price predictor. It is the layer
   that turns text into features (earnings calls, hyperscaler capex
   guidance, memory pricing news, filings) on a schedule, writes the daily
   research brief from the model's outputs, and generates the experiment
   code. That is where a 1M-context local model has an edge; numeric
   forecasting from a table of returns is not.

7. **Training environment.** A decision, not a slice: a `research` venv or
   image on spark1 with torch for aarch64 CUDA, separate from the backend
   container. A cross-sectional model of this size needs well under 1 GB of
   GPU memory, inside the 9.9 GB budget.

## Suggested order

1. Swap the source for Tiingo, store raw + events as parquet on spark1,
   drop the partial-bar problem by only storing sessions that have closed.
2. Broaden the universe; add industry tags and the ETF baskets.
3. Build the walk-forward harness and the four baselines; report rank IC
   and net PnL for them. This is the first number that means anything.
4. Only then a model, starting with a small cross-sectional MLP or a
   gradient-boosted ranker as the reference before any sequence model.
5. Position sizing on top of whatever beats the baselines.
