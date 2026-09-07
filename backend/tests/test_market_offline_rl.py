"""Offline RL over the desk's history.

What has to hold: every logged book around the rule keeps the rule's
gross and never goes short; the advantage of a logged book is measured
against the other books on its own session; the overlap-aware t equals
the naive one when nothing overlaps and is smaller when rewards are
autocorrelated; and a learned book put through the desk's caps respects
them.
"""

import numpy as np
import torch

from backend.cli import market_allocation_rl as alloc
from backend.cli import market_offline_rl as off


# The family keeps the gross, holds nothing short, and includes the rule
# itself and equal weight on its names first.
def test_family_keeps_the_gross_and_never_shorts():
    rule = np.array([0.15, 0.10, 0.05, 0.0, 0.0, 0.0])
    family = off._family(rule, np.random.default_rng(0), count=12)
    assert len(family) == 14
    assert np.array_equal(family[0], rule)
    assert np.allclose(family[1][:3], 0.10) and np.all(family[1][3:] == 0.0)
    for book in family:
        assert np.isclose(book.sum(), 0.30)
        assert np.all(book >= 0.0)
    # The fourth mode moves some weight onto names the rule left out.
    assert any(book[3:].sum() > 0 for book in family[2:])


# A logged book's advantage is its reward less its own session's mean.
def test_advantage_is_relative_to_the_same_session():
    rewards = torch.tensor([1.0, 3.0, 10.0, 20.0])
    owner = torch.tensor([0, 0, 1, 1])
    adv = off._advantages(rewards.to(off.DEVICE), owner.to(off.DEVICE), 2).cpu()
    raw = torch.tensor([-1.0, 1.0, -5.0, 5.0])
    assert torch.allclose(adv, raw / raw.std())


# With no autocorrelation the Newey-West t is the naive t; with rewards
# that overlap it is smaller.
def test_overlap_aware_t_shrinks_for_autocorrelated_differences():
    rng = np.random.default_rng(1)
    white = rng.normal(0.1, 1.0, 2_000)
    naive = white.mean() / (white.std(ddof=1) / np.sqrt(len(white)))
    assert np.isclose(alloc._hac_t(white, 0), naive, rtol=1e-3)  # ddof aside
    # Twenty-day rolling sums are strongly autocorrelated.
    rolled = np.convolve(white, np.ones(20), mode="valid")
    naive_rolled = rolled.mean() / (rolled.std(ddof=1) / np.sqrt(len(rolled)))
    assert alloc._hac_t(rolled, 19) < 0.5 * naive_rolled


# A learned book put through the desk's caps sits inside the name cap and
# keeps the gross it was given, spending less only when the caps bind.
def test_capped_book_respects_the_name_cap():
    from backend.agents.trading.desk import risk
    from backend.market.panel import Panel

    tickers = ("A", "B", "C", "D", "SPY")
    rows = 3
    panel = Panel(
        dates=np.arange("2026-01-05", "2026-01-08", dtype="datetime64[D]"),
        tickers=tickers,
        open=np.ones((rows, 5)),
        high=np.ones((rows, 5)),
        low=np.ones((rows, 5)),
        close=np.ones((rows, 5)),
        adj_close=np.ones((rows, 5)),
        volume=np.ones((rows, 5)),
        themes={"A": ("ai",), "B": ("ai",), "C": ("software",), "D": ("software",)},
        benchmark="SPY",
    )
    problem = alloc.Problem(
        simple=np.zeros((rows, 4)),
        states=np.zeros((rows, 4, 5)),
        regime=np.zeros((rows, 3)),
        rule=np.zeros((rows, 4)),
        dates=panel.dates,
        cols=np.array([0, 1, 2, 3]),
        panel=panel,
    )
    concentrated = np.array([0.40, 0.05, 0.03, 0.02])
    capped = off._capped(problem, concentrated)
    assert capped.max() <= risk.BOOK_CONFIG.name_cap + 1e-9
    assert capped.sum() <= concentrated.sum() + 1e-9
    assert np.all(capped >= 0.0)
    largest, effective = off._concentration(concentrated)
    assert largest == 0.40
    assert 1.0 < effective < 4.0
