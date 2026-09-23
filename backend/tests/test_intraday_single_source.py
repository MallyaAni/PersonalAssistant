"""Synthetic acceptance of the single-source price-component diagnostic.

Per COMPARISON_SINGLE_SOURCE_TASK.md, the reviewed comparison/replay/preflight/
input modules and the intraday comparison protocol. What has to hold on small
synthetic Alpaca IEX 15Min adjustment=all page snapshots: a valid source parses
and runs the real reviewed replay; a malformed numeric future bar is retained as
NaN and cannot change earlier events; same-time duplicates are not cleaned; a
missing previous daily session is retained unavailable; an early-close
historical day is counted from 14 bars while extended hours are excluded; wrong
adjustment, a hash mismatch, truncated pages and a duplicate symbol are rejected
or explicit unavailable; a symbol missing from the snapshot stays requested; the
as-of maturity horizons remain fixed 20/5; and the single source never applies a
raw/Yahoo conversion or double adjustment (derived rows carry close==adj_close
and the replay runs on an adjusted basis).
"""

import hashlib
import json
from datetime import UTC, date, timedelta

import pytest

from backend.market.intraday_comparison import DailyRow, Eligibility, fixed_levels
from backend.market.intraday_entry import Bar, session_open_for
from backend.market.intraday_inputs import (
    ResearchCalendar,
    load_calendar,
)
from backend.market.intraday_preflight import session_schedule_from_calendar
from backend.market.intraday_replay import (
    PRICE_DIAGNOSTIC,
    PRIMARY_HORIZON,
    SECONDARY_HORIZON,
    SessionKind,
    replay_session_outcome,
)
from backend.market.intraday_single_source import (
    DATA_AS_OF,
    ENTRY_END,
    ENTRY_START,
    PRICE_BASIS,
    READY,
    SOURCE_END,
    SOURCE_START,
    SYMBOLS,
    UNAVAILABLE,
    DiagnosticResult,
    _daily_row,
    _daily_rows_by_date,
    run_diagnostic,
    to_dict,
    validate_snapshot,
)

# The real committed 2019-2028 exchange calendar and its full-coverage schedule.
CALENDAR = load_calendar()
SCHEDULE = session_schedule_from_calendar(CALENDAR)


# One regular-window 15-minute bar row dict at ``slot`` (0 = 09:30) on ``day``.
def _bar_row(day, slot, o, h, lo, c, v=100.0):
    """Return an aware-UTC Alpaca bars row dict for the given slot and OHLC."""
    start = session_open_for(day) + timedelta(minutes=15 * slot)
    return {
        "t": start.astimezone(UTC).isoformat(),
        "o": o,
        "h": h,
        "l": lo,
        "c": c,
        "v": v,
    }


# The session's single-source reference close, rising gently over the window.
def _close_for(day):
    """Return the fixture close for a session date, increasing in time."""
    return 100.0 + 0.1 * (day - SOURCE_START).days


# A complete 26-bar regular session at one close.
def _full_session_rows(day, close=None):
    """Return 26 regular bar rows on ``day`` around the given close."""
    close = close if close is not None else _close_for(day)
    return [
        _bar_row(day, slot, close - 0.05, close + 0.05, close - 0.05, close)
        for slot in range(26)
    ]


# One direct Bar (not a payload row) at ``slot`` on ``day``, for unit probes.
def _bar(day, slot, o, h, lo, c, v=100.0):
    """Return a reviewed ``Bar`` at the given slot and OHLC on ``day``."""
    return Bar(
        start=session_open_for(day) + timedelta(minutes=15 * slot),
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=v,
    )


# Every full/early-close session date in the source window on the real calendar.
def _window_sessions():
    """Return the trading session dates in the source window, in order."""
    sessions = []
    day = SOURCE_START
    while day <= SOURCE_END:
        if SCHEDULE.is_session(day):
            sessions.append(day)
        day += timedelta(days=1)
    return sessions


# One page body for a symbol, with the given rows and optional next token.
def _page_body(symbol, rows, token=None):
    """Return the JSON text of one Alpaca bars page for ``symbol``."""
    return json.dumps({"bars": {symbol: rows}, "next_page_token": token})


