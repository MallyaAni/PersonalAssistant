"""Price charts as images.

What has to hold: the window's highest high sits on the top price row
and its lowest low on the bottom one; the open is a tick on the day's
left column, the close on its right, the high-low bar in the middle;
volume fills from the bottom in proportion to the window's largest; the
moving average needs a full window behind every day and is NaN
otherwise; and an image of the session t is drawn from sessions up to t
and nothing after.
"""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from backend.market import charts  # noqa: E402


def _flat(days: int, batch: int = 1, level: float = 100.0):
    shape = (batch, days)
    return charts.Window(
        open=np.full(shape, level),
        high=np.full(shape, level),
        low=np.full(shape, level),
        close=np.full(shape, level),
        volume=np.ones(shape),
        average=np.full(shape, level),
    )


# The paper's dimensions, and prices placed by the window's extremes.
def test_image_has_the_papers_layout_and_scaling():
    days = 20
    window = _flat(days)
    window.high[0, 3] = 110.0  # the window's highest high, on day 3
    window.low[0, 7] = 90.0  # its lowest low, on day 7
    window.open[0, 3] = 105.0
    window.close[0, 3] = 100.0
    image = charts.render(window, days)
    assert image.shape == (1, 64, 60)
    price_rows = charts.SPEC[days]["price"]
    mid3, left3, right3 = 3 * 3 + 1, 3 * 3, 3 * 3 + 2
    assert image[0, 0, mid3] == 1  # the high on the top row
    assert image[0, price_rows - 1, 3 * 7 + 1] == 1  # the low on the bottom price row
    assert image[0, price_rows, :].sum() == 0  # the gap row stays empty
    # The open of day 3 at 105 sits a quarter of the way down the price rows.
    assert image[0, round((110 - 105) / 20 * (price_rows - 1)), left3] == 1
    assert image[0, price_rows // 2, right3] == 1  # the close at 100, halfway
    # Day 3's bar runs from the top row to the row of its low (100).
    assert image[0, : price_rows // 2 + 1, mid3].all()


# Volume is a bar from the bottom, the window's largest filling the area.
def test_volume_fills_from_the_bottom():
    days = 5
    window = _flat(days)
    window.volume[0] = [1.0, 2.0, 4.0, 1.0, 0.0]
    image = charts.render(window, days)
    assert image.shape == (1, 32, 15)
    volume_rows = charts.SPEC[days]["volume"]
    bottom = 31
    assert image[
        0, bottom - (volume_rows - 1) : bottom + 1, 2 * 3 + 1
    ].all()  # the largest
    # A quarter of the largest: round(0.25 * 5) = 1 pixel above the bottom.
    assert image[0, bottom - 1 : bottom + 1, 3 * 3 + 1].all()
    assert image[0, bottom - 2, 3 * 3 + 1] == 0
    assert image[0, bottom, 4 * 3 + 1] == 1  # zero volume still marks the bottom


# Windows come from the panel's arrays, the average needs a full window
# behind each day, and nothing after session t reaches its image.
def test_windows_are_causal_and_the_average_needs_its_window():
    rows, days = 60, 5
    rng = np.random.default_rng(0)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, (rows, 2)), axis=0))
    arrays = {
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": np.ones((rows, 2)),
    }
    sessions = np.array([8, 30])
    columns = np.array([0, 1])
    window, complete = charts.windows(arrays, columns, sessions, days)
    assert complete.tolist() == [True, True]
    assert np.allclose(window.close[1], close[26:31, 1])
    assert np.isclose(window.average[1, -1], close[26:31, 1].mean())
    assert np.isclose(window.average[1, 0], close[22:27, 1].mean())
    # Session 8 with a five-day window needs sessions 0..8 for every average.
    assert np.isfinite(window.average[0]).all()
    short, complete_short = charts.windows(arrays, columns[:1], np.array([6]), days)
    assert not complete_short[0]  # not enough history for the first day's average
    # Change the future and the image does not move.
    before = charts.render(window, days)
    arrays["close"][31:] *= 2.0
    arrays["high"][31:] *= 2.0
    window_after, _ = charts.windows(arrays, columns, sessions, days)
    assert np.array_equal(before, charts.render(window_after, days))


# The network accepts the paper's image and returns two logits.
def test_network_reads_an_image():
    net = charts.ChartNet(20)
    x = torch.zeros((4, 1, 64, 60))
    assert net(x).shape == (4, 2)
    net5 = charts.ChartNet(5)
    assert net5(torch.zeros((2, 1, 32, 15))).shape == (2, 2)
