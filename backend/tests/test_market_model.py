"""The learned ranker: it finds a planted signal out of sample, and only there.

Trusting the model's number rests on three properties tested here: the
assembled scores exist only on test sessions; the normalizer is fit on the
fold's training sessions alone; and on a panel with a planted, learnable
signal the out-of-sample rank IC through the shared harness is clearly
positive, while on pure noise it is not.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from backend.market.harness import evaluate_scores  # noqa: E402
from backend.market.model import (  # noqa: E402
    Normalizer,
    TrainConfig,
    _eligible,
    build_features,
    session_loss,
    walk_forward,
)
from backend.market.panel import panel_from_histories  # noqa: E402
from backend.market.yahoo import DailyBar, TickerHistory  # noqa: E402


# A history from a return series.
def _history(ticker: str, returns: np.ndarray) -> TickerHistory:
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    first = date(2024, 1, 1)
    bars = tuple(
        DailyBar(
            first + timedelta(days=i),
            p,
            p * (1 + 0.01 * (1 + (i % 3))),
            p * 0.99,
            p,
            p,
            1_000_000 + 1000 * i,
        )
        for i, p in enumerate(prices)
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# A panel where the next 5-session residual return is partly predictable
# from the last session's own return (a planted continuation), or not.
def _panel(n: int = 30, t: int = 320, planted: bool = True, seed: int = 3):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.01, size=(t, n))
    returns = noise.copy()
    if planted:
        # A shock on day s continues over days s+1..s+5 at a quarter strength.
        for s in range(t - 6):
            returns[s + 1 : s + 6] += 0.25 * noise[s] / 5
    histories = {f"N{i:03d}": _history(f"N{i:03d}", returns[:, i]) for i in range(n)}
    histories["SPY"] = _history("SPY", returns.mean(axis=1))
    themes = {f"N{i:03d}": ("alpha",) if i % 2 else ("beta",) for i in range(n)}
    return panel_from_histories(histories, "SPY", themes)


_CONFIG = TrainConfig(
    window_size=5,
    horizon=5,
    momentum_length=30,
    momentum_skip=5,
    lookback=10,
    train_size=120,
    test_size=40,
    embargo=2,
    hidden=32,
    epochs=6,
    sessions_per_batch=4,
    patience=6,
    seed=1,
)


# Scores exist only on the folds' test sessions, and every eligible cell
# on those sessions is scored.
def test_scores_cover_exactly_the_test_ranges():
    panel = _panel(t=260, planted=False)
    result = walk_forward(panel, _CONFIG)
    scored_rows = np.flatnonzero(np.isfinite(result.scores).any(axis=1))
    expected = sorted({t for f in result.folds for t in f.test})
    assert scored_rows.tolist() == expected
    assert len(result.folds) >= 2
    for fold in result.folds:
        assert fold.train.stop + _CONFIG.horizon + _CONFIG.embargo == fold.test.start


# The normalizer sees only the training range: its statistics do not
# change when the test range is altered.
def test_normalizer_is_fit_on_training_sessions_only():
    panel = _panel(t=200, planted=False)
    features = build_features(
        panel, horizon=5, momentum_length=30, momentum_skip=5, lookback=10
    )
    eligible = _eligible(features, window_size=5, need_label=True)
    first = Normalizer.fit(features, range(10, 100), eligible)
    features.channels[120:] *= 50.0  # corrupt the future
    second = Normalizer.fit(features, range(10, 100), eligible)
    assert np.allclose(first.channel_mean, second.channel_mean)
    assert np.allclose(first.channel_std, second.channel_std)


# The session loss is minimal when scores order the labels perfectly and
# finite when scores are constant.
def test_session_loss_extremes():
    y = torch.tensor([0.1, -0.2, 0.3, 0.0, -0.1])
    assert session_loss(y.clone(), y).item() == pytest.approx(-1.0, abs=1e-5)
    assert session_loss(-y, y).item() == pytest.approx(1.0, abs=1e-5)
    assert torch.isfinite(session_loss(torch.zeros(5), y))


# A planted continuation is learned: out-of-sample rank IC through the
# shared harness is clearly positive, and the same run on noise is not.
def test_ranker_finds_a_planted_signal_out_of_sample():
    planted = walk_forward(_panel(planted=True), _CONFIG)
    report = evaluate_scores(
        planted.scores, _panel(planted=True), _CONFIG.horizon, cost_bps=0, min_names=10
    )
    assert report.count >= 20
    assert report.mean_ic > 0.08, report.mean_ic
    assert report.ic_tstat > 2.5, report.ic_tstat

    noise = walk_forward(_panel(planted=False), _CONFIG)
    noise_report = evaluate_scores(
        noise.scores, _panel(planted=False), _CONFIG.horizon, cost_bps=0, min_names=10
    )
    assert abs(noise_report.mean_ic) < 0.08, noise_report.mean_ic


# The cross-sectional encoder scores a session as a set: permuting the
# names permutes the scores and changes nothing else, and removing a name
# changes the others' scores (it really attends across the session).
def test_xsect_encoder_is_permutation_equivariant_and_cross_sectional():
    from backend.market.model import BASELINE_FEATURES, Ranker
    from backend.market.windows import CHANNELS

    torch.manual_seed(0)
    model = Ranker(
        CHANNELS + len(BASELINE_FEATURES), 3 * CHANNELS, 5, "xsect", 32, 0.0
    ).eval()
    x = torch.randn(12, 5, CHANNELS + len(BASELINE_FEATURES))
    with torch.no_grad():
        scores = model(x)
        perm = torch.randperm(12)
        permuted = model(x[perm])
        fewer = model(x[:6])
    assert torch.allclose(permuted, scores[perm], atol=1e-5)
    assert not torch.allclose(fewer, scores[:6], atol=1e-4)


# The MASTER-style encoder is gated by the market vector: a different
# market state changes the scores, and the encoder trains end to end.
def test_master_encoder_uses_market_state_and_runs():
    from backend.market.model import BASELINE_FEATURES, Ranker
    from backend.market.windows import CHANNELS

    torch.manual_seed(0)
    width = CHANNELS + len(BASELINE_FEATURES)
    model = Ranker(width, 3 * CHANNELS, 5, "master", 32, 0.0).eval()
    x = torch.randn(9, 5, width)
    with torch.no_grad():
        calm = model(x, torch.zeros(3 * CHANNELS))
        stressed = model(x, torch.ones(3 * CHANNELS) * 2.0)
    assert not torch.allclose(calm, stressed, atol=1e-4)
    config = replace(
        _CONFIG, encoder="master", epochs=2, features="alpha", label="rank"
    )
    result = walk_forward(_panel(t=300, planted=False), config)
    assert np.isfinite(result.scores).any()


# LightGBM runs the same folds and scores only the test ranges.
def test_lgbm_runs_on_the_same_folds():
    pytest.importorskip("lightgbm")
    config = replace(_CONFIG, encoder="lgbm", features="alpha", label="rank")
    panel = _panel(t=300, planted=False)
    result = walk_forward(panel, config)
    scored_rows = np.flatnonzero(np.isfinite(result.scores).any(axis=1))
    expected = sorted({t for f in result.folds for t in f.test})
    assert scored_rows.tolist() == expected


# Seed ensembling averages standardised scores and keeps the test coverage.
def test_seed_ensemble_covers_test_ranges():
    config = replace(_CONFIG, seeds=2, epochs=2)
    result = walk_forward(_panel(t=260, planted=False), config)
    scored_rows = np.flatnonzero(np.isfinite(result.scores).any(axis=1))
    expected = sorted({t for f in result.folds for t in f.test})
    assert scored_rows.tolist() == expected


# Rank labels are centred percentile ranks of the residual return.
def test_rank_labels_are_centred_ranks():
    panel = _panel(t=200, planted=False)
    features = build_features(
        panel, horizon=5, momentum_length=30, momentum_skip=5, lookback=10, label="rank"
    )
    row = features.labels[100]
    known = np.isfinite(row)
    assert known.sum() >= 20
    assert abs(row[known].max() - 0.5) < 1e-6
    assert abs(row[known].min() + 0.5) < 1e-6


# The cross-sectional encoder trains end to end on the same folds.
def test_xsect_encoder_runs():
    config = replace(_CONFIG, encoder="xsect", epochs=2)
    result = walk_forward(_panel(t=260, planted=False), config)
    assert np.isfinite(result.scores).any()


# The GRU encoder runs end to end on the same folds.
def test_gru_encoder_runs():
    config = replace(_CONFIG, encoder="gru", epochs=2)
    result = walk_forward(_panel(t=260, planted=False), config)
    assert np.isfinite(result.scores).any()
