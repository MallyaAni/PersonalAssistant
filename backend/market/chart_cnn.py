"""A network that reads charts: the Jiang, Kelly and Xiu (2023) CNN, on this panel.

The one credible published case of a neural network learning technical
analysis is "(Re-)Imag(in)ing Price Trends" (Journal of Finance, 2023): a
small convolutional network trained on images of 20-day OHLC charts with a
moving average and volume bars, predicting the sign of the next 20-day
return, held an out-of-sample long-short Sharpe near 1.7 equal-weighted on
all US stocks 2001-2019, with the edge concentrated in small illiquid names
and decaying under costs. This module rebuilds that input and that
network so the same claim can be measured on this universe through the
same harness as everything else.

The image: a 64 x 60 binary raster of the last 20 sessions, three pixels
wide per day. The top 51 rows hold the OHLC bar (a vertical line from low
to high, an open tick on the left pixel and a close tick on the right) and
the 20-day moving average line; the bottom 12 rows hold the volume bar,
each scaled to its own window's range, so every image is comparable
whatever the price level. The network: three blocks of (5x3 convolution,
leaky ReLU, 2x1 max-pool) with 64/128/256 channels, a fully connected
head, dropout 0.5, trained with cross-entropy on whether the residual
forward return is above the session's median. Scores are the probability
of "above", standardised per session like every other encoder.

It plugs into the walk-forward as encoder "chart_cnn": the same purged
folds, the same validation tail, the same assembled out-of-sample score
matrix, the same evaluate_scores.
"""

from collections.abc import Callable

import numpy as np
import torch
from torch import nn

from backend.market.panel import Panel

IMAGE_HEIGHT = 64
IMAGE_WIDTH = 60
WINDOW = 20
PRICE_ROWS = 51
VOLUME_ROWS = 12


# Render the (H, W) chart image of one name over the 20 sessions ending at
# t, or None when any price in the window is unknown.
def render_chart(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    moving_average: np.ndarray,
) -> np.ndarray | None:
    """Return a (64, 60) float32 image of 20 sessions of OHLC, MA and volume."""
    if len(closes) != WINDOW or not (
        np.isfinite(opens).all()
        and np.isfinite(highs).all()
        and np.isfinite(lows).all()
        and np.isfinite(closes).all()
    ):
        return None
    image = np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH), dtype=np.float32)
    ma = np.where(np.isfinite(moving_average), moving_average, np.nan)
    top = float(np.nanmax(np.concatenate([highs, ma[np.isfinite(ma)]])))
    bottom = float(np.nanmin(np.concatenate([lows, ma[np.isfinite(ma)]])))
    if top <= bottom:
        return None

    # Price rows: 0 at the top is the highest price.
    def row(price: float) -> int:
        frac = (price - bottom) / (top - bottom)
        return int(round((PRICE_ROWS - 1) * (1.0 - frac)))

    volume_top = float(np.nanmax(volumes)) if np.isfinite(volumes).any() else 0.0
    for day in range(WINDOW):
        x = 3 * day
        r_high, r_low = row(highs[day]), row(lows[day])
        image[min(r_high, r_low) : max(r_high, r_low) + 1, x + 1] = 1.0
        image[row(opens[day]), x] = 1.0
        image[row(closes[day]), x + 2] = 1.0
        if np.isfinite(ma[day]):
            image[row(ma[day]), x : x + 3] = 1.0
        if volume_top > 0 and np.isfinite(volumes[day]):
            height = int(round(VOLUME_ROWS * volumes[day] / volume_top))
            if height > 0:
                image[IMAGE_HEIGHT - height :, x + 1] = 1.0
    return image


# Render every (session, name) image of the panel that can be rendered.
#
# Returns (images, index) where images is (k, 1, 64, 60) float32 and index
# is a (k, 2) array of (session, column); memory is ~15 KB per image, so a
# 500-name, 11-year panel is ~20 GB — callers render per fold instead.
def render_cells(panel: Panel, cells: np.ndarray) -> np.ndarray:
    """Return (k, 1, 64, 60) images for the (session, column) rows in `cells`."""
    close = panel.adj_close
    # The moving average and the bars use raw OHLC scaled by the adjusted
    # ratio, so splits inside a window do not draw a cliff.
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(panel.close > 0, panel.adj_close / panel.close, np.nan)
    opens = panel.open * ratio
    highs = panel.high * ratio
    lows = panel.low * ratio
    ma = np.full_like(close, np.nan)
    cumulative = np.cumsum(np.where(np.isfinite(close), close, 0.0), axis=0)
    counts = np.cumsum(np.isfinite(close), axis=0)
    for t in range(WINDOW - 1, close.shape[0]):
        span = counts[t] - (counts[t - WINDOW] if t >= WINDOW else 0)
        total = cumulative[t] - (cumulative[t - WINDOW] if t >= WINDOW else 0)
        ma[t] = np.where(span == WINDOW, total / WINDOW, np.nan)
    out = np.zeros((len(cells), 1, IMAGE_HEIGHT, IMAGE_WIDTH), dtype=np.float32)
    keep = np.zeros(len(cells), dtype=bool)
    for i, (t, c) in enumerate(cells):
        if t < WINDOW - 1:
            continue
        window = slice(t - WINDOW + 1, t + 1)
        image = render_chart(
            opens[window, c],
            highs[window, c],
            lows[window, c],
            close[window, c],
            panel.volume[window, c],
            ma[window, c],
        )
        if image is not None:
            out[i, 0] = image
            keep[i] = True
    return out, keep


