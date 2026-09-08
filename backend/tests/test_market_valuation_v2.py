"""The second valuation analyst's inputs.

What has to hold: the trailing four quarters are the sum of four
consecutive filed quarters and nothing before four are known or when
one is missing; the sum is known only from the filing date on; a name's
own-history rank places today's reading among its trailing readings;
and peer groups fall back to the side where a sub-industry is thin.
"""

from datetime import date
from types import SimpleNamespace

import numpy as np

from backend.market import valuation
from backend.market.levels_pit import ttm_series


def _fact(name, end, value, filed):
    return SimpleNamespace(name=name, end=end, value=value, filed=filed)


def test_trailing_sum_needs_four_consecutive_quarters_and_is_point_in_time():
    dates = np.array(
        ["2025-01-02", "2025-05-15", "2025-08-15", "2025-11-15", "2026-02-15"],
        dtype="datetime64[D]",
    )
    facts = [
        _fact("revenue", date(2024, 3, 31), 10.0, date(2024, 5, 1)),
        _fact("revenue", date(2024, 6, 30), 11.0, date(2024, 8, 1)),
        _fact("revenue", date(2024, 9, 30), 12.0, date(2024, 11, 1)),
        _fact("revenue", date(2024, 12, 31), 13.0, date(2025, 2, 1)),  # four known
        # The March 2025 quarter is never filed; June 2025 arrives in August.
        _fact("revenue", date(2025, 6, 30), 15.0, date(2025, 8, 1)),
        _fact("revenue", date(2025, 3, 31), 14.0, date(2025, 11, 1)),  # late
    ]
    out = ttm_series(facts, "revenue", dates)
    assert np.isnan(out[0])  # three quarters known on 2025-01-02
    assert out[1] == 46.0  # 10 + 11 + 12 + 13, known from 2025-02-01
    # June 2025 filed with March missing: the last four are not consecutive.
    assert np.isnan(out[2])
    # March arrives late in November: the four are consecutive again.
    assert out[3] == 12.0 + 13.0 + 14.0 + 15.0
    assert np.isnan(ttm_series(facts, "net_income", dates)).all()


def test_own_history_rank_places_today_among_the_trailing_readings():
    values = np.linspace(1.0, 10.0, 300)[:, None]
    ranks = valuation.own_history_rank(values, window=300, min_known=250)
    assert np.isnan(ranks[248, 0])
    assert ranks[299, 0] > 0.99  # the highest reading in its own history
    falling = np.vstack([values, np.full((10, 1), 0.5)])
    ranks = valuation.own_history_rank(falling, window=300, min_known=250)
    assert ranks[-1, 0] < 0.05  # the cheapest it has been


def test_fine_groups_fall_back_to_the_side_where_a_sub_industry_is_thin():
    panel = SimpleNamespace(tickers=("A", "B", "C", "D", "E", "SPY"))
    sides = {"A": "ai", "B": "ai", "C": "ai", "D": "software", "E": "software"}
    sub = {"A": "Semis", "B": "Semis", "C": "Semis", "D": "Apps", "E": ""}
    ids = valuation.fine_groups(panel, sides, sub, min_peers=3)
    assert ids[0] == ids[1] == ids[2]  # three semis form a group
    assert ids[3] == ids[4]  # D's sub-industry is thin, so both fall to software
    assert ids[0] != ids[3]
    assert ids[5] == -1  # the benchmark has no group