# One stored page dict with its body hash and its explicit request cursor.
def _stored_page(symbol, rows, token=None, *, request_page_token=None):
    """Return a stored page dict (status 200, sha256, request cursor).

    ``token`` is the response ``next_page_token`` written into the body;
    ``request_page_token`` is the cursor the caller actually sent for this page.
    The single-page helpers default to an honest first page (null request
    cursor); multi-page callers must pass the previous page's response token.
    """
    body = _page_body(symbol, rows, token)
    return {
        "status": 200,
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "body": body,
        "request_page_token": request_page_token,
    }


# A whole snapshot over a set of samples.
def _snapshot(samples, *, adjustment="all", schema=1):
    """Return a snapshot dict with the declared metadata and samples."""
    return {
        "schema": schema,
        "feed": "iex",
        "timeframe": "15Min",
        "adjustment": adjustment,
        "start": SOURCE_START.isoformat(),
        "end": SOURCE_END.isoformat(),
        "fetched_at": "2026-09-20T12:00:00+00:00",
        "samples": samples,
    }


# A full-window sample for one symbol with complete bars on every session.
def _full_window_sample(symbol):
    """Return a sample whose single page carries every session's full bars."""
    rows = []
    for day in _window_sessions():
        rows.extend(_full_session_rows(day))
    return {"symbol": symbol, "pages": [_stored_page(symbol, rows)]}


# A full-window sample with the given entry days replaced by reclaim paths.
def _sample_with_reclaim_entries(symbol, entries):
    """Return a full-window sample whose listed entry days use reclaim bars."""
    rows = []
    for day in _window_sessions():
        if day in entries:
            rows.extend(_reclaim_entry_rows(day, symbol))
        else:
            rows.extend(_full_session_rows(day))
    return {"symbol": symbol, "pages": [_stored_page(symbol, rows)]}


# The 20 daily rows strictly before an entry, derived from the single source.
def _module_history(sample, entry):
    """Return the module-derived prior daily rows for ``entry`` from ``sample``."""
    daily = _daily_rows_by_date(sample.bars, SCHEDULE)
    return tuple(
        sorted((r for r in daily.values() if r.date < entry), key=lambda r: r.date)
    )[-20:]


# Group a parsed sample's bars by date, as the module's outcome mapping does.
def _outcome_bars(sample):
    """Return {session date: bars} preserving order, duplicates and NaN bars."""
    by_date = {}
    for bar in sample.bars:
        by_date.setdefault(bar.start.date(), []).append(bar)
    return {day: tuple(day_bars) for day, day_bars in by_date.items()}


# A reclaim entry path calibrated to the module's adjusted daily levels.
def _reclaim_entry_rows(day, symbol):
    """Return a regular entry path that breaks the level then reclaims.

    The path is calibrated from the fixture's deterministic single-source daily
    closes (each session at ``_close_for``), so it is consistent with the levels
    the reviewed replay recomputes on the same adjusted history. The setup bar
    keeps its low above the invalidation level so the path is a clean reclaim,
    never an ambiguous touch of both levels.
    """
    prior_days = [d for d in _window_sessions() if d < day][-20:]
    history = [DailyRow(d, _close_for(d), _close_for(d)) for d in prior_days]
    context = fixed_levels(history, day, price_basis=PRICE_BASIS)
    level = context.levels.level
    entry = context.levels.entry_level
    invalidation = context.levels.invalidation_level
    above = level + 1.0
    below = level - 0.5
    assert below > invalidation
    rows = [
        _bar_row(day, 0, above, above, above - 0.5, above),
        _bar_row(day, 1, above, above, invalidation + 0.6, below),
        _bar_row(day, 2, entry + 0.1, entry + 0.5, entry - 0.4, entry + 0.2),
    ]
    rows += [_bar_row(day, slot, above, above, above, above) for slot in range(3, 26)]
    return rows


# A grade-A eligibility known at the session open, for the direct replay probes.
def _ready_timeline(day):
    """Return a single eligibility record known at the entry session's open."""
    at = session_open_for(day)
    return [Eligibility("A", at, False, at)]


