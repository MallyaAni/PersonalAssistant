# Implementation specs — volatile book and 15-minute engine (2026-09-26)

Read-only specs written by parallel spec agents against HEAD 990fa981 before implementation.
They are inputs for the Wave 1 agents, not a record of what shipped; the status table in
[TRADING_VOLATILE_BOOK_ARCHITECTURE.md](../../TRADING_VOLATILE_BOOK_ARCHITECTURE.md) is the record.
The parallel work-breakdown spec failed (usage limit) and is replaced by the wave table in that doc.

## sip-15m-data

**Item.** Qualified delayed-SIP 15-minute history (plus 1-minute fill windows) for the book and SPY/QQQ. It covers fetch parameters, a multi-symbol paged fetch, raw-basis append-only store kinds with provenance, a reconciliation and acceptance gate against the daily store, early-close-safe session slicing, a CLI with backfill, append, accept, estimate and nightly modes, and live-shaped recorded fixtures.

**HEAD.** 990fa9819a514c939b1777dca66b73e0e7e97a6d (working tree has no backend/ changes relative to HEAD. The only uncommitted edits are AGENTS.md, deploy/spark/*, docs/NEXT_SESSION.md and wifi-watchdog files, which belong to another agent and none of which are cited as code anchors.)

### Current state

FETCH
- backend/market/alpaca.py:52 has _BARS_URL = https://data.alpaca.markets/v2/stocks/bars, and :54 has BARS_KIND='bars_15m'. At :88, Transport is (url, headers) -> (status, body). Response headers are not returned, so Retry-After cannot be read.
- alpaca.py:112-136 parse_bars_page(payload, symbol) reads payload['bars'][symbol] and returns (bars, next_page_token).
  - It silently skips malformed rows (:134-135), which intraday_single_source.py:16-17 already calls out.
  - It drops Alpaca's 'n' (trade count) and 'vw' (VWAP).
- alpaca.py:139-172 fetch_bars(symbol, start, end, transport, headers, sleep) fetches one symbol at a time.
  - The URL hard-codes timeframe=15Min&feed=iex&adjustment=all&limit=10000&sort=asc, with UTC day bounds {start}T00:00:00Z / {end}T23:59:59Z (:153-157). Those bounds are not New York session bounds.
  - page_token is appended unquoted (:158-159).
  - On 429 it sleeps 5 s and retries inside a 10,000-iteration loop (:152, :161-163), which is effectively unbounded.
  - Every other non-200 raises (:164-165). json.loads is unguarded (:166). It sleeps 0.35 s between pages (:170-171).
- bars_frame / bars_from_frame (:175-201) store start as an ISO string plus OHLCV. sessions() (:204-214) uses a fixed 09:30-16:00 window.
- Callers:
  - Live: live_quotes.quotes defaults fetch=alpaca.fetch_bars (live_quotes.py:131-137) and calls fetch(symbol, today, today, headers=headers) (:153). This must stay IEX.
  - backend/cli/market_intraday.py:63.
  - backend/cli/market_pick_audit.py:125-140. _historical_transport rewrites the URL string 'feed=iex' to 'feed={feed}', and _intraday loops symbols one at a time.

CACHE CLI
- backend/cli/market_intraday.py:23-35 accepts --refresh --status --tickers --roles --since (default 2016-01-01) --asof --data-dir.
- :57-79 refetches each ticker's full history into kind bars_15m at partition asof=today. It skips the ticker when has_frame is true (:58).
- Metadata is only {source: 'alpaca-iex', since} (:73). Feed, adjustment, timeframe, fetched_at and the request identity are not persisted, and there is no append mode.

STORE
- backend/market/store.py:130-156 write_frame is immutable per (kind, asof, ticker). Metadata values must be str (:151-154). Writes are atomic via tmp+rename (:330-334).
- :158-161 has_frame. :163-178 read_frame returns only the single newest partition <= asof; it never merges partitions. :180-193 _latest_of_kind ignores non-directories.
- :246-289 read() returns a daily TickerHistory with actions.
- Daily basis (backend/market/yahoo.py:22-27): close is split-adjusted as of the fetch; adjusted_close is split- and dividend-adjusted; there is no raw series. Splits are stored as ratio numerator/denominator (:144-149).
- backend/market/levels_pit.py:131-144 _splits(store, ticker, asof) returns [(date, ratio)].

PROVENANCE PATTERN
- backend/market/intraday_cache.py:76-88 defines CacheProvenance(source_path, sha256, partition_label, metadata_source, price_basis, row_count, data_bounds, limitation).
- :163-185 _read_cache hashes exactly the bytes it parses (pq.read_table(pa.BufferReader(payload))).
- :54 INTRADAY_SOURCE='alpaca-iex'; any other source is rejected (:174-177). :188-197 accepts only the 'adjusted' basis. SIP frames under a new source label therefore cannot leak into the IEX adapter.
- intraday_single_source.py:283-307 _check_page checks each page's {status, sha256, body} and its JSON. :342-450 runs the pagination-chain refusal gates: request_page_token continuity, cyclic tokens, truncated last page. :117-118 set 26 bars for a full session and 14 for an early close.

CALENDAR
- calendar.py:112-127 _published_early_closes covers 2019-2028 only. :138-140 session_close() silently returns 16:00 outside that coverage. That is deliberate for live readers.
- calendar.py:97-109 reviewed_sessions() has live users: live_technical.py:757-758 and ticker_chart.py:91-93. It also feeds publication_session (:143-160) and edgar.py:647-652, whose strict-publication path drops pre-2019 filings because publication_session returns None.
- data/nyse_historical_sessions.json covers 2019-2025, and nyse_holidays.json / nyse_early_closes.json cover 2026-2028. 2016-2018 has no reviewed holidays or early closes, and those are the first 754 of the 1,259 sessions in the primary 2016-2020 window.
- intraday_inputs.py:19-56 ResearchCalendar.close_time raises 'calendar coverage unavailable' for uncovered years (fail-closed). :59-92 load_calendar. tests/test_intraday_inputs.py:24 pins 2018 as uncovered.
- intraday.py:23 hard-codes ROOT=data/market/bars_15m, and :70-85 sessions_from uses 09:30 plus a fixed 26 slots, so it does not know about early closes.

UNIVERSE
- universe.py:343-372 book_sides() returns 94 names at HEAD. CRWV, IREN and SNDK are not members. The member role has 528 names, 437 of them outside the book. Benchmarks include SPY and QQQ.
- :234-236 source_symbol maps BRK.B to BRK-B for Yahoo. Alpaca needs the dotted form.

LOCK
- nightly_lock.py:80-110 acquire(root) is flock-based. market_daily.py:1461-1474 holds it for the desk nightly. Host cron is intraday */15 9-16 and evening 30 19, per NEXT_SESSION.md:7896. The launch scripts live outside the repo.

EVIDENCE THAT DRIVES THE DESIGN
- intraday-comparison-input-audit-2026-09-22.md:5-22: across 782,568 closes, the median cross-provider |diff| is 0.028% but p99 is 9.83%, and AVGO's median ratio is 9.9964.
- intraday-price-basis-reconciliation-2026-09-22.md:14-21, last regular close on each date:

  | Symbol / date | Cached | Daily adj | Alpaca raw | Alpaca all | Yahoo close |
  |---|---:|---:|---:|---:|---:|
  | AVGO 2024-07-12 | 1667.26 | 166.93 | 1698.62 | | |
  | WDC (pre-spin) | | | 68.715 | | 51.935 (≈68.715 / 1.3231) |
  | APTV 2026-03-31 | | 69.44 | 69.445 | 58.83 | |

  So Yahoo encodes the WDC spin-off as split 1.323, while for APTV Alpaca's all basis disagrees with Yahoo.
- extended-hours-source-options-2026-09-25.md:56-79: one approved SIP request (1Min, raw) returned HTTP 200 with 3,316 bars. Free SIP history needs end at least 15 minutes old (:21-24).
- NEXT_SESSION.md:1004 at HEAD: probe allowances are exhausted, so every new provider request needs a fresh, bounded allowance.

DESIGN CONSEQUENCES
1. adjustment=all cannot support append. A corporate action after the base fetch rescales history, so a later delta lands on a different basis; this is the mechanism behind the AVGO ~10x defect. Alpaca's all also disagrees with Yahoo on spin-offs. The canonical SIP store must therefore be adjustment=raw, with split and total-return views derived at read time from the same pinned daily partition the gate used.
2. 2016-2018 calendar coverage must be added without touching reviewed_sessions(), otherwise EDGAR and expectations history change.

### Changes

#### `backend/market/alpaca.py` — _bars_url (new, pure)

Comment: '# Build one bars-endpoint URL; the defaults reproduce the legacy IEX request byte for byte.'

Signature: _bars_url(symbols: str, start: str, end: str, *, timeframe: str = '15Min', feed: str = 'iex', adjustment: str = 'all', limit: int = 10_000, page_token: str | None = None, quote_token: bool = False) -> str

It returns f'{_BARS_URL}?symbols={symbols}&timeframe={timeframe}&feed={feed}&adjustment={adjustment}&limit={limit}&sort=asc&start={start}&end={end}'. When a page_token is given it appends '&page_token=' followed by the token, which is urllib.parse.quote(token, safe='') when quote_token is set and the raw token otherwise. Parameter order is identical to alpaca.py:154-159.

#### `backend/market/alpaca.py` — fetch_bars

New signature: fetch_bars(symbol, start, end, transport=alpaca_transport, headers=None, sleep=time.sleep, *, timeframe: str = '15Min', feed: str = 'iex', adjustment: str = 'all') -> list[IntradayBar].

The new parameters are keyword-only, so positional callers (live_quotes.py:153, market_intraday.py:63, market_pick_audit.py:135) are untouched.

The parameters are validated against TIMEFRAMES / FEEDS / ADJUSTMENTS, and a bad value raises ValueError before any transport call.

The URL is built with _bars_url(symbol, f'{start.isoformat()}T00:00:00Z', f'{end.isoformat()}T23:59:59Z', ..., quote_token=False). With the defaults, every request URL, the unquoted page_token, the 5 s sleep on 429, the 0.35 s sleep between pages and the error text are byte-identical to HEAD.

The docstring names the three parameters and states that the IEX defaults serve the live candle loop.

#### `backend/market/alpaca.py` — module constants and errors (new)

FEEDS = ('iex', 'sip'). ADJUSTMENTS = ('raw', 'split', 'dividend', 'all'). TIMEFRAMES = ('1Min', '5Min', '15Min'). MAX_BARS_PER_PAGE = 10_000 (inherited from the API limit, alpaca.py:155).

REQUESTS_PER_MINUTE = 190. Inherited: the Basic plan allows 200/min (alpaca.py:170); 190 leaves headroom.

SIP_MIN_AGE = timedelta(minutes=16). Inherited: the Alpaca FAQ requires end at least 15 minutes old (extended-hours-source-options :21-24); one minute is added as margin.

MAX_SYMBOLS_PER_REQUEST = 100 (default). RETRY_429 = (5, 10, 20, 40, 60, 60) and RETRY_5XX = (2, 5, 15) (defaults; the 5 s first step is inherited from :162).

class AlpacaEntitlementError(AlpacaUnavailableError), raised on HTTP 403 with the body's message and no retry. class RequestBudgetExceeded(AlpacaUnavailableError).

Every class and constant block gets a plain-language comment.

#### `backend/market/alpaca.py` — alpaca_symbol (new, pure)

alpaca_symbol(ticker: str) -> str returns ticker.strip().upper().replace('-', '.'). It is the inverse of universe.source_symbol (universe.py:234-236), so BRK-B is requested as BRK.B, and the response keys are mapped back to store tickers.

#### `backend/market/alpaca.py` — RequestPacer (new dataclass)

RequestPacer(per_minute: int = REQUESTS_PER_MINUTE, max_requests: int | None = None, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep). It carries a count and a deque of recent request instants.

acquire() sleeps until fewer than per_minute requests fall inside the trailing 60 s. It then records the request and raises RequestBudgetExceeded once count would exceed max_requests.

One pacer is shared across a whole CLI run, so the 200/min limit and the operator's request budget hold across symbols and phases.

#### `backend/market/alpaca.py` — PageReceipt, MultiFetch, canonical_request (new)

PageReceipt(index: int, request_page_token: str | None, next_page_token: str | None, status: int, body_sha256: str, rows: dict[str, int]) is a frozen dataclass.

MultiFetch is a frozen dataclass with these fields:
- bars: dict[str, list[IntradayBar]], keyed by store ticker
- extras: dict[str, list[tuple[int | None, float | None]]], holding (trade_count, vwap) aligned index-for-index with bars
- request: dict
- request_sha256: str
- fetched_at: datetime (UTC, first request)
- receipts: tuple[PageReceipt, ...]
- pages: tuple[dict, ...], filled only when record_pages=True, as {status, sha256, body, request_page_token}. That is the shape intraday_single_source._check_page (:283-307) already validates.

canonical_request(symbols, start, end, *, timeframe, feed, adjustment, limit) -> tuple[dict, str] returns the request dict {endpoint, symbols (sorted Alpaca form), timeframe, feed, adjustment, start, end (RFC3339 Z), limit, sort: 'asc'} and the sha256 of json.dumps(sort_keys=True, separators=(',', ':')). The hash never includes credentials or page tokens.

#### `backend/market/alpaca.py` — row_extras (new, pure)

row_extras(payload: dict, symbol: str) -> list[tuple[int | None, float | None]] returns (int(row['n']) or None, float(row['vw']) or None) per row of payload['bars'][symbol]. It is used only after the strict count check guarantees index alignment with parse_bars_page's output.

#### `backend/market/alpaca.py` — fetch_bars_multi (new)

Comment: '# Fetch several symbols in one paged request stream, keeping every page's hash and refusing silent row loss.'

Signature: fetch_bars_multi(tickers: Sequence[str], start: datetime, end: datetime, *, timeframe: str, feed: str, adjustment: str, transport: Transport = alpaca_transport, headers: dict[str, str] | None = None, pacer: RequestPacer | None = None, sleep: Callable[[float], None] = time.sleep, now: Callable[[], datetime] = lambda: datetime.now(UTC), record_pages: bool = False) -> MultiFetch. feed, adjustment and timeframe are required keywords, with no defaults.

Behaviour, in order:
1. Tickers are deduped, mapped with alpaca_symbol and sorted. More than MAX_SYMBOLS_PER_REQUEST raises ValueError. start and end must be aware datetimes with start < end.
2. If feed == 'sip' and end > now() - SIP_MIN_AGE, raise ValueError before any call.
3. Each page first calls pacer.acquire(). The URL is _bars_url(','.join(symbols), ..., quote_token=True).
4. Status handling:
   - 429 retries on the RETRY_429 schedule, then raises AlpacaUnavailableError.
   - 5xx or a transport exception retries on the RETRY_5XX schedule, then raises.
   - 403 raises AlpacaEntitlementError at once.
   - Any other non-200 raises with at most the first 200 bytes of the body.
   - A non-JSON body raises AlpacaUnavailableError.
5. A key in payload['bars'] that was not requested raises. For each requested symbol, parse_bars_page(payload, symbol) is reused (per the item spec). If len(parsed) != len(raw rows), it raises 'malformed rows'. It never drops silently.
6. A duplicate (symbol, start) across pages, a non-ascending start per symbol, or a repeated or cyclic next_page_token (the rule from intraday_single_source :342-450) raises.
7. The stream stops when next_page_token is null. It raises after 10,000 pages.

Nothing is written to disk. The legacy fetch_bars loop is unchanged.

#### `backend/market/intraday_sip.py (new)` — kinds, source and gate constants

Kinds:
- SIP_15M_KIND = 'bars_15m_sip' (feed sip, adjustment raw, timeframe 15Min; append chain)
- SIP_15M_ALL_KIND = 'bars_15m_sip_all' (feed sip, adjustment all; snapshot only, never accepted, append refused)
- SIP_1M_WINDOW_KIND = 'bars_1m_sip_window' (raw, 1Min, fill windows; append chain)
- SIP_15M_ACCEPTANCE_KIND = 'bars_15m_sip_acceptance'
- SIP_1M_WINDOW_ACCEPTANCE_KIND = 'bars_1m_sip_window_acceptance'

SOURCE = 'alpaca-sip'. SCHEMA_VERSION = '1'. REFERENCE_SYMBOL = 'SPY'. EXTENDED_START = time(4, 0) and EXTENDED_END = time(20, 0), inherited from the UTP schedule cited in extended-hours doc :114-116.

WINDOWS = (('open', offset 09:30, 45 minutes), ('close', session close - 30 min, 35 minutes)). The close window includes the first post-close minute that carries the closing-auction print. It is early-close aware, becoming 12:30-13:05. These are defaults; confirming them is open question 5.

Gate constants, all defaults recorded with rationale in the research note and never tuned per symbol or on 2016-2020 data:
- CLOSE_TOLERANCE = 0.03, as |ln| between the last regular bar close and the daily close. It fences gross scale error while allowing the gap between the last pre-16:00 trade and the auction close.
- REGIME_TOLERANCE = 0.01, as |median ln| over a split regime, catching basis factors of 1% or more.
- MIN_REGIME_SESSIONS = 5.
- RANGE_TOLERANCE = 0.02.

QUARANTINE_REASONS is ordered, and the first failing gate wins: calendar_uncovered, bars_on_closed_day, off_grid, duplicate_bar, invalid_ohlc, no_bars, no_closing_bar, no_daily_reference, close_mismatch, range_mismatch, calendar_tape_conflict, regime_too_short, basis_offset.

#### `backend/market/intraday_sip.py (new)` — load_sip_calendar, sip_close_time, session_bounds, last_settled_session

load_sip_calendar(directory=intraday_inputs.DATA) -> ResearchCalendar returns intraday_inputs.load_calendar() merged with data/nyse_sessions_2016_2018.json. It applies load_calendar's validations: weekday, year match, no duplicates, no holiday/early-close overlap, early closes only at 13:00, and every year carries at least one official source. It refuses any year overlap with the existing files. calendar.py, reviewed_sessions and publication_session are NOT changed, so live, EDGAR and expectations paths keep 2019+ coverage.

sip_close_time(day, calendar) -> time | None wraps calendar.close_time. It raises for uncovered years, so there is never a silent 16:00. For every 2019-2028 session it equals calendar.session_close(day), which a test enforces.

session_bounds(day, calendar) -> (extended_start_utc, open_utc, close_utc, extended_end_utc) uses ZoneInfo('America/New_York'), so it is DST-correct.

last_settled_session(now_utc, calendar, settle_sessions=1) -> date returns the newest session s with now >= s 20:00 ET + SIP_MIN_AGE, then steps back settle_sessions sessions with calendar.offset. settle_sessions=1 is a default whose rationale is late SIP trade corrections; it is measured by the overlap check in the CLI.

#### `backend/market/intraday_sip.py (new)` — segment_columns, segment_metadata, write_segment

segment_columns(bars, extras, *, windows: list[tuple[str, str]] | None = None) -> dict[str, list] returns alpaca.bars_frame(bars) columns (start ISO, open, high, low, close, volume) plus trade_count and vwap. For the 1-minute kind it adds session (ISO date) and window ('open' or 'close').

segment_metadata(fetch: MultiFetch, ticker, kind, *, segment_start: date, segment_end: date, segment_type: 'base' | 'delta', prior: SegmentRef | None, code_revision: str) -> dict[str, str]. Every value is a str (store.py:151-154). Keys:
- source = 'alpaca-sip', feed, adjustment, timeframe
- fetched_at (ISO UTC), request_sha256, request (canonical JSON)
- pages (JSON list of receipts: index, request_page_token, next_page_token, status, body_sha256, rows for this symbol)
- alpaca_symbol, ticker, segment_type, segment_start, segment_end
- first_bar, last_bar, rows
- prior_asof, prior_sha256 (empty strings for a base)
- schema_version, code_revision

write_segment(store, kind, asof, ticker, columns, metadata) -> bool refuses, with ValueError, any metadata whose feed, adjustment or timeframe does not match the kind. For example, adjustment 'all' can never enter bars_15m_sip, so mixed bases in one chain are impossible. It then calls MarketStore.write_frame (store.py:134-156), which keeps immutability: an existing file returns False and stays byte-identical.

#### `backend/market/intraday_sip.py (new)` — SegmentRef, Chain, read_chain, chain_end

SegmentRef(asof: date, sha256: str, segment_type: str, segment_start: date, segment_end: date, provenance: CacheProvenance) reuses the dataclass at intraday_cache.py:76-88.

Chain(ticker, kind, columns: dict[str, list], segments: tuple[SegmentRef, ...]).

read_chain(store, kind, ticker, asof, calendar) -> Chain | None follows the _read_cache pattern at intraday_cache.py:163-185: read bytes, sha256, parse from the same bytes.
1. It lists partitions <= asof holding the ticker, oldest first.
2. It takes the newest segment_type='base' <= asof and every later delta.
3. It verifies:
   - source, feed, adjustment and timeframe equal the kind's declaration
   - each delta's prior_asof/prior_sha256 names the previous file's actual hash
   - each delta's segment_start == calendar.offset(previous segment_end, 1)
   - no overlapping starts
4. It concatenates the columns in order.

A violation raises ChainError(reason), with no partial return.

chain_end(store, kind, ticker, asof) -> SegmentRef | None reads only the parquet schema metadata of the newest file (pq.ParquetFile(...).schema_arrow.metadata, as store.describe does at :305-306). It is used for append planning.

#### `backend/market/intraday_sip.py (new)` — read_daily_pinned, split_factor

read_daily_pinned(store, ticker, daily_asof) -> tuple[TickerHistory, DailyRef] | None hashes the bars and actions parquet bytes of the partition store.latest_asof(ticker, daily_asof) resolves to. It parses from those same bytes, mirroring store.read (:246-289).

DailyRef(asof, bars_sha256, actions_sha256, complete_through, source).

split_factor(day: date, splits: list[tuple[date, float]], basis_date: date) -> float returns the product of ratio over splits with day < split_date <= basis_date. That is the Yahoo convention: close is split-adjusted as of the fetch (yahoo.py:22-27), and the split date is the first post-split session. Spin-offs that Yahoo encodes as splits (WDC 1.323) are handled the same way. The splits come from the pinned history's actions with kind == 'split', which is the rule in levels_pit._splits (:131-144).

#### `backend/market/intraday_sip.py (new)` — SessionVerdict, reconcile

SessionVerdict is a frozen dataclass with fields: session, status ('accepted' | 'quarantined'), reason, expected_slots, slots_present, complete, extended_bars, sip_close, daily_close, split_factor, close_log_diff, sip_high, sip_low, daily_high, daily_low, regime, regime_median, volume_ratio.

reconcile(ticker, chain, daily: TickerHistory, basis_date: date, calendar, reference_grid: Mapping[date, bool]) -> tuple[SessionVerdict, ...] covers every calendar date in [first chain session, last chain session]. Bars are grouped by New York date, and regular bars are open <= start < sip_close_time(day). On 2024-11-29, bars from 13:00 to 16:00 are post-market.

Ordered gates:
1. The year is covered (else calendar_uncovered).
2. The date is a session (else, if bars exist, bars_on_closed_day).
3. Regular starts lie on the 15-minute grid from 09:30 (off_grid) and are unique (duplicate_bar).
4. OHLC is finite, > 0 and ordered (invalid_ohlc).
5. At least one regular bar exists (no_bars).
6. The bar starting at close - 15 min exists (no_closing_bar).
7. A daily row with a finite close > 0 exists (no_daily_reference).
8. |ln(sip_close / (daily.close * S))| <= CLOSE_TOLERANCE (else close_mismatch).
9. sip_high <= daily.high * S * (1 + RANGE_TOLERANCE) and sip_low >= daily.low * S * (1 - RANGE_TOLERANCE) (else range_mismatch).
10. reference_grid[day] is True, meaning SPY has every expected regular slot on the date (else calendar_tape_conflict). This detects an unrecorded closure or early close without inferring the calendar from bars.
11. Sessions passing 1-10 are grouped into split regimes. A regime with fewer than MIN_REGIME_SESSIONS gives regime_too_short. |median close_log_diff| > REGIME_TOLERANCE gives basis_offset for the whole regime.

complete (slots_present == expected_slots, 26 or 14) is reported but not gated, so consumers decide. volume_ratio = sum(regular volume) * S / daily.volume is a diagnostic only.

Why the AVGO class cannot be accepted: raw storage means the only way to accept a session is for the SIP price level to equal the daily level times the documented split product. A 10x, 1.5x or 1.323x error gives |ln| of 2.30, 0.41 or 0.28, far above 0.03. Factors between 1.01 and 1.03 fail the regime median.

#### `backend/market/intraday_sip.py (new)` — accept

accept(store, ticker, asof, *, calendar, daily_asof: date | None = None, reference: Chain | None = None) -> AcceptanceResult reads the chain and the pinned daily data and runs reconcile.

It writes kind SIP_15M_ACCEPTANCE_KIND at partition asof, keyed by ticker, through MarketStore.write_frame. Each run is a full re-judgement snapshot over all sessions, so a new split or a corrected Yahoo close is re-evaluated the next night.

Columns are the SessionVerdict fields. Metadata (all str) holds:
- daily_asof, daily_bars_sha256, daily_actions_sha256, basis_date
- segments (JSON list of {asof, sha256})
- tolerances (JSON)
- calendar_sha256 (hash of the four calendar JSON files)
- code_revision, evaluated_at
- counts by status and reason

It raises when SPY's chain is missing (the reference tape is required). Frames are immutable, so a same-day rerun is a no-op and reports 'kept'.

#### `backend/market/intraday_sip.py (new)` — load_accepted

load_accepted(store, ticker, asof, *, basis: str = 'split', regular_only: bool = True, calendar=None) -> AcceptedBars(columns, sessions: tuple[date, ...], basis_label: str, provenance: dict).

It reads the chain and the newest acceptance frame <= asof, then requires the acceptance's segments list to match the chain's hashes. Sessions from a segment not listed are excluded, and a hash mismatch raises. It keeps only accepted sessions.

Basis conversion uses the acceptance's pinned daily partition:
- 'raw' leaves prices as stored.
- 'split' divides prices by S(day, basis_date) and multiplies volume by S. The label is 'split-adjusted as of <basis_date>'.
- 'total' is split times (adjusted_close / close) per day, which adjusts for dividends exactly once and fixes the entry_pilot double-adjustment class for new consumers.

The returned columns match bars_frame plus trade_count, vwap, session, slot and regular, so intraday.sessions_from still works. With regular_only=True, early-close sessions arrive with 14 bars. The legacy 26-bar check then drops them instead of reading post-market prints.

Defence in depth: for every returned session, |ln(last regular close on the basis / daily close on the same basis)| <= CLOSE_TOLERANCE, else ScaleInvariantError. A hand-edited or mismatched acceptance frame therefore still cannot deliver a mis-scaled series. It refuses SIP_15M_ALL_KIND.

#### `backend/market/intraday_sip.py (new)` — reconcile_windows, accept_windows

reconcile_windows(window_chain, accepted_15m: AcceptedBars in raw basis, calendar) -> tuple[WindowVerdict, ...] works per (session, window). The 1-minute bars inside regular hours are aggregated into their 15-minute buckets and must equal the accepted 15-minute bar:
- first open equals the open
- last close equals the close
- max high and min low equal high and low within 1e-9 relative
- summed volume is within 0.1% (default)

The parent session must be accepted (else parent_session_not_accepted). Minutes at or after the close are recorded as auction_minute_close with ln against the daily close * S as a diagnostic, not a gate.

accept_windows writes SIP_1M_WINDOW_ACCEPTANCE_KIND frames with the same metadata pattern.

#### `backend/market/intraday_sip.py (new)` — estimate_requests, estimate_window_requests, code_revision

estimate_requests(sessions_by_ticker: Mapping[str, int], *, bars_per_session: int, limit: int = 10_000) -> dict is pure. It returns per-ticker bars and pages (ceil(bars / limit)) plus totals, and minutes at REQUESTS_PER_MINUTE.

estimate_window_requests(n_symbols, n_sessions, *, minutes=(45, 35), chunk=100, limit=10_000) -> dict.

code_revision() -> str returns git rev-parse --short HEAD or 'unknown'. It is a copy of the market_daily._read_git_revision pattern (:1202-1216), not an import of the CLI.

#### `backend/market/data/nyse_sessions_2016_2018.json (new)` — research-only calendar years 2016-2018

Same schema as nyse_historical_sessions.json: description, checked, timezone, and years -> {full_closures, early_closes, sources[{url, published, note}], coverage_notes}.

The dates must come from the official NYSE/ICE calendar releases and the 2018-12-05 closure notice. The recalled candidates below are UNVERIFIED until sourced:

| Year | Full closures | Early closes (13:00) |
|---|---|---|
| 2016 | 01-01, 01-18, 02-15, 03-25, 05-30, 07-04, 09-05, 11-24, 12-26 | 11-25 |
| 2017 | 01-02, 01-16, 02-20, 04-14, 05-29, 07-04, 09-04, 11-23, 12-25 | 07-03, 11-24 |
| 2018 | 01-01, 01-15, 02-19, 03-30, 05-28, 07-04, 09-03, 11-22, 12-05, 12-25 | 07-03, 11-23, 12-24 |

Only load_sip_calendar reads this file.

#### `backend/cli/market_intraday.py` — build_parser

New flags:
- --feed {iex, sip}, default 'iex'
- --adjustment {raw, all}, default None: iex resolves to 'all' and refuses 'raw' because the bars_15m kind carries no adjustment flag; sip resolves to 'raw'
- --timeframe {15Min, 1Min}, default '15Min'; 1Min implies the fill windows and needs sip
- --universe {roles, book}, default 'roles'; 'book' = sorted(book_sides(build_universe())) + SPY, QQQ
- --through DATE, default last_settled_session
- --settle-sessions N, default 1
- --append, --accept, --estimate, --nightly
- --max-requests N, required for any sip fetch mode except --estimate and --status
- --daily-asof DATE
- --record-pages DIR

The existing flags keep their names and defaults. --adjustment all together with --append exits 2 with the reason that the all basis rescales history.

#### `backend/cli/market_intraday.py` — main and new helpers

When --feed is iex and no new flag is given, main() runs today's code path unchanged: the same prints, kind bars_15m, and metadata {'source': 'alpaca-iex', 'since': ...}. Every new helper gets a comment line above it.

_book_tickers() -> tuple[str, ...].

_sip_backfill(args, store, tickers, pacer) runs one fetch_bars_multi stream per ticker over [first session >= --since 04:00 ET, --through 20:00 ET]. It skips a ticker whose chain already exists, keeping the existing resumability, and writes a base segment in partition asof=today with segment_start/segment_end set to the requested sessions.

_sip_append(args, store, tickers, pacer) reads chain_end per ticker and groups tickers by end. It requests from the chain-end session (an overlap of one session) through --through, in chunks of at most 100 symbols. It compares the overlapping session bar by bar with the stored chain and records any differences as revisions in the run receipt. Then it writes a delta for sessions after the chain end, including a zero-row delta when a requested symbol returned nothing. A ticker with no base is reported as needs_backfill.

_sip_windows(args, store, tickers, pacer) runs per session, per window, with all tickers in chunks of 100. It stages into <data root>/_staging/bars_1m_sip_window/<run id>/ (resumable, deleted after consolidation) and consolidates one segment per ticker.

_sip_accept(args, store, tickers) accepts SPY first as the reference tape, then the other tickers, then the windows.

_sip_estimate(args, store, tickers) makes no provider call. Session counts come from the daily store (store.read over [since, through]) and are printed at 64, 56 and 26 bars per session, with request totals and minutes.

_sip_status(args, store, tickers) prints per ticker: segments, coverage, last session, and accepted and quarantined counts by reason.

_nightly(args):
1. Takes nightly_lock.acquire(Path(store.root) / 'intraday_sip'), a separate lock from the desk nightly. If the lock is held it exits 75.
2. Uses --universe book and --max-requests default 100.
3. Runs append for 15Min, append for the windows, then accept.
4. Writes a write-once receipt at <root>/intraday_sip/runs/<UTC stamp>.json holding request count, revisions, needs_backfill, failures and counts.
5. Exits 0 when clean and 2 on any failure or needs_backfill.

--record-pages writes each stream's canonical request plus pages {status, sha256, body, request_page_token} to DIR/<request_sha256>.json with exclusive create, and asserts that no 'APCA' string appears in the bytes.

#### `scripts/intraday_sip_nightly.sh (new)` — host cron wrapper (not installed by the implementer)

The script does:

```
set -euo pipefail
cd /home/animallya96/deploy/anios
exec ~/research-venv/bin/python -m backend.cli.market_intraday --nightly --max-requests 100
```

It carries a comment giving the proposed operator-installed cron line, '35 20 * * 1-5' (host ET). That is after the 19:30 desk nightly writes the daily partition and after the 20:00 SIP close plus 15 minutes. Installing it is a deploy action, done only when the operator asks.

#### `docs/diagrams/market-data.mmd (+ regenerated .svg), docs/ARCHITECTURE.md, docs/DEVELOPMENT_GUIDE.md, docs/research/sip-intraday-history-<date>.md` — documentation

- Diagram: add the Alpaca SIP history (external), the raw append chain and acceptance kinds (data), the gate edge to the daily store, and the nightly SIP job. Render via the dockerised mermaid-cli on the Spark, per the architecture render method.
- ARCHITECTURE.md: store kinds and the basis rule (raw stored, views derived).
- DEVELOPMENT_GUIDE.md: CLI commands, --estimate, budgets.
- Research note: every constant tagged measured, inherited or default with its date, the capture receipts and hashes, and the acceptance statistics.
- NEXT_SESSION.md and CHANGELOG.md: only after verification.
- No change to AGENTS.md.

### New files

- backend/market/intraday_sip.py
- backend/market/data/nyse_sessions_2016_2018.json
- scripts/intraday_sip_nightly.sh
- docs/research/sip-intraday-history-<date>.md
- backend/tests/test_alpaca_fetch_params.py
- backend/tests/test_alpaca_sip_fetch.py
- backend/tests/test_sip_calendar.py
- backend/tests/test_intraday_sip_store.py
- backend/tests/test_intraday_sip_acceptance.py
- backend/tests/test_intraday_sip_windows.py
- backend/tests/test_market_intraday_sip_cli.py

backend/tests/fixtures/alpaca_sip/ holds recorded pages in the intraday_single_source page shape ({request, captured_at, pages: [{status, sha256, body, request_page_token}]}):
- c1_avgo_qqq_spy_15min_2024-07-11_15_raw_limit250.json: 3 or more pages that cross symbol boundaries and span the 10:1 split.
- c2_aaoi_qqq_spy_15min_2024-11-27_29_raw.json: the 2024-11-29 early close.
- c3_avgo_spy_1min_2024-11-29_open.json
- c4_avgo_spy_1min_2024-11-29_close.json: 12:30-13:05.
- c5_wdc_15min_2025-02-21_24_raw.json: spin-off that Yahoo codes as split 1.323.
- c6_aptv_15min_2026-03-30_31_raw.json
- c7_spy_15min_2024-03-08_11_raw.json: DST week.
- daily_extract_<partition>.json: trimmed daily rows and actions for AVGO/SPY/QQQ/AAOI/WDC/APTV, read read-only from the Spark daily partition, carrying that partition's asof and parquet sha256.

C1-C7 are about 9 provider requests.

### Tests

All tests use tmp_path MarketStore and replay transports: no network, no writes outside tmp. Every test function gets a plain-language comment. Fixtures come from recorded pages. Defect cases are derived by transforming the recorded fixtures, which keeps real tickers, timestamps and tokens. Until capture is approved, hand-built pages in the exact Alpaca shape (t/o/h/l/c/v/n/vw, opaque tokens) stand in, marked RECORDED=False, and are replaced once captured.

1. test_alpaca_fetch_params.py
   - The default fetch_bars('AVGO', date(2024,7,12), date(2024,7,15)) first URL equals the literal legacy string ...?symbols=AVGO&timeframe=15Min&feed=iex&adjustment=all&limit=10000&sort=asc&start=2024-07-12T00:00:00Z&end=2024-07-15T23:59:59Z.
   - The second URL appends the token unquoted, for example '&page_token=tok+/=1'. The sleeps are [0.35]. A 429 then 200 sequence sleeps [5.0].
   - feed='sip', adjustment='raw', timeframe='1Min' land in the same parameter positions.
   - Bad values raise before any transport call.
   - market_pick_audit._historical_transport('sip', legacy_url) sends exactly _bars_url(feed='sip').
   - live_quotes.quotes still calls fetch(symbol, today, today, headers=None) with no new kwargs.

2. test_alpaca_sip_fetch.py (replay of C1)
   - Per-symbol counts equal the raw row counts. Bars that straddle a page boundary are merged without duplicates and in ascending order.
   - Receipts' body_sha256 values equal the sha256 of the page bytes.
   - request_sha256 is stable across runs and independent of tokens and credentials.
   - Tickers are deduped and sorted, and BRK-B is requested as BRK.B and keyed back to BRK-B.
   - The next request carries urllib-quoted real tokens, asserted against the recorded request_page_token chain.
   - A malformed row (missing 'c') raises instead of being dropped. An unrequested symbol key raises. A cyclic token raises.
   - 429 follows the RETRY_429 schedule, then raises. 403 raises AlpacaEntitlementError with no retry. 5xx and transport exceptions retry within bounds. A non-JSON body raises.
   - A SIP end within 16 minutes of the injected now raises before any call.
   - RequestPacer with a fake clock allows at most 190 requests in any 60 s window, and max_requests raises RequestBudgetExceeded before the (N+1)th call.

3. test_sip_calendar.py
   - load_sip_calendar covers 2016-2028. The 2016-2018 early closes return time(13) and the closures return None. Every year has sources.
   - sip_close_time equals calendar.session_close for every session in 2019-2028.
   - An uncovered year (2015 or 2029) raises.
   - calendar.reviewed_sessions() years still start at 2019, and publication_session for a 2018 instant still returns None, which protects the EDGAR, live-technical and chart paths.
   - session_bounds is DST-correct across 2024-03-08 and 2024-03-11 (C7): the 09:30 bar is 14:30Z, then 13:30Z.

4. test_intraday_sip_store.py
   - A base plus two deltas written via write_segment carry metadata with exactly feed, adjustment, timeframe, fetched_at and request_sha256 (plus the listed keys), all str.
   - read_chain concatenates them.
   - Flipping one byte of the base raises ChainError (hash). A delta whose start is not the next session raises (gap). An overlap raises.
   - Metadata adjustment='all' in bars_15m_sip is refused at write time.
   - A re-write of the same (kind, asof, ticker) returns False and the file bytes are unchanged.
   - chain_end reads metadata only.

5. test_intraday_sip_acceptance.py (C1, C2, C5, C6 plus the daily extract)
   - AVGO 2024-07-11 and 07-12 are accepted with split_factor 10 and 07-15 with 1. The close_log_diff magnitudes are below the tolerance.
   - Parametrised over factors {10, 1.5, 1.323, 1.05}: one regime of AVGO or WRB-style bars scaled by the factor is never accepted (close_mismatch). Six sessions scaled by 1.02 give basis_offset. A regime of fewer than 5 sessions gives regime_too_short.
   - WDC 2025-02-21 is accepted with factor 1.323. APTV 2026-03-31 is accepted with factor 1 while the Alpaca-all-style scaled copy is quarantined.
   - SPY 2024-11-29 has expected_slots 14, the closing bar is 12:45, and 13:00-15:45 bars are counted as extended.
   - With a calendar lacking 2024 coverage the session gives calendar_uncovered, never a 16:00 assumption.
   - The missing-daily-row, dropped-12:45-bar, duplicate-start and high-below-low transforms give their specific reasons.
   - SPY missing slots on a declared full day gives calendar_tape_conflict for AVGO on that date.
   - The acceptance frame is immutable and its metadata pins the daily partition sha256.
   - load_accepted with basis 'split' matches the daily close and with 'total' matches adjusted_close (no double dividend). regular_only drops pre- and post-market and early-close afternoon bars. A forged acceptance frame marking a scaled session accepted raises ScaleInvariantError. A segment-hash mismatch raises.

6. test_intraday_sip_windows.py (C3, C4 against C2)
   - 1-minute bars aggregate exactly to the accepted 15-minute open, close, high and low and to the summed volume.
   - One perturbed minute quarantines the window.
   - The early-close close window is 12:30-13:05.
   - A parent session that was not accepted gives parent_session_not_accepted.

7. test_market_intraday_sip_cli.py (argv plus monkeypatched transport and credentials)
   - A default run with no --feed writes bars_15m with metadata exactly {'source': 'alpaca-iex', 'since': '2016-01-01'} (regression).
   - --feed sip --tickers AVGO,SPY --max-requests 10 writes base segments. A second run the same day makes zero transport calls.
   - --append the next day requests only from the chain end (overlap one session) in one multi-symbol stream and writes deltas. A revised overlap bar lands in the receipt.
   - --estimate makes zero transport calls. A --max-requests below the estimate exits non-zero before any call.
   - --adjustment all with --append exits 2.
   - --nightly holds the lock, so a second concurrent run exits 75. The receipt is written once. needs_backfill gives exit 2.

No prompt changes, so no backend/tests/functional test applies.

### Acceptance

1. Unit tests, in the trading/volatile-book-15m worktree on the Spark. Use the research venv or a probe-clone container, not the Mac: python3 there lacks numpy.

   python -m pytest backend/tests/test_alpaca_fetch_params.py backend/tests/test_alpaca_sip_fetch.py backend/tests/test_sip_calendar.py backend/tests/test_intraday_sip_store.py backend/tests/test_intraday_sip_acceptance.py backend/tests/test_intraday_sip_windows.py backend/tests/test_market_intraday_sip_cli.py backend/tests/test_market_alpaca.py backend/tests/test_market_live_quotes.py backend/tests/test_market_pick_audit.py backend/tests/test_intraday_inputs.py backend/tests/test_intraday_cache.py backend/tests/test_intraday_cache_review_edges.py backend/tests/test_intraday_single_source.py backend/tests/test_market_intraday.py -q

   Then:
   - ruff check and ruff format --check on the touched files
   - bash scripts/gate.sh --unit, which must be green

2. Frozen-path guard. This must print nothing:

   git diff main...trading/volatile-book-15m --stat -- backend/market/live_quotes.py backend/market/intraday_cache.py backend/market/calendar.py backend/market/intraday_inputs.py backend/market/intraday.py backend/cli/market_pick_audit.py backend/market/data/nyse_historical_sessions.json backend/market/data/nyse_holidays.json backend/market/data/nyse_early_closes.json

   Also check that no frozen study file or bars_15m partition is touched.

3. Offline estimate, on the Spark with the APCA keys unset to prove there is no provider call:

   python -m backend.cli.market_intraday --feed sip --universe book --estimate --since 2016-01-01 --through 2026-09-24

   It prints per-ticker sessions and pages and the totals.

4. Only after the operator approves the request budget in chat:
   a. Capture fixtures C1-C7 with --record-pages (about 9 requests). Commit the trimmed fixtures and flip RECORDED=True. The tests must pass on the recorded bytes.
   b. Backfill: --feed sip --universe book --since 2016-01-01 --through <D> --max-requests 1900.
   c. Run --accept, then --status. Pass criteria (defaults, recorded in the research note):
      - SPY and QQQ are accepted on at least 99% of sessions since 2016-01-04.
      - AVGO 2024-07-12 is accepted with split_factor 10.0 and 07-15 with 1.0. WDC 2025-02-21 is accepted with 1.323.
      - Every early close from 2016 to 2026 shows expected_slots=14.
      - load_accepted(basis='split') runs over every ticker without ScaleInvariantError.
      - The quarantine list by reason is written to the receipt and reviewed.
      - The CLI summary prints counts only. It prints no return-like statistics for 2016-2020.
   d. Windows: --timeframe 1Min --max-requests 5600, then --accept. At least 99% of accepted 15-minute sessions have reconciling windows.
   e. Run --nightly once by hand. It must exit 0, write one delta per ticker, and produce acceptance frames and a receipt.
   f. Installing the cron line is a separate deploy step, done only when the operator asks.

5. Docs: the diagram is rendered and the research note carries tolerance provenance and receipts. NEXT_SESSION and CHANGELOG are updated only after steps 1-4 are verified.

### Files owned

Modified:
- backend/market/alpaca.py, the fetch region only: lines 52-172 and new definitions placed right after fetch_bars. The sessions() and session_features regions (:204-258) are left to the early-close and slot-indexing items.
- backend/cli/market_intraday.py
- docs/diagrams/market-data.mmd and docs/diagrams/market-data.svg
- docs/ARCHITECTURE.md (store section)
- docs/DEVELOPMENT_GUIDE.md (market CLI section)

New:
- backend/market/intraday_sip.py
- backend/market/data/nyse_sessions_2016_2018.json
- scripts/intraday_sip_nightly.sh
- docs/research/sip-intraday-history-<date>.md
- backend/tests/test_alpaca_fetch_params.py, test_alpaca_sip_fetch.py, test_sip_calendar.py, test_intraday_sip_store.py, test_intraday_sip_acceptance.py, test_intraday_sip_windows.py, test_market_intraday_sip_cli.py
- backend/tests/fixtures/alpaca_sip/*

Shared: NEXT_SESSION.md and CHANGELOG.md, append-only after verification.

Explicitly NOT touched: live_quotes.py, market_pick_audit.py, intraday_cache.py, calendar.py, intraday_inputs.py, intraday.py, tape.py, entry_pilot.py, the existing nyse_*.json files, and tests/test_market_alpaca.py (left free for other items).

### Depends on

Code has no dependency on other items and can start immediately in the worktree.

Data runs depend on:
- The operator's explicit, bounded approval in chat for:
  - fixture capture (about 9 requests)
  - the 15-minute backfill (1,900 request cap)
  - the windows backfill (5,600 cap)
  - the optional S&P member runs (about 6,500 and 13,500)
  NEXT_SESSION.md:1004 records that earlier probe allowances are exhausted.
- An official source for the 2016-2018 NYSE calendar.
- Existing Spark daily partitions (market_daily --refresh) for the reconciliation.

Downstream, these consume load_accepted: the 15-minute chart-structure engine, the 15:45 decision plus MOC execution study, the fill and latency model unification, the forward fidelity shadow, and any 2016-2020 intraday gate.

Coordinate with any item that edits alpaca.sessions/session_features (region split above) or adds calendar coverage.

### Risks

1. Entitlement. Free delayed SIP history is verified for one 4-symbol request only. At scale it could return 403 or change without notice. 403 fails fast with AlpacaEntitlementError, the budget caps bound the damage, and nothing partial is written per ticker.

2. Calendar 2016-2018. The recalled dates are UNVERIFIED. A wrong early close would mis-slice about 6 sessions in the primary window. Putting them in reviewed_sessions instead of a separate file would silently change live_technical, ticker_chart and EDGAR strict-publication history (edgar.py:647-652). A separate file plus fail-closed coverage prevents both.

3. Tolerance false quarantines. CLOSE 3%, REGIME 1% and RANGE 2% are defaults. For volatile small names, the last trade before 16:00 can occasionally differ from the auction close by more than 3%, and bad Yahoo daily rows would quarantine good SIP data. Both errors are conservative. Any recalibration must use only examined 2021-2026 data, with a dated rationale, and never per symbol and never on 2016-2020.

4. Untouched-window leakage. Acceptance frames store last-trade-vs-close diagnostics, which relate to the value of MOC-vs-15:45 execution. The research protocol must treat them as QA fields that no study reads for 2016-2020 before registration. The CLI prints counts only.

5. Symbol history. Examples: META before 2022 as FB, GEN as NLOK, old SanDisk before 2016 under SNDK. Alpaca's symbol-mapping behaviour (the asof parameter) is unverified. The gate quarantines mismatches (no_daily_reference or close_mismatch), but that may cost valid history.

6. Live and backtest feed mismatch. A live 15:45 decision must use real-time IEX: delayed SIP is at least 15 minutes old, so the 15:30 SIP bar only arrives after the 15:50 cls cutoff. The forward fidelity shadow must measure IEX-vs-SIP decision agreement, and this store cannot remove that gap.

7. Page-token encoding. The legacy path appends tokens unquoted to stay byte-identical, while the new path quotes them. If real tokens contain '+', historical IEX multi-page fetches may have been affected. That is unverified; the recorded fixtures reveal the token alphabet.

8. Late SIP corrections after fetch. Settle lag of 1 session plus overlap verification measures this rather than assuming it away. Stored segments are never rewritten.

9. Memory and disk for 1-minute windows (about 20.7M rows for the book, 115M for the members). This is handled by staging and per-ticker consolidation.

10. Terms. Alpaca data is for personal, non-redistributed use. It stays in the Spark store, and nothing is published.

11. Merge conflicts in alpaca.py with other items. Mitigated by the region ownership above and by putting new tests in new files.

12. Survivorship. The optional S&P member set is today's constituents only (universe.py:23-28), so any cross-section study on it inherits that bias.

### Effort

About 3.5-4.5 engineer-days:
- fetch params and multi-fetch with pacer: 0.75 d
- store segments and chain: 0.5 d
- calendar file and wrapper: 0.25 d, plus sourcing time
- acceptance gate and load_accepted: 1 d
- windows: 0.5 d
- CLI, nightly and receipts: 0.5 d
- fixtures and tests: 0.75 d
- docs and diagram: 0.25 d

PROVIDER REQUEST BUDGET. Sessions from 2016-01-04 to 2026-09-24 number 2,697 (2016-2020: 1,259; 2021 onward: 1,438). That count uses the committed 2019+ calendar and the UNVERIFIED 2016-2018 list. Each page holds at most 10,000 bars, the limit applies to the total across symbols in a multi-symbol request, and pacing is 190 requests per minute.

- 15-minute history, 96 symbols (94 book plus SPY and QQQ), 04:00-20:00 ET:
  - Upper bound: every symbol listed for the whole period at 64 bars per session is 172,608 bars per symbol, or 18 pages. That gives 1,728 requests and 16.6M bars.
  - Planning figure: 80% of symbol-sessions (later listings: CRWV, ALAB, ARM, NBIS, etc.) at 56 bars is about 11.6M bars, or about 1,210 requests.
  - Regular-hours-only lower bound: about 590 requests.
  - Pacing floor is 9 minutes. Latency with pages of about 1.1 MB puts wall time at about 45-90 minutes.
- 1-minute fill windows (open 09:30-10:15, close 15:30-16:05): 2 requests per session (4,320 and 3,360 bars) gives 5,394 requests, a pacing floor of 28 minutes, about 45-60 minutes wall, and about 20.7M rows.
- Nightly: about 2 requests for 15-minute bars (the overlap session doubles the bars) and 4 for windows. A missed-night catch-up of 10 sessions is about 27 requests, within the default cap of 100.
- Optional S&P members (437 names not in the book): about 62.7M 15-minute bars, or about 6,500 requests (34-minute pacing floor, about 3-5 hours wall). Windows need about 5 requests per session, or about 13,500 requests (71-minute floor). Nightly then takes about 8 plus 10 requests.
- Storage: 15-minute book about 12M rows (a few hundred MB of parquet); members about 75M rows (about 2 GB).

--estimate recomputes all of this from the actual daily-store session counts before any run.

### Open questions

1. Budget approval. Does the approved free-SIP acquisition cover fixture capture C1-C7 (about 9 requests), the 15-minute backfill (cap 1,900) and the windows backfill (cap 5,600) now? Are the S&P member runs (about 6,500 and 13,500) wanted, or deferred?

2. Alpaca's asof symbol-mapping parameter for bars. Confirm from the docs whether it exists and what its default is. If it exists, pin it to the run date in the canonical request so FB/META-style renames are reproducible.

3. 2016-2018 calendar. The official NYSE/ICE release URLs are needed, including the 2018-12-05 closure notice, before the file is committed. The recalled dates are unverified.

4. Settle lag. Should the default be 1 session (bars for day D appended on the evening of D+1, safer against corrections) or 0 (same evening, better for the fidelity shadow's timeliness)?

5. Fill windows. Do 09:30-10:15 and close-30m to close+5m match what the execution-timing item needs? It may also want 15:45-15:50 before the cls cutoff, or 10:00-10:15 for deferred buys, both of which are covered. Is 5Min history also wanted?

6. Gate defaults. Are CLOSE 3%, REGIME 1% with at least 5 sessions, RANGE 2%, and the 99% SPY/QQQ acceptance pass bar acceptable as predeclared values?

7. Nightly. Should it run at 20:35 ET on the Spark host cron as a separate job, not inside market_daily? Should a needs_backfill result (a new book name) exit 2 so it is paged?

8. Legacy data. Should the IEX bars_15m partitions stay as read-only provenance, with new research reading only load_accepted? This spec leaves them untouched.

## evaluation-harness

**Item.** One canonical candidate-evaluation harness and statistics: new backend/market/candidate_bench.py, candidate_stats.py, candidate_gate.py and trials_registry.py, plus the CLI backend/cli/market_candidate_bench.py. It runs any candidate, expressed as simulate.run kwargs, an allocator or a custom runner, at all 20 reset offsets and at 10 and 25 bp against fixed controls. It reports a zero-yield column and a separate T-bill-credited column (^IRX added to macro.SERIES). Outputs: paired stationary-bootstrap CIs, PSR/DSR with N taken from a JSONL trials registry, a numpy-only Hansen SPA, CSCV PBO, and a verdict against a gate file that is committed and hashed before the run. market_strategy_bench.py and strategy_bench.py stay unchanged because the Research page reads their output.

**HEAD.** 990fa9819a514c939b1777dca66b73e0e7e97a6d

### Current state

All anchors are at HEAD 990fa981. I opened every cited file.

EXISTING BENCH (single offset, 10 bp only, feeds a live page)
- backend/cli/market_strategy_bench.py:44-108 main() builds the desk once: desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,)) at :49.
- It prices three candidates (:60-71):
  - adopted: rebalance=paper.REBALANCE_EVERY plus **simulate.LIVE_POLICY
  - calendar-only: the same with live_midcycle False (:64-67)
  - 120 + DipRule tails
- Each runs through simulate.run(since=first panel date, use_exits=False, event_exposure=event_risk.live_path(panel), event_lifecycle=True) (:73-81) at the default cost, simulate.COST_BPS=10.
- SPY and QQQ come from benchmarks.load_benchmark at simulate.COST_BPS (:87-94).
- It writes data/market/desk/strategy_bench.json through strategy_bench.build/save (:96-104).
- The Research page reads that file (backend/api/v1/market.py:169; frontend/src/components/DeskPanel/DeskPanel.tsx:1553).
- There are no offsets, no 25 bp run, no equal-weight or exposure-matched controls, no statistics and no gate.

strategy_bench.py
- :40-47 REGIMES: Whole sample; Pre-COVID bull 2015-01-02..2020-02-19; COVID crash; COVID recovery; 2022 bear; AI boom.
- :53 METRIC_KEYS.
- :65-85 stats(): volatility uses ddof=0, Sharpe uses rf=0, and any NaN is rejected.
- :143-215 build(): drops only the initial NAV slot.

benchmarks.py:133-192 load_benchmark(store, symbol, sessions, cost_bps, start_equity, asof)
- Strict coverage.
- Buys everything at the session-1 adjusted open with shares = E/(open*(1+c)) (:185-186) and never liquidates.
- daily[0] = NaN.

simulate.py
- :643-675 run(report, since, config, rebalance, cost_bps, use_exits, redeploy, allocator, dip, exits, ..., event_exposure, event_lifecycle, live_midcycle, deferred_buys, funded_allocation, ..., benchmark_prices, trend_brake, brake_scale, brake_path_override, journal).
- :72-78 LIVE_POLICY = {block_overbought, exit_at_close, green_day_skip, live_midcycle, deferred_buys}, all True.
- Reset offsets exist only through `since`:
  - start = searchsorted(dates, since) (:887)
  - next_rebalance = start (:920)
  - the clock runs t >= next_rebalance (:1127-1129)
- SimResult is sliced from start (:1285-1297) and carries returns, invested, equity, traded and top_weight.
- stats() uses Sharpe rf=0 (:256-310).
- Cash never accrues: _Book.cash (:1320) and equity() (:1385-1392). equity() raises on a missing held mark when require_complete_marks is set.

allocation_controls.py:98-196 constant_exposure(closes, opens, fraction, cost_bps, *, journal, sessions, symbol)
- Constant fraction, decided at the close and filled at the next open.
- Idle cash earns nothing (:21).
- adjusted_open is at :79-94.

macro.py
- :40-45 SERIES = {vix, tnx, dollar, oil}. There is no T-bill series.
- :49-63 aligned_close reads only panel.dates and carries forward.
- macro_by_session reads keys explicitly (:79-82).
- market_daily.bar_tickers (:131-134) appends SERIES.values(), so every SERIES symbol is fetched nightly.

neural_study_metrics.py
- Curve :35-43; from_simulation :55-73.
- _checked_curves (:112-132) enforces:
  - cost in {10, 25}
  - the accounts {candidate, incumbent, SPY, QQQ, equal_weight}
  - identical dates
- scorecard (:230-278): CAGR, maxDD, Sharpe with ddof=1, turnover, exposure, concentration, and rolling 63/252 wins vs SPY/QQQ/incumbent. It hard-codes "cash_yield": 0.0 (:252).
- regime_scorecard :429-508.
- chronological_fold_scorecard :563-695. Its fold slices carry marks with no reset (:512-527).

entry_pilot.py:349-363 paired_interval
- A circular fixed-block (20) bootstrap of the mean daily difference, 1000 reps, seed 713.
- Not stationary, and no block-length rule.

research_journal.py
- ResearchJournal :136-546; manifest cash_yield 0.0 (:185); archive :532.
- research_journal_replay.verify_snapshot (:770) asserts cash_yield == 0 (:187).

nested_market_study.py is the nearest existing matched-account harness and the pattern to copy:
- _source_hashes :54-67
- frozen /3 configuration check :71-126
- _journal :169-189
- _verified_account (independent replay plus NAV equality) :193-232
- _incumbent :236-252
- SPY/QQQ via constant_exposure(1.0) :269-282
- equal weight via allocation_replay :286-310
- _runtime (git head and porcelain) :389-419
- check_destination :500-509
- nested_market_inputs.binding(report) (:304-347) hashes the consumed report state.

Pieces that exist but cannot be imported, or are private:
- market_neural_price_study.verify_calendar (:44-55) checks XNYS completeness, but that CLI imports torch at module top (:12), so the gate container cannot import it.
- Its equal_allocator (:149-155) is the causal equal-weight allocator pattern.
- market_allocation_rl._hac_t (:285-291) is a Newey-West t inside a CLI.

Missing entirely (grep of backend/ and docs/ at HEAD): PSR, DSR, SPA, CSCV/PBO, stationary bootstrap, Politis-White block length, and a trials registry. Zero cash yield is used everywhere.

Dependencies
- The Dockerfile test stage installs exchange-calendars (:69-71).
- requirements.txt pins scikit-learn==1.9.1, so scipy is present only transitively.
- arch and statsmodels are not present.
- The ^IRX data is not in the store.

Incumbent definition
- The published curve (market_daily.curve_block :1260-1267) is rebalance=paper.REBALANCE_EVERY (20, paper.py:68), use_exits=False, event_exposure=event_risk.live_path(panel) (event_risk.py:24-26, active only from 2026-06-18), event_lifecycle=True and **LIVE_POLICY.
- POLICY_VERSION is cash-bounded-breakout-rotation/3 (paper.py:169).
- BOOK_CONFIG is at risk.py:48-50.
- desk.LIVE_INPUTS = (expectations-gap) (desk.py:141).
- desk.run(store, asof, inputs, fundamentals) is at desk.py:156.

Research diagram: docs/diagrams/market-data.mmd:30-46 draws the research accounts, journal and study CLI. It has no harness, gate or registry nodes.

### Changes

#### `backend/market/macro.py` — SERIES

Add "irx": "^IRX" (the 13-week T-bill discount rate in percent, from Yahoo through the existing store and snapshot path). Side effects:
- market_daily.bar_tickers (:131-134) will fetch ^IRX nightly. This takes effect only after a deploy the operator requests.
- MACRO_NAMES and macro_by_session are unchanged, because they read keys explicitly, so no learned or desk feature changes.
- desk.tightening_for still reads only SERIES['tnx'].

#### `backend/market/macro.py` — discount_to_bond_equivalent (new)

discount_to_bond_equivalent(d: np.ndarray) -> np.ndarray.
- d is a decimal discount rate.
- Returns y = 365*d/(360 - 91*d).
- Negative d is floored at 0, because money funds do not pay negative yield.
- Pure function with a plain-language comment above it.

#### `backend/market/macro.py` — CashYield / cash_yield_path (new)

@dataclass(frozen=True) CashYield(dates, rate_percent (T,), daily (T,), symbol, asof_partition, source_time, first_print, last_print, max_staleness_days, convention='cash-yield/1').

cash_yield_path(store, dates, asof=None, symbol=SERIES['irx'], max_stale_days=7) -> CashYield:
- Reads the rate with aligned_close(store, symbol, SimpleNamespace(dates=dates), asof), which carries forward over bond-only holidays.
- daily[0] = 0.0.
- For t>=1: daily[t] = discount_to_bond_equivalent(rate[t-1]/100) * (dates[t]-dates[t-1]).days/365. The rate is the one known at the previous close, accrued over calendar days, so Monday earns 3 days.
- Raises ValueError when any t>=1 has no prior print, or when the last print is more than max_stale_days before dates[t-1].
- Provenance comes from store.latest_asof and the history's source_time.

#### `backend/market/macro.py` — parse_fred_daily (new)

parse_fred_daily(content: str, series_id: str) -> dict[date, float].
- An offline parser for a downloaded fredgraph CSV (for example DTB3), used only as a cross-check of ^IRX.
- The header must be exactly ['observation_date', series_id]; '.' means missing; duplicate dates are refused.
- The harness never fetches over the network.

#### `backend/market/allocation_controls.py` — constant_exposure

Add a keyword `cash_yield: np.ndarray | None = None`: (T,) simple interest per interval, with index 0 ignored.
- When given: after the t+1 fill, `cash += max(cash_close_t, 0) * cash_yield[t+1]`, where cash_close_t is the balance at close t before the fill. This matches the harness overlay convention of interest on the prior close's cash.
- Validation: shape (T,), finite, and >= 0.
- Raise ValueError when used together with journal, because research_journal_replay only supports cash_yield 0 (:187).
- cash_yield=None must reproduce today's NAV byte for byte (np.array_equal), and a zero array must match it too.
- Update the module docstring line at :21.

#### `backend/market/candidate_stats.py (new)` — stationary_indices

stationary_indices(n, mean_block, replications, seed, chunk=1000) yields int32 arrays of shape (chunk, n), using the Politis-Romano 1994 stationary bootstrap:
- idx[:,0] is uniform.
- For each t: with probability p = 1/mean_block, idx[:,t] is a new uniform draw; otherwise it is (idx[:,t-1]+1) mod n.
- Uses np.random.default_rng(seed). The loop over t is vectorised over the chunk.
- Uses only numpy and the standard library. No arch.

#### `backend/market/candidate_stats.py (new)` — optimal_block_length

optimal_block_length(x) -> float: the Politis-White 2004 automatic stationary-bootstrap mean block length, with the Patton-Politis-White 2009 correction.
- Demean x.
- K_N = max(5, ceil(sqrt(log10 n))); m_max = ceil(sqrt n) + K_N; c = 2.
- m_hat is the smallest m with |rho(m+j)| < c*sqrt(log10 n / n) for j = 1..K_N.
- M = min(2*m_hat, m_max).
- Flat-top kernel: lambda(s) = 1 for |s| <= 0.5, 2(1-|s|) for |s| <= 1, else 0.
- G = sum over |k|<=M of lambda(k/M)|k|R(k); g0 = sum over |k|<=M of lambda(k/M)R(k); D_SB = 2*g0^2.
- b = (2G^2/D_SB)^(1/3) * n^(1/3), clipped to [1, ceil(min(3 sqrt n, n/3))].
- The harness uses max(b, gate.min_mean_block), with a default floor of 20 so the 20-session reset dependence is kept.

#### `backend/market/candidate_stats.py (new)` — paired_bootstrap

paired_bootstrap(a, b, *, mean_block, replications, seed, levels=(0.90, 0.95)) -> dict.
- The same stationary indices resample both aligned daily-return series.
- Reports the point estimate and percentile intervals for:
  - mean daily difference (bp)
  - CAGR difference (compounded from resampled paths)
  - zero-rf Sharpe difference
  - max-drawdown difference
- Also reports the mean_block used and the block_rule string.
- Refuses on length mismatch or non-finite values.

#### `backend/market/candidate_stats.py (new)` — sample_moments / psr / min_trl / expected_max_sr / dsr

All inputs are per-period, with annualisation for display only.
- sample_moments(x) -> (sr = mean/std(ddof=1), skew = m3/m2^1.5, raw kurtosis = m4/m2^2, which is about 3 for normal returns).
- psr(x, sr_star=0) = Phi((sr - sr_star)*sqrt(T-1)/sqrt(1 - skew*sr + (kurt-1)/4*sr^2)).
- min_trl(x, sr_star=0, alpha=0.05) = 1 + (1 - skew*sr + (kurt-1)/4*sr^2)*(Phi^-1(1-alpha)/(sr - sr_star))^2, and inf when sr <= sr_star.
- expected_max_sr(n_trials, sr_variance) = sqrt(V)*((1-g)*Phi^-1(1-1/N) + g*Phi^-1(1-1/(N*e))), with g = 0.5772156649. It is 0 when N == 1.
- dsr(x, n_trials, sr_variance) = psr(x, expected_max_sr(...)).
- Phi and Phi^-1 come from statistics.NormalDist.
- Zero-variance input returns None with a reason instead of raising, which is needed for a null candidate identical to the incumbent.

#### `backend/market/candidate_stats.py (new)` — spa

spa(perf_diff (T,K), *, mean_block, replications, seed) -> {statistic, p_lower, p_consistent, p_upper, omega, dbar, k_used, excluded}. This is Hansen (2005) SPA.
- perf_diff = candidate returns minus benchmark returns (higher is better). The null is max_k E[d_k] <= 0.
- Bootstrap means use the stationary indices through a counts matrix: counts (chunk, T) @ d (T, K), chunked so memory stays bounded.
- omega_k is the standard deviation of sqrt(T)*(dbar*_{k,b} - dbar_k) across draws.
- T_stat = max(0, max_k sqrt(T)*dbar_k/omega_k).
- Recentring: g_l(x) = max(x, 0); g_c(x) = x*1{sqrt(T)x/omega >= -sqrt(2 log log T)}; g_u(x) = x.
- T*_b = max(0, max_k sqrt(T)(dbar*_{k,b} - g(dbar_k))/omega_k), and p = mean(T*_b > T_stat).
- Columns with omega = 0 are excluded with a reason. If none remain, p = 1.
- Why numpy instead of adding `arch`: arch would bring scipy, pandas and statsmodels into the backend image and the gate container. The repository has a record of breakages from dependency drift (see requirements.txt comments). The algorithm is about 60 lines and the ordering property p_l <= p_c <= p_u can be tested. `arch` is not added.

#### `backend/market/candidate_stats.py (new)` — cscv_pbo

cscv_pbo(returns (T,N), *, blocks=16, metric='mean_log') -> {pbo, logits, n_splits, degradation_slope, prob_oos_loss}. This is the Bailey-Borwein-Lopez de Prado-Zhu CSCV.
- np.array_split the rows into S contiguous blocks, and precompute block sums of log(1+r).
- For each of the C(S, S/2) combinations (itertools.combinations; 12,870 for S=16):
  - the in-sample best configuration n* is chosen by mean log return
  - its out-of-sample relative rank is w = rank/(N+1)
  - lambda = log(w/(1-w))
- PBO = mean(lambda <= 0).
- Requires S even, T >= S and N >= 2. Otherwise it returns {'pbo': None, 'reason': ...}.

#### `backend/market/candidate_stats.py (new)` — newey_west_t / time_under_water / ols_beta

- newey_west_t(x, lag): a Bartlett-kernel HAC t. It uses the same formula as market_allocation_rl._hac_t (:285-291), reimplemented because that CLI module is not a library.
- time_under_water(equity) -> {max_sessions (longest run strictly below the prior peak), fraction (share of sessions under water), current_sessions}.
- ols_beta(r, m) -> {beta, alpha_annual, alpha_nw_t}.

#### `backend/market/trials_registry.py (new)` — append / read / lock / trial_counts / matched_returns / load_legacy

Constants:
- SCHEMA = 'candidate-trial/1'
- FILE = 'trials.jsonl', stored under the harness out dir (default data/market/desk/candidate-bench/)
- LOCK = 'trials.lock', taken with fcntl.flock(LOCK_EX | LOCK_NB); refuse when it is held.

append(path, record):
- Writes one canonical JSON line (sort_keys, separators=(',', ':'), allow_nan=False).
- Adds seq and prev_sha256 (sha256 of the previous line's bytes, or 64 zeros for the first line).
- Opens with O_APPEND and fsyncs. It never rewrites.

read(path):
- Verifies the hash chain, seq and schema, and raises on any broken line (fail closed).

The record has these fields:
- trial_id (uuid4 hex), event ('started' | 'complete' | 'failed'), run_id, recorded_at (UTC)
- candidate_id, variant_id, family, counts_as_trial (bool; false only for purpose='harness-acceptance', whose fingerprint must equal the incumbent's)
- gate_path, gate_sha256, protocol_hash, candidate_fingerprint, report_binding_sha256, code_revision
- calendar {first, last, sessions, dates (ISO list), dates_sha256}
- returns {'zero': {'10': [...], '25': [...]}, 'tbill': {...}}: composite daily returns, finite floats, present only on 'complete'
- incumbent_returns_sha256 {cash: {cost: hex}}, results_sha256, failure

trial_counts(records, legacy, scope) -> {n_registry, n_legacy_variants, n_legacy_effective, n_total, families}:
- Counts distinct trial_ids with counts_as_trial whose first event is 'started'. A crashed run still counts.

matched_returns(records, *, dates_sha256, report_binding_sha256, cash, cost) -> (ids, (T,K) matrix, counted_not_comparable list).

load_legacy(path):
- Validates docs/research/trials-legacy-<date>.json: {schema 'candidate-trials-legacy/1', families: [{id, source, variants, effective, portfolio_level, note}]}.

#### `backend/market/candidate_gate.py (new)` — Gate / load / require_committed / require_protocol_document / refuse_rerun / evaluate

load(path, repo_root) -> Gate
- Validates schema 'candidate-gate/1' and returns (gate, gate_sha256 = sha256(file bytes), protocol_hash = sha256(canonical JSON of the parsed object)).
- Required fields:
  - candidate_id, family, purpose ('candidate' | 'harness-acceptance'), written
  - protocol_document and protocol_document_sha256
  - candidate {factory 'pkg.module:function', params}, variants [ids]
  - data {asof, desk_inputs, fundamentals, report_sha256|null, cash_series '^IRX'}
  - evaluation {first_session, last_session|null, offsets == 20, costs_bps == [10, 25]}
  - windows {primary {from, to, status}, examined {from, to, status}}
  - controls ⊆ {incumbent, calendar_only, equal_weight_book, SPY, QQQ, exposure_matched_SPY, exposure_matched_QQQ, beta_matched_QQQ}
  - statistics {bootstrap {replications, seed, min_mean_block, levels}, spa {replications, seed, benchmarks}, dsr {trial_scope, n_basis, legacy_file, legacy_families, sr_variance_floor_annual}, pbo {blocks, metric}, newey_west_lag}
  - decision {cash_column ('zero' | 'tbill'), window ('primary' | 'full'), rules [...]}, where a rule is {id, metric in {cagr_diff, total_return_diff, dsr, psr, spa_p_consistent, pbo, boot_cagr_diff_lower}, vs, costs, aggregate in {median_offset, share_offsets, composite}, op in {'>', '>=', '<', '<='}, value, when?}
  - forward_shadow {min_weeks, max_weeks} (informational)
- Unknown keys are refused.

require_committed(path, repo_root, run_started):
- Runs git ls-files --error-unmatch and git diff --quiet HEAD -- path.
- Checks that `git rev-parse HEAD:<path>` equals `git hash-object <path>`.
- Records the commit sha and time from `git log -n1 --format=%H%x09%cI -- path`.
- Refuses when the commit time is at or after run start. The gate must be written and hashed before the run.

require_protocol_document: the sha256 of the protocol markdown must equal the declared value.

refuse_rerun(records, gate_sha256):
- Refuses when a 'complete' line exists for that gate_sha256, because frozen studies are never rerun.
- A 'failed' run may be retried, and the retry is a new trial_id that also counts.

evaluate(gate, results) -> {rules: [{id, passed, value, threshold, unavailable_reason}], historical_gate_passed, adoption_eligible: False, next_step: 'forward fidelity shadow <min>-<max> weeks, then operator decision'}.
- Any rule whose input is unavailable fails (fail closed).
- Drawdown, time under water, turnover, exposure and top weight are never valid rule metrics. The user's decision is that drawdown is reported, not gated.

#### `backend/market/candidate_bench.py (new)` — CandidateSpec / fingerprint / load_candidate

@dataclass(frozen=True) CandidateSpec with fields:
- candidate_id, variant_id
- run_kwargs: Mapping, JSON-serialisable simulate.run kwargs, excluding report, since, cost_bps and journal
- allocator: Callable | None
- dip_signal: Callable[[report], np.ndarray] | None, wrapped as DipRule(signal=..., funded=True)
- brake_path: Callable[[report], np.ndarray] | None, passed as brake_path_override
- runner: Callable[..., SimResult] | None, called as (report, *, since, cost_bps, journal, context). This hook lets later items plug in fill models such as same-session MOC buys that simulate.run cannot express.
- needs_benchmark_prices: bool
- equal_weight_universe: Callable[[report, int], np.ndarray(bool)] | None, the candidate's qualifying set. When given, an extra 'equal_weight_qualifying' control is run.
- code_refs: tuple[str, ...]

fingerprint(spec) = sha256 of canonical JSON of {ids, run_kwargs, qualnames of the callables, sha256 of each callable's source file (inspect.getsourcefile) and of each code_ref}.

load_candidate(factory, params) imports only from the 'backend.market.' or 'backend.agents.trading.desk.' prefixes. It returns one CandidateSpec per declared variant and refuses when the set of variant ids differs from gate.variants.

#### `backend/market/candidate_bench.py (new)` — INCUMBENT_V3 / CALENDAR_ONLY / check_incumbent / equal_weight_allocator

INCUMBENT_V3 is an explicit dict: {rebalance: 20, use_exits: False, event_lifecycle: True, block_overbought: True, exit_at_close: True, green_day_skip: True, live_midcycle: True, deferred_buys: True}, plus event_exposure=event_risk.live_path(panel) and config=risk.BOOK_CONFIG. It is identical to curve_block (market_daily.py:1260-1267). It is not read from LIVE_POLICY, so the /3 incumbent stays fixed when a later switch edits LIVE_POLICY.

CALENDAR_ONLY is INCUMBENT_V3 with live_midcycle False (market_strategy_bench.py:64-67).

check_incumbent() asserts paper.POLICY_VERSION == 'cash-bounded-breakout-rotation/3', paper.REBALANCE_EVERY == 20 and event_risk.VERSION == 'fomc-3-session-weakness/2'. It returns the configuration record, including asdict(risk.BOOK_CONFIG), following nested_market_study._configuration :71-126.

equal_weight_allocator(universe=None) -> allocator(report, panel, config, t):
- Weights 1/n over report.sides names, excluding panel.benchmark, with finite positive adj_close at t.
- The benchmark column gets 0.
- It runs with rebalance=20 at the same offset, use_exits=False, no LIVE_POLICY flags and no event path.
- This follows market_neural_price_study.equal_allocator :149-155.

#### `backend/market/candidate_bench.py (new)` — offsets / verify_exchange_calendar / index_prices / benchmark_context

offsets(dates, first_session, count=20) -> [(k, start_index)]:
- b0 = searchsorted(dates, first_session), and start_index = b0 + k.
- Requires dates[b0] == first_session and at least 252 sessions after b0 + 19.
- An offset is exactly simulate.run(since=dates[b0+k].astype(object)), because the reset clock starts at since (:920).

verify_exchange_calendar(dates): lazily imports exchange_calendars and requires dates[b0:] to equal the XNYS sessions exactly, reporting what is missing and extra. It is reimplemented because market_neural_price_study imports torch.

index_prices(store, symbol, sessions, asof) -> (adj_close, adj_open) or an unavailable reason. It is strict, like benchmarks._coverage_failure, and builds the open with allocation_controls.adjusted_open.

benchmark_context(store, dates, asof) -> {'dates', 'SPY', 'QQQ'} adjusted closes, the shape simulate's trend_brake and funded paths expect. It is passed only when spec.needs_benchmark_prices is set.

#### `backend/market/candidate_bench.py (new)` — Account / run_accounts

Account(name, variant, offset, cost_bps, dates, equity, returns, invested, top_weight, traded, cash_method, available, reason).

run_accounts(gate, specs, report, store, asof, workers) loops over k in the 20 offsets and cost in (10, 25), building these accounts:
- each candidate variant: through its runner, or simulate.run(report, since=..., cost_bps=cost, **run_kwargs plus hooks)
- incumbent, calendar_only and equal_weight_book through simulate.run
- SPY and QQQ: benchmarks.load_benchmark(store, s, dates[b0+k:], cost_bps=cost, asof=asof)
- exposure_matched_SPY and exposure_matched_QQQ: allocation_controls.constant_exposure(adj_close, adj_open, fraction = mean of the candidate's invested[1:] at that offset and cost, cost). This fraction is an ex-post exposure match and is labelled as such.
- beta_matched_QQQ, a return-space diagnostic that is not a tradable account under the no-leverage mandate:
  - beta_t is the OLS beta of the candidate's returns on QQQ's funded returns over a trailing 252 window, minimum 63, else 1.0, clipped to [0, 3]
  - r_t = beta_{t-1}*rQQQ_t + (1 - beta_{t-1})*rf_t - (cost/1e4)*|beta_{t-1} - beta_{t-2}|

Every account is validated: its dates must equal dates[b0+k:] and its equity must be finite and positive. A held-mark ValueError or a coverage failure makes the account unavailable with a reason. It is never dropped or zero-filled.

Parallelism: ProcessPoolExecutor with a 'fork' context on Linux and serial elsewhere. Results are ordered by (account, variant, k, cost), so the output is independent of the worker count.

#### `backend/market/candidate_bench.py (new)` — cash_credited / composite / window_slice

cash_credited(account, cy: CashYield) returns a 'tbill' twin:
- Simulator accounts use an overlay: r'_t = r_t + (1 - invested_{t-1})*rf_t, which pays interest on the prior close's cash. The method is labelled 'overlay-from-invested/1'.
- Constant-exposure accounts use native accrual through constant_exposure(cash_yield=...).
- load_benchmark accounts use the overlay with invested = [0, 1, 1, ...].
- beta_matched uses (1 - beta)*rf.
- If a later simulator item adds native accrual, a CandidateSpec can supply it, and the harness then prefers the native series and labels it.
- The zero column is never altered.

composite(accounts over k) is the tranche NAV on the common window [b0+19, end]:
- NAV_t = mean_k(E_{k,t}/E_{k,b0+19}).
- Returns come from NAV, and invested and top weight are NAV-weighted means.
- It is unavailable if any offset is unavailable.

window_slice(account, lo, hi) keeps the carried marks, rebased at the mark before lo, with no reset and no extra cost. These are the same semantics as neural_study_metrics._fold_curve (:512-527).

#### `backend/market/candidate_bench.py (new)` — metrics / offset_summary / statistics / journal_offset_zero

metrics:
- For each (offset | composite, cost, cash column, window in {full, primary, examined}), build neural_study_metrics.Curve objects named candidate, incumbent, SPY, QQQ and equal_weight, plus the extra controls, and call neural_study_metrics.scorecard(curves, cost_bps=cost). For the tbill column, replace its 'cash_yield' key with the CashYield provenance.
- Also report:
  - time_under_water
  - desk scorecard.yearly and matched_at_volatility at QQQ's volatility
  - rolling 63/252 wins vs equal_weight, using the same definition as _rolling_wins :198-210
  - strategy_bench.build(sessions, series) for REGIMES (vol ddof=0, labelled)
  - neural_study_metrics.regime_scorecard with RegimeEvidence(panel.dates, SPY adj_close)

offset_summary: for each comparator, the median, min and max of per-offset differences in CAGR and total return, and share_offsets = the fraction of the 20 offsets with a strict win.

statistics: on the composite, per cash column, cost and window:
- paired_bootstrap vs each control, with mean_block = max(optimal_block_length(diff), gate.min_mean_block)
- entry_pilot.paired_interval with block 20 as a continuity cross-check
- psr and min_trl for candidate minus QQQ and candidate minus incumbent
- dsr with:
  - N = trials_registry.trial_counts(...).n_total
  - V = max(the variance of the per-period active SRs of comparable registry trials, sr_variance_floor_annual/252)
  - the report shows N_registry, N_legacy_variants, N_legacy_effective, the V source and SR0
- spa vs incumbent and vs QQQ over matched_returns from the same family, including this run. The report shows k_used and counted_not_comparable.
- cscv_pbo over the declared variants plus the incumbent
- newey_west_t(lag) and ols_beta vs QQQ

journal_offset_zero: journals the candidate and the incumbent at offset 0 at both costs:
- ResearchJournal is built as in nested_market_study._journal :169-189
- verify_snapshot and NAV equality to 1e-12 follow :193-232
- ResearchJournal.archive writes into the run dir
- a candidate runner without journal support is recorded as journal 'unavailable'

#### `backend/market/candidate_bench.py (new)` — run / write_artifacts / render_markdown

run(gate, specs, *, store, report, out_root, workers, dtb3_csv=None) -> (results, arrays) does these things:
- binds the report with nested_market_inputs.binding (:304)
- checks that the report pickle sha256 matches when the gate pins one
- records source hashes like nested_market_study._source_hashes (:54-67) and checks them again at the end, refusing if they changed mid-run
- records the runtime like _runtime (:389-419)

write_artifacts writes a fresh directory <out_root>/<run_id>/, where run_id = <slug>-<gate_sha12>-<UTCyyyymmddThhmmssZ>. It refuses an existing directory (pattern check_destination :500-509). Contents:
- manifest.json: gate, protocol_hash, commit, fingerprint, binding, sources, runtime, data provenance for SPY/QQQ/^IRX partitions and source_time, the DTB3 cross-check {csv sha256, max and median |IRX - DTB3|}, and receipts {file: {sha256, bytes}}
- results.json: schema 'candidate-bench/1' with calendar, data, configuration, accounts, comparisons, statistics, registry {lines_read, last_line_sha256, trial_id, N}, verdict and caveats. The caveats cover survivorship, the split-cap look-ahead in value/expectations-gap, LLM-tone hindsight, examined windows, the zero-yield paper account, and IEX/SIP.
- accounts.npz: float64 arrays keyed <cash>/<cost>/<account>/<variant>/<offset|composite>/{equity, returns, invested, top_weight}, plus the dates
- journals/
- report.md

render_markdown(results) produces these sections: Identity, Verdict, Composite tables (zero and tbill, for each cost), Offsets (median/min/max/share vs each control), Windows (2016-2020 primary / 2021-26 examined), Regimes, Statistics (CIs, PSR/DSR with the N breakdown, SPA l/c/u, PBO), and Caveats. Every number is generated, with no hand edits.

#### `backend/cli/market_candidate_bench.py (new)` — build_parser / main

Command: python -m backend.cli.market_candidate_bench

Flags:
- --root (default data/market)
- --gate PATH (required)
- --out (default data/market/desk/candidate-bench)
- --report-pickle PATH, checked against gate.data.report_sha256
- --build-report DIR: runs desk.run(store, asof, inputs, fundamentals) from the gate, writes <asof>-<sha12>.pkl and a .sha256 file, and exits
- --workers (default 1)
- --dtb3-csv PATH
- --dry-run: validates the gate, git, the protocol document, the calendar, SPY/QQQ/^IRX coverage and the candidate import, prints the planned run count, and writes nothing

Order in main:
1. gate checks and refuse_rerun
2. registry lock
3. append a 'started' line
4. build the accounts
5. append a 'complete' line with the composite returns
6. compute statistics (reading the registry)
7. evaluate the verdict
8. write artifacts
9. release the lock

On an exception it appends 'failed' with the reason and exits 1.

It never touches paper.py state, the broker, the network or data/market/desk/strategy_bench.json.

#### `backend/cli/market_strategy_bench.py, backend/market/strategy_bench.py, backend/market/benchmarks.py, backend/agents/trading/desk/simulate.py, backend/market/neural_study_metrics.py, backend/market/entry_pilot.py, backend/market/research_journal*.py` — (no change)

These are reused read-only. strategy_bench.json is a live Research-page payload (api/v1/market.py:169, DeskPanel.tsx:1553), so the harness writes elsewhere. Simulator changes such as MOC buys, same-auction swaps or native cash accrual belong to other items and plug in through CandidateSpec.runner or run_kwargs.

#### `docs/research/gates/TEMPLATE.gate.json, docs/research/gates/harness-acceptance-null-2026-09-26.gate.json (new)` — gate format

Template defaults. The operator confirms the thresholds.

Settings:
- evaluation.first_session 2016-01-04, offsets 20, costs [10, 25]
- windows: primary 2016-01-04..2020-12-31 'untouched-for-intraday-timing'; examined 2021-01-04.. 'examined'
- decision.cash_column 'zero', decision.window 'primary'

Rules:
- R1: cagr_diff vs equal_weight_book, median_offset > 0 at both costs
- R2: cagr_diff vs equal_weight_book, share_offsets >= 0.75 (15/20) at both costs
- R3/R4: the same two tests vs QQQ
- R5/R6: the same two tests vs SPY
- R7: vs incumbent, median > 0 and share >= 0.75
- R8: dsr vs QQQ >= 0.95 at 25 bp
- R9: dsr vs incumbent >= 0.95 at 25 bp
- R10: spa_p_consistent vs incumbent < 0.05 at 25 bp
- R11: pbo < 0.2 when there are 2 or more variants

Statistics settings:
- bootstrap: 10,000 replications, seed 20260926, min_mean_block 20
- spa: 10,000 replications
- pbo: 16 blocks
- newey_west_lag 20
- sr_variance_floor_annual 0.09

The acceptance gate uses purpose 'harness-acceptance', candidate = incumbent config and counts_as_trial false.

#### `docs/research/trials-legacy-2026-09-26.json (new), docs/research/candidate-bench-2026-09-26.md (new)` — legacy trial count; harness design doc

Legacy file: one row per prior portfolio-level study family, with {id, source doc, variants, effective, note}. Examples are the FOMC windows (48 variants), the dead-cat bounce (56), the reset cadence sweep, ENTRY_BAND_Z, the vol/vol_trend allocations, and the neural, HGB and nested studies. Each source doc is cited.

Design doc:
- the method and each convention's origin, marked measured, inherited or default
- the gate format
- the registry semantics
- why numpy SPA instead of arch
- known limits: overlay approximation, ex-post exposure match, beta-matched leverage, 2019-2020 IEX exposure in earlier intraday studies
- a status table

#### `docs/diagrams/market-data.mmd (+ regenerated .svg)` — research subsystem

Add nodes and edges:
- CLI market_candidate_bench
- committed gate file, which is hashed before the run
- trials registry (append-only JSONL, hash-chained)
- ^IRX cash-yield series
- run archive

Draw them next to the existing Study, Journal and Scorecards nodes (:30-46). Render with the dockerised mermaid-cli on the Spark. Diagram impact: UPDATED - market-data.

### New files

New files:
- backend/market/candidate_stats.py: pure statistics (stationary bootstrap, Politis-White block length, paired CIs, PSR/MinTRL/DSR, Hansen SPA, CSCV PBO, Newey-West t, time under water, OLS beta). Uses only numpy and statistics.NormalDist.
- backend/market/trials_registry.py
- backend/market/candidate_gate.py
- backend/market/candidate_bench.py
- backend/cli/market_candidate_bench.py
- backend/tests/test_candidate_stats.py
- backend/tests/test_trials_registry.py
- backend/tests/test_candidate_gate.py
- backend/tests/test_candidate_bench.py
- backend/tests/test_market_candidate_bench_cli.py
- docs/research/candidate-bench-2026-09-26.md
- docs/research/gates/TEMPLATE.gate.json
- docs/research/gates/harness-acceptance-null-2026-09-26.gate.json
- docs/research/trials-legacy-2026-09-26.json
- docs/research/harness-acceptance-null-results-<date>.md: the rendered report.md from the acceptance run, with results.json sha256 and run_id in its header.

Runtime artifacts on the Spark, not committed because data/ is gitignored (.gitignore:34):
- data/market/desk/candidate-bench/trials.jsonl and trials.lock
- data/market/desk/candidate-bench/reports/<asof>-<sha12>.pkl and .sha256
- data/market/desk/candidate-bench/<run_id>/{manifest.json, results.json, accounts.npz, journals/, report.md}
- a new ^IRX bars partition in data/market/bars/, written by market_snapshot with operator approval

### Tests

Every test function gets the plain-language comment AGENTS.md requires. Fixtures are shaped like live data, per the operator memory 'fixtures must be live-shaped':
- the calendar is the real XNYS session list from exchange_calendars, 2015-01-02..2021-12-31, holidays included
- tickers are real (NVDA, AVGO, MU, SNDK, CRWV); CRWV is NaN before a mid-sample listing, and SPY is the benchmark column as in funded_simulator_fixtures._panel
- trial ids are 32-hex uuid4
- ^IRX bars omit Columbus Day and Veterans Day (the bond market is closed while stocks trade) and hold a 0.00-0.05 stretch, a single -0.02 print, and 2023-like 5.2-5.3 levels
- the store double follows the _Store pattern in test_benchmark_boundary.py:74-80

backend/tests/test_candidate_stats.py
1. stationary_indices: indices are in [0, n); the empirical mean block length is within 10% of mean_block at 20,000 draws; the same seed gives identical output; mean_block=1 gives iid draws.
2. optimal_block_length: iid gives <= 3; AR(1) with phi 0.8 gives more than phi 0.2; the result is never above ceil(min(3 sqrt n, n/3)); it is deterministic.
3. paired_bootstrap: identical series give a point and every interval of exactly 0; b = a - 1bp/day gives a mean-difference interval containing +1bp and excluding 0 at n=2,500; the same indices are applied to both series (checked by a monkeypatched index generator).
4. dsr reproduces the Bailey-Lopez de Prado worked example with 250 periods/yr. Per-period SR = 2.5/sqrt(250), V = 0.5/250, T = 1,250, skew -3, raw kurtosis 10. N=100 gives 0.9004 ± 1e-3 and N=46 gives 0.9505 ± 1e-3 (checked numerically with python -c on 2026-09-25: 0.90040 and 0.95050). N=1 gives psr(x, 0). Normal returns give kurtosis about 3, which guards against using excess kurtosis. min_trl is inf when sr <= sr_star. Zero variance gives None with a reason.
5. spa: p_lower <= p_consistent <= p_upper on random data. Size under the null (K=5 iid N(0,1) differences, T=500, B=499, 200 simulations) rejects at 5% no more than 10% of the time. Power: one column with mean 0.25 sd gives p_c < 0.05. omega=0 columns are excluded with a reason, and if all are excluded p=1.
6. cscv_pbo: S=16 gives n_splits 12,870. Pure-noise N=10 gives PBO in [0.3, 0.7] with a fixed seed. One column with +5bp/day drift in every block gives PBO < 0.05. Odd S, T < S or N < 2 are refused.
7. newey_west_t equals the Bartlett formula of market_allocation_rl._hac_t on a fixed vector (reimplemented inline in the test). time_under_water is checked on a hand-made curve (max 3 sessions, fraction 0.4).

backend/tests/test_trials_registry.py
1. append writes a canonical line, and seq and prev_sha256 chain correctly.
2. read raises on an edited middle line, a dropped line, a NaN or a schema mismatch.
3. The lock is refused while it is held (a second fd in the same test).
4. trial_counts counts a started-then-failed trial, ignores counts_as_trial false, and adds the legacy effective and variants separately.
5. matched_returns excludes a trial with a different dates_sha256 or report binding but lists it in counted_not_comparable.
6. A uuid4 trial_id round-trips unchanged.

backend/tests/test_candidate_gate.py
1. The template loads. A missing field, an unknown key, costs other than [10, 25], offsets other than 20, or drawdown as a rule metric are each refused.
2. protocol_hash is stable across key order and whitespace, and gate_sha256 changes with any byte.
3. require_committed in a tmp git repo (git init via subprocess): untracked is refused, modified-after-commit is refused, committed is accepted with commit sha and time returned, and a commit time at or after run start is refused.
4. A protocol document hash mismatch is refused.
5. refuse_rerun refuses after 'complete' and allows after 'failed'.
6. evaluate: median_offset and share_offsets aggregation; op semantics; an unavailable input fails the rule; adoption_eligible is always False.

backend/tests/test_candidate_bench.py (synthetic desk report built on funded_simulator_fixtures._report, but with a real XNYS calendar and tickers)
1. offsets: 20 accounts per control; SimResult.dates[0] == dates[b0+k]; the first rebalance is at b0+k.
2. A null candidate equal to INCUMBENT_V3 gives every paired difference exactly 0.0 at every offset, cost and cash column. SPA excludes it and DSR vs incumbent is None with a reason, without crashing.
3. load_benchmark SPY equity equals constant_exposure(adj_close, adj_open, 1.0, cost) NAV with rtol 1e-12 at every offset and both costs. This cross-checks the two funded-benchmark conventions.
4. The exposure-matched fraction equals mean(candidate.invested[1:]).
5. Composite NAV equals the mean of the rebased per-offset NAVs to 1e-12. The primary and examined slices compound to the full window to 1e-12.
6. cash_credited: the zero column is untouched; tbill >= zero when invested < 1 and rf > 0; an all-cash account grows as prod(1 + rf); the overlay vs native constant_exposure(fraction 0.5) CAGR differs by less than 1bp/yr over 6 years.
7. A missing held mark on one name at one offset marks that account unavailable with a reason. The composite is then unavailable and gate rules that need it fail; nothing is dropped.
8. QQQ absent from the store makes the QQQ, exposure-matched QQQ and beta-matched QQQ controls unavailable, and the rules that need them fail closed.
9. Rolling wins vs SPY equal neural_study_metrics.scorecard's own output, and strategy_bench.build blocks are present for REGIMES.
10. Offset-0 journals pass research_journal_replay.verify_snapshot, and NAV matches the producer to 1e-12.
11. The canary test_incumbent_kwargs_match_live_policy asserts INCUMBENT_V3's flags == simulate.LIVE_POLICY at HEAD. It fails on purpose when the paper switch edits LIVE_POLICY, forcing a conscious incumbent update.
12. workers=1 and workers=2 give identical results.json except for runtime fields.
13. check_incumbent refuses a monkeypatched POLICY_VERSION.

backend/tests/test_market_candidate_bench_cli.py (tmp git repo plus the synthetic parquet store written with MarketStore)
1. --dry-run writes nothing and prints the run count.
2. A full run writes manifest, results, accounts, journals and report with matching receipts.
3. The registry gets 'started' and 'complete' lines.
4. A second run of the same gate is refused.
5. An existing run dir is refused.
6. A forced exception writes a 'failed' line and exits 1.
7. --build-report writes the pickle and sha256, and a mismatched --report-pickle is refused.

backend/tests/test_market_macro.py (append)
1. SERIES['irx'] == '^IRX', and market_daily.bar_tickers() contains '^IRX'.
2. discount_to_bond_equivalent(0.05) == 365*0.05/(360 - 4.55), and negatives floor to 0.
3. cash_yield_path is causal (rf_t uses the t-1 rate), carries forward over the bond-holiday gaps, uses calendar-day accrual (Friday to Monday is 3 days), and refuses a leading gap or a print older than 7 days.
4. parse_fred_daily handles '.', and a wrong header or duplicates are refused.

backend/tests/test_allocation_controls.py (append)
1. cash_yield=None and a zero array are both byte-identical to the current NAV.
2. fraction 0 with rf gives prod(1 + rf).
3. cash_yield combined with journal raises.

Regression suites that must stay green, unchanged: test_benchmark_boundary.py, test_strategy_parity.py, test_neural_study_metrics.py, test_entry_pilot.py, test_research_journal*.py, test_trading_simulate.py, test_market_daily.py, and test_no_undefined_names.py (ruff F821).

### Acceptance

1. Scope guard, in the trading/volatile-book-15m worktree:
`git diff --stat origin/main -- backend/agents/trading/desk/simulate.py backend/market/strategy_bench.py backend/cli/market_strategy_bench.py backend/market/benchmarks.py backend/market/neural_study_metrics.py backend/market/entry_pilot.py backend/market/research_journal.py backend/market/research_journal_replay.py` must be empty for this item.

2. Unit and regression tests, run in a Spark probe clone per the operator's notes (/tmp/anios-probe with `docker compose -p anios run --rm ...`, never during a deploy gate; AUTH_REQUIRED=false for full-suite runs):
`python -m pytest backend/tests/test_candidate_stats.py backend/tests/test_trials_registry.py backend/tests/test_candidate_gate.py backend/tests/test_candidate_bench.py backend/tests/test_market_candidate_bench_cli.py backend/tests/test_market_macro.py backend/tests/test_allocation_controls.py backend/tests/test_benchmark_boundary.py backend/tests/test_neural_study_metrics.py backend/tests/test_entry_pilot.py backend/tests/test_research_journal_replay.py backend/tests/test_market_daily.py backend/tests/test_trading_simulate.py -q`
Then run `python -m pytest backend/tests -q` and `ruff check backend scripts`.

3. Data step. This is a store write, so it needs operator approval, and no deploy is involved:
`python -m backend.cli.market_snapshot --refresh --tickers "^IRX" --data-dir data/market`
Check that store.read('^IRX') covers 2015-01-02..asof with a maximum staleness of 4 calendar days. Optionally download DTB3 manually and pass --dtb3-csv; expect a median |IRX - DTB3| below 5 bp.

4. Pin the report:
`python -m backend.cli.market_candidate_bench --root data/market --gate docs/research/gates/harness-acceptance-null-2026-09-26.gate.json --build-report data/market/desk/candidate-bench/reports`
Put the printed sha256 into the acceptance gate, then commit the gate and the protocol document before step 5.

5. Dry run: the same command with `--report-pickle <pkl> --dry-run`. It must report XNYS complete from 2016-01-04, 20 offsets × 2 costs, SPY/QQQ/^IRX coverage OK, the gate committed at a SHA, and zero files written.

6. Null acceptance run: the same command with `--report-pickle <pkl> --workers 6`. Pass criteria:
   - (a) candidate minus incumbent is exactly 0.0 on every per-offset daily return in both cash columns and at both costs; the bootstrap intervals are [0, 0]; SPA marks the candidate excluded; DSR vs incumbent is None with the zero-variance reason.
   - (b) load_benchmark SPY/QQQ equals constant_exposure(1.0) to rtol 1e-12 at all 20 offsets.
   - (c) 4 journals verify and their NAVs match to 1e-12.
   - (d) the composite and window slices reconcile to 1e-12.
   - (e) The offset-0, 10 bp incumbent vs SPY/QQQ on 2016-01-04..2026-09-18 lands within about 1 CAGR point of the 2026-09-21 common-window scorecard (incumbent 43.57%, maxDD 34.23%; SPY 15.07%; QQQ 20.07%). Any larger gap must be explained by data vintage or input changes and recorded. This is a sanity check, not an equality.
   - (f) the tbill column is at least the zero column for every account with mean invested below 1, and the SPY/QQQ tbill and zero columns differ by less than 1 bp/yr.
   - (g) trials.jsonl gains 'started' and 'complete' lines with counts_as_trial false and a valid hash chain, and rerunning the same gate is refused.
   - (h) manifest receipts match the files, results.json sha256 is recorded, report.md renders every section, and the runtime is recorded.

7. Commit the rendered report as docs/research/harness-acceptance-null-results-<date>.md. Update docs/diagrams/market-data.mmd and render the SVG. The integrator adds the CHANGELOG and NEXT_SESSION entries only after steps 1-6 pass. There is no deploy; macro.SERIES reaches the nightly only when the operator asks for a deploy.

### Files owned

New:
- backend/market/candidate_bench.py
- backend/market/candidate_stats.py
- backend/market/candidate_gate.py
- backend/market/trials_registry.py
- backend/cli/market_candidate_bench.py
- backend/tests/test_candidate_stats.py
- backend/tests/test_trials_registry.py
- backend/tests/test_candidate_gate.py
- backend/tests/test_candidate_bench.py
- backend/tests/test_market_candidate_bench_cli.py
- docs/research/candidate-bench-2026-09-26.md
- docs/research/gates/TEMPLATE.gate.json
- docs/research/gates/harness-acceptance-null-2026-09-26.gate.json
- docs/research/trials-legacy-2026-09-26.json
- docs/research/harness-acceptance-null-results-<date>.md

Edited:
- backend/market/macro.py: SERIES, plus new functions only
- backend/market/allocation_controls.py: an optional cash_yield kwarg on constant_exposure and a docstring line
- backend/tests/test_market_macro.py: appended tests
- backend/tests/test_allocation_controls.py: appended tests
- docs/diagrams/market-data.mmd and docs/diagrams/market-data.svg

Not owned (read-only reuse):
- simulate.py, paper.py, strategy_bench.py, market_strategy_bench.py, benchmarks.py, neural_study_metrics.py, entry_pilot.py, research_journal*.py, nested_market_*.py, market_daily.py
- docs/CHANGELOG.md and docs/NEXT_SESSION.md, which the integrator appends at merge

Runtime-only, gitignored: data/market/desk/candidate-bench/**

### Depends on

Code: nothing. The item builds on HEAD 990fa981 and can proceed in parallel with the simulator, selection and 15-minute items. Those items plug in through CandidateSpec.runner or run_kwargs and never edit this item's files.

Data: the ^IRX partition, fetched with operator approval, is needed only for the tbill column and the acceptance step (f). The zero column and every other part run without it.

Candidates: real candidate gates and factory modules come from the other items and are registered as trials in their own runs.

Optional later: native cash accrual in simulate._Book, if the simulator item adds it. The harness would then prefer the native series for simulator accounts.

### Risks

- Runtime. One candidate means about 4 simulator accounts × 20 offsets × 2 costs, which is 160 simulate.run calls, plus 4 journaled reruns; live_midcycle calls paper.plan every session. Mitigation: --workers with fork on the Spark, while respecting shared vLLM load. Control caching across trials is deferred (see open questions).
- Parallel-item drift. Other items will add simulate.run kwargs and may edit LIVE_POLICY. INCUMBENT_V3 is explicit, so it does not drift. The canary test fails on purpose when LIVE_POLICY changes. New simulator flags must default off so the incumbent stays identical.
- Nightly side effect. macro.SERIES feeds market_daily.bar_tickers, so the nightly will fetch ^IRX after the next deploy. That is one extra Yahoo request, and no feature changes because macro_by_session reads keys explicitly. It is visible and tested, but it is a live change and needs the operator's deploy request.
- Cash-yield approximation. For simulator accounts the overlay credits interest pro rata instead of holding it as cash until the next reset. The error is second order (under 1 bp/yr, tested on constant_exposure), and the result is labelled 'overlay-from-invested/1'. Journals stay zero-yield because the replay asserts that (research_journal_replay.py:187).
- Statistical power. On the 1,250-session primary window, DSR >= 0.95 against QQQ with N in the tens needs an annualised active Sharpe of roughly 1 or more. The research-map MinTRL figure is 708 sessions for SR 1.0 at N=1. Honest gates may therefore fail. Worked DSR examples are in the design doc so nobody is surprised.
- Trial counting. The legacy N is a judgement: raw variants or effective clusters, and which families count. Undercounting inflates DSR; the default n_basis is effective legacy plus raw registry, and both N values are reported.
- Registry durability. trials.jsonl lives in gitignored data/ on one host. Loss would reset N. The hash chain detects edits but not deletion. Needs a backup or commit decision (see open questions).
- Comparability. SPA and PBO only use trials with an identical report binding and calendar. Trials run on a newer data asof are counted in N but excluded from SPA; k_used is reported.
- Data vintages. With --prune-days 30, a gate asof older than 30 days cannot be rebuilt. The pinned report pickle with its sha256 mitigates this.
- Pickle loading. Only a pickle whose sha256 matches the gate is loaded, following market_neural_price_study.load_report.
- Hindsight caveats remain in every number: today's universe (about 19 pts/yr of name choice), the split-cap look-ahead in value and expectations-gap inputs that both the incumbent and candidates read, and LLM tone scored in 2026. The equal-weight-book control is the real hurdle, and results.json carries these caveats verbatim.
- Beta-matched QQQ implies leverage when beta > 1. It is a diagnostic only and is labelled as not tradable under the no-leverage mandate. The exposure-matched fraction is ex-post.
- Sharpe conventions differ: strategy_bench uses ddof=0 and neural_study_metrics uses ddof=1. Tables label which one each uses.

### Effort

About 5 agent-days:
- candidate_stats and tests: 1.5 days
- trials_registry, candidate_gate and tests: 1 day
- candidate_bench, the CLI, artifacts and tests: 1.5 days
- design doc, legacy trial file, gate template and diagram: 0.5 day
- Spark acceptance run and report: 0.5 day, plus the wall-clock of the run itself (an estimated 15-40 minutes at 6 workers; measure and record it)

### Open questions

1. Cash column for the verdict. The user modelled cash and SWVXX as earning T-bill yield, but the Alpaca paper account pays nothing. Should the gate's decision.cash_column default to 'zero' (conservative, the template default) or 'tbill'? Or should both be required to pass?
2. Legacy trial count. Which prior study families enter DSR's N, and is the effective (clustered) count or the raw variant count used? This needs operator sign-off on docs/research/trials-legacy-2026-09-26.json before the first real candidate run.
3. Registry storage. Keep trials.jsonl only in gitignored data/ on the Spark, add a nightly or offsite backup, or commit a returns-free index to docs/research?
4. ^IRX fetch. Approve the one-time `market_snapshot --refresh --tickers "^IRX"` store write, and the eventual nightly inclusion via macro.SERIES at the next operator-requested deploy. Is a manually downloaded FRED DTB3 CSV acceptable as the cross-check source?
5. Thresholds. Confirm the template values: 15/20 offsets, median > 0 against EW, QQQ, SPY and the incumbent at both costs, DSR >= 0.95, SPA p_c < 0.05 at 25 bp, and PBO < 0.2. Should any of them be 10 bp or 'both costs' instead?
6. Primary window. Is 2016-2020 really untouched for intraday timing? The IEX 15-minute cache used by the 2026-09-15..09-23 intraday studies spans 2019-01-02 onward, so 2019-2020 has been looked at in some form. Should the primary window be 2016-2018, or kept as declared with that caveat?
7. Desk inputs. Both the incumbent and the candidates read the expectations-gap and value inputs, which carry the split-cap look-ahead (levels_pit.py:186). Should gates default to desk_inputs=[] (the plain rule) until that defect is fixed, or keep LIVE_INPUTS for parity with /3?
8. Should control accounts (incumbent, calendar-only, EW, SPY/QQQ) be cached per report binding and offset to cut the runtime of later candidates? The v1 spec has no cache.
9. Beta-matched QQQ with beta > 1 uses implied leverage financed at the cash rate. Is it acceptable as a reported diagnostic, or should it be capped at 1, which makes it equal to QQQ?

## correctness-fixes

**Item.** Correctness fixes that flatter or distort evaluation. Each one is versioned so a live change can be shadowed before it is switched on: (1) point-in-time market cap uses the wrong split basis, and Yahoo spin-offs are recorded as splits; (2) residual_momentum fills pre-listing returns with zero; (3) the frozen ML shadow's identity guard now fails at HEAD; (4) an option to accrue a sourced cash yield in simulate._Book, default off; (5) the nightly as-of date follows UTC rather than the New York session, and --prune-days deletes point-in-time vintages; (6) several places still hard-code a 16:00 close. Ship order: 3, then 5, then the correction shadow with 2 and 1, then 4, then 6. Live impact per item is given at the end of current_state.

**HEAD.** 990fa9819a514c939b1777dca66b73e0e7e97a6d (re-checked 2026-09-25 21:54 EDT). The working tree is clean apart from 4 untracked wifi-watchdog files. origin/main is the same commit.

### Current state

Every defect was re-verified at HEAD by reading the code. No data exists locally and numpy is not installed on the Mac, so no numeric reruns were done.

(1) SPLIT BASIS
- backend/market/levels_pit.py:153-189 split_adjusted_shares multiplies a filed share count only by splits where `seen < day <= days[t]` (:185-187). panel.close is Yahoo close, split-adjusted to the fetch date (yahoo.py:22-27). Market cap is shares*panel.close (valuation.py:68; opportunity_learning.py:27).
- Result: for every session between a filing and a split that the fetch already reflects, cap = true cap / ratio. Example: AVGO 2024-07-12 read at about $78B instead of about $780B.
- Two existing tests pin this behaviour as intended: backend/tests/test_grading_input_fixes.py:43-56 (`out[0] == 250.0`) and test_expectations_clock_boundaries.py:200-224 (legacy [10,20,20,20,20]).
- Paths that apply no split at all:
  - fundamentals_asof.levels (:361-375) and levels_for (:266-318). Shares are the raw latest instant (:311-312, :345-346).
  - levels_pit.trailing_levels (:115-118), which reads raw edgar._known_series.
- Spin-offs: the Yahoo action cache records WDC as split 1.323 on 2025-02-24. Raw close was 68.715 against a cached daily close of 51.68 (docs/research/intraday-price-basis-reconciliation-2026-09-22.md:20,31-32). Nothing in backend/market handles spin-offs (grep for "spin" returns nothing).
  - Pre-spin sessions: cap is understated 1.323x.
  - Post-spin sessions before the next filing: current code multiplies the count by 1.323, so cap is overstated.
- Split ratios are stored only as floats (yahoo.py:144-148).
- The only correct share-basis alignment is neural_price_basis._aligned_versions (:188-235), which is research-only.
- Consumers:
  - Live value analyst, desk.py:209,219.
  - Live expectations gap: challenger.expectations_gap (:62-88) → market_expectations._features :368 (strict path) → log_cap and implied-growth features (:386-397) of a LightGBM retrained on full history every night. The gap is live: LIVE_INPUTS=(EXPECTATIONS_GAP,), desk.py:140-141.
  - Page re-grade in live_technical.py:170-177.
  - Evidence block fundamentals_shadow.py:45.
  - Frozen ML via ol.features → trailing_levels (opportunity_learning.py:48-56).
  - Research: market_valuation.py:242 and market_xsect_net.py:138.

(2) RESIDUAL MOMENTUM
- baselines.py:158-169 sets own = where(isfinite, returns, 0) at :161. panel.rolling_beta falls back to beta 1 (panel.py:104-113).
- Result: residual = -market on pre-listing rows, and a window needs no known returns. trailing_sum (:22-37), by contrast, requires complete windows.
- Live through technical.opine (technical.py:128). rank_blend propagates NaN (baselines.py:122-128). The residual_momentum_120 evidence (technical.py:173) is shown in live_technical.py:647.
- No universe name listed within the last 141 sessions (the latest are CRWV 2025-03-28 and GLXY 2025-05-16). Historical rows for CRWV, SNDK, NBIS, ALAB, OKLO, GEV, CORZ and GLXY in their first ~141 sessions are distorted.

(3) SHADOW IDENTITY
- opportunity_shadow.identity (:41-47) hashes the bundle plus the source of growth_pilot, opportunity_learning, edgar, levels_pit, calendar and opportunity_shadow.
- I recomputed it read-only with the same algorithm:

| Revision | Identity |
|---|---|
| HEAD | 95a54c5804a2d85610a8f2c069bfd87e6fc5d5a543002d1e57c5dc9c2842a551 |
| df4dc669^ | fb37c034… |
| 26b3cb14 | dc1d5fa6…, which matches the last declared `to` in data/opportunity_shadow_migrations.json |

- Two commits changed hashed files without a declaration:
  - 4cadc135 (2026-09-25 09:59) added calendar.reviewed_sessions.
  - df4dc669 (10:18) added calendar.publication_session, strict flags in edgar._known_quarters and _event_series, and levels_pit basis_dates/strict_publication.
- The diff 26b3cb14..HEAD on hashed files is additive. calendar.py has additions only. The non-strict edgar._known_series still means filed <= session. trailing_levels, ttm_series and _future_session_offset are untouched. A declaration is therefore justified.
- test_opportunity_shadow.py:216-220 asserts migration('19f933ff…', identity(BUNDLE)) is not None, so it fails at HEAD. The unit gate is red and deploy.sh is blocked.
- The nightly pulls main before it runs (NEXT_SESSION.md:7155-7158; market_daily.py:829-831). So tonight's 2026-09-25 observation was almost certainly refused by initialize (:88-95) and swallowed by observe_if_current (:247-254). A missed session cannot be backfilled.
- The next nightly is Monday 2026-09-28 at 19:30 ET.

(4) CASH YIELD
- simulate._Book (:1303-1339) changes cash only in _fill (:1524-1592).
- Marks happen at :1092-1112 (funded), :1117-1124 (event lifecycle) and :1261-1267 (default).
- The research_journal manifest has cash_yield 0.0 (:185), and replay rejects a non-zero value (research_journal_replay.py:187).
- No T-bill series is stored (macro.SERIES :40-45).

(5) AS-OF AND PRUNE
- market_daily._run :1513 sets asof = datetime.now(UTC).date(). The cron is `30 19 * * 1-5` on a New York-time host (NEXT_SESSION.md:7895-7896).
- From EST (the first run is Monday 2026-11-02) the partition is labelled D+1.
- snapshot._repair_sessions (:167-199) requires exchange_status(source_time).session == asof and complete_through == asof (:178-182, :193-198), so every repair would be refused all winter.
- snapshot.refresh (:388) defaults to UTC as well.
- prune (:232-253) deletes every partition older than asof-days except the newest, for PRUNABLE (:46), called at :1623. The documented cron passes --prune-days 30 (NEXT_SESSION.md:9459-9467). ~/desk_daily.sh is not in the repo.

(6) 16:00 CLOSES
- alpaca.sessions: `minutes >= 16*60` (:211).
- intraday.py: BARS=26 (:25); keep window (:74).
- tape.session_tape: slots 0..25 (:46-48) via alpaca.sessions (:93).
- record_status.CLOSE (:23) used at :46.
- execution_quality.CLOSE_MINUTE (:50) used at :81.
- Stored 15-minute bars include extended hours (intraday.py:10-13). On 13:00 early-close days the research paths therefore keep 13:00-15:45 after-hours prints as regular bars, and intraday last_close/prev become an after-hours print.
- calendar.session_close (:138-140) knows early closes only for 2019-2028. The 2016-2018 part of the primary 2016-2020 window is not covered.
- intraday_inputs.ResearchCalendar (:19-55) is the fail-closed research calendar. load_calendar (:59-89) requires the current years to equal the early-close years, so nyse_early_closes.json cannot take 2016-2018.
- Out of scope, noted only:
  - opportunity_shadow.py:201 `hour < 16`: frozen, and the nightly runs at 19:30.
  - edgar.py:153-158 and fundamentals_asof.py:81-88 16:00 acceptance cutoffs: hashed legacy code; the strict path already uses publication_session.
  - timing_research.py:58 and market_pick_audit.py:31: research.
  - intraday_entry.py:97 SESSION_CLOSE: unused.

LIVE IMPACT
- (1) Yes, once switched on. Live grades, book and orders change through the expectations gap, which retrains on the corrected history. The value analyst's last row changes only within PERSISTENCE=3 sessions of a split (opinions.py:19). The page re-grade, the fundamentals_asof evidence and the historical curve change too.
- (2) Yes, once switched on, but it should change no last-row grade today. It will affect every future listing for ~141 sessions.
- (3) Live ML shadow ledger continuity and the deploy gate. No orders.
- (4) None. Research simulators only; the Alpaca paper account earns nothing.
- (5) asof: an operational fix, not a no-op. At 19:30 in summer it gives the same label as today, but runs started after 20:00 EDT get a new label. In winter it restores repairs and New York-dated partitions. prune: storage only, no grades.
- (6) record_status and execution_quality are display and evidence only. alpaca, intraday and tape are research inputs to the 15-minute engine and the 2016-2020 gate.

### Changes

#### `backend/market/data/opportunity_shadow_migrations.json` — (data row) item 3 — land on MAIN directly, before 2026-09-28 19:30 ET

Append {"from": <the ledger's actual latest policy, expected dc1d5fa6a445b8d0fcfaddc0886fcd13d2025f26b771ece3a6fb37aab574fbed>, "to": "95a54c5804a2d85610a8f2c069bfd87e6fc5d5a543002d1e57c5dc9c2842a551", "declared": <date>, "reason": "4cadc135 added calendar.reviewed_sessions. df4dc669 added calendar.publication_session and strict flags in edgar and levels_pit, with legacy defaults. The shadow's reads are unchanged: trailing_levels, ttm_series, edgar._known_series (filed <= session when not strict), _future_session_offset, the model, features and execution. Session 2026-09-25 was refused by the guard and is not backfilled."}. If the Spark ledger's latest row still carries 19f933ff…, add the same `to` from 19f933ff as well. Compute `to` from the exact tree being pushed. Declarations must always run from the ledger's latest observed policy to the current identity, because initialize() (:85-104) allows only one hop. Do NOT change identity() to hash individual functions. That would itself change the identity, and function-level hashing misses module constants such as QUARTERS and edgar tag tables.

#### `backend/tests/test_opportunity_shadow.py` — test_the_deployed_ledger_continues_into_the_current_identity (:216-220) + new golden input test

Set `deployed` to the ledger's actual latest identity, read from the Spark. Add test_shadow_inputs_are_unchanged_on_a_live_shaped_store. It builds a tmp MarketStore with 3 tickers from the bundle plus SPY on real sessions, a 10:1 split and real-shaped edgar frames, hashes ol.features(panel, store, asof) values plus the trailing_levels arrays, and pins the digest computed at the pre-change HEAD. From now on, any identity declaration requires this test to pass unchanged. That makes the declaration a mechanical check rather than a claim.

#### `backend/cli/market_daily.py` — _nightly_asof (new), _run :1513 — item 5a, MAIN, before 2026-11-01

New `_nightly_asof(now: datetime) -> date` returns now.astimezone(calendar.NEW_YORK).date(). calendar.NEW_YORK already exists at :49, so calendar.py is not edited. :1513 becomes `asof = args.asof or _nightly_asof(datetime.now(tz=UTC))`. New guard before refresh: if the newest bars partition in store.asofs() is later than asof, print that a UTC-labelled partition exists and raise SystemExit(75). Otherwise store.has() would silently skip every ticker (snapshot.py:399-403). An explicit --asof behaves exactly as today.

#### `backend/market/snapshot.py` — refresh :388

Default `asof = asof or datetime.now(tz=UTC).astimezone(NEW_YORK).date()`. An explicit asof is unchanged. Optional consistent one-liners for manual CLIs: market_edgar.py:132, market_tone.py:331, market_fundamentals_asof.py:217, market_intraday.py:52.

#### `backend/cli/market_daily.py` — prune(root, asof, days, keep='none') :232-253; --prune-keep flag; call :1623 — item 5b

New keep argument with values 'none' | 'weekly'. 'none' keeps today's behaviour byte for byte. 'weekly': among partitions older than the cutoff, for each kind in PRUNABLE, retain the newest partition of each ISO week and the newest of each calendar month; the newest overall is still always kept. New CLI flag `--prune-keep {none,weekly}` with default 'none'. When --prune-days>0 and keep is none, print one line: 'pruning deletes point-in-time vintages; pass --prune-keep weekly'. The call at :1623 passes args.prune_keep. The operator adds `--prune-keep weekly` to ~/desk_daily.sh. Partitions already deleted cannot be recovered.

#### `backend/agents/trading/desk/desk.py` — LIVE_CORRECTIONS, CORRECTION_* constants, run(..., corrections=LIVE_CORRECTIONS), DeskReport.corrections

Add constants CORRECTION_SHARE_BASIS='share-basis/2', CORRECTION_RESIDUAL_MOMENTUM='residual-momentum/2' and LIVE_CORRECTIONS: frozenset[str] = frozenset(). run() gains `corrections: frozenset[str] = LIVE_CORRECTIONS`; an unknown name raises ValueError before assembly. The share basis is passed to point_in_time_levels at :219 and to challenger.expectations_gap at :228. The momentum version is passed to technical.opine at :217. DeskReport gains `corrections: tuple[str, ...] = ()`, which the record provenance carries. The default reproduces today byte for byte. Switching a correction on live is a separate one-line commit that adds it to LIVE_CORRECTIONS, made only on operator approval after its shadow review.

#### `backend/market/correction_shadow.py (new)` — KEY, corrected_report, compare, block

KEY='corrections'.
- `corrected_report(store, report, asof, correction) -> DeskReport` starts from the plain opinions ((report.alternate or report).opinions).
  - share-basis/2: recompute value.opine with point_in_time_levels(share_basis=v2). If EXPECTATIONS_GAP is in report.inputs, recompute challenger.expectations_gap(share_basis=v2) and apply with_gap.
  - residual-momentum/2: recompute technical.opine(panel, report.regime.ai_trend, momentum=v2).
  - Then trading_desk.assemble(panel, sides, opinions, report.regime, report.inputs, fundamentals_source=report.fundamentals_source).
- `compare(live, corrected, version) -> dict` has the same shape as fundamentals_shadow.comparison (:63-106) but uses keys live/corrected, plus `version` and the summary fields grades_changed, book_names_changed and turnover_if_switched.
- `block(store, report, asof)` returns {'live': sorted(report.corrections), 'shadowed': {version: compare(...) or {'error': str}}} for every correction not yet live. It never raises.

#### `backend/cli/market_daily.py` — _corrections_block (new), record(..., corrections=None) :960-971, _run after :1568

`_corrections_block(store, report, args.asof)` prints a summary line per correction and returns None on any exception, the same pattern as _fundamentals_block at :894-900. record() gains `corrections: dict | None = None`, written to record['corrections']. provenance gains 'corrections_live'. With no corrections, the record has corrections=None and nothing else changes.

#### `backend/market/live_technical.py` — technical/value re-grade :169-177

Pass trading_desk.LIVE_CORRECTIONS to technical_analyst.opine (momentum version) and to point_in_time_levels (share_basis), so the page and the record always agree.

#### `backend/market/share_basis.py (new, deliberately not in the shadow hash)` — PRICE_ONLY, is_share_split, classify, PriceBasis, read_basis, to_price_basis, align_versions, distribution_factor

PRICE_ONLY: dict[(ticker, date), reason] = {('WDC', date(2025,2,24)): 'SanDisk spin-off recorded by Yahoo as split 1.323 (docs/research/intraday-price-basis-reconciliation-2026-09-22.md:31-32)'}.

`is_share_split(r)`: Fraction(r).limit_denominator(100) matches r within 1e-6 relative, and the numerator is at most 100. This covers 2, 3/2, 4, 5/4, 10, 20, 1/10 and 1/15, and rejects 1.323.

`classify(ticker, actions) -> (splits, distributions)`: split-kind actions that are in PRICE_ONLY or fail is_share_split go to distributions.

PriceBasis(splits, distributions, basis: date).

`read_basis(store, ticker, asof) -> PriceBasis | None`: one store.read; basis = history.complete_through, the price vintage's adjustment date.

`to_price_basis(shares, dates, seen, pb) -> ndarray`: factor_t = product of r over splits with seen[t] < d <= pb.basis, times product of r over distributions with dates[t] < d <= pb.basis. NaT seen gives NaN; NaN shares stay NaN.

`align_versions(versions, pb)`: multiply each 'shares' Version value by the product of split r with v.filed < d <= pb.basis.

`distribution_factor(dates, pb) -> (T,)`: product of distribution r with dates[t] < d <= pb.basis.

Why: a real split changes the share count, so the factor depends on the count's filing date. A spin-off leaves the count unchanged; only the price was restated, so the factor depends on the session date.

#### `backend/market/levels_pit.py (hashed: needs a shadow declaration in the merge commit to main)` — SHARE_BASIS_SESSION/PRICE, point_in_time_levels(..., share_basis=SHARE_BASIS_SESSION) :193-239, trailing_levels(..., share_basis=SHARE_BASIS_SESSION) :76-126

New constants SHARE_BASIS_SESSION='share-basis/1' and SHARE_BASIS_PRICE='share-basis/2'. In v1 both functions are unchanged byte for byte; split_adjusted_shares and _splits are not touched. In v2:
- point_in_time_levels: out['shares'] = share_basis.to_price_basis(series['shares'][0], panel.dates, known['shares'][2], read_basis(store, ticker, asof)). The source filing dates are always used, strict or not.
- trailing_levels: shares come from edgar._known_quarters(record.facts, 'shares', panel.dates) values [0][0] and source dates [2], through to_price_basis.
- If read_basis returns None, the raw count is left as is; with no price the cap is NaN anyway.
The frozen ML path keeps calling trailing_levels with no argument, so it stays v1.

#### `backend/market/fundamentals_asof.py` — levels(panel, versions_by_ticker, ytd_names=ALL_YTD_NAMES, *, price_bases=None) :361-375

price_bases: Mapping[str, PriceBasis] | None. With None, nothing changes. When given: levels_for(share_basis.align_versions(found, pb), ...), then out['shares'][:, col] *= distribution_factor(panel.dates, pb). levels_for, Version and the store frame are unchanged.

#### `backend/market/fundamentals_shadow.py` — asof_report :33-59

If CORRECTION_SHARE_BASIS is in base.corrections, build price_bases with share_basis.read_basis for the panel tickers and pass them to fa.levels. The nightly as-of evidence then compares two value analysts on the same share basis, which fixes defect [5] (spurious 'grades differ' around splits).

#### `backend/cli/market_expectations.py; backend/market/challenger.py` — _features(store, panel, records, asof=None, *, share_basis=SHARE_BASIS_SESSION) :360-377; expectations_gap(store, book, asof=None, *, share_basis=SHARE_BASIS_SESSION) :62-88

Thread share_basis through to point_in_time_levels(..., strict_publication=True, share_basis=share_basis) at :368. The default is byte for byte. The gap retrains on corrected log_cap and implied growth only when v2 is passed.

#### `backend/market/baselines.py` — RESIDUAL_MOMENTUM_FILLED/KNOWN, residual_momentum(..., *, require_known=False) :152-170

New constants 'residual-momentum/1' and 'residual-momentum/2'. require_known=False is today's code. require_known=True:
- residual = where(isfinite(returns), residual, NaN).
- For t >= length+skip, out[t, j] is NaN unless all `length` window residuals are finite, the same completeness rule as trailing_sum.
- Otherwise sum/std are computed with the same arithmetic, so fully known columns equal v1 exactly.
- The beta-1 fallback for young names is unchanged and documented.

#### `backend/agents/trading/desk/technical.py` — opine(panel, ai_trend=None, *, momentum=baselines.RESIDUAL_MOMENTUM_FILLED) :122-173

At :128 call residual_momentum(panel, MOMENTUM_SESSIONS, MOMENTUM_SKIP, require_known=(momentum == baselines.RESIDUAL_MOMENTUM_KNOWN)). A young name then gets a NaN technical score (neutral stance) until it has 141 known returns.

#### `backend/market/cash_yield.py (new)` — SYMBOL, VERSION, session_rates

SYMBOL='^IRX' (13-week bill, percent, Yahoo). VERSION='cash-yield/1'.

`session_rates(store, panel, asof=None) -> (rates (T,), known (T,) bool)`:
- y = macro.aligned_close(store, SYMBOL, panel, asof) / 100, forward-filled and clipped at 0.
- rates[t] = (1+y[t])**((dates[t+1]-dates[t]).days/365) - 1 for t < T-1, and 0 at T-1.
- An unknown y gives 0 with known=False.
- It is causal: the close at t prices the interval (t, t+1].
- The docstring states that ^IRX is a discount yield and that SWVXX earns roughly this rate less its expense ratio.

#### `backend/agents/trading/desk/simulate.py` — run(..., cash_rates=None) :643-676; loop :923; marks :1092/:1120/:1261; _Book.__init__ :1307-1339, _Book.accrue (new); SimResult.cash_rates/stats

run() gains `cash_rates: np.ndarray | None = None`. It must have shape (rows,), be finite and be >= 0. A ValueError is raised when a journal is attached, because research_journal_replay rejects a non-zero cash_yield at :187.

At the top of each iteration: `carry = book.cash * cash_rates[t]`, which is interest on the cash held at close t. `book.accrue(carry)` is called immediately before each mark block: before the `unpriced` computation at :1092, before :1120 and before :1261. The decision at t never sees that interest.

When cash_rates is None, no call is made, so results are byte for byte identical.

_Book gets `self.interest = 0.0` and `accrue(amount)` (cash += amount; interest += amount). SimResult gets an optional `cash_rates: np.ndarray | None = None`; stats() adds 'sharpe_excess' only when it is present.

#### `backend/cli/market_daily.py` — bar_tickers :131-134

Append cash_yield.SYMBOL so the nightly keeps ^IRX current. No live consumer reads it. Update the tickers assertion in test_refresh_order_and_tickers if it enumerates them. The one-off history backfill uses the existing market_snapshot CLI on the Spark, as an operator action.

#### `backend/market/alpaca.py` — sessions(bars, *, close_time=None) :204-214

close_time: Callable[[date], time | None] | None. With None, the current 16:00 rule applies (frozen studies still replicate). With a callable: drop days where it returns None, and drop bars with local start >= close_time(day).

#### `backend/market/intraday.py` — sessions_from(columns, *, close_time=None) :70-85; load/episodes(..., *, close_time=None)

With a callable, keep a bar only if local < the close minute of its New York day (days with no close are dropped). BARS stays 26, so early-close sessions (14 bars) are excluded by episodes_from (:104), and last_close is the true 12:45-bar close, which gives the next day a correct prev. None keeps the legacy behaviour.

#### `backend/market/tape.py` — session_tape(bars, *, close=None) :36-72; tape_tensor(panel, bars_by_ticker, *, close_time=None) :76-97

With a close given, bars in slots >= the close slot are not placed; those slots take the existing flat fill at last close with zero volume. tape_tensor passes close_time to alpaca.sessions and close_time(day) to session_tape. None keeps the legacy behaviour.

#### `backend/market/record_status.py` — last_completed_session :40-51

Replace `local.time() >= CLOSE` at :46 with `local.time() >= exchange_calendar.session_close(local.date())`. Keep CLOSE as the regular-close constant. Live display only.

#### `backend/market/execution_quality.py` — _submitted_within :70-81

Take the close minute from calendar.session_close(when.date()) instead of CLOSE_MINUTE (:50). Evidence only.

#### `backend/market/intraday_inputs.py; backend/market/data/nyse_research_sessions_2016_2018.json (new)` — load_calendar(directory=DATA, *, extra=()) :59-89

The new file uses the nyse_historical_sessions.json schema (years → {full_closures, early_closes}) and a header giving source, published and checked dates from NYSE notices. Its dates are to be verified against the source (for example 2016-11-25, 2017-07-03, 2017-11-24, 2018-07-03, 2018-11-23, 2018-12-24 early closes, and 2018-12-05 full closure). load_calendar merges `extra` files with the existing overlap and duplicate validation; the default () is unchanged. The new harness passes extra=('nyse_research_sessions_2016_2018.json',) and uses ResearchCalendar.close_time as close_time. calendar.py, nyse_historical_sessions.json and nyse_early_closes.json are NOT edited. Adding years there would change calendar.reviewed_sessions, and with it publication_session and the live strict expectations-gap training rows, the intraday_research policy_sha256, and (for calendar.py) the shadow identity.

#### `docs/research/evaluation-corrections-2026-09-XX.md (new); docs/NEXT_SESSION.md; docs/CHANGELOG.md` — design + status table

Record, for each correction: its version string, provenance (measured/inherited/default), live impact, shadow evidence and switch status. Update NEXT_SESSION with the verified SHAs. Add a CHANGELOG entry only after verification. Diagram impact is expected to be NONE: the new record block sits inside the existing nightly-to-record flow and adds no dependency (^IRX comes from the same Yahoo source). Confirm against docs/diagrams/agent-trading.mmd.

### New files

- backend/market/share_basis.py
- backend/market/correction_shadow.py
- backend/market/cash_yield.py
- backend/market/data/nyse_research_sessions_2016_2018.json
- backend/tests/test_share_basis.py
- backend/tests/test_residual_momentum_known.py
- backend/tests/test_correction_shadow.py
- backend/tests/test_cash_yield.py
- backend/tests/test_nightly_asof_and_prune.py
- backend/tests/test_early_close_sessions.py
- docs/research/evaluation-corrections-2026-09-XX.md

The golden shadow-input test is added inside the existing backend/tests/test_opportunity_shadow.py. Every new function carries a plain-language comment above it, per AGENTS.md:41.

### Tests

No prompt changes anywhere, so no functional-model test is required. Fixtures use real tickers, real NYSE sessions (holidays excluded) and real ratios, per fixtures-must-be-live-shaped.

1. test_opportunity_shadow.py
- test_the_deployed_ledger_continues_into_the_current_identity: updated constant.
- test_shadow_inputs_are_unchanged_on_a_live_shaped_store: a tmp MarketStore with NVDA, AVGO, WDC and SPY; bars 2024-05-01..2024-08-30; the NVDA 10:1 split on 2024-06-10; edgar frames with dei shares filed 2024-05-29 and 2024-08-28. The sha256 of ol.features values plus the trailing_levels dict must equal a digest pinned at pre-change HEAD.
- A stranger identity still refuses.

2. test_share_basis.py
- is_share_split accepts 2, 1.5, 4, 1.25, 10, 20, 0.1 and 1/15, and rejects 1.323. classify routes WDC 2025-02-24 to distributions and also routes any PRICE_ONLY override.
- **Core invariance (the requested test).** Two vintages written with the real MarketStore.write into one tmp store:
  - A: asof=2024-06-07, raw closes, no action.
  - B: asof=2024-06-21, pre-2024-06-10 closes divided by 10, action (2024-06-10, 10.0).
  - Filing: dei 2,464,000,000 filed 2024-05-29.
  - Assert market_cap(B, share-basis/2)[t] == market_cap(A, v2)[t] (rtol 1e-12) at every t <= 2024-06-07. Cap is taken via valuation.multiples on build_panel(asof=...) with point_in_time_levels(share_basis=v2).
  - Run this for strict_publication False and True.
  - Assert legacy B/A == 0.1 on those rows, which documents the defect.
  - Assert B cap for t >= 2024-06-10 equals raw close × 24,640,000,000.
- The same invariance for:
  - AVGO 10:1 on 2024-07-15.
  - A reverse split (ratio 0.1).
  - Two cumulative NVDA splits (4:1 2021-07-20 and 10:1 2024-06-10).
  - fa.levels(price_bases=...) with Versions.
  - trailing_levels(share_basis=v2).
- WDC spin: vintage A (2025-02-21 raw close 68.715) and vintage B (close 68.715/1.323, 'split' 1.323 on 2025-02-24), with the share count unchanged across the event. Caps are identical for t <= 2025-02-21. For t >= 2025-02-24 before the next filing, B cap = close × shares, NOT × 1.323.
- Defaults are unchanged: test_grading_input_fixes.py:43, test_expectations_clock_boundaries.py:200 and :213, and test_neural_price_basis.py all pass untouched. A vintage B with complete_through before the split's date applies no factor.

3. test_residual_momentum_known.py
- Panel of SPY (full history) plus CRWV (listed 2025-03-28, NaN before) on real sessions 2024-06-03..2026-09-24.
- Legacy is finite at rows whose window overlaps pre-listing, and equals the -market-driven value there.
- require_known is NaN until the first row whose 120-session window, ending 21 sessions back, is fully after the first return.
- require_known == legacy exactly (np.array_equal) for SPY-like fully known columns and for CRWV after that row.
- technical.opine with momentum=v2 gives CRWV a NaN technical score in those early rows and an unchanged score afterwards.
- One interior missing bar makes the v2 score NaN for the covered windows. This is a documented property; its count is to be measured.

4. test_correction_shadow.py
- Given a synthetic DeskReport with alternate and inputs=(EXPECTATIONS_GAP,), with challenger.expectations_gap monkeypatched to record its share_basis argument:
  - block() returns both versions with the documented keys.
  - A raising correction yields {'error': ...} and never propagates.
  - desk.run(corrections=frozenset()) is identical to today (same graded letters, scores and book).
  - An unknown correction name raises.
- market_daily.record carries corrections=None by default, and the block when given.

5. test_cash_yield.py
- session_rates from a ^IRX fixture (5.25 on 2023-10-02, with a weekend gap): a Friday→Monday rate uses 3 calendar days; negatives clip to 0; values before the first print are 0 with known False.
- simulate.run with no cash_rates is identical to today (array_equal on returns and equity) on funded_simulator_fixtures, and so is cash_rates = zeros.
- An all-cash book with a constant 5% yield over 2023 compounds to 1.05 ± 1e-12.
- Changing cash_rates[-1] does not change the result (causality).
- Journal plus cash_rates raises.
- stats() gains sharpe_excess only when rates are given.

6. test_nightly_asof_and_prune.py
- _nightly_asof:
  - 2026-11-03T00:30Z → 2026-11-02 (EST).
  - 2026-09-24T23:30Z → 2026-09-24 (EDT).
  - 2026-09-25T00:30Z (20:30 EDT) → 2026-09-24; legacy gave 09-25.
- snapshot._repair_sessions passes for a history with source_time 2026-11-03T00:30Z and complete_through 2026-11-02 when asof comes from _nightly_asof; it refuses with the UTC asof.
- The guard refuses when the newest partition is later than asof.
- prune: keep='none' matches the existing test_prune_keeps_newest_tone_and_records, which is unchanged. keep='weekly' on 90 daily partitions keeps exactly the last partition of each ISO week and of each month older than the cutoff, plus all within the cutoff, for every PRUNABLE kind; tone and desk are never touched.
- The CLI parses --prune-keep, defaulting to none.

7. test_early_close_sessions.py (plus additions to test_market_alpaca.py, test_market_intraday.py, test_market_tape.py, test_record_status.py and test_execution_quality.py)
- Bars on 2025-11-28 (13:00 close) including 13:00-15:45 extended-hours bars, with close_time from ResearchCalendar:
  - alpaca.sessions keeps 09:30-12:45 only.
  - intraday.sessions_from keeps 14 slots, episodes_from drops the day, and last_close is the 12:45 close.
  - tape slots 14..25 are flat with zero volume.
- A regular day (2025-11-26) is identical to legacy. Defaults are unchanged on both days.
- record_status.last_completed_session(2025-11-28 13:30 ET) == 2025-11-28; legacy gave 2025-11-26.
- execution_quality._submitted_within at 14:00 ET on 2025-11-28 → False.
- load_calendar(extra=(new file,)) covers 2016-2018, with close_time(2018-12-24)=13:00 and close_time(2018-12-05)=None. load_calendar() without extra still raises for 2017. calendar.reviewed_sessions years are unchanged (2019+).

### Acceptance

1. Item 3, on the Spark, read-only first:
- `python -c "from pathlib import Path; from backend.market import opportunity_shadow as s; r=s.latest(Path('data/market/desk/ml-forward')); print(r['sequence'], r['session'], r['policy'])"`
- `grep 'ML forward' ~/desk_daily.log | tail -5`
- Then, on the Mac, recompute the identity from the pushed tree with pure hashlib. The snippet mirrors identity(): git show of the bundle plus the 6 sources, CRLF→LF, then sha256. Assert it equals the new `to`.
- Gate-style run in a probe clone (/tmp/anios-probe, `compose run -p anios`, AUTH_REQUIRED=false caveat): `pytest backend/tests/test_opportunity_shadow.py -q`.
- The next nightly log shows 'ML forward: Observed frozen policies (sequence N)'.

2. Every item: `pytest backend/tests/test_share_basis.py backend/tests/test_residual_momentum_known.py backend/tests/test_correction_shadow.py backend/tests/test_cash_yield.py backend/tests/test_nightly_asof_and_prune.py backend/tests/test_early_close_sessions.py backend/tests/test_grading_input_fixes.py backend/tests/test_expectations_clock_boundaries.py backend/tests/test_neural_price_basis.py backend/tests/test_fundamentals_asof.py backend/tests/test_fundamentals_shadow.py backend/tests/test_market_daily.py backend/tests/test_market_technical.py backend/tests/test_funded_simulator.py backend/tests/test_funded_simulator_edges.py backend/tests/test_market_alpaca.py backend/tests/test_market_intraday.py backend/tests/test_market_tape.py backend/tests/test_record_status.py backend/tests/test_execution_quality.py backend/tests/test_intraday_inputs.py backend/tests/test_intraday_policy_fingerprint.py -q`, then the full unit gate through scripts/gate.sh, then `ruff check` and `black --check` on the touched files.

3. Merge of the branch into main: levels_pit.py is hashed, so the merge commit must carry a migrations row from the ledger's latest policy to the post-merge identity, and the golden input test must pass unchanged.

4. Shadow review before any switch-on:
- At least 5 consecutive nightly records carry record['corrections'] with share-basis/2 and residual-momentum/2 blocks.
- residual-momentum/2 is expected to show 0 grade changes today; turn it on after confirmation.
- For share-basis/2, the operator reviews the grade, book and turnover differences and the changes in gap values. Separately, a read-only historical measurement on the Spark (value IC, gap vs plain rule, published curve under v2) is written to the dated doc. It is reported as examined and not used for tuning. No frozen study is rerun.
- Switching on means adding the version to desk.LIVE_CORRECTIONS in its own commit, and only when the operator asks. The deploy is the operator's.

5. Item 5 is verified by the first EST nightly (2026-11-02): partition asof=2026-11-02 and no 'repair requires today's completed exchange session' refusals. Prune keeps weekly vintages once the operator adds --prune-keep weekly.

### Files owned

Main (items 3 and 5a/5b, because the nightly pulls main):
- backend/market/data/opportunity_shadow_migrations.json
- backend/tests/test_opportunity_shadow.py
- backend/cli/market_daily.py
- backend/market/snapshot.py
- backend/tests/test_nightly_asof_and_prune.py
- optionally backend/cli/market_edgar.py, backend/cli/market_tone.py, backend/cli/market_fundamentals_asof.py and backend/cli/market_intraday.py (one-line asof)

Branch trading/volatile-book-15m:
- backend/market/share_basis.py (new)
- backend/market/levels_pit.py
- backend/market/fundamentals_asof.py
- backend/market/fundamentals_shadow.py
- backend/cli/market_expectations.py
- backend/market/challenger.py
- backend/agents/trading/desk/desk.py
- backend/market/live_technical.py
- backend/market/correction_shadow.py (new)
- backend/market/baselines.py
- backend/agents/trading/desk/technical.py
- backend/market/cash_yield.py (new)
- backend/agents/trading/desk/simulate.py
- backend/market/alpaca.py
- backend/market/intraday.py
- backend/market/tape.py
- backend/market/record_status.py
- backend/market/execution_quality.py
- backend/market/intraday_inputs.py
- backend/market/data/nyse_research_sessions_2016_2018.json (new)
- tests: test_share_basis.py, test_residual_momentum_known.py, test_correction_shadow.py, test_cash_yield.py, test_early_close_sessions.py, plus additions to test_market_alpaca.py, test_market_intraday.py, test_market_tape.py, test_record_status.py, test_execution_quality.py, test_market_daily.py and test_fundamentals_shadow.py
- backend/cli/market_daily.py for bar_tickers and the corrections block (the same file as 5a/5b, so one owner should do these serially or rebase onto the main change)
- docs/research/evaluation-corrections-*.md, docs/NEXT_SESSION.md, docs/CHANGELOG.md

Not touched, on purpose: backend/market/calendar.py, nyse_historical_sessions.json, nyse_early_closes.json, edgar.py and opportunity_shadow.py.

### Depends on

SHIP ORDER:
1. Item 3 on main, before Mon 2026-09-28 19:30 ET. Tonight's 09-25 observation is presumably already lost; confirm from the log. It depends only on a read-only check on the Spark and on the operator/main-agent coordinating the main commit.
2. Item 5a on main, before 2026-11-01. If it ships after the switch to EST, the guard fires on the first night. Item 5b alongside it; it needs an operator edit of ~/desk_daily.sh.
3. The correction registry and shadow infrastructure, then item 2 (residual-momentum/2), then item 1 (share-basis/2), on the branch. Items 1 and 2 depend on the infrastructure. Merging to main needs a shadow-identity declaration because levels_pit.py is edited. The live switch-on comes later and is operator-gated.
4. Item 4 (cash yield). Research only. Depends on a ^IRX backfill on the Spark.
5. Item 6 (16:00 closes plus the 2016-2018 research calendar). Research and display only.

Downstream, these items are prerequisites for:
- The predeclared historical gate. It needs 1, 2, 4 and 6. The gate must pass share-basis/2, residual-momentum/2, cash_rates and close_time explicitly, and record those versions in its manifest.
- The 15-minute engine's 2016-2020 timing evaluation. It needs item 6. On early-close days the 15:45 decision and same-session MOC do not exist (the close is 13:00), so the engine must read close_time.

### Risks

Item 1
- Once switched on, it changes live grades through the retrained expectations gap. The gap's promotion evidence (+30.3%/yr against +25.2%) was measured on the distorted cap, and after the correction it may shrink. Report that as examined evidence for the operator's decision; do not tune on it.
- Share-count basis is ambiguous when a split falls between a count's period end and its filing date. Cover-page dei counts are as of `end`; us-gaap balance-sheet counts are restated. Using `filed` gets dei counts wrong in that window (rare). The alternative, masking the count the way neural_price_basis does, removes value opinions right after splits.
- The rational-ratio heuristic could misclassify an odd real split or a spin-off with a simple ratio. Mitigation: the PRICE_ONLY override table, plus a one-off read-only audit on the Spark of all ~179 stored split actions against filed share counts before and after each event.
- Editing levels_pit changes the shadow identity. A missing declaration costs an observation that cannot be recovered.
- Computing the gap twice adds nightly runtime. Measure it; if it breaks the budget, run the corrected-gap shadow weekly.

Item 2
- Young names get a neutral technical stance for ~141 sessions, so they cannot reach an A through the fundamental-plus-technical route, and the page's 'slow momentum' line disappears for them.
- One interior missing bar blanks the score for up to 141 sessions. snapshot's dropped-session guard makes that rare, but measure the count on the Spark before switching on.

Item 3
- The test's `deployed` constant goes stale after every observed hop. The golden test only covers the fixture's code paths.

Item 4
- ^IRX is a discount yield, not SWVXX's net yield. The difference is roughly the expense ratio plus the difference between discount yield and bond-equivalent yield. It must be labelled as a model and reported beside the zero-yield column, because the Alpaca paper account pays nothing.
- ^IRX printed ~0 in 2020-21; those values clip at 0.
- A journal cannot be combined with a cash yield until replay supports it.

Item 5
- If shipped during EST, a partition collision would make refresh skip every ticker. The guard fails the night closed, at the cost of the session.
- The prune fix only protects vintages from now on.
- Weekly retention makes exact replay of a non-retained day's record approximate.
- The host timezone and crontab are inferred from docs, not read.

Item 6
- The legacy defaults keep the frozen studies' early-close contamination. Only callers that pass close_time get the fix.
- The 2016-2018 calendar needs sourcing and review.
- If coverage is ever moved into calendar.py or the historical JSON, it changes the live strict gap, the intraday policy_sha256 and possibly the shadow identity. Keep it in the separate research file.

### Effort

About 6-7 engineer-days in total, plus Spark read-only checks and an operator review window of at least 5 nightly records.

| Item | Effort |
|---|---|
| 3 | ~1 h, plus the Spark read |
| 5a + 5b | ~0.5 day |
| Correction registry and shadow | ~1 day |
| 1 (share basis with spin handling, three paths, tests) | ~2 days |
| 2 | ~0.5 day |
| 4 | ~1 day, plus the ^IRX backfill |
| 6 (5 files, research-calendar file, sourcing) | ~1-1.5 days |

### Open questions

1. What is the ML ledger's latest policy and sequence on the Spark (expected dc1d5fa6 at sequence 7, session 2026-09-24)? Did the 2026-09-25 nightly log 'ML forward unavailable … Frozen experiment changed'? Declarations must start from the real latest policy.

2. Items 3 and 5 must land on main because the nightly pulls main. Who commits them, given another agent owns main? The rest go on trading/volatile-book-15m.

3. What does the spark1 crontab and ~/desk_daily.sh currently contain (is --prune-days 30 still set, is --challenger set)? What is the host timezone? Should the --prune-keep default flip to 'weekly' instead of requiring a cron edit? Deletion cannot be undone.

4. Share-count basis date: `filed` (spec default, matching the requested seen < split <= basis rule), or tag-aware (dei → end, us-gaap → filed)? The fa path has the tag; the levels_pit QuarterFact path does not.

5. Should the corrected expectations gap be computed nightly or weekly? This depends on the measured runtime.

6. Cash-yield source: ^IRX (proposed), SGOV/BIL total-return series, or SWVXX's published 7-day yield? Should the expense ratio be netted for SWVXX?

7. Does the target real account earn interest on cash? This decides whether the yield column is decision-relevant or informational only.

8. Before switching on share-basis/2, the operator decides whether the expectations gap stays live if its corrected historical edge shrinks. That is a strategy decision, not part of this fix.

## simulator-api

**Item.** Extend simulate.run and the shared paper planner so every Phase 1-3 candidate can run on the incumbent (LIVE_POLICY) path. The extension covers: (a) sizing variants; (b) a rank buffer and no de-grossing at resets; (c) reset phase, tranches and averaging over offsets; (d) redeployment to the next-best names and persistent deferred buys; (e) deterministic trim bands; (f) entry clocks with decision prices, paired-close remainders and same-auction funding; (g) profit-take and structure-exit hooks with a per-position journal; (h) a defensive destination for the trend brake (cash, cash_yield, SPY, QQQ or a per-session state array); plus a per-order fill log for paired statistics. With every new option at its default, all outputs are byte-identical to today's.

**HEAD.** 990fa9819a514c939b1777dca66b73e0e7e97a6d (origin main, commit "Record personal guidance wording checkpoint and release boundary", 2026-09-25 19:48 -0400). I re-checked it at the end of the review and it had not moved. The working tree holds only 4 unrelated untracked wifi-watchdog files. Every anchor below was opened at this HEAD. Because main is moving, rebase the trading/volatile-book-15m worktree onto origin/main before starting, and re-verify the anchors marked (!) because they are the likeliest to shift.

### Current state

INCUMBENT SIMULATOR (backend/agents/trading/desk/simulate.py)
- run() is at 643-1297 and takes 31 parameters (643-675).
- LIVE_POLICY is at 72-78 and has 5 flags: block_overbought, exit_at_close, green_day_skip, live_midcycle, deferred_buys.
- funded_allocation refuses every LIVE_POLICY flag and the trend brake (806-839), so every candidate has to live on the incumbent path.
- Brake and override setup is at 843-861. deferred_buys requires exit_at_close (862-866). live_bands = entry.bollinger_z(adj_close) (868). pending_deferred (872). The ceiling is min(FOMC path, brake path) via _ceiling_path (572-578, used at 880).

Session loop (923-1267), in order:
1. The FOMC lifecycle branch (1114-1125) calls _settle_event (582-605) and `continue`s.
2. The rebalance clock: next_rebalance starts at `start` (920). On a reset, next_rebalance = t + rebalance (1127-1129).
3. On a reset, target = decide(report, panel, config, t) (1130). decide is allocator or _targets (431-452), which calls risk.desk_targets and zeroes the benchmark column.
4. _gated_targets applies the band blocker (458-466; applied 1131-1136).
5. Between resets, book.between plus the dip add runs (1139-1154).
6. The ceiling label and the relative scaling in _event_target (552-564; 1163-1176).
7. order = book.plan(target, closes[t]) (1177), which calls planner.plan.
8. Brake and FOMC pause, then the deferred carry, then _live_midcycle (116-168) or _deferred_leg (192-218). _unpaid_buys (174-186) runs on resets (1182-1215).
9. buy_prices = opens[t+1]; sell_prices = closes[t+1] when exit_at_close and the ceiling did not change (1216-1219).
10. observe_decision, with metadata keys scheduled, event_changed, braked, sell_at_close and deferred_units (1220-1236).
11. The green-day skip, applied to every sell where opens[t+1] > closes[t] (1239-1252).
12. settle_split (1253-1260).
13. Marks (1261-1267). The journal finishes (1268-1284). SimResult is built from 11 positional values (1285-1297).

The ledger is _Book (1303-1683):
- _fill (1524-1588): one cost scalar; sells first; buys scaled to the budget; the recycle_sells flag decides whether sale proceeds fund buys.
- settle_split (1594-1616) and _fill_split (1619-1637): open buys are paid from existing cash, then sells fill at the close.
- equity (1385-1392) raises on a missing held mark.
- invested and top_weight (1376-1401) run over all columns.
- _log and finish (1640-1683) read report.graded for every column.

A latent defect worth knowing: under live_midcycle, the between/exit/dip target (1139-1154) is computed and then thrown away, because _live_midcycle replaces `order` (1193-1208). So use_exits, exits, trim and dip do nothing on ordinary mid-cycle sessions, yet dip_adds still counts the adds.

SIZING
- risk.BOOK_CONFIG (risk.py:48-50) and _holdable (135-141).
- desk_targets (160-192): candidates are A/A+ only; top_fraction is rescaled by total/graded; size_today is called; then × SIZE_MULTIPLIER × regime.exposure; then the tightening tilt _steepen_weights (236-264).
- sizing.target_weights (sizing.py:264-303): top_fraction selection at 283-286, 1/vol at 287, caps via _apply_caps (352-384), vol target at 296-299.
- `held` in desk_targets and size_today (risk.py:166,184; sizing.py:501-527) is a WEIGHT vector that turns on sizing.rebalance speed 0.5 and min_trade (429-448). No caller passes it (desk.py:401; simulate.py:444-450).
- _cap_themes (400-426) does not guard cap <= 0. A theme_cap of 0 would zero every themed name, so "theme cap off" has to be 1.0, never 0.
- nested_market_study.py:79-104 refuses any change to asdict(risk.BOOK_CONFIG) or to LIVE_POLICY. So no field may be added to SizingConfig and no key to LIVE_POLICY until adoption.

PAPER PLANNER (backend/agents/trading/desk/paper.py)
- Constants: REBALANCE_EVERY / MIN_TRADE (68-69); ENTRY_BAND_Z / ENTRY_ADD / ENTRY_NAME_CAP / ENTRY_MIN_GRADE / POLICY_VERSION (160-169).
- plan (662-835): the reset uses planner.plan plus _rebalance_orders, with whole shares, MIN_TRADE and entry_blocked (745-771, 484-524).
- Between resets: the deferred retry via _fund_buys(_deferred_orders), which DISCARDS _unpaid (786-800), then midcycle_orders (808-820).
- deferred_buys holds only this session's unfunded buys (834). bound_orders re-caps every buy at 15% and pays from cash (842-862).
- midcycle_orders (610-652): the budget is cash only (639-647).
- _rotation_orders (348-418) sends proceeds pro rata to held takers (374-378, 399-417). _entry_orders (422-475). _deferred_orders (558-604) retries once and drops the rest.
- planner.target_shares and plan (planner.py:42-87).

LIVE EXECUTION
- market_daily._paper_trade (639-816):
  - targets come from report.book (661);
  - held comes from broker positions (683);
  - event_execution takes over while orders are pending, an event is active, or the calendar is unknown (695-699);
  - paper.plan is called with finished=_downgraded (537-563), entries=_price_entries (566-595) and entry_blocked=_band_blocked (602-619) (701-714);
  - the reset clock rolls back on a refusal (752-758).
- _submit (389-472): refuses orders while the market is open (428); sends MOC for sells without event_id, priority or next_open (436-448); sends everything else as next-open DAY orders (449-456).
- market_balancer._green_day_skip_locked (132-211): window at 144; filter at 147-154 excludes event_id, priority and next_open orders; compares the open with the prior close at 174.
- event_execution.plan (29-90) snapshots every held symbol (44).
- alpaca_trading.submit_market_on_close (279-296) already accepts buys.
- The published curve is market_daily.curve_block (1244-1318): use_exits=False, REBALANCE_EVERY, event_risk.live_path, lifecycle on, **LIVE_POLICY.

JOURNAL CONSTRAINTS
- research_journal: phases are open/close only (260-263); the manifest has cash_yield 0.0 (185).
- research_journal_replay:
  - cash_yield must be 0.0 (186);
  - a decision must follow its mark (626);
  - execution must come after the decision session and after the last mark;
  - open then close, each at most once per decision (415-441).
- The journal records per-column batches and carries no order or leg identity.

DATA
- QQQ is not a column of the book panel (desk.py:98-105 is the book names plus SPY). The brake reads QQQ closes from benchmark_prices (trend_brake.py:28-51).
- SPY/QQQ adjusted opens come from allocation_controls.build_adjusted_opens (297+).
- Cash earns zero everywhere. SWVXX is declared unavailable (paper_allocation.py:62-69).
- technical.sma is cumsum-based (technical.py:105-117), so a provisional band read must reproduce the prefix arithmetic.
- There is no numpy or pytest on the Mac; tests run in the Spark functional-tests container.

PARITY POINTS TODAY (the live and simulated paths must stay equal at each of these)
1. LIVE_POLICY ↔ POLICY_VERSION ↔ curve_block ↔ the nested-study expected_flags.
2. _targets ↔ desk.py:401 risk.size → report.book → market_daily:661.
3. _Book.plan / planner.plan ↔ paper.plan reset plus _rebalance_orders (whole-share rounding is the only difference).
4. _gated_targets ↔ _rebalance_orders entry_blocked. The simulator's `blocked` ↔ _band_blocked.
5. _paper_inputs finished ↔ _downgraded. Entries: the simulator passes every finite band and entry_size zeroes those below 1.10, which matches _price_entries.
6. _live_midcycle ↔ the paper.plan mid-cycle branch plus midcycle_orders.
7. _unpaid_buys / _deferred_leg / carry at 1191-1215 ↔ plan 743-834 plus bound_orders.
8. settle_split / _fill_split ↔ _submit MOO/MOC routing.
9. The simulator's green-day skip ↔ the balancer filter plus skip_sell.
10. _settle_event ↔ event_execution.plan and the 695-699 selection.
11. The brake pause (1183-1213) has no live counterpart.
12. Known divergences: fractional vs whole shares, the official open vs the first print, the IEX vs SIP open, clock rollback, reconstructed grades.

### Changes

#### `backend/agents/trading/desk/simulate.py` — CANDIDATE_DEFAULTS (new module constant, placed after LIVE_POLICY)

Add a dict of every new run() keyword and its default:
- sizing=None
- reset_phase=0
- rotation_redeploy='pro_rata'
- persist_deferred=False
- trim_bands=None
- entry_clock='next_open'
- decision_prices=None
- decision_bands=None
- remainder_clock=None
- same_auction_funding=False
- profit_take=None
- structure_exit=None
- hooks_skip_exempt=True
- defensive_destination='cash'
- cash_rate=None
- cash_rate_scope='defensive'
- fill_log=False

The byte-identity test passes this dict explicitly. Do not edit LIVE_POLICY (72-78) or paper.POLICY_VERSION (169). Candidates are always expressed as overrides on top of **LIVE_POLICY, because nested_market_study.py:93-104 refuses any change to LIVE_POLICY.

#### `backend/agents/trading/desk/simulate.py` — run (signature 643-675, docstring 676-798)

Append the CANDIDATE_DEFAULTS keywords after `journal`, leaving the order of the existing 31 parameters unchanged. Types:
- sizing: book_sizing.BookSizing | None
- reset_phase: int
- rotation_redeploy: 'pro_rata' | 'next_best'
- persist_deferred: bool
- trim_bands: planner.TrimBands | None
- entry_clock: 'next_open' | 'next_close' | 'same_close'
- decision_prices: (T,N) float | None
- decision_bands: (T,N) float | None
- remainder_clock: None | 'paired_close'
- same_auction_funding: bool
- profit_take: (T,N) float in [0,1] | None
- structure_exit: (T,N) bool | None
- hooks_skip_exempt: bool
- defensive_destination: str | (T,) array of str
- cash_rate: (T,) float | None
- cash_rate_scope: 'defensive' | 'all'
- fill_log: bool

Rules that keep the default path byte-identical:
- Every new branch is guarded by `<option> is not default`, so with defaults the executed statements are exactly today's.
- No existing arithmetic expression is reordered.
- The decision_row, opens_book and closes_book variables introduced below are the same array objects as closes and opens when their options are off.
- observe_decision metadata gains keys (buy_phase, decision_clock, legs, sleeve) only when the owning option is active.
- SimResult is still built from the same 11 positional values; new fields are passed by keyword only when enabled.

The docstring gains one paragraph per option, stating semantics, clocks and refusals.

#### `backend/agents/trading/desk/simulate.py` — _validate_candidate_options (new, above run; called right after the brake setup at 861)

Raise ValueError, naming the options, for each of these combinations:
- sizing together with an allocator.
- reset_phase not an int in [0, rebalance).
- rotation_redeploy='next_best', persist_deferred, profit_take, structure_exit, or trim_bands.daily without live_midcycle. These hooks are defined on the shared paper planner.
- persist_deferred without deferred_buys.
- entry_clock='same_close' without decision_prices, or with exit_at_close=False. A sell at the t+1 open cannot be decided at 15:45 of t+1.
- decision_prices or decision_bands given with any entry_clock other than same_close.
- decision_prices whose shape is not (T,N), or any value outside the session's adjusted [low, high] × (1 ± 1e-9). Adjusted as low·adj_close/close and high·adj_close/close; NaN is allowed only where adj_close is NaN.
- remainder_clock='paired_close' unless entry_clock='next_open', exit_at_close and same_auction_funding all hold.
- same_auction_funding without some leg that buys at a close in the same batch as close sells (entry_clock != 'next_open' with exit_at_close, or paired_close).
- profit_take not finite in [0,1] or not (T,N); structure_exit not a (T,N) bool array.
- defensive_destination other than 'cash' without trend_brake or brake_path_override.
- An unknown destination label, or an array not of shape (T,).
- An index destination without prices. SPY or QQQ must be a panel column, or benchmark_prices must carry D and f'{D}_open' aligned to panel.dates, validated with the trend_brake.aligned_qqq rules.
- 'cash_yield' without cash_rate.
- cash_rate not a finite (T,) array in [0, 0.001].
- cash_rate together with a journal. research-journal/1 pins cash_yield to 0.0 (research_journal.py:185; replay :186).
- fill_log is allowed everywhere.

Also extend the funded_allocation `incompatible` list (806-839) with every option that is not at its default.

#### `backend/agents/trading/desk/simulate.py` — run: rebalance clock (920, 1127-1129)

reset_phase=p. The first reset is still at `start` (or at the first session after a lifecycle deferral). After that first reset only, next_rebalance = t + (p if p else rebalance); every later reset uses t + rebalance. With p=0 this is today's clock exactly. This one option serves both the gate's 20 reset offsets on a common start date and the tranche members.

#### `backend/agents/trading/desk/simulate.py` — run: reset targets (1130-1138) and ceiling (1163-1177)

Changes to the reset branch:
- When sizing is given: target = book_sizing.targets(report, panel, sizing, t, held_mask=(book.shares[:N] > 0) & ~sleeve_mask[:N] with the benchmark excluded, invested=stock_invested at decision_row). Otherwise use decide() unchanged.
- When structure_exit is given, zero the target of every name flagged at signal row s. s = t, or t+1 under same_close. Flagged names are neither kept nor bought.
- _gated_targets runs as today. Pad fired and blocked with False for appended sleeve columns, and mask the SPY column False when it is the sleeve.

After _event_target, and only when rebalanced and not event_changed and trim_bands is set: target = _banded_targets(target, book, decision_row, trim_bands). This converts to dicts over the stock tickers, calls planner.apply_bands, and converts back. A change in the ceiling always executes in full.

When a sleeve exists, _event_target scales only the stock slice; sleeve columns are set by the defensive rule below.

#### `backend/agents/trading/desk/simulate.py` — run: mid-cycle leg (1182-1215)

When live_midcycle, pass new keywords to _live_midcycle:
- prices_row=decision_row and equity_row=decision_row.
- bands_row = decision_bands[t+1] under same_close, else live_bands[t].
- exclude=sleeve_mask.
- structure = structure_exit[s] adds finished entries with reason 'structure break'.
- trims = merged {symbol: (fraction, reason)}. Each fraction is the max of profit_take[s] ('profit take') and planner.cap_trims when trim_bands.daily ('band trim').
- rotation_targets = the ordered [(symbol, weight)], only when rotation_redeploy='next_best' and `finished` is non-empty. It comes from decide or book_sizing at t, cached per t, keeping stock names with target > 0, sorted by report.scores[t] descending then symbol.
- same_auction=same_auction_funding.
- persist=persist_deferred.
- legs=dict when fill_log is on.

When a hook is active, the persisted remainder returned by paper.retry_deferred is added to `unfunded`, so pending_deferred carries it.

On resets under paired_close or same_auction: pending_deferred = _unpaid_buys(book, order, decision_row, extra_budget=projected same-auction net proceeds, exclude=sleeve_mask).

When braked or event_paused, np.minimum(order, book.shares) applies to stock columns only if a sleeve exists.

The hooks do not run on ceiling-change sessions, which the event and brake own as today; this is documented.

#### `backend/agents/trading/desk/simulate.py` — run: decision row and fill clocks (1177, 1216-1260)

decision_row:
- entry_clock='same_close' and the ceiling does not change at t: decision_prices[t+1] (the 15:45 of session t+1).
- Otherwise: closes[t], the same object as today.

The ceiling-change flag is computed before the target, from ceiling[t] vs previous_scale. Every sizing, weighting and equity read in the decision block uses decision_row: book.plan, the _gated_targets weights, book.between, _dip_add, the _live_midcycle inputs, _unpaid_buys and _banded_targets.

Fill phases:
- buy_phase = 'open' if entry_clock == 'next_open' or event_changed or sleeve_changed, else 'close'.
- sell_phase = 'close' if exit_at_close and not event_changed, else 'open'. This is today's sell rule.

The green-day skip (1239-1252) is unchanged, except that skip &= ~exempt. exempt covers sleeve columns plus structure-exit and trim sells when hooks_skip_exempt. By default exempt is all False.

Settlement:
- buy 'open' with no paired remainder: call today's settle_split with the exact arguments at 1253-1260.
- Every other combination: book.settle_clocked(order, opens_book[t+1], closes_book[t+1], t+1, reason, buy_phase, sell_phase, recycle_close=same_auction_funding, paired=(remainder_clock == 'paired_close')).

#### `backend/agents/trading/desk/simulate.py` — _Book.settle_clocked (new method after settle_split 1594-1616)

Fill one decision in at most two phase batches:
1. buy close, sell close: one close batch, _fill(order, close, recycle_sells=recycle_close, phase='close').
2. buy close, sell open: _fill(np.minimum(order, shares), open, phase='open'), then _fill(np.maximum(order, shares), close, recycle_sells=False, phase='close').
3. paired (buy open, sell close): _fill(np.maximum(order, shares), open, phase='open'), then _fill(order, close, recycle_sells=True, phase='close'). The close batch sells, then tops up every buy still short of `order` from cash plus net proceeds; _fill's scale enforces that nothing is borrowed.

Each phase is preceded by observe_adjustment(session, phase, units, '<phase> leg'), so research_journal_replay accepts it: open then close, each once per decision. opened and paid use the price of the phase the buy filled in. _log uses the sell phase's price.

The existing settle_split, _fill_split and _fill arithmetic is untouched.

#### `backend/agents/trading/desk/simulate.py` — _paper_inputs (83-109), _live_midcycle (116-168), _deferred_leg (192-218), _unpaid_buys (174-186)

Add keyword-only parameters, each defaulting to today's value:
- _paper_inputs(..., prices_row=None, exclude=None, structure=None): prices come from prices_row or panel.adj_close[t]; held skips columns where exclude is True; finished adds 'structure break' for held flagged names.
- _live_midcycle(..., prices_row=None, bands_row=None, equity_row=None, exclude=None, structure=None, trims=None, rotation_targets=None, same_auction=False, persist=False, legs=None, carried_out=None):
  - equity = book.equity(equity_row if given else panel.adj_close[t]); the default is the same expression as line 126;
  - entries come from bands_row or bands[t];
  - the retry is delegated to paper.retry_deferred, which reproduces lines 128-148 statement for statement;
  - midcycle_orders gets rotation_targets, trims and same_auction;
  - legs, when a dict is passed, maps each order's column to a leg label derived from the PaperOrder reason via fill_log.REASON_LEGS;
  - carried_out, when a dict is passed, receives the persisted retry remainder;
  - the return value is unchanged.
- _deferred_leg: the same equity_row, prices_row, exclude and persist keywords.
- _unpaid_buys(book, order, prices, extra_budget=0.0, exclude=None): budget = max(0, cash) + extra_budget; excluded columns are never unpaid. The default arithmetic is identical.

#### `backend/agents/trading/desk/simulate.py` — _Book (1303-1683), SimResult (234-310), _dip_add (389-417), _event_target (552-564)

_Book.__init__ gains keyword-only tickers=None, sleeve_mask=None and fill_log=False. A None tickers keeps the panel's tickers (1332-1336).

New and changed behaviour on _Book:
- between (1407-1456) skips exit evaluation and redeploy for sleeve columns, only when sleeve_mask is set.
- _log and finish use self.tickers[column] and grade '—' for columns at or beyond len(panel.tickers). Behaviour is unchanged otherwise.
- New accrue(rate): cash += cash × rate.
- New stock_weights(prices) and top_stock_weight(prices), which exclude the sleeve.
- _fill (1524-1588) calls self._observe_fills(before, after, prices, phase, session, scale) after the ledger update, only when fill_log is on. It is a pure observer that adds no arithmetic.
- New tag(t, decision_row, legs, clock) stores the decision context the fill observer reads.

_dip_add's funded pool and _event_target's scaling exclude sleeve columns, only when a sleeve exists.

SimResult appends keyword-default fields:
- fills: list[fill_log.SimFill] | None = None
- positions: list[fill_log.SimPosition] | None = None
- holdings: np.ndarray | None = None, shares per mark, shape (T, N_ext)
- sleeve_weight: np.ndarray | None = None
- stock_invested: np.ndarray | None = None
- defensive: np.ndarray | None = None, the destination label per session
- cash_income: float = 0.0

With a sleeve, top_weight excludes the sleeve and invested stays all positions / NAV. stats() is unchanged.

#### `backend/agents/trading/desk/simulate.py` — run: defensive destination and cash yield (setup 843-866; loop 1163-1267)

Setup: defensive.resolve(panel, benchmark_prices, defensive_destination, brake_path) returns the sleeve columns.
- SPY: the panel column when 'SPY' is in panel.tickers.
- Otherwise the symbol is appended from benchmark_prices[D] and benchmark_prices[f'{D}_open'].
- Appending builds closes_book/opens_book with np.column_stack, tickers_ext, and a sleeve_mask covering the appended columns plus the SPY column when SPY is the sleeve.
- With destination 'cash' nothing is built, and closes_book/opens_book are the same objects as closes/opens.
- journal.assert_inputs receives the extended arrays. The new helper simulate.journal_inputs(report, benchmark_prices, destination) returns (sessions, symbols, opens, closes) so callers can build a matching ResearchJournal.

Sleeve rule, applied on every non-lifecycle session where rebalanced, event_changed or the destination label changed:
- G = sum of the post-ceiling stock target.
- e = event_exposure[t] or 1; b = brake_path[t] or 1; c = min(e, b).
- q = G × max(0, e − c) / c when c > 0.
- The sleeve target is q in column D when b < 1 and D is SPY or QQQ; otherwise 0.
- On all other sessions, order[sleeve] = book.shares[sleeve], so the sleeve is held and drifts.

Why this does not double-count: on the ceiling path, total risky exposure is e × G_base and the brake alone sizes the sleeve. On the event_lifecycle path, _settle_event snapshots and cuts the sleeve together with the stocks, which is what live event_execution.plan:44 does. Cash released by the event is therefore never parked in the index, and the sleeve is never re-targeted inside a cycle. A brake change during a cycle is applied at the first session after the cycle, as today.

Sleeve legs:
- They are next-open orders on both sides.
- They are exempt from the green-day skip, the band blocker, the deferral and the brake/event pause.
- They are never in `held` for rotation.

Cash yield: after the t+1 fills and before the t+1 mark, when cash_rate is set and (scope == 'all', or (brake_path[t] < 1 and destination[t] == 'cash_yield')): interest = book.cash × cash_rate[t]; book.accrue(...); cash_income += interest.

risk_off is unchanged. result.defensive records the label per session.

#### `backend/agents/trading/desk/paper.py` — retry_deferred (new, extracted from plan 778-804 and simulate 128-148)

retry_deferred(deferred, held, prices, equity, grades, finished, blocked, session, state, cash, whole_shares=True, persist=False) -> (orders, spent, reserved, carried). It reproduces the existing expressions exactly:
- budget = max(0, cash or equity − Σ held × price);
- _fund_buys(_deferred_orders(...));
- spent = Σ qty × price;
- reserved = held + retry.

When persist=False, carried = {}; this is today's behaviour, in which _unpaid is discarded.

When persist=True, carried = the retry's _unpaid, plus each deferred name that _deferred_orders skipped only because it was band-blocked or under MIN_TRADE, provided it is still A/A+, not finished and has cap room. A deferred name is dropped when it is downgraded, finished or at the cap. Everything is superseded by the next reset.

plan (786-820) and simulate._live_midcycle / _deferred_leg call this function, which moves the shared logic into one place.

#### `backend/agents/trading/desk/paper.py` — _rotation_orders (348-418), midcycle_orders (610-652), _trim_orders (new), PAIRED_FUNDING_HAIRCUT (new)

_rotation_orders(..., *, targets=None):
- None keeps the pro-rata code (374-417) untouched.
- With a list: the freed value goes to names in list order (conviction descending). A name qualifies when it is A/A+, not leaving, not blocked and priced. Each receives min(target − w, ENTRY_NAME_CAP − w, remaining) × equity, legs under MIN_TRADE are skipped, the whole-share floor applies, and the reason is 'redeploying a downgraded name (next best)'.

New _trim_orders(trims, held, prices, equity, session, state, whole_shares): sells qty = held × fraction (the whole-share floor applies), skipping names in finished and legs under MIN_TRADE × equity; the reason is 'profit take' or 'band trim'.

midcycle_orders(..., unfunded=None, *, rotation_targets=None, trims=None, same_auction=False, haircut=PAIRED_FUNDING_HAIRCUT):
- trim orders are appended after the rotation;
- when same_auction, budget += Σ(sell qty × price) × (1 − haircut);
- defaults are identical to today.

PAIRED_FUNDING_HAIRCUT = 0.01 is predeclared and not tuned. It covers 10/25 bp costs plus drift between the decision and the auction, and it is used by both the simulator and the later live path so both decide identical quantities.

#### `backend/agents/trading/desk/planner.py` — TrimBands, apply_bands, cap_trims (new)

New dataclass: @dataclass(frozen=True) TrimBands(hard_cap: float | None = None, relative: float | None = None, trim_to: str = 'edge', daily: bool = False).

apply_bands(targets, held, equity, prices, bands) -> dict. For each symbol with w = held × price / equity and τ = the target:
- τ == 0: unchanged; the name leaves the book.
- w <= τ: τ' = min(τ, hard_cap or τ).
- w > τ: edge = min of the set limits (relative × τ, hard_cap). If w <= edge, τ' = w (no trade). Otherwise τ' = edge ('edge') or τ ('target').
- No limits set: unchanged.

cap_trims(held, prices, equity, bands) -> {symbol: 1 − hard_cap / w} for w > hard_cap, or {} when hard_cap or daily is unset.

Both are pure functions, shared by the simulator now and by paper.plan at the later stage.

#### `backend/agents/trading/desk/risk.py and backend/market/sizing.py` — desk_targets (160-192), size_today (501-554), target_weights (264-303), long_order (new), holdable_mask (new alias)

Add keyword-only weighting='inverse_vol' and selected: np.ndarray | None = None, passed through desk_targets → size_today → target_weights.

In target_weights:
- when selected is given, long_names = np.flatnonzero(usable & selected) and top_fraction is not used;
- weighting 'equal' sets weights[long_names] = 1.0 (instead of 1/vol at 287);
- everything after that is unchanged.

Extract sizing.long_order(scores, volatility, config) -> (order ascending, k_long) from lines 280-285. It keeps the same np.argsort call (quicksort) so ties break identically, and target_weights calls it as a pure refactor.

risk.holdable_mask = _holdable is a public alias.

SizingConfig and BOOK_CONFIG are NOT changed, to keep the nested-study asdict guard (nested_market_study.py:101) satisfied.

#### `backend/agents/trading/desk/entry.py` — provisional_bollinger_z (new, after bollinger_z 60-68)

provisional_bollinger_z(close, decision, window=20) -> (T,N). Row s is exactly the value bollinger_z would return at row s if close[s] were decision[s]. The mean reuses sma's cumsum prefix arithmetic (technical.py:105-117): cumulative[s] + decision[s] − cumulative[s+1−window]. The std is np.nanstd over vstack(close[s−window+1:s], decision[s]).

It is used when decision_bands is None under same_close. The later 15:45 live job applies the same function to (the panel's closes through t, the live 15:45 row).

#### `backend/agents/trading/desk/book_sizing.py (new)` — BookSizing, INCUMBENT, targets, universe_equal_weight

@dataclass(frozen=True) BookSizing with fields:
- selection: 'top_fraction' | 'top_k' | 'all_qualifying' | 'universe' = 'top_fraction'
- top_fraction = 0.1
- top_k: int | None = None
- weighting: 'inverse_vol' | 'equal' = 'inverse_vol'
- name_cap = 0.15 (None → 1.0)
- theme_cap = 0.40 (None → 1.0, never 0)
- volatility_target: float | None = 0.30 (None → math.inf, so the scale is exactly 1.0)
- regime_exposure = True
- tightening_tilt = True
- rank_buffer: float | None = None
- buffer_mode: 'extend' | 'fill' = 'extend'
- reset_gross: 'target' | 'preserve' = 'target'

targets(report, panel, sizing, t, *, held_mask=None, invested=None):
1. Slice the panel window as _targets does (431-443).
2. config = dataclasses.replace(risk.BOOK_CONFIG, top_fraction=..., name_cap=..., theme_cap=..., target_volatility=...).
3. Regime view = SimpleNamespace(exposure=state.exposure if regime_exposure else 1.0, tightening=state.tightening if tightening_tilt else False).
4. selected = None for plain top_fraction with no buffer. This is the incumbent path, and targets(INCUMBENT) is np.array_equal to simulate._targets(BOOK_CONFIG).
5. Otherwise build the mask on holdable_mask(grades) candidates using long_order:
   - K = k_long for top_fraction, min(top_k, n) for top_k, n for all_qualifying;
   - buffer 'extend' = top K ∪ {held holdable names with rank < floor(rank_buffer × K)};
   - buffer 'fill' = held-in-buffer names by rank, then the best non-held names, up to K.
6. Call risk.desk_targets(..., weighting=..., selected=...), then zero the benchmark column.
7. 'preserve': when invested > Σtarget > 0, target *= min(1, invested) / Σtarget, then sizing.apply_limits(name_cap, theme_cap, gross).

'universe': equal weight over priced non-index names, capped with apply_limits. This is the equal-weight hurdle, the same basket as nested_market_inputs._compositions (164-168).

#### `backend/agents/trading/desk/defensive.py (new)` — DESTINATIONS, resolve, sleeve_weight, cash_rate_from_discount_yield

DESTINATIONS = ('cash', 'cash_yield', 'SPY', 'QQQ').

resolve(panel, benchmark_prices, destination, brake_path) validates the labels and the calendar and returns (labels_per_session, sleeve_symbols, appended_closes, appended_opens, sleeve_mask).

sleeve_weight(stock_gross, e, b) returns G × max(0, e − min(e, b)) / min(e, b).

cash_rate_from_discount_yield(yield_pct, sessions_per_year=252) returns yield / 100 / 252, forward-filled. It refuses any NaN before the first print.

The module docstring states that 'cash_yield' is modelling-only on the Alpaca account (paper_allocation.py:62-69 marks SWVXX unavailable).

#### `backend/agents/trading/desk/tranches.py (new)` — run, offsets, TrancheResult

run(report, *, n=4, spacing=5, **run_kwargs) runs n simulate.run members with reset_phase = (i × spacing) % rebalance and fill_log=True. It refuses journal and funded_allocation.

The combined result:
- equity = the mean of the member equities (each starts at 1.0, and the ledger is linear under fractional shares);
- returns come from the combined equity, keeping run's NaN-first convention;
- invested = Σ invested_i × equity_i / Σ equity_i;
- traded = the mean;
- top_weight is exact, from the summed holdings × closes / combined equity;
- rebalances = the sum.

Members are kept. With n=1 the result equals simulate.run(reset_phase=0).

offsets(report, **kw) = run(n=rebalance, spacing=1) and also returns each member's stats (median and range for the 20-offset gate). This is the no-netting 4-account version, which is conservative on cost. A netted single-account tranche is later-stage.

#### `backend/agents/trading/desk/fill_log.py (new)` — SimFill, SimPosition, REASON_LEGS, build_positions, pair_orders, pair_positions, exit_regret, overnight_intraday

SimFill(frozen) fields: decision_session, decision_clock ('close' | '15:45 next'), fill_session, phase, ticker, side, leg, reason, requested_units, filled_units, decision_price, fill_price, notional, fee, cash_scale, held_back (a green-day skip), position_id = f'{ticker}:{opened_session}'.

Leg values: reset_buy, reset_trim, reset_exit, rotation_sell, rotation_buy, entry, deferred, paired_remainder, band_trim, profit_take, structure_exit, defensive, fomc, brake, dip, exit_overlay.

SimPosition fields: position_id, ticker, opened, closed | None, entry_fills, trim_fills, exit_fills, max_units, cost_basis, realized_pnl, open_units_end, end_mark, grade_at_open.

REASON_LEGS maps the PaperOrder and planner reasons to legs.

pair_orders(base, cand, key=('ticker', 'decision_session', 'side', 'leg')) returns pairs with signed bp (side_sign × (base_fill − cand_fill) / base_fill × 1e4, positive means the candidate did better), plus the unmatched lists on each side.

pair_positions(base, cand) is keyed by (ticker, opening decision session).

exit_regret(fills, closes, horizons=(1, 5, 20)) returns the forward return of the sold units from their fill price.

overnight_intraday(result, opens, closes) splits held P&L into the close→open and open→close legs.

Statistics beyond these (DSR, SPA, clustering) belong to the gate item.

#### `backend/tests/test_strategy_parity.py (append) plus new tests` — sim↔paper parity matrix

Add parity tests, in the style of test_historical_midcycle_matches_shared_planner (64-95), for each new shared hook:
- rotation_targets;
- trims and structure;
- persist;
- same_auction budget;
- apply_bands vs paper.plan rebalance.

Each asserts that simulate._live_midcycle and paper.midcycle_orders / retry_deferred give identical quantities before whole-share rounding.

New parity obligations that the later live wiring must honour (recorded in the run() docstring):
- The sleeve is excluded from held, rotation takers, _downgraded and deferral.
- Sleeve orders carry priority='defensive' (next-open, green-skip exempt), and event_execution snapshots them.
- Paired MOC buys are cancelled with their funding sells.
- Under same_close, the grades and blocker come from the nightly record (row t) and the bands from provisional_bollinger_z.
- PAIRED_FUNDING_HAIRCUT is shared.
- The rank buffer's held mask comes from broker positions.

#### `backend/agents/trading/desk/paper.py, backend/cli/market_daily.py, backend/cli/market_balancer.py` — LATER-STAGE, only for an adopted candidate. Not part of this item's merge.

paper.plan gains keyword-only trim_bands (apply_bands before planner.plan at 765), rotation_targets, trims, persist_deferred and same_auction, all defaulting to None/False.

PaperOrder gains hold_exempt: bool = False and funded_by: str | None = None.

market_daily._paper_trade (639-816):
- targets from book_sizing.targets(..., held_mask from broker `held`) instead of 661;
- sleeve symbols filtered out of `held` before paper.plan;
- brake state from trend_brake.risk_off_path on stored QQQ, with sleeve orders as priority='defensive';
- structure and profit-take signals from the 15-minute engine record.

_submit (389-472):
- execution_timing='next_close' buys go to submit_market_on_close;
- a same-session 'same_close' submission is allowed while the market is open only before the MOC cutoff (the 428 guard is relaxed for that timing only);
- _pending_orders records funded_by and hold_exempt.

market_balancer:
- a 15:45 ET job builds the decision row via live_technical.with_live_row and provisional_bollinger_z, calls paper.plan, submits same-close MOC, and gates on calendar.session_close;
- _green_day_skip_locked (147-154) also excludes hold_exempt, and cancelling a sell cancels any buy whose funded_by names it.

At adoption:
- the policy dict moves to a versioned entry;
- POLICY_VERSION goes to 'cash-bounded-breakout-rotation/4', and curve_block (1260-1267) uses it;
- the nested_market_study guard (93-104) remains pinned to /3 by design.

'cash_yield' cannot go live on Alpaca.

#### `backend/agents/trading/desk/simulate.py docstring; docs/NEXT_SESSION.md` — documentation

Update the run() docstring for every option, its clock semantics and its refusals.

Record the verified checkpoint SHA and evidence in NEXT_SESSION.md only after the acceptance path passes. Add no CHANGELOG entry until it is verified.

Diagram impact: NONE. These are research-only simulator options; there is no new component, store or live data flow until the later-stage wiring.

### New files

backend/agents/trading/desk/book_sizing.py: the BookSizing variants (selection, weighting, caps, vol target, regime, tilt, rank buffer, reset gross) and the equal-weight universe hurdle. It delegates to risk.desk_targets so that INCUMBENT is exact.
backend/agents/trading/desk/defensive.py: destination validation, sleeve sizing, and the T-bill cash-rate helper.
backend/agents/trading/desk/tranches.py: tranche books combined from reset-phase members, and averaging over all 20 offsets.
backend/agents/trading/desk/fill_log.py: the per-order SimFill and per-position SimPosition observers, plus pairing, exit-regret and overnight/intraday helpers.
Tests:
- backend/tests/test_simulate_candidate_defaults.py
- backend/tests/test_book_sizing.py
- backend/tests/test_simulate_tranches.py
- backend/tests/test_simulate_trim_bands.py
- backend/tests/test_simulate_redeploy.py
- backend/tests/test_simulate_entry_clock.py
- backend/tests/test_simulate_exit_hooks.py
- backend/tests/test_simulate_defensive.py
- backend/tests/test_simulate_fill_log.py
- backend/tests/simulate_candidate_fixtures.py: live-shaped fixtures.
Every new function carries a plain-language comment above it, per AGENTS.md:41.

### Tests

FIXTURES (backend/tests/simulate_candidate_fixtures.py)
The fixtures are live-shaped:
- 95 columns: 94 realistic 2-5 letter tickers plus SPY, with themes 'ai' and 'software' and theme overlaps.
- 700 sessions of fat-tailed returns with annual vol dispersed from 20% to 90%.
- Distinct open, high, low and close, with the adjusted factor ≠ 1 on one name to exercise the split basis.
- Grades that switch regime every 10-30 sessions, so the book holds 5-25 A/A+ names.
- One tightening spell and one hype spell.
- An FOMC-like path from event_risk.exposure_path with synthetic decisions.
- benchmark_prices with dates, SPY, QQQ and QQQ_open, with a QQQ path containing one brake episode.
- decision_prices strictly inside each session's adjusted [low, high].
The small test_trading_simulate._report is also used.

1. test_simulate_candidate_defaults.py
- For bare defaults; for LIVE_POLICY + use_exits=False + rebalance 20 + the FOMC path + event_lifecycle; for LIVE_POLICY + trend_brake; for LIVE_POLICY + brake_path_override; and for funded_allocation: run(**CANDIDATE_DEFAULTS) must equal the plain run exactly on equity, returns, invested, top_weight, risk_off, traded, trades, rebalances, dip_adds and trace, and the ResearchJournal.snapshot() JSON bytes must be equal.
- test_default_digest_is_pinned: sha256 over equity, returns, invested and top_weight bytes plus repr(traded), for three fixture configurations. The constants are computed on the untouched base commit before any edit.
- test_live_policy_and_book_config_unchanged: LIVE_POLICY keys and values, asdict(BOOK_CONFIG) and POLICY_VERSION all equal the values nested_market_study pins.
- Each non-default option combined with funded_allocation raises.

2. test_book_sizing.py
- targets(INCUMBENT) is array_equal to _targets(BOOK_CONFIG) on every 20th session, and a run with sizing=INCUMBENT is byte-identical to sizing=None.
- volatility_target=None gives a scale of exactly 1 (the sum equals the capped normalised gross).
- Equal weight gives equal weights before the caps; name_cap and theme_cap hold, and theme_cap None never zeroes a themed name.
- top_k and all_qualifying give the expected counts.
- regime_exposure=False ignores exposure 0.75; tightening_tilt=False gives no inverse-vol tilt.
- rank_buffer=2.0 'extend' keeps a held A name ranked K+3 and drops it at rank 2K+1. 'fill' keeps the book size at K.
- reset_gross 'preserve' lifts the gross to the invested level without breaching the caps.
- 'universe' reproduces nested_market_inputs._compositions weights.
- sizing.long_order refactor: target_weights is unchanged on random inputs that include ties.

3. test_simulate_tranches.py
- reset_phase p puts resets at start, start+p and start+p+20.
- reset_phase=0 is identical to today.
- run(n=1) equals simulate.run.
- run(n=4) combined equity equals the mean of the 4 members to 1e-15 relative, and top_weight equals the exact holdings-based value.
- offsets returns 20 member stats.

4. test_simulate_trim_bands.py
- apply_bands: a name at 1.5× target with relative 2.0 is not traded; at 2.5× it is trimmed to the edge, or to the target with trim_to='target'; a leaving name is sold fully; buys are capped at hard_cap.
- A reset with bands is applied after the ceiling and never blocks a ceiling cut.
- With daily=True, cap_trims sells a name over the hard cap mid-cycle.
- green_day_skip=False plus bands is deterministic (the same result on repeated runs, with no dependence on opens[t+1]).
- paper.plan (later-stage keyword) matches when present.

5. test_simulate_redeploy.py
- 'next_best' sends proceeds to the highest-conviction A names below target and gives nothing to a held name already at target (whereas pro-rata does).
- persist_deferred carries the remainder until filled, drops it on downgrade or at the cap, and a reset supersedes it.
- A default run keeps discarding _unpaid.
- Parity with paper.retry_deferred and midcycle_orders.

6. test_simulate_entry_clock.py
- next_close fills buys at closes[t+1].
- same_close sizes at decision_prices[t+1] and fills at closes[t+1]; perturbing closes[t+1] (the 16:00 close) changes fills but not a single decision quantity.
- decision_prices outside [low, high] is refused, as is same_close with exit_at_close=False.
- same_auction_funding pays buys from same-close sells and cash never goes below 0.
- paired_close fills the remainder at the close, funded by the sells; a green-day skip shrinks the funding and the unpaid residual goes to the deferral.
- Ceiling-change sessions stay next-open.
- The archived journal passes research_journal_replay.verify_payload for every clock.
- provisional_bollinger_z equals bollinger_z on the matrix with row s replaced, exactly, for sampled s.

7. test_simulate_exit_hooks.py
- profit_take=0.5 sells half the held units at the configured clock.
- structure_exit rotates the name, and its proceeds follow rotation_redeploy.
- The hooks take effect under live_midcycle (a regression test for the silent-drop pattern at 1193-1208).
- On a reset day, flagged names get a zero target.
- Hook sells are exempt from the green-day skip when hooks_skip_exempt.
- positions record the trims and exits.
- Without live_midcycle the hooks are refused.

8. test_simulate_defensive.py
- Destination 'cash' is byte-identical to today's brake.
- SPY or QQQ: on brake entry, stocks are sold and the sleeve bought with the released value at the same open; on exit the sleeve is sold.
- e=b=0.5 on the ceiling path gives q=0; e=1, b=0.5 gives q=0.5·G.
- event_lifecycle cuts and restores the sleeve with the book, and nothing is re-targeted mid-cycle.
- A state array switching SPY→QQQ trades the sleeve.
- The sleeve never appears in rotation, deferral, the green-day skip or top_weight.
- A missing QQQ_open is refused.
- cash_yield accrual equals Σ cash × r over defensive sessions, and 'all' accrues on every session.
- journal + cash_rate raises.
- A journal with an appended QQQ column replays.

9. test_simulate_fill_log.py
- With fill_log off, fills is None and the result is identical.
- With fill_log on: Σ notional equals traded (1e-12 relative); Σ fee equals traded × cost; the positions' units reconcile to holdings at every mark; the leg labels cover every nonzero fill.
- pair_orders gives bp=0 for identical runs, and the expected sign for a next_close vs next_open pair.
- overnight_intraday sums to the total P&L.

10. Existing suites must pass unchanged: test_trading_simulate, test_strategy_parity, test_trading_trend_brake, test_research_journal_integration, test_research_journal_phase_states, test_live_policy_missing_marks, test_funded_simulator(_edges), test_allocation_acceptance, test_nested_market_study, test_neural_policy_comparison, test_market_sizing, test_benchmark_boundary.

No prompt changes, so the backend/tests/functional requirement does not apply.

### Acceptance

0. Pin the golden digests before any edit. On the worktree base (the SHA recorded in NEXT_SESSION), inside the Spark probe clone, run a python -c that builds the three fixture configurations and prints the sha256 of the equity, returns, invested and top_weight bytes plus repr(traded). Paste the output into test_simulate_candidate_defaults.py.

1. Run the unit suites in the probe clone, per the memory note on gate-style runs. First check that no deploy is running (`pgrep -f "^bash scripts/deploy.sh"` returns nothing). Then:
   ssh spark 'rm -rf /tmp/anios-probe && git clone -q -b trading/volatile-book-15m <origin url> /tmp/anios-probe && cd /tmp/anios-probe && cp ~/anios/.env .env && r=/tmp/anios-probe && docker compose -p anios -f $r/docker-compose.yml --profile test run --rm --no-deps -v $r/backend:/app/backend:ro -v $r/docs:/app/docs:ro -e REDIS_URL=redis://redis:6379/0 functional-tests python -m pytest /app/backend/tests/test_simulate_candidate_defaults.py /app/backend/tests/test_book_sizing.py /app/backend/tests/test_simulate_tranches.py /app/backend/tests/test_simulate_trim_bands.py /app/backend/tests/test_simulate_redeploy.py /app/backend/tests/test_simulate_entry_clock.py /app/backend/tests/test_simulate_exit_hooks.py /app/backend/tests/test_simulate_defensive.py /app/backend/tests/test_simulate_fill_log.py /app/backend/tests/test_trading_simulate.py /app/backend/tests/test_strategy_parity.py /app/backend/tests/test_trading_trend_brake.py /app/backend/tests/test_research_journal_integration.py /app/backend/tests/test_research_journal_phase_states.py /app/backend/tests/test_live_policy_missing_marks.py /app/backend/tests/test_funded_simulator.py /app/backend/tests/test_funded_simulator_edges.py /app/backend/tests/test_allocation_acceptance.py /app/backend/tests/test_nested_market_study.py /app/backend/tests/test_market_sizing.py -q -p no:cacheprovider --no-header; rm -f .env'
   Everything must pass, with 0 skips in the new files.

2. Lint in the same container: python -m ruff check backend/agents/trading/desk backend/market/sizing.py backend/tests/test_simulate_*.py backend/tests/test_book_sizing.py, and python -m black --check on the same paths.

3. Byte-identity on real data (read-only). Use the Spark market store at a fixed asof, for example 2026-09-18, and run the same command at base and at branch head:
   python -c "import hashlib,numpy as np; from datetime import date; from backend.market.store import MarketStore; from backend.agents.trading.desk import desk,simulate,event_risk,paper; r=desk.run(MarketStore('<market data root>'), date(2026,9,18), fundamentals=desk.FUNDAMENTALS_CURRENT); x=simulate.run(r,use_exits=False,rebalance=paper.REBALANCE_EVERY,event_exposure=event_risk.live_path(r.panel),event_lifecycle=True,**simulate.LIVE_POLICY); print(hashlib.sha256(b''.join(np.asarray(a,float).tobytes() for a in (x.equity,x.returns,x.invested,x.top_weight))).hexdigest(), repr(x.traded), len(x.trades))"
   The two outputs must be identical. Also run it with **simulate.CANDIDATE_DEFAULTS added; the output must again be identical.

4. Journal replay: archive a same_close run and a QQQ-sleeve run from the fixtures to a scratch directory, then run python -m backend.cli.market_verify_journal --archive <dir>. It must verify.

5. Guards: git diff origin/main -- backend/cli backend/agents/trading/desk/event_execution.py backend/agents/trading/desk/desk.py is empty (the later-stage wiring is untouched), and grep shows LIVE_POLICY and BOOK_CONFIG unchanged.

6. No deploy, no provider calls, no paper-account change. Report each criterion as VERIFIED, FAILED or UNVERIFIED with the digests and test counts.

### Files owned

Modified:
- backend/agents/trading/desk/simulate.py
- backend/agents/trading/desk/paper.py (only retry_deferred, _rotation_orders(targets), _trim_orders, midcycle_orders keywords and PAIRED_FUNDING_HAIRCUT; plan keeps its current behaviour and only calls retry_deferred)
- backend/agents/trading/desk/planner.py
- backend/agents/trading/desk/risk.py (keyword passthrough and the holdable_mask alias)
- backend/agents/trading/desk/entry.py (provisional_bollinger_z)
- backend/market/sizing.py (target_weights and size_today keywords, long_order)
- backend/tests/test_strategy_parity.py (append-only)
- docs/NEXT_SESSION.md (after verification)

New:
- backend/agents/trading/desk/book_sizing.py
- backend/agents/trading/desk/defensive.py
- backend/agents/trading/desk/tranches.py
- backend/agents/trading/desk/fill_log.py
- backend/tests/simulate_candidate_fixtures.py
- backend/tests/test_simulate_candidate_defaults.py
- backend/tests/test_book_sizing.py
- backend/tests/test_simulate_tranches.py
- backend/tests/test_simulate_trim_bands.py
- backend/tests/test_simulate_redeploy.py
- backend/tests/test_simulate_entry_clock.py
- backend/tests/test_simulate_exit_hooks.py
- backend/tests/test_simulate_defensive.py
- backend/tests/test_simulate_fill_log.py

Not owned (later-stage or other items):
- backend/cli/market_daily.py
- backend/cli/market_balancer.py
- backend/agents/trading/desk/desk.py
- backend/agents/trading/desk/event_execution.py
- backend/market/alpaca_trading.py
- backend/market/research_journal.py and research_journal_replay.py
- backend/market/nested_market_study.py

### Depends on

Code: none. Slices S0-S6 build and test on synthetic, live-shaped fixtures.

Measurement inputs, which are not needed to merge:
1. The approved delayed-SIP consolidated 15-minute history, plus a builder for adjusted 15:45 decision_prices (and optionally decision_bands) aligned to panel.dates. This comes from the data item and is needed for real same_close and next_close runs.
2. The 15-minute chart-structure engine emitting (T,N) profit_take and structure_exit arrays on the loop's decision index. This comes from the engine item and is needed for real (g) runs.
3. A daily T-bill series in the store (^IRX via market_snapshot, or DTB3), converted with defensive.cash_rate_from_discount_yield. A provider call needs the operator's approval.
4. SPY/QQQ adjusted opens from the existing allocation_controls.build_adjusted_opens npz, passed as benchmark_prices['QQQ_open'] / ['SPY_open'].
5. The predeclared-gate/protocol item. It consumes CANDIDATE_DEFAULTS overrides, tranches.offsets for the 20 offsets, the fill_log pairing, and the 10/25 bp cost settings. It owns the trials registry, DSR/SPA, and the 2016-2020 primary window.

Work happens on branch trading/volatile-book-15m in its own worktree, rebased on origin/main at or after 990fa981.

### Risks

1. Byte-identity regressions from the two refactors (sizing.long_order, paper.retry_deferred) through float reordering or a different argsort. Mitigation: digests are pinned before any edit, np.argsort and the retry expressions are kept verbatim, and the real-store sha256 is compared at base and head.

2. Silent option drops. The incumbent already discards between/dip/exits under live_midcycle (1139-1154 vs 1193-1208) and still counts dip_adds. The new hooks must go through _live_midcycle and paper, or be refused. The existing drop is documented but not changed, because changing it would alter dip_adds.

3. Lookahead under same_close. decision_prices, decision_bands and the supplied signals must reflect only 15:45 information. Mitigations: the [low, high] validator; the perturb-close test; grades and the blocker read from row t; ceiling-change sessions decided at close t. The builder that produces 15:45 prices remains an external trust boundary.

4. Sleeve leakage into stock rules (held, rotation takers, the grade-C 'rotation' of SPY, the blocker, exits, deferral, the green-day skip, top_weight). Every touchpoint must take the mask, backed by explicit tests. Live must filter sleeve symbols out of `held` before paper.plan, or rotation will sell or feed SPY/QQQ.

5. Journal constraints. There is no cash yield under research-journal/1 (combining it with cash_rate is refused), each phase fills once per decision, and a decision must follow its mark. settle_clocked is designed around these rules, and a schema /2 with income events would be a separate item.

6. Paired and same-auction funding live: no leverage is allowed, yet an Alpaca paper margin account can fill a MOC buy after its funding sell is cancelled. The haircut, the funded_by cancel pairing and the account type must be settled before any live stage.

7. The nested-study guard pins LIVE_POLICY and asdict(BOOK_CONFIG). No field may be added to SizingConfig and no key to LIVE_POLICY, or that frozen study refuses to run. Source hashes change on any edit (nested_market_inputs.py:333-345). This is expected, and frozen studies are never rerun.

8. Performance: next_best calls decide() on rotation days (O(T·T·N) worst case), so it is cached per t. Tranches with 20 members multiply the runtime by 20.

9. Tranche evaluation without netting overstates cost relative to a single netted account. This is conservative, but the gap must be reported.

10. Theme cap 0 zeroes themed names (sizing.py:400-426), so 'off' must map to 1.0.

11. run() complexity (noqa C901): the additions must be factored into helpers to keep ruff passing.

12. Main is moving. simulate.py and paper.py are hot files, so rebase often and split slices by area.

13. The candidate grid inflates the trial count. Every option combination run must be registered in the gate item's trials registry.

### Effort

Large: about 8 developer-days in 7 slices that can be merged one at a time behind defaults. Each slice ends with the byte-identity suite green.

| Slice | Content | Estimate |
|---|---|---|
| S0 | Golden digests, CANDIDATE_DEFAULTS, and the pure refactors (sizing.long_order, paper.retry_deferred) | 0.5 d |
| S1 | fill_log observer, SimResult fields, holdings | 1.0 d |
| S2 | book_sizing, reset_phase, tranches | 1.5 d |
| S3 | planner.TrimBands, apply_bands, cap_trims at resets and daily | 0.75 d |
| S4 | Mid-cycle hooks: next_best, persist_deferred, profit_take, structure_exit through the shared paper functions, plus parity tests | 1.5 d |
| S5 | Clocks: next_close, same_close, paired_close, same_auction; settle_clocked; provisional_bollinger_z; journal replay tests | 1.5 d |
| S6 | Defensive sleeve (SPY/QQQ, state array, FOMC composition) and cash_rate | 1.25 d |

Later-stage live wiring (paper.plan keywords, market_daily, the 15:45 balancer job, green-skip pairing, policy /4) is separate: roughly 3-5 d, and only after the gate and shadow adopt a candidate.

### Open questions

1. Does cash_yield accrue only while the brake holds the book down (the default scope 'defensive', read from the user's "SWVXX as a defensive destination"), or on all idle cash (scope 'all', an honest-accounting sensitivity)? SWVXX cannot be traded on Alpaca (paper_allocation.py:62-69), so 'cash_yield' is modelling-only there.

2. How big is the sleeve? The spec parks only what the brake released: q = G_base × (e − c). The alternative is to fill the whole residual 1 − stock gross, which the user's "SPY/QQQ only as a defensive destination" appears to exclude. Please confirm.

3. Under same_close, the spec uses row-t (prior-close) grades and blocker plus provisional 15:45 bands. Should it instead compute provisional 15:45 grades? That would need a second report and live_technical parity.

4. Are profit-take, structure-exit and band-trim sells exempt from the green-day skip (the default hooks_skip_exempt=True), or should they stay subject to it?

5. Should the mid-cycle buy-time cap (ENTRY_NAME_CAP 0.15, used by the entry, rotation, deferral and bound_orders legs) follow a broader equal-weight book's smaller name_cap? The spec leaves it at 0.15.

6. The rank buffer's default mode ('extend', a variable book size K..K+held, vs 'fill', a fixed K) and its multiple (2.0) must be predeclared in the protocol, not chosen here.

7. Is PAIRED_FUNDING_HAIRCUT = 0.01 acceptable as a predeclared constant? Is the Alpaca paper account a margin account, and what are the MOC submit and cancel cutoffs (believed to be ~15:50 ET)? These are unverified, and they block live same-auction and same-close.

8. Tranches: is the no-netting 4-account evaluation acceptable for the gate, with a netted virtual-sub-book implementation only at the live stage?

9. Should the existing silent drop of use_exits/dip/exits under live_midcycle become a refusal? The spec says no, to keep today's results and dip_adds unchanged. A separate cleanup item could deprecate it.