class ChartCNN(nn.Module):
    """The JKX-2023 architecture for 64 x 60 images: three conv blocks and a head."""

    def __init__(self, dropout: float = 0.5) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 64, kernel_size=(5, 3), padding=(2, 1)),
            nn.BatchNorm2d(64),
            nn.LeakyReLU(0.01),
            nn.MaxPool2d((2, 1)),
            nn.Conv2d(64, 128, kernel_size=(5, 3), padding=(2, 1)),
            nn.BatchNorm2d(128),
            nn.LeakyReLU(0.01),
            nn.MaxPool2d((2, 1)),
            nn.Conv2d(128, 256, kernel_size=(5, 3), padding=(2, 1)),
            nn.BatchNorm2d(256),
            nn.LeakyReLU(0.01),
            nn.MaxPool2d((2, 1)),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(dropout),
            nn.Linear(256 * 8 * 60, 2),
        )

    # Logits over (below median, above median).
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Return (batch, 2) logits."""
        return self.head(self.features(x))


# The classification target of each cell: 1 where its label is above the
# median label of its session, so the network learns the cross-section.
def above_median_targets(labels: np.ndarray, cells: np.ndarray) -> np.ndarray:
    """Return 0/1 targets for (session, column) cells against session medians."""
    out = np.zeros(len(cells), dtype=np.int64)
    by_session: dict[int, list[int]] = {}
    for i, (t, _) in enumerate(cells):
        by_session.setdefault(int(t), []).append(i)
    for t, rows in by_session.items():
        values = np.array([labels[t, cells[i, 1]] for i in rows])
        median = np.nanmedian(values)
        for i, v in zip(rows, values, strict=True):
            out[i] = 1 if v > median else 0
    return out


# Train the chart CNN on the labelled cells of a training range and score
# the cells of a test range. Labels: 1 where the residual forward return is
# above the session's median. Returns (scores for test cells, validation
# accuracy, epochs run).
def train_and_score(
    panel: Panel,
    labels: np.ndarray,
    train_cells: np.ndarray,
    validation_cells: np.ndarray,
    test_cells: np.ndarray,
    device: str = "cpu",
    epochs: int = 5,
    batch_size: int = 128,
    learning_rate: float = 1e-4,
    seed: int = 7,
    log: Callable[[str], None] | None = None,
) -> tuple[np.ndarray, float, int]:
    """Fit the CNN on the train cells, early-stop on validation, score the test cells."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    train_images, train_keep = render_cells(panel, train_cells)
    train_images = train_images[train_keep]
    train_y = above_median_targets(labels, train_cells)[train_keep]
    val_images, val_keep = render_cells(panel, validation_cells)
    val_images = val_images[val_keep]
    val_y = above_median_targets(labels, validation_cells)[val_keep]
    model = ChartCNN().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.CrossEntropyLoss()
    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    best_acc = -1.0
    stale = 0
    epochs_run = 0
    for epoch in range(epochs):
        model.train()
        order = rng.permutation(len(train_images))
        for start in range(0, len(order), batch_size):
            idx = order[start : start + batch_size]
            x = torch.from_numpy(train_images[idx]).to(device)
            y = torch.from_numpy(train_y[idx]).to(device)
            optimizer.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            optimizer.step()
        epochs_run = epoch + 1
        acc = (
            _accuracy(model, val_images, val_y, device, batch_size)
            if len(val_images)
            else float("nan")
        )
        if log:
            log(f"    chart_cnn epoch {epoch + 1}: validation accuracy {acc:.4f}")
        if np.isnan(acc) or acc > best_acc:
            if not np.isnan(acc):
                best_acc = acc
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= 2:
                break
    model.load_state_dict(best_state)
    model.eval()
    test_images, test_keep = render_cells(panel, test_cells)
    scores = np.full(len(test_cells), np.nan, dtype=np.float32)
    if test_keep.any():
        probs = _probabilities(model, test_images[test_keep], device, batch_size)
        scores[test_keep] = probs
    return scores, best_acc, epochs_run


# Classification accuracy on a set of images.
def _accuracy(
    model: ChartCNN, images: np.ndarray, y: np.ndarray, device: str, batch_size: int
) -> float:
    probs = _probabilities(model, images, device, batch_size)
    return float(np.mean((probs > 0.5) == (y == 1)))


# P(above median) per image.
def _probabilities(
    model: ChartCNN, images: np.ndarray, device: str, batch_size: int
) -> np.ndarray:
    model.eval()
    out = np.zeros(len(images), dtype=np.float32)
    with torch.no_grad():
        for start in range(0, len(images), batch_size):
            x = torch.from_numpy(images[start : start + batch_size]).to(device)
            out[start : start + batch_size] = (
                torch.softmax(model(x), dim=1)[:, 1].cpu().numpy()
            )
    return out