# A valid single-symbol snapshot parses and runs the real reviewed replay: the
# symbol's 34 requested full sessions are ready with 26 observations each, the
# summary covers them all, and the other five requested symbols stay unavailable
# rather than disappearing.
def test_valid_source_parses_and_runs_real_replay():
    snapshot = _snapshot([_full_window_sample("SPY")])
    result = run_diagnostic(snapshot, CALENDAR)
    assert isinstance(result, DiagnosticResult)
    assert result.name == "single_source_price_component"
    assert result.schema_version == 1
    assert result.feed == "iex"
    assert result.timeframe == "15Min"
    assert result.adjustment == "all"
    assert result.symbols == SYMBOLS
    assert result.data_as_of == DATA_AS_OF
    assert result.primary_horizon == PRIMARY_HORIZON == 20
    assert result.secondary_horizon == SECONDARY_HORIZON == 5
    assert result.price_basis == PRICE_BASIS == "adjusted"
    assert result.mode == PRICE_DIAGNOSTIC
    spy = [o for o in result.opportunities if o.symbol == "SPY"]
    assert len(spy) == 34
    for opp in spy:
        assert opp.status == READY
        assert opp.reason == ""
        assert opp.session_outcome is not None
        assert opp.observation_count == 26
        assert opp.session_outcome.mode == PRICE_DIAGNOSTIC
        assert opp.session_outcome.price_basis == "adjusted"
        assert opp.session_outcome.incumbent.primary.horizon == 20
        assert opp.session_outcome.candidate.secondary.horizon == 5
    assert result.summary is not None
    assert result.summary.mode == PRICE_DIAGNOSTIC
    assert result.summary.price_basis == "adjusted"
    assert result.summary.session_count == 34
    assert result.summary.neither_entries == 34
    assert result.summary.both_entries == 0
    assert result.totals.requested == 6 * 34 == 204
    assert result.totals.ready == 34
    assert result.totals.unavailable == 170
    assert result.totals.by_reason["no sample supplied for symbol"] == 170
    assert result.opportunities[0].session == result.requested_sessions[0]
    assert result.requested_sessions[0] == ENTRY_START
    assert result.requested_sessions[-1] == ENTRY_END
    assert len(result.requested_sessions) == 34


# The JSON-safe view round-trips through the JSON encoder, so the result can be
# persisted and reviewed without losing any opportunity.
def test_result_to_dict_is_json_safe():
    snapshot = _snapshot([_full_window_sample("SPY")])
    result = run_diagnostic(snapshot, CALENDAR)
    payload = to_dict(result)
    text = json.dumps(payload)
    reloaded = json.loads(text)
    assert reloaded["name"] == "single_source_price_component"
    assert reloaded["totals"]["requested"] == 204
    assert reloaded["totals"]["ready"] == 34
    assert reloaded["totals"]["unavailable"] == 170
    assert len(reloaded["opportunities"]) == 204
    assert reloaded["summary"]["session_count"] == 34
    assert "limitations" in reloaded
    assert reloaded["primary_horizon"] == 20
    assert reloaded["secondary_horizon"] == 5


