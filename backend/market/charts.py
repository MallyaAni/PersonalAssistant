"""Price charts as images, and the network that reads them.

Jiang, Kelly and Xiu, "(Re-)Imag(in)ing Price Trends", Journal of
Finance 2023: draw each stock's last 5, 20 or 60 sessions as the chart a
trader would look at - OHLC bars, a moving-average line, volume bars
underneath - and train a convolutional network to say whether the next
return is positive. The network learns the shapes that matter, support
and consolidation among them, instead of being handed a formula for
them. Out of sample on the US cross-section it beat momentum, short-term
reversal and moving-average rules, and the twenty-day image predicting
the twenty-day return was the strongest.

This is that image and that network, kept to the paper's specification
so the result here can be read against theirs:

  days    width   height   price rows   volume rows
   5       15       32         25           6
  20       60       64         51          12
  60      180       96         76          19

Three pixels per day: the open as a tick on the left, the high-low bar in
the middle, the close as a tick on the right; prices scaled so the
window's highest high sits on the top row and its lowest low on the
bottom price row; the moving average over the window's length drawn
through the middle columns; volume as a bar from the bottom scaled to
the window's largest. Black on white becomes 1 on 0.

The network is the paper's: blocks of a 5x3 convolution with vertical
dilation 2, batch normalisation, leaky ReLU and a 2x1 max-pool; 64, 128
and 256 filters for the twenty-day image; a fully connected layer with
50% dropout to two classes; Xavier initialisation; Adam at 1e-5; early
stopping on validation loss.
"""

from dataclasses import dataclass

import numpy as np
from torch import nn

SPEC = {
    5: {"height": 32, "price": 25, "volume": 6, "filters": (64, 128)},
    20: {"height": 64, "price": 51, "volume": 12, "filters": (64, 128, 256)},
    60: {"height": 96, "price": 76, "volume": 19, "filters": (64, 128, 256, 512)},
}
PIXELS_PER_DAY = 3


@dataclass(frozen=True)
class Window:
    """The arrays a batch of images is drawn from: (batch, days) each."""

    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    average: np.ndarray  # the moving average at each day


# Rows for prices: the window's highest sits on row 0, its lowest on the
# last price row. NaN stays NaN.
def _price_rows(values: np.ndarray, top: np.ndarray, bottom: np.ndarray, rows: int):
    with np.errstate(all="ignore"):
        span = np.where(top > bottom, top - bottom, np.nan)
        scaled = (top[:, None] - values) / span[:, None] * (rows - 1)
    return scaled


# Draw a batch of windows as images, (batch, height, width) of 0/1.
def render(window: Window, days: int) -> np.ndarray:
    """Return the images of `window`, one per row, in the paper's layout."""
    spec = SPEC[days]
    batch = window.close.shape[0]
    height, price_rows, volume_rows = spec["height"], spec["price"], spec["volume"]
    width = PIXELS_PER_DAY * days
    image = np.zeros((batch, height, width), dtype=np.uint8)
    with np.errstate(all="ignore"):
        top = np.nanmax(np.concatenate([window.high, window.average], axis=1), axis=1)
        bottom = np.nanmin(np.concatenate([window.low, window.average], axis=1), axis=1)
        vmax = np.nanmax(window.volume, axis=1)
    rows = {
        name: _price_rows(getattr(window, name), top, bottom, price_rows)
        for name in ("open", "high", "low", "close", "average")
    }
    grid = np.arange(price_rows)[None, :]
    volume_base = height - 1
    for d in range(days):
        left, mid, right = (
            PIXELS_PER_DAY * d,
            PIXELS_PER_DAY * d + 1,
            PIXELS_PER_DAY * d + 2,
        )
        _tick(image, rows["open"][:, d], left)
        _tick(image, rows["close"][:, d], right)
        hi, lo = rows["high"][:, d], rows["low"][:, d]
        ok = np.isfinite(hi) & np.isfinite(lo)
        if ok.any():
            span = (grid >= np.rint(hi)[:, None]) & (grid <= np.rint(lo)[:, None])
            image[
                np.flatnonzero(ok)[:, None], np.arange(price_rows)[None, :], mid
            ] |= span[ok].astype(np.uint8)
        for column in (left, mid, right):
            _tick(image, rows["average"][:, d], column)
        if d + 1 < days:
            _connect(image, rows["average"][:, d], rows["average"][:, d + 1], right)
        with np.errstate(all="ignore"):
            bars = np.rint(window.volume[:, d] / vmax * (volume_rows - 1))
        okv = np.isfinite(bars) & (bars >= 0)
        if okv.any():
            depth = np.arange(volume_rows)[None, :]  # 0 at the bottom row
            filled = depth <= bars[okv][:, None]
            rows_from_top = volume_base - depth
            image[np.flatnonzero(okv)[:, None], rows_from_top, mid] |= filled.astype(
                np.uint8
            )
    return image


