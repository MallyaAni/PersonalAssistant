"""Option walls from a chain.

What has to hold: a contract symbol parses into its expiry, side and
strike; a Cboe payload parses into rows within the horizon; the put wall
is the largest put open interest at or below the price and the call wall
the largest call open interest at or above it, on the nearest expiry far
enough away, within a quarter of the price; the gamma proxy carries the
dealer sign; and a frame round-trips.
"""

import json
from datetime import date

from backend.market import options


def test_symbol_parses():
    assert options.parse_symbol("ADBE260911C00130000") == (
        date(2026, 9, 11),
        "call",
        130.0,
    )
    assert options.parse_symbol("BRK.B261218P00450500") == (
        date(2026, 12, 18),
        "put",
        450.5,
    )
    assert options.parse_symbol("garbage") is None


def _payload():
    def opt(sym, oi, iv, gamma, vol=1):
        return {
            "option": sym,
            "open_interest": oi,
            "iv": iv,
            "gamma": gamma,
            "volume": vol,
        }

    return {
        "data": {
            "current_price": 100.0,
            "options": [
                opt("XYZ260911C00105000", 500, 0.4, 0.02),
                opt("XYZ260911C00110000", 2000, 0.4, 0.015),
                opt("XYZ260911C00140000", 9000, 0.5, 0.001),
                opt("XYZ260911P00095000", 700, 0.45, 0.02),
                opt("XYZ260911P00090000", 3000, 0.5, 0.018),
                opt("XYZ260911P00060000", 9000, 0.9, 0.0005),
                opt("XYZ271217C00100000", 10, 0.4, 0.01),  # too far out: dropped
            ],
        }
    }


def test_parse_and_walls():
    today = date(2026, 9, 1)
    price, rows = options.parse_chain(_payload(), today)
    assert price == 100.0
    assert len(rows) == 6  # the 2027 contract is beyond the horizon
    w = options.walls(rows, price, today, min_days=5)
    assert w.expiry == date(2026, 9, 11)
    # 140 and 60 carry the most open interest but sit outside a quarter of the price.
    assert (w.call_wall, w.call_wall_oi) == (110.0, 2000)
    assert (w.put_wall, w.put_wall_oi) == (90.0, 3000)
    # Dealer sign: calls long, puts short. Puts' gamma-weighted open interest
    # (700*0.02 + 3000*0.018 + 9000*0.0005) beats the calls' here.
    assert w.net_gamma < 0
    # A chain expiring within min_days is not a level for this book.
    none = options.walls(rows, price, date(2026, 9, 9), min_days=5)
    assert none.expiry is None
    assert none.put_wall is None


def test_frame_round_trips():
    _price, rows = options.parse_chain(_payload(), date(2026, 9, 1))
    back = options.rows_from_frame(options.frame(rows))
    assert back == rows


def test_fetch_uses_the_transport():
    calls = []

    def transport(url):
        calls.append(url)
        return 200, {}, json.dumps(_payload()).encode()

    price, rows = options.fetch_chain("XYZ", transport, date(2026, 9, 1))
    assert price == 100.0
    assert calls == [options.CHAIN_URL.format(ticker="XYZ")]
    assert len(rows) == 6
    refused = options.fetch_chain("XYZ", lambda url: (429, {}, b""), date(2026, 9, 1))
    assert refused == (None, [])


# Walls are read across the near expiries together: ORCL's put wall sat on
# a weekly with 2,224 contracts while the monthly two days nearer held
# 55,000 at one strike. Open interest is summed per strike over every
# expiry from tomorrow to sixty days out, a strike needs a minimum to be
# called a wall, and the farthest expiry summed is reported.
def test_walls_sum_open_interest_across_the_near_expiries():
    today = date(2026, 9, 16)
    rows = [
        options.ChainRow(date(2026, 9, 18), "call", 170.0, 36000, 0, 0.5, 0.01),
        options.ChainRow(date(2026, 9, 25), "call", 170.0, 8000, 0, 0.5, 0.01),
        options.ChainRow(date(2026, 9, 25), "call", 150.0, 9000, 0, 0.5, 0.01),
        options.ChainRow(date(2026, 9, 18), "put", 140.0, 20000, 0, 0.5, 0.01),
        options.ChainRow(date(2026, 9, 25), "put", 138.0, 2224, 0, 0.5, 0.01),
        options.ChainRow(date(2026, 12, 18), "put", 130.0, 90000, 0, 0.5, 0.01),
        options.ChainRow(date(2026, 9, 16), "call", 145.0, 99999, 0, 0.5, 0.01),
    ]
    w = options.walls(rows, 143.24, today)
    assert w.expiry == date(2026, 9, 18)  # today's own expiry is not a level
    assert w.through == date(2026, 9, 25)  # December is beyond the window
    assert (w.call_wall, w.call_wall_oi) == (170.0, 44000)
    assert (w.put_wall, w.put_wall_oi) == (140.0, 20000)
    thin = options.walls(rows[1:3] + rows[4:5], 143.24, today, min_oi=5000)
    assert thin.put_wall is None  # 2,224 contracts is not a wall
    assert thin.call_wall == 150.0