# A malformed numeric future bar is retained as NaN (never dropped or cleaned)
# and cannot change an earlier event: a direct replay with a ready eligibility
# timeline records the same event and the same earlier observations on both the
# clean and the malformed bars, and the prefix becomes unavailable only once the
# corrupt bar is completed.
def test_malformed_numeric_future_bar_keeps_earlier_events():
    entry = ENTRY_START
    reclaim = _reclaim_entry_rows(entry, "SPY")
    clean_rows = []
    malformed_rows = []
    for day in _window_sessions():
        if day == entry:
            malformed = [dict(row) for row in reclaim]
            malformed[10]["c"] = "not-a-number"
            clean_rows.extend(reclaim)
            malformed_rows.extend(malformed)
        else:
            clean_rows.extend(_full_session_rows(day))
            malformed_rows.extend(_full_session_rows(day))
    clean_sample = {"symbol": "SPY", "pages": [_stored_page("SPY", clean_rows)]}
    malformed_sample = {"symbol": "SPY", "pages": [_stored_page("SPY", malformed_rows)]}
    clean = validate_snapshot(_snapshot([clean_sample])).samples[0]
    malformed = validate_snapshot(_snapshot([malformed_sample])).samples[0]
    assert clean.status == "available"
    assert malformed.status == "available"
    assert len(malformed.bars) == len(clean.bars)
    entry_start = next(
        i for i, b in enumerate(malformed.bars) if b.start.date() == entry
    )
    assert (
        malformed.bars[entry_start + 10].close != malformed.bars[entry_start + 10].close
    )
    for offset in (0, 1, 2, 11):
        assert (
            malformed.bars[entry_start + offset].open
            == clean.bars[entry_start + offset].open
        )
    entry_bars_m = [b for b in malformed.bars if b.start.date() == entry]
    entry_bars_c = [b for b in clean.bars if b.start.date() == entry]
    assert len(entry_bars_m) == 26
    history = _module_history(clean, entry)
    schedule = SCHEDULE
    outcome_bars = {}
    for b in malformed.bars:
        outcome_bars.setdefault(b.start.date(), []).append(b)
    clean_outcome = replay_session_outcome(
        symbol="SPY",
        session=entry,
        bars=entry_bars_c,
        history=list(history),
        price_basis=PRICE_BASIS,
        eligibility_timeline=_ready_timeline(entry),
        schedule=schedule,
        mode=PRICE_DIAGNOSTIC,
        outcome_bars=outcome_bars,
        data_as_of=DATA_AS_OF,
    )
    malformed_outcome = replay_session_outcome(
        symbol="SPY",
        session=entry,
        bars=entry_bars_m,
        history=list(history),
        price_basis=PRICE_BASIS,
        eligibility_timeline=_ready_timeline(entry),
        schedule=schedule,
        mode=PRICE_DIAGNOSTIC,
        outcome_bars=outcome_bars,
        data_as_of=DATA_AS_OF,
    )
    assert clean_outcome.replay.events == malformed_outcome.replay.events
    assert clean_outcome.candidate.event is not None
    for index, (clean_obs, malformed_obs) in enumerate(
        zip(
            clean_outcome.replay.observations,
            malformed_outcome.replay.observations,
            strict=True,
        )
    ):
        if index < 10:
            assert clean_obs.comparison == malformed_obs.comparison
        else:
            assert not malformed_obs.comparison.candidate.readiness


# Same-time duplicates are preserved by the parser and the module never cleans
# them, so a duplicate bar start stays in the parsed sample in order.
def test_same_time_duplicates_are_not_cleaned():
    entry = ENTRY_START
    rows = _full_session_rows(entry)
    dup = [rows[4], rows[4], rows[5], rows[5]]
    rows = rows[:4] + dup + rows[6:]
    sample = _full_window_sample("SPY")
    sample["pages"] = [_stored_page("SPY", rows)]
    parsed = validate_snapshot(_snapshot([sample])).samples[0]
    assert parsed.status == "available"
    assert len(parsed.bars) == len(rows)
    assert parsed.bars[4].start == parsed.bars[5].start
    assert parsed.bars[6].start == parsed.bars[7].start
    # A duplicated regular session never yields a daily reference row.
    daily = _daily_rows_by_date(parsed.bars, SCHEDULE)
    assert entry not in daily


# A missing previous daily session keeps the requested opportunity unavailable
# with its reason and its raw source hashes, never silently dropped.
def test_missing_previous_daily_session_is_retained_unavailable():
    removed = date(2026, 7, 20)
    assert SCHEDULE.kind(removed) is SessionKind.FULL
    sample = _full_window_sample("SPY")
    rows = []
    for day in _window_sessions():
        if day == removed:
            continue
        rows.extend(_full_session_rows(day))
    sample["pages"] = [_stored_page("SPY", rows)]
    result = run_diagnostic(_snapshot([sample]), CALENDAR)
    entry = ENTRY_START
    opp = next(
        o for o in result.opportunities if o.symbol == "SPY" and o.session == entry
    )
    assert opp.status == UNAVAILABLE
    assert "prior daily history unavailable" in opp.reason
    assert opp.source_hashes
    # An entry whose preceding 20 sessions avoid the gap is still ready.
    last = result.requested_sessions[-1]
    opp_last = next(
        o for o in result.opportunities if o.symbol == "SPY" and o.session == last
    )
    assert opp_last.status == READY


