"""The raw-basis SIP fifteen-minute store and its acceptance gate.

What has to hold: a partition is one ticker's one New York session, holds
only regular-session bars bounded by the calendar close (26 slots, 14 on
an early close), carries its provenance in the schema metadata and says
whether it is complete; an append fetches only the sessions not stored,
one request per contiguous run, and never overwrites a complete
partition; and the reconcile gate compares the session with the daily
store's bar on the raw basis, undoing the daily store's split adjustment.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from backend.market import alpaca
from backend.market import intraday_sip as sip
from backend.market.alpaca import IntradayBar
from backend.market.store import MarketStore
from backend.market.yahoo import CorporateAction, DailyBar, TickerHistory

EARLY = date(2025, 11, 28)  # 13:00 close
MON = date(2025, 12, 1)
TUE = date(2025, 12, 2)
WED = date(2025, 12, 3)
PROVENANCE = sip.Provenance(
    fetched_at="2026-09-26T01:00:00+00:00", source_revision="abc123"
)


# Winter bars for one New York day: `count` bars from 09:30 EST (14:30
# UTC) at fifteen-minute steps, optionally with pre-market bars in front.
def _bars(
    day: date,
    base: float = 100.0,
    count: int = 26,
    pre_market: int = 0,
    volume: float = 100.0,
) -> list[IntradayBar]:
    start = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
    out = []
    for i in range(-pre_market, count):
        price = base + i
        out.append(
            IntradayBar(
                start + timedelta(minutes=15 * i),
                price,
                price + 0.5,
                price - 0.5,
                price,
                volume,
            )
        )
    return out


# A daily history whose raw session bars match `_bars(day, base)`: open
# `base`, close `base + 25`, high `base + 25.5`, low `base - 0.5`, volume
# 2600, with an optional split after the sessions that scales the stored
# (split-adjusted) values the way the daily store holds them.
def _daily(
    days: list[date], bases: list[float], split: tuple[date, float] | None = None
):
    factor = split[1] if split else 1.0
    bars = tuple(
        DailyBar(
            session_date=d,
            open=b / factor,
            high=(b + 25.5) / factor,
            low=(b - 0.5) / factor,
            close=(b + 25) / factor,
            adjusted_close=(b + 25) / factor,
            volume=int(2600 * factor),
        )
        for d, b in zip(days, bases, strict=True)
    )
    actions = (CorporateAction(split[0], "split", split[1]),) if split else ()
    return TickerHistory(
        ticker="AVGO",
        bars=bars,
        actions=actions,
        complete_through=days[-1],
        source_time=datetime(2026, 9, 26, tzinfo=UTC),
    )


# A partition holds only the regular bars, labelled by the session date,
# with the provenance and completeness in its metadata, and reads back.
def test_write_and_read_a_session_with_provenance(tmp_path):
    store = MarketStore(tmp_path)
    assert sip.write_session(store, "AVGO", MON, _bars(MON, pre_market=2), PROVENANCE)
    assert (tmp_path / "bars_15m_sip" / "asof=2025-12-01" / "AVGO.parquet").exists()
    bars, meta = sip.read_session(store, "AVGO", MON)
    assert len(bars) == 26
    assert bars[0].open == 100.0
    assert bars[-1].close == 125.0
    assert meta["feed"] == "sip"
    assert meta["adjustment"] == "raw"
    assert meta["timeframe"] == "15Min"
    assert meta["fetched_at"] == "2026-09-26T01:00:00+00:00"
    assert meta["source_revision"] == "abc123"
    assert meta["session_date"] == "2025-12-01"
    assert meta["session_close"] == "16:00:00"
    assert meta["bars_expected"] == "26"
    assert meta["bar_count"] == "26"
    assert meta["complete"] == "true"
    assert sip.sessions_available(store, "AVGO") == [MON]
    assert sip.read_session(store, "AVGO", TUE) is None  # never the day before


# An early-close session keeps 09:30..12:45 only, is complete at 14 bars,
# and its after-hours prints are not stored.
def test_early_close_session_is_bounded_and_complete_at_fourteen(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", EARLY, _bars(EARLY), PROVENANCE)
    bars, meta = sip.read_session(store, "AVGO", EARLY)
    assert len(bars) == 14
    assert bars[-1].start.astimezone(sip.NEW_YORK).strftime("%H:%M") == "12:45"
    assert meta["session_close"] == "13:00:00"
    assert meta["bars_expected"] == "14"
    assert meta["complete"] == "true"
    assert sip.is_complete(_bars(EARLY, count=13), EARLY) is False
    assert sip.is_complete(_bars(MON, count=25), MON) is False


# A complete partition is never overwritten; an incomplete one is
# replaced by a fuller fetch.
def test_complete_partitions_are_immutable_and_incomplete_ones_replaced(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON, count=20), PROVENANCE)
    assert sip.read_session(store, "AVGO", MON)[1]["complete"] == "false"
    assert sip.completeness(store, "AVGO") == {MON: False}
    sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    assert sip.read_session(store, "AVGO", MON)[1]["complete"] == "true"
    with pytest.raises(sip.SipStoreError):
        sip.write_session(store, "AVGO", MON, _bars(MON, base=500.0), PROVENANCE)
    assert sip.read_session(store, "AVGO", MON)[0][0].open == 100.0


# An append fetches only the sessions without a partition, one request
# per contiguous run, writes each session on its own, reports the ones
# the feed had nothing for, and a dry run fetches nothing.
def test_append_missing_fetches_only_the_gaps_in_contiguous_runs(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", TUE, _bars(TUE), PROVENANCE)
    calls: list[tuple[str, date, date]] = []
    tape = {EARLY: _bars(EARLY), MON: _bars(MON), TUE: _bars(TUE, base=999.0)}

    # Return the bars of every session in the range, extended hours included.
    def fetch(ticker, start, end):
        calls.append((ticker, start, end))
        return [b for d, bars in tape.items() if start <= d <= end for b in bars]

    sessions = [EARLY, MON, TUE, WED]
    dry = sip.append_missing(store, "AVGO", sessions, fetch, PROVENANCE, dry_run=True)
    assert calls == []
    assert dry.to_fetch == (EARLY, MON, WED)
    assert dry.fetch_ranges == ((EARLY, MON), (WED, WED))
    assert dry.written == ()
    result = sip.append_missing(store, "AVGO", sessions, fetch, PROVENANCE)
    assert calls == [("AVGO", EARLY, MON), ("AVGO", WED, WED)]
    assert result.already_stored == 1
    assert result.written == (EARLY, MON)
    assert result.incomplete == ()
    assert result.no_bars == (WED,)
    assert sip.sessions_available(store, "AVGO") == [EARLY, MON, TUE]
    assert sip.read_session(store, "AVGO", TUE)[0][0].open == 100.0  # untouched
    # A second run has nothing left but the empty Wednesday.
    calls.clear()
    again = sip.append_missing(store, "AVGO", sessions, fetch, PROVENANCE)
    assert calls == [("AVGO", WED, WED)]
    assert again.written == ()
    assert again.already_stored == 3


# Only with `include_incomplete` is a short partition fetched again.
def test_append_refetches_incomplete_sessions_only_on_request(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON, count=10), PROVENANCE)
    calls: list[tuple[date, date]] = []

    def fetch(ticker, start, end):
        calls.append((start, end))
        return _bars(MON)

    assert sip.append_missing(store, "AVGO", [MON], fetch, PROVENANCE).to_fetch == ()
    assert calls == []
    result = sip.append_missing(
        store, "AVGO", [MON], fetch, PROVENANCE, include_incomplete=True
    )
    assert calls == [(MON, MON)]
    assert result.written == (MON,)
    assert sip.completeness(store, "AVGO") == {MON: True}


# The gate passes a session whose first open, last close, high, low and
# summed volume agree with the daily bar, and reports the differences.
def test_reconcile_passes_a_matching_session(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    store.write(date(2026, 9, 26), _daily([MON], [100.0]))
    record = sip.reconcile(store, "AVGO", MON)
    assert record.passed
    assert record.reason == ""
    assert record.stored
    assert record.complete
    assert record.daily_found
    assert record.split_factor == 1.0
    for diff in (
        record.open_diff,
        record.close_diff,
        record.high_diff,
        record.low_diff,
    ):
        assert abs(diff) < 1e-9
    assert abs(record.volume_diff) < 1e-9
    assert record.close_tolerance == sip.DEFAULT_CLOSE_TOLERANCE == 0.005
    assert record.volume_tolerance == sip.DEFAULT_VOLUME_TOLERANCE == 0.20
    as_json = sip.reconciliation_record(record)
    assert as_json["session"] == "2025-12-01"
    assert as_json["passed"] is True


# The daily store's close is split-adjusted as of its fetch; the raw SIP
# close of a pre-split session is compared after undoing the split, so
# AVGO's ten-for-one does not read as a tenfold error.
def test_reconcile_undoes_a_later_split(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    store.write(date(2026, 9, 26), _daily([MON], [100.0], split=(WED, 10.0)))
    record = sip.reconcile(store, "AVGO", MON)
    assert record.split_factor == 10.0
    assert record.passed, record.reason
    assert abs(record.close_diff) < 1e-9
    assert abs(record.volume_diff) < 1e-9


# A close outside the tolerance, a volume outside its tolerance, an
# incomplete session and a missing daily bar each fail with a reason.
def test_reconcile_fails_with_a_reason(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    sip.write_session(store, "AVGO", TUE, _bars(TUE, volume=200.0), PROVENANCE)
    sip.write_session(store, "AVGO", WED, _bars(WED, count=20), PROVENANCE)
    store.write(date(2026, 9, 26), _daily([MON, TUE, WED], [101.0, 100.0, 100.0]))
    close = sip.reconcile(store, "AVGO", MON)
    assert not close.passed
    assert close.reason.startswith("close differs")
    assert abs(close.close_diff) > sip.DEFAULT_CLOSE_TOLERANCE
    volume = sip.reconcile(store, "AVGO", TUE)
    assert not volume.passed
    assert volume.reason.startswith("volume differs")
    assert volume.volume_diff == pytest.approx(1.0)
    assert sip.reconcile(store, "AVGO", WED).reason == "session incomplete"
    assert sip.reconcile(store, "AVGO", EARLY).reason == "session not stored"
    sip.write_session(store, "AVGO", EARLY, _bars(EARLY), PROVENANCE)
    assert sip.reconcile(store, "AVGO", EARLY).reason == "no daily bar for the session"
    assert sip.reconcile(store, "AVGO", TUE, volume_tolerance=1.5).passed


# The coverage report counts the calendar's sessions, what is stored, how
# much of it is complete, and the reconcile pass rate; years the calendar
# has not reviewed are named rather than counted.
def test_coverage_report(tmp_path):
    store = MarketStore(tmp_path)
    for day in (EARLY, MON, TUE):
        sip.write_session(store, "AVGO", day, _bars(day), PROVENANCE)
    sip.write_session(store, "AVGO", WED, _bars(WED, count=20), PROVENANCE)
    store.write(
        date(2026, 9, 26), _daily([EARLY, MON, TUE, WED], [100.0, 100.0, 100.0, 100.0])
    )
    report = sip.coverage(store, "AVGO", EARLY, date(2025, 12, 5))
    assert report["sessions_in_calendar"] == 6  # Fri 28, Mon 1 .. Fri 5
    assert report["sessions_stored"] == 4
    assert report["sessions_missing"] == 2
    assert report["complete"] == 3
    assert report["complete_share"] == pytest.approx(0.75)
    assert report["reconciled"] == 4
    assert report["reconcile_passed"] == 2  # the early close has a 14-bar volume
    assert report["calendar_unreviewed_years"] == []
    sessions, unreviewed = sip.calendar_sessions(date(2015, 12, 30), date(2016, 1, 5))
    assert unreviewed == [2015]
    assert sessions == [date(2016, 1, 4), date(2016, 1, 5)]


# The source revision is a git SHA here, and "" where git cannot answer.
def test_source_revision_is_a_sha_or_empty(tmp_path):
    sha = sip.source_revision()
    assert sha == "" or (len(sha) == 40 and all(c in "0123456789abcdef" for c in sha))
    assert sip.source_revision(tmp_path) == ""
    meta = sip.provenance_now(lambda: datetime(2026, 9, 26, 1, tzinfo=UTC))
    assert meta.fetched_at == "2026-09-26T01:00:00+00:00"
    assert meta.feed == "sip"
    assert meta.adjustment == "raw"


# A partition written while the calendar took a half day for a full one
# (the first backfill, before 2016-2018 were reviewed) holds after-hours
# prints in slots 14-25 and says "complete". Once the calendar knows the
# 13:00 close, that partition is stale: completeness reports it
# incomplete, `calendar_stale` names it, the refresh wants it again, and
# the rewrite - the one case a complete partition may be replaced -
# leaves 14 correctly bounded bars.
def test_partition_cut_under_a_wrong_calendar_close_is_stale_and_rewritten(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    monkeypatch.setattr(sip.calendar, "session_close", lambda day: time(16, 0))
    alpaca.close_minutes.cache_clear()
    assert sip.write_session(store, "AVGO", EARLY, _bars(EARLY), PROVENANCE)
    bars, meta = sip.read_session(store, "AVGO", EARLY)
    assert len(bars) == 26 and meta["complete"] == "true" and meta["session_close"] == "16:00:00"
    monkeypatch.undo()
    # `alpaca.close_minutes` caches the close per day; the patched value
    # would otherwise outlive the patch in this process (it never changes
    # in a real one).
    alpaca.close_minutes.cache_clear()
    assert sip.calendar.session_close(EARLY) == time(13, 0)
    assert sip.calendar_stale(store, "AVGO") == [EARLY]
    assert sip.completeness(store, "AVGO") == {EARLY: False}
    # A correctly bounded complete partition is still never overwritten.
    assert sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    assert sip.calendar_stale(store, "AVGO") == [EARLY]
    with pytest.raises(sip.SipStoreError):
        sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    fetched = []

    def fetch(ticker, first, last):
        fetched.append((first, last))
        return _bars(EARLY)

    result = sip.append_missing(store, "AVGO", [EARLY, MON], fetch, PROVENANCE, include_incomplete=True)
    assert fetched == [(EARLY, EARLY)]
    assert result.written == (EARLY,) and result.incomplete == ()
    bars, meta = sip.read_session(store, "AVGO", EARLY)
    assert len(bars) == 14 and meta["complete"] == "true" and meta["session_close"] == "13:00:00"
    assert sip.calendar_stale(store, "AVGO") == []
    assert sip.completeness(store, "AVGO") == {EARLY: True, MON: True}


# A bar that starts at the session close, carrying the closing cross.
def _auction(day: date, price: float, volume: float) -> IntradayBar:
    close = sip.calendar.session_close(day)
    start = datetime(day.year, day.month, day.day, close.hour, close.minute, tzinfo=sip.NEW_YORK).astimezone(UTC)
    return IntradayBar(start, price, price + 0.1, price - 0.1, price + 0.05, volume)


# The closing-auction bar is the one starting at the close - 16:00 on an
# ordinary day, 13:00 on a half day - and never a regular slot; the
# partition keeps it after the regular slots, `read_session` still
# returns only the regular slots, and `read_closing_auction` returns it.
def test_closing_auction_bar_is_kept_beside_the_regular_slots(tmp_path):
    store = MarketStore(tmp_path)
    bars = _bars(MON) + [_auction(MON, 125.0, 900.0)]
    assert sip.closing_auction(bars, MON) == bars[-1]
    assert sip.closing_auction(_bars(MON), MON) is None
    early = _bars(EARLY)  # 26 bars from 09:30: the 13:00 bar is the auction on a half day
    assert sip.closing_auction(early, EARLY) == early[14]
    assert len(sip.regular_bars(early, EARLY)) == 14
    assert sip.write_session(store, "AVGO", MON, bars, PROVENANCE)
    regular, meta = sip.read_session(store, "AVGO", MON)
    assert len(regular) == 26 and regular[-1].close == 125.0
    assert meta["auction_bar"] == "true" and meta["schema"] == sip.SCHEMA_VERSION == "2"
    assert sip.read_closing_auction(store, "AVGO", MON) == bars[-1]
    assert sip.write_session(store, "AVGO", TUE, _bars(TUE), PROVENANCE)
    assert sip.read_closing_auction(store, "AVGO", TUE) is None
    _, meta = sip.read_session(store, "AVGO", TUE)
    assert meta["auction_bar"] == "false"
    assert sip.completeness(store, "AVGO") == {MON: True, TUE: True}


# A partition written under the previous layout (no schema tag, no
# auction row) is stale: reported incomplete, named, and rewritten by the
# refresh even though it was complete.
def test_partition_without_the_auction_row_is_stale_and_rewritten(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    monkeypatch.setattr(sip, "SCHEMA_VERSION", "1")
    assert sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    monkeypatch.undo()
    assert sip.calendar_stale(store, "AVGO") == [MON]
    assert sip.completeness(store, "AVGO") == {MON: False}
    result = sip.append_missing(
        store, "AVGO", [MON], lambda t, a, b: _bars(MON) + [_auction(MON, 125.0, 900.0)], PROVENANCE, include_incomplete=True
    )
    assert result.written == (MON,)
    assert sip.calendar_stale(store, "AVGO") == []
    assert sip.read_closing_auction(store, "AVGO", MON).volume == 900.0


# The daily bar's close is the closing cross and its volume includes it,
# so with the auction row the reconcile compares the cross's first print
# to the daily close and adds the cross's volume to the regular slots'.
def test_reconcile_counts_the_closing_auction(tmp_path):
    store = MarketStore(tmp_path)
    # Regular slots: 26 x 100 shares; the cross: 900; the daily bar: 2600 + 900.
    sip.write_session(store, "AVGO", MON, _bars(MON) + [_auction(MON, 125.0, 900.0)], PROVENANCE)
    from dataclasses import replace

    daily = _daily([MON, TUE], [100.0, 100.0])
    daily = replace(daily, bars=tuple(replace(b, volume=3500) for b in daily.bars))
    store.write(date(2026, 9, 26), daily)
    record = sip.reconcile(store, "AVGO", MON)
    assert record.passed, record.reason
    assert abs(record.volume_diff) < 1e-9
    assert abs(record.close_diff) < 1e-9
    # The same session without the auction row fails the volume gate by
    # the size of the cross, which is what the first backfill showed.
    sip.write_session(store, "AVGO", TUE, _bars(TUE), PROVENANCE)
    record = sip.reconcile(store, "AVGO", TUE)
    assert record.reason.startswith("volume differs")
    assert record.volume_diff == pytest.approx(2600 / 3500 - 1)