# One pixel at a price row in a column, where the row is known.
def _tick(image: np.ndarray, row: np.ndarray, column: int) -> None:
    ok = np.isfinite(row)
    if ok.any():
        r = np.rint(row[ok]).astype(int)
        image[np.flatnonzero(ok), r, column] = 1


# Fill the column between two consecutive average rows so the line joins.
def _connect(image: np.ndarray, row_a: np.ndarray, row_b: np.ndarray, column: int):
    ok = np.isfinite(row_a) & np.isfinite(row_b)
    if not ok.any():
        return
    a, b = np.rint(row_a[ok])[:, None], np.rint(row_b[ok])[:, None]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    grid = np.arange(image.shape[1])[None, :]
    span = (grid >= lo) & (grid <= hi)
    image[np.flatnonzero(ok)[:, None], grid, column] |= span.astype(np.uint8)


# The window ending at each requested session for one name, from the
# panel's arrays: days `t - days + 1 .. t`, and the moving average over
# the same length at every day of the window (needs 2 * days - 1 sessions).
def windows(panel_arrays: dict, columns: np.ndarray, sessions: np.ndarray, days: int):
    """Return the Window for (session, column) pairs, and which are complete."""
    offsets = np.arange(-days + 1, 1)
    idx = sessions[:, None] + offsets[None, :]
    take = lambda key: panel_arrays[key][idx, columns[:, None]]  # noqa: E731
    close = panel_arrays["close"]
    cum = np.cumsum(np.where(np.isfinite(close), close, 0.0), axis=0)
    count = np.cumsum(np.isfinite(close), axis=0)
    start = idx - days + 1
    valid = start >= 0
    hi_c = cum[np.clip(idx, 0, None), columns[:, None]]
    hi_n = count[np.clip(idx, 0, None), columns[:, None]]
    # The sum before the window starts: nothing when the window starts at 0.
    before = np.clip(start - 1, 0, None)
    lo_c = np.where(start >= 1, cum[before, columns[:, None]], 0.0)
    lo_n = np.where(start >= 1, count[before, columns[:, None]], 0)
    with np.errstate(all="ignore"):
        average = np.where(
            valid & (hi_n - lo_n == days),
            (hi_c - lo_c) / np.maximum(hi_n - lo_n, 1),
            np.nan,
        )
    window = Window(
        take("open"),
        take("high"),
        take("low"),
        close[idx, columns[:, None]],
        take("volume"),
        average,
    )
    complete = (
        np.isfinite(window.close).all(axis=1)
        & np.isfinite(window.high).all(axis=1)
        & np.isfinite(window.low).all(axis=1)
        & (sessions >= 2 * days - 2)
    )
    return window, complete


class ChartNet(nn.Module):
    """The paper's CNN for one image size."""

    def __init__(self, days: int) -> None:
        super().__init__()
        spec = SPEC[days]
        blocks = []
        channels = 1
        height, width = spec["height"], PIXELS_PER_DAY * days
        for filters in spec["filters"]:
            blocks += [
                nn.Conv2d(
                    channels,
                    filters,
                    kernel_size=(5, 3),
                    dilation=(2, 1),
                    padding=(4, 1),
                ),
                nn.BatchNorm2d(filters),
                nn.LeakyReLU(0.01),
                nn.MaxPool2d((2, 1)),
            ]
            channels = filters
            height //= 2
        self.blocks = nn.Sequential(*blocks)
        self.head = nn.Sequential(
            nn.Dropout(0.5), nn.Linear(channels * height * width, 2)
        )
        for module in self.modules():
            if isinstance(module, nn.Conv2d | nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                nn.init.zeros_(module.bias)

    def forward(self, x):
        """Return the two-class logits for a batch of (1, H, W) images."""
        return self.head(self.blocks(x).flatten(1))