# A complete early-close historical day is derived from exactly 14 bars while a
# full session needs exactly 26, extended-hours bars are excluded, and an
# incomplete session yields no daily row at all.
def test_early_close_historical_day_counts_correctly():
    full = date(2026, 7, 15)
    early = date(2026, 11, 27)
    synthetic = ResearchCalendar(
        frozenset({2026}),
        frozenset(),
        frozenset({early}),
    )
    sched = session_schedule_from_calendar(synthetic)
    assert sched.kind(full) is SessionKind.FULL
    assert sched.kind(early) is SessionKind.EARLY_CLOSE
    full_rows = [_bar(full, s, 100.0, 100.2, 99.8, 100.0) for s in range(26)]
    early_rows = [_bar(early, s, 100.0, 100.2, 99.8, 100.0) for s in range(14)]
    assert _daily_row(early, early_rows, sched) == DailyRow(early, 100.0, 100.0)
    assert _daily_row(full, full_rows, sched) == DailyRow(full, 100.0, 100.0)
    assert _daily_row(early, full_rows, sched) is None
    assert _daily_row(early, early_rows[:-1], sched) is None
    # Extended-hours bars are excluded before the 26-bar completeness count.
    late = _bar(early, 26, 101.0, 101.0, 101.0, 101.0)
    assert _daily_row(early, early_rows + [late], sched) == DailyRow(
        early, 100.0, 100.0
    )


