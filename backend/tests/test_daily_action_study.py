"""Cash benchmarks, strict metrics, causal regimes and fixed daily-action floors."""

from copy import deepcopy

import numpy as np
import pytest

from backend.market import daily_action_study as study
from backend.market.research_journal_replay import verify_archive
from backend.tests.test_benchmark_boundary import _history, _sessions, _Store


# Replay actual index cash, fees and holdings and retain exactly one initial purchase.
@pytest.mark.parametrize("cost", [0.0, 10.0, 25.0])
def test_index_account_is_verified_buy_and_hold(tmp_path, cost):
    dates = _sessions(30)
    close = np.linspace(100, 160, 30)
    opens = close * 0.98
    store = _Store({"QQQ": _history("QQQ", dates, close, open_=opens)})
    result, journal = study.index_account(store, "QQQ", dates, cost)
    journal.archive(tmp_path / "index")
    proof = verify_archive(tmp_path / "index")
    assert proof["ok"], proof["errors"]
    assert result.equity[-1] == pytest.approx(close[-1] / opens[1] / (1 + cost / 1e4))
    fills = [e for e in journal.snapshot()["events"] if e["type"] == "fill_batch"]
    assert len(fills) == 1
    assert fills[0]["fee_total"] == pytest.approx(cost / 1e4 / (1 + cost / 1e4))


# Missing source observations cannot silently become an apparently stable benchmark.
def test_index_missing_session_fails():
    dates = _sessions(10)
    store = _Store({"SPY": _history("SPY", dates, drop={4})})
    with pytest.raises(ValueError, match="no adjusted price"):
        study.index_account(store, "SPY", dates, 25)


# A later store refresh cannot change any benchmark after the model begins fitting.
def test_indexes_are_frozen_before_fitting():
    dates = _sessions(10)
    store = _Store({symbol: _history(symbol, dates) for symbol in ("SPY", "QQQ")})
    frozen = study.FrozenIndexes(store)
    expected = study.index_prices(frozen, "QQQ", dates)[1]
    store.histories["QQQ"] = _history("QQQ", dates, adj=np.full(10, 20.0))
    np.testing.assert_array_equal(study.index_prices(frozen, "QQQ", dates)[1], expected)


# Include the opening endowment in drawdown and reject gaps within evaluated returns.
def test_metrics_starting_loss_and_gap():
    stats = study.metrics([-0.1, 0.05])
    assert stats["drawdown"] == pytest.approx(-0.1)
    assert stats["total_return"] == pytest.approx(-0.055)
    with pytest.raises(ValueError, match="finite"):
        study.metrics([0.1, np.nan, -0.1])


# Today's eventual price cannot change the regime used for today's account return.
def test_regimes_use_previous_close_only():
    prices = 100 * np.exp(np.arange(300) * 0.001)
    original = study.regime_labels(prices)
    revised = prices.copy()
    revised[250:] *= 0.3
    changed = study.regime_labels(revised)
    np.testing.assert_array_equal(original[:251], changed[:251])
    assert original[251] != changed[251]


# Do not label a discontinuous regime return selection as a funded CAGR.
def test_regime_summary_has_contributions_not_cagr():
    dates = _sessions(5)
    daily = np.array([np.nan, 0.01, -0.02, 0.03, -0.04])
    regimes = np.array(["a", "a", "b", "a", "b"])
    result = study.account_summary(dates, daily, regimes)
    assert "cagr" not in result["regimes"]["a"]
    assert sum(
        row["log_growth_contribution"] for row in result["regimes"].values()
    ) == pytest.approx(np.log1p(daily[1:]).sum())


# Create the minimum full four-offset evidence required by the registered screen.
def passing_runs():
    runs = []
    for offset in study.OFFSETS:
        runs.append(
            {
                "cost_bps": 25.0,
                "offset": offset,
                "accounts": {
                    name: {
                        "all": {
                            "cagr": 0.12 if name in ("ridge", "tree") else 0.1,
                            "drawdown": -0.2,
                        }
                    }
                    for name in ("ridge", "tree", "original_v4", "daily_v4")
                },
                "paired": {
                    name: {
                        control: {
                            "mean_daily_bp": 2.0,
                            "hac_t": 2.1,
                            "recent_mean_daily_bp": 0.1,
                        }
                        for control in ("original_v4", "daily_v4")
                    }
                    for name in ("ridge", "tree")
                },
            }
        )
    return runs


# A nominal pass allows only further research, and either comparator can veto it.
def test_floors_require_both_controls_and_never_promote():
    runs = passing_runs()
    assert study.verdict(runs)["ridge"]["status"] == "ADVANCE_RESEARCH_ONLY"
    runs[0]["paired"]["ridge"]["daily_v4"]["hac_t"] = 1.99
    assert study.verdict(runs)["ridge"]["status"] == "DO_NOT_PROMOTE"
    failed = deepcopy(passing_runs())
    failed[0]["accounts"]["tree"]["all"]["drawdown"] = -0.24
    assert study.verdict(failed)["tree"]["status"] == "DO_NOT_PROMOTE"


# Strict pairing never drops inconvenient sessions or substitutes a recent-window gain.
def test_paired_missing_returns_fail():
    dates = _sessions(4)
    with pytest.raises(ValueError, match="unavailable"):
        study.paired(dates, [np.nan, 0.1, np.nan, 0.2], [np.nan, 0.1, 0.2, 0.3])
