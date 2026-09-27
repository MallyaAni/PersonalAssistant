"""The SIP session cube: complete 26-slot sessions stacked, on the raw basis.

What has to hold: only calendar-full, store-complete sessions with a
daily bar before them enter, and every other stored session is counted
under its reason; the arrays are (N, 26) in slot order; the prior close
is the previous session's daily close moved onto the session's own raw
basis, so a 2:1 split between the two reads as no gap rather than a
halving; and the on-disk cache is reused while the store's session count
and newest date match, and rebuilt when either or the version moves.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.market import intraday_sip as sip
from backend.market import sip_cube
from backend.market.alpaca import IntradayBar
from backend.market.store import MarketStore
from backend.market.yahoo import CorporateAction, DailyBar, TickerHistory

EARLY = date(2025, 11, 28)  # 13:00 close, 14 slots
MON = date(2025, 12, 1)
TUE = date(2025, 12, 2)
WED = date(2025, 12, 3)
THU = date(2025, 12, 4)
PROVENANCE = sip.Provenance(
    fetched_at="2026-09-26T01:00:00+00:00", source_revision="abc123"
)


# Winter bars for one New York day: `count` bars from 09:30 EST (14:30
# UTC) at fifteen-minute steps, close = base + slot.
def _bars(day: date, base: float = 100.0, count: int = 26) -> list[IntradayBar]:
    start = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
    out = []
    for i in range(count):
        price = base + i
        out.append(
            IntradayBar(
                start + timedelta(minutes=15 * i),
                price,
                price + 0.5,
                price - 0.5,
                price,
                100.0 + i,
            )
        )
    return out


# A daily history from explicit (date, close) pairs on the store's basis,
# with optional split actions.
def _daily(
    closes: dict[date, float], splits: tuple[tuple[date, float], ...] = ()
) -> TickerHistory:
    bars = tuple(DailyBar(d, c, c, c, c, c, 1000) for d, c in sorted(closes.items()))
    return TickerHistory(
        ticker="AVGO",
        bars=bars,
        actions=tuple(CorporateAction(d, "split", r) for d, r in splits),
        complete_through=max(closes),
        source_time=datetime(2026, 9, 26, tzinfo=UTC),
    )


# Complete full-day sessions enter in slot order with their prior close;
# an early close, an incomplete partition and a session with no daily
# bar before it are each excluded and counted.
def test_build_stacks_complete_sessions_and_counts_exclusions(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", EARLY, _bars(EARLY), PROVENANCE)
    sip.write_session(store, "AVGO", MON, _bars(MON, base=100.0), PROVENANCE)
    sip.write_session(store, "AVGO", TUE, _bars(TUE, base=200.0), PROVENANCE)
    sip.write_session(store, "AVGO", WED, _bars(WED, count=20), PROVENANCE)
    sip.write_session(store, "AVGO", THU, _bars(THU, base=300.0), PROVENANCE)
    # No daily bar before EARLY or MON: MON has no prior close.
    store.write(
        date(2026, 9, 26),
        _daily({MON: 125.0, TUE: 225.0, WED: 250.0, THU: 325.0}),
    )
    cube = sip_cube.build(store, "AVGO")
    assert cube.ticker == "AVGO"
    assert len(cube) == 2
    assert list(cube.dates.astype(str)) == ["2025-12-02", "2025-12-04"]
    for name in ("open", "high", "low", "close", "volume"):
        assert getattr(cube, name).shape == (2, 26)
    assert cube.open[0, 0] == 200.0
    assert cube.close[0, 25] == 225.0
    assert cube.high[1, 3] == 303.5
    assert cube.low[1, 3] == 302.5
    assert cube.volume[0, 25] == 125.0
    assert list(cube.prior_close) == [125.0, 250.0]
    assert cube.excluded == {"early_close": 1, "incomplete": 1, "no_prior_close": 1}


# With no daily history at all every session lacks a prior close; the
# cube is empty but well shaped.
def test_build_without_daily_history_is_empty_and_shaped(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    cube = sip_cube.build(store, "AVGO")
    assert len(cube) == 0
    assert cube.close.shape == (0, 26)
    assert cube.prior_close.shape == (0,)
    assert cube.excluded["no_prior_close"] == 1


# A 2:1 split dated on WED: TUE's raw close is 225 and WED opens at 100
# raw. The daily store (adjusted as of a later fetch) holds TUE at 112.5.
# On WED's basis the prior close is 112.5, so the gap is a small number;
# on TUE's own row the prior close (MON) is back in pre-split dollars.
def test_prior_close_crosses_a_split_on_the_sessions_basis(tmp_path):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON, base=180.0), PROVENANCE)
    sip.write_session(store, "AVGO", TUE, _bars(TUE, base=200.0), PROVENANCE)
    sip.write_session(store, "AVGO", WED, _bars(WED, base=100.0), PROVENANCE)
    store.write(
        date(2026, 9, 26),
        _daily(
            {EARLY: 90.0, MON: 102.5, TUE: 112.5, WED: 125.0},
            splits=((WED, 2.0),),
        ),
    )
    cube = sip_cube.build(store, "AVGO")
    assert list(cube.dates.astype(str)) == ["2025-12-01", "2025-12-02", "2025-12-03"]
    # MON's prior (EARLY): 90 adjusted x 2 = 180 raw, matching MON's open.
    assert cube.prior_close[0] == pytest.approx(180.0)
    # TUE's prior (MON): 102.5 x 2 = 205 raw pre-split dollars.
    assert cube.prior_close[1] == pytest.approx(205.0)
    # WED's prior (TUE): 112.5 x 1 = 112.5, TUE's close in post-split dollars.
    assert cube.prior_close[2] == pytest.approx(112.5)
    gap = np.log(cube.open[:, 0] / cube.prior_close)
    assert abs(gap[0]) < 1e-12
    assert gap[2] == pytest.approx(np.log(100.0 / 112.5))
    # Scaling by the previous session's own factor would have read the
    # split as a halving overnight.
    assert abs(np.log(100.0 / 225.0)) > 0.5


# The first load writes the cache and a second load reads it without
# rebuilding; a new session or a new module version rebuilds.
def test_cache_hit_and_miss(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    sip.write_session(store, "AVGO", MON, _bars(MON), PROVENANCE)
    sip.write_session(store, "AVGO", TUE, _bars(TUE), PROVENANCE)
    store.write(date(2026, 9, 26), _daily({EARLY: 99.0, MON: 125.0, TUE: 125.0}))
    path = sip_cube.cache_path(store, "AVGO")
    assert not path.exists()
    first = sip_cube.load(store, "AVGO")
    assert path.exists()
    assert path == tmp_path / "research" / "sip_cubes" / "AVGO.npz"
    assert len(first) == 2

    calls: list[str] = []
    real_build = sip_cube.build

    # Count rebuilds while still building for real.
    def counting_build(store_, ticker, history=None):
        calls.append(ticker)
        return real_build(store_, ticker, history)

    monkeypatch.setattr(sip_cube, "build", counting_build)
    second = sip_cube.load(store, "AVGO")
    assert calls == []
    assert list(second.dates.astype(str)) == list(first.dates.astype(str))
    np.testing.assert_array_equal(second.close, first.close)
    np.testing.assert_array_equal(second.prior_close, first.prior_close)
    assert second.excluded == first.excluded
    assert second.dates.dtype == np.dtype("datetime64[D]")

    # A new session changes the key: rebuilt once, then cached again.
    sip.write_session(store, "AVGO", WED, _bars(WED), PROVENANCE)
    third = sip_cube.load(store, "AVGO")
    assert calls == ["AVGO"]
    assert len(third) == 3
    sip_cube.load(store, "AVGO")
    assert calls == ["AVGO"]

    # A version bump invalidates a cache whose sessions did not change.
    monkeypatch.setattr(sip_cube, "CUBE_VERSION", sip_cube.CUBE_VERSION + 1)
    sip_cube.load(store, "AVGO")
    assert calls == ["AVGO", "AVGO"]

    # An unreadable file is a miss, not an error.
    path.write_bytes(b"not a cube")
    sip_cube.load(store, "AVGO")
    assert calls == ["AVGO", "AVGO", "AVGO"]