# Wrong adjustment, an unknown schema, a hash mismatch, truncated pages and a
# duplicate symbol are rejected or explicit unavailable, never silently scored.
def test_wrong_adjustment_hash_pages_and_duplicate_symbol_are_rejected():
    with pytest.raises(ValueError, match="adjustment"):
        run_diagnostic(
            _snapshot([_full_window_sample("SPY")], adjustment="raw"), CALENDAR
        )
    with pytest.raises(ValueError, match="schema"):
        run_diagnostic(_snapshot([_full_window_sample("SPY")], schema=2), CALENDAR)
    bad_hash = _full_window_sample("SPY")
    bad_hash["pages"][0] = dict(bad_hash["pages"][0], sha256="0" * 64)
    result = run_diagnostic(_snapshot([bad_hash]), CALENDAR)
    spy = [o for o in result.opportunities if o.symbol == "SPY"]
    assert spy
    assert all(o.status == UNAVAILABLE for o in spy)
    assert "sha256" in spy[0].reason
    truncated = _full_window_sample("SPY")
    first = json.loads(truncated["pages"][0]["body"])
    truncated["pages"] = [
        _stored_page("SPY", first["bars"]["SPY"], token="abc"),
        _stored_page(
            "SPY",
            first["bars"]["SPY"],
            token="def",
            request_page_token="abc",
        ),
    ]
    result = run_diagnostic(_snapshot([truncated]), CALENDAR)
    assert all(
        o.status == UNAVAILABLE for o in result.opportunities if o.symbol == "SPY"
    )
    assert (
        "truncated" in next(o for o in result.opportunities if o.symbol == "SPY").reason
    )
    discontinuous = [
        _stored_page("SPY", first["bars"]["SPY"], token=None),
        _stored_page("SPY", first["bars"]["SPY"], token="abc"),
    ]
    result = run_diagnostic(
        _snapshot([{"symbol": "SPY", "pages": discontinuous}]), CALENDAR
    )
    assert all(
        o.status == UNAVAILABLE for o in result.opportunities if o.symbol == "SPY"
    )
    assert (
        "pagination ended"
        in next(o for o in result.opportunities if o.symbol == "SPY").reason
    )
    dup = [
        _full_window_sample("SPY"),
        {"symbol": "SPY", "pages": [_stored_page("SPY", [])]},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        run_diagnostic(_snapshot(dup), CALENDAR)
    with pytest.raises(ValueError, match="outside the declared cohort"):
        run_diagnostic(_snapshot([{"symbol": "NOPE", "pages": []}]), CALENDAR)


# A symbol that is requested but absent from the snapshot remains a requested,
# unavailable opportunity with an explicit reason, in the declared symbol order.
def test_missing_symbol_remains_requested():
    result = run_diagnostic(_snapshot([_full_window_sample("SPY")]), CALENDAR)
    assert result.totals.requested == 204
    assert result.totals.ready == 34
    assert result.totals.unavailable == 170
    for symbol in ("AVGO", "WRB", "WDC", "APTV", "QQQ"):
        opps = [o for o in result.opportunities if o.symbol == symbol]
        assert len(opps) == 34
        assert all(o.status == UNAVAILABLE for o in opps)
        assert all(o.reason == "no sample supplied for symbol" for o in opps)
    symbols_seen = [o.symbol for o in result.opportunities]
    assert symbols_seen[0] == "AVGO"
    assert symbols_seen[34] == "WRB"
    assert result.symbols == ("AVGO", "WRB", "WDC", "APTV", "SPY", "QQQ")


# A stored page body that is not valid JSON (truncated) makes the sample
# explicitly unavailable rather than dropping the symbol.
def test_truncated_invalid_json_page_is_explicit_unavailable():
    sample = _full_window_sample("SPY")
    body = sample["pages"][0]["body"]
    truncated_body = body[:-20]
    sample["pages"] = [
        {
            "status": 200,
            "sha256": hashlib.sha256(truncated_body.encode()).hexdigest(),
            "body": truncated_body,
        }
    ]
    parsed = validate_snapshot(_snapshot([sample])).samples[0]
    assert parsed.status == UNAVAILABLE
    assert "JSON" in parsed.reason
    result = run_diagnostic(_snapshot([sample]), CALENDAR)
    assert all(
        o.status == UNAVAILABLE for o in result.opportunities if o.symbol == "SPY"
    )


# The as-of maturity logic keeps the fixed 20/5 horizons: an early entry whose
# endpoints lie before the dataset as-of are complete, while a late entry whose
# endpoints close after it are immature, never shortened.
def test_as_of_maturity_remains_20_and_5_unchanged():
    result = run_diagnostic(_snapshot([_full_window_sample("SPY")]), CALENDAR)
    assert result.primary_horizon == 20
    assert result.secondary_horizon == 5
    early_opp = next(
        o
        for o in result.opportunities
        if o.symbol == "SPY" and o.session == ENTRY_START
    )
    assert early_opp.session_outcome.incumbent.primary.horizon == 20
    assert early_opp.session_outcome.incumbent.secondary.horizon == 5
    assert early_opp.session_outcome.candidate.primary.horizon == 20
    assert early_opp.session_outcome.candidate.secondary.horizon == 5
    # The reviewed replay with a ready eligibility timeline proves the maturity
    # behaviour: the 08-03 entry's endpoints close before the 09-18 as-of.
    sample = validate_snapshot(
        _snapshot([_sample_with_reclaim_entries("SPY", (ENTRY_START, ENTRY_END))])
    ).samples[0]
    early = replay_session_outcome(
        symbol="SPY",
        session=ENTRY_START,
        bars=[b for b in sample.bars if b.start.date() == ENTRY_START],
        history=list(_module_history(sample, ENTRY_START)),
        price_basis=PRICE_BASIS,
        eligibility_timeline=_ready_timeline(ENTRY_START),
        schedule=SCHEDULE,
        mode=PRICE_DIAGNOSTIC,
        outcome_bars=_outcome_bars(sample),
        data_as_of=DATA_AS_OF,
    )
    assert early.candidate.secondary.status == "complete"
    assert early.candidate.primary.status == "complete"
    assert early.candidate.secondary.horizon == 5
    assert early.candidate.primary.horizon == 20
    last = replay_session_outcome(
        symbol="SPY",
        session=ENTRY_END,
        bars=[b for b in sample.bars if b.start.date() == ENTRY_END],
        history=list(_module_history(sample, ENTRY_END)),
        price_basis=PRICE_BASIS,
        eligibility_timeline=_ready_timeline(ENTRY_END),
        schedule=SCHEDULE,
        mode=PRICE_DIAGNOSTIC,
        outcome_bars=_outcome_bars(sample),
        data_as_of=DATA_AS_OF,
    )
    assert last.candidate.secondary.status == "immature"
    assert last.candidate.primary.status == "immature"
    assert last.candidate.primary.forward_return is None


# The single source never mixes providers or double-adjusts: derived daily rows
# carry close == adjusted close (both the last regular close of the same bars),
# the replay runs on an adjusted basis, and no raw/Yahoo conversion is applied.
def test_no_raw_yahoo_conversion_or_double_adjustment():
    sample = validate_snapshot(_snapshot([_full_window_sample("SPY")])).samples[0]
    daily = _daily_rows_by_date(sample.bars, SCHEDULE)
    assert daily
    for row in daily.values():
        assert row.close == row.adj_close
        assert row.close > 0
    result = run_diagnostic(_snapshot([_full_window_sample("SPY")]), CALENDAR)
    assert result.price_basis == "adjusted"
    opp = next(
        o
        for o in result.opportunities
        if o.symbol == "SPY" and o.session == ENTRY_START
    )
    assert opp.session_outcome.price_basis == "adjusted"
    # The reviewed fixed levels in adjusted mode use the raw history as-is: the
    # incumbency ratio is 1.0 (adj==close), never a doubled raw conversion.
    history = _module_history(sample, ENTRY_START)
    context = fixed_levels(list(history), ENTRY_START, price_basis="adjusted")
    assert context.ratio == pytest.approx(1.0)
    assert (
        context.levels.entry_level
        > context.levels.level
        > context.levels.invalidation_level
    )


# A per-symbol sample with a naive bar timestamp is unavailable (unplaceable
# causality) rather than parsed at a guessed clock.
def test_naive_timestamp_makes_sample_unavailable():
    rows = _full_session_rows(ENTRY_START)
    naive = dict(rows[0])
    naive["t"] = "2026-08-03T09:30:00"
    rows = [naive] + rows[1:]
    sample = _full_window_sample("SPY")
    sample["pages"] = [_stored_page("SPY", rows)]
    parsed = validate_snapshot(_snapshot([sample])).samples[0]
    assert parsed.status == UNAVAILABLE
    assert "naive timestamp" in parsed.reason
    result = run_diagnostic(_snapshot([sample]), CALENDAR)
    assert all(
        o.status == UNAVAILABLE for o in result.opportunities if o.symbol == "SPY"
    )


# The assumed common eligibility (grade A, rejecting_band False at each session
# open) fires BOTH methods on a synthetic reclaim through run_diagnostic itself,
# and the fixed 20/5 horizons keep mature (early) and immature (late) labels
# rather than being shortened by the as-of.
def test_assumed_eligibility_fires_both_methods_via_run_diagnostic():
    sample = _sample_with_reclaim_entries("SPY", (ENTRY_START, ENTRY_END))
    result = run_diagnostic(_snapshot([sample]), CALENDAR)
    early = next(
        o
        for o in result.opportunities
        if o.symbol == "SPY" and o.session == ENTRY_START
    )
    assert early.status == READY
    assert set(early.events) == {"incumbent", "candidate"}
    assert early.events["incumbent"]
    assert early.events["candidate"]
    assert early.session_outcome.candidate.primary.horizon == 20
    assert early.session_outcome.candidate.primary.status == "complete"
    assert early.session_outcome.candidate.secondary.horizon == 5
    assert early.session_outcome.candidate.secondary.status == "complete"
    late = next(
        o for o in result.opportunities if o.symbol == "SPY" and o.session == ENTRY_END
    )
    assert late.status == READY
    assert set(late.events) == {"incumbent", "candidate"}
    assert late.events["incumbent"]
    assert late.events["candidate"]
    assert late.session_outcome.candidate.primary.horizon == 20
    assert late.session_outcome.candidate.primary.status == "immature"
    assert late.session_outcome.candidate.secondary.status == "immature"
    assert late.session_outcome.candidate.primary.forward_return is None


# A late malformed numeric bar on a reclaim entry day cannot disable the earlier
# events the assumed eligibility already fired through run_diagnostic.
def test_late_bad_bar_does_not_disable_earlier_events_via_run_diagnostic():
    entry = ENTRY_START
    rows = []
    for day in _window_sessions():
        if day == entry:
            reclaim = _reclaim_entry_rows(day, "SPY")
            malformed = [dict(row) for row in reclaim]
            malformed[10]["c"] = "not-a-number"
            rows.extend(malformed)
        else:
            rows.extend(_full_session_rows(day))
    sample = {"symbol": "SPY", "pages": [_stored_page("SPY", rows)]}
    result = run_diagnostic(_snapshot([sample]), CALENDAR)
    opp = next(
        o for o in result.opportunities if o.symbol == "SPY" and o.session == entry
    )
    assert opp.status == READY
    assert set(opp.events) == {"incumbent", "candidate"}
    assert opp.events["incumbent"]
    assert opp.events["candidate"]
    assert opp.session_outcome.candidate.event is not None


# An honest multi-page chain (each later page requests exactly the previous
# page's response token, and the last page carries a null response token)
# parses as available.
def test_continuous_pagination_chain_is_available():
    rows = _full_session_rows(ENTRY_START)
    pages = [
        _stored_page("SPY", rows[:13], token="tok-1"),
        _stored_page("SPY", rows[13:], token=None, request_page_token="tok-1"),
    ]
    parsed = validate_snapshot(_snapshot([{"symbol": "SPY", "pages": pages}])).samples[
        0
    ]
    assert parsed.status == "available"
    assert len(parsed.bars) == len(rows)


# A disconnected, cyclic or non-string pagination cursor makes the sample
# unavailable with an exact reason, and the verified source hashes are retained.
def test_disconnected_or_cyclic_pagination_is_unavailable():
    rows = _full_session_rows(ENTRY_START)
    mismatch = [
        _stored_page("SPY", rows[:13], token="tok-1"),
        _stored_page("SPY", rows[13:], token=None, request_page_token="tok-2"),
    ]
    result = run_diagnostic(_snapshot([{"symbol": "SPY", "pages": mismatch}]), CALENDAR)
    opp = next(o for o in result.opportunities if o.symbol == "SPY")
    assert opp.status == UNAVAILABLE
    assert "does not match" in opp.reason
    assert opp.source_hashes
    cyclic = [
        _stored_page("SPY", rows[:13], token="tok-1"),
        _stored_page("SPY", rows[13:], token="tok-1", request_page_token="tok-1"),
    ]
    result = run_diagnostic(_snapshot([{"symbol": "SPY", "pages": cyclic}]), CALENDAR)
    opp = next(o for o in result.opportunities if o.symbol == "SPY")
    assert opp.status == UNAVAILABLE
    assert "repeated" in opp.reason
    nonstring = [
        _stored_page("SPY", rows[:13], token="tok-1"),
        _stored_page("SPY", rows[13:], token=None, request_page_token=123),
    ]
    result = run_diagnostic(
        _snapshot([{"symbol": "SPY", "pages": nonstring}]), CALENDAR
    )
    opp = next(o for o in result.opportunities if o.symbol == "SPY")
    assert opp.status == UNAVAILABLE
    assert "must be a string" in opp.reason


# A page whose bars payload names a symbol other than the sample's own is
# contamination and is rejected, never silently ignored.
def test_unexpected_symbol_in_page_payload_is_rejected():
    body = json.dumps({"bars": {"SPY": [], "QQQ": []}, "next_page_token": None})
    page = {
        "status": 200,
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "body": body,
        "request_page_token": None,
    }
    parsed = validate_snapshot(_snapshot([{"symbol": "SPY", "pages": [page]}])).samples[
        0
    ]
    assert parsed.status == UNAVAILABLE
    assert "unexpected symbols" in parsed.reason
    assert "QQQ" in parsed.reason
