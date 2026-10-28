"""The listed-security basis: ADR ratios and non-USD reporting."""

from datetime import UTC, date, datetime

import numpy as np

from backend.market import fundamentals_asof as fa
from backend.market import levels_pit
from backend.market.panel import Panel

STAMP = datetime(2026, 4, 16, tzinfo=UTC)
SHARES = "dei:EntityCommonStockSharesOutstanding"
REVENUE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def version(name, tag, start, end, value, filed):
    return fa.Version(
        name,
        tag,
        None if start is None else date.fromisoformat(start),
        date.fromisoformat(end),
        float(value),
        date.fromisoformat(filed),
        None,
        f"a-{filed}",
        "20-F",
    )


# TSMC's filed facts: 25.93 billion common shares, equity and a quarter of
# revenue in New Taiwan dollars.
def tsm_versions():
    return [
        version("shares", SHARES, None, "2026-04-16", 25.93e9, "2026-04-16"),
        version("equity", "ifrs-full:Equity", None, "2025-12-31", 4.279e12, "2026-04-16"),
        version("revenue", REVENUE, "2026-01-01", "2026-03-31", 1.0e12, "2026-04-16"),
        version(
            "net_income", "us-gaap:NetIncomeLoss", "2026-01-01", "2026-03-31", 4.0e11,
            "2026-04-16",
        ),
    ]  # fmt: skip


class VersionStore:
    """Serve one ticker's versions frame in memory."""

    def __init__(self, ticker, versions=None):
        self.ticker = ticker
        self.versions = tsm_versions() if versions is None else versions

    def read_frame(self, kind, ticker, asof=None):
        if ticker != self.ticker or kind != fa.KIND:
            return None
        return fa.frame(self.versions), {}

    def read(self, ticker, asof=None):
        return None


def make_panel(ticker):
    dates = np.asarray(["2026-04-16", "2026-04-17"], dtype="datetime64[D]")
    close = np.full((len(dates), 2), 436.87)
    return Panel(
        dates, (ticker, "SPY"), close, close, close, close, close,
        np.full_like(close, 1e6), {}, "SPY",
    )  # fmt: skip


# The ADR ratio puts the filed common shares on the listed ADS basis; the
# TWD levels are withheld, while a USD reporter keeps every level.
def test_adr_ratio_and_non_usd_levels():
    for ticker in ("TSM", "SYNTH"):
        out = levels_pit.point_in_time_levels(
            VersionStore(ticker), make_panel(ticker)
        )
        column = 0
        if ticker == "TSM":
            np.testing.assert_allclose(out["shares"][:, column], 25.93e9 / 5.0)
            assert np.isnan(out["equity"][:, column]).all()
            assert np.isnan(out["revenue"][:, column]).all()
            assert np.isnan(out["earnings"][:, column]).all()
        else:
            np.testing.assert_allclose(out["shares"][:, column], 25.93e9)
            np.testing.assert_allclose(out["equity"][:, column], 4.279e12)
            np.testing.assert_allclose(out["revenue"][:, column], 4.0e12)
            np.testing.assert_allclose(out["earnings"][:, column], 1.6e12)


# Revenue growth compares same-currency values, so the currency mask does not
# erase it even though the revenue level itself is withheld.
def test_growth_survives_the_currency_mask():
    versions = tsm_versions() + [
        version("revenue", REVENUE, "2025-01-01", "2025-03-31", 8.0e11, "2025-04-17"),
    ]
    out = levels_pit.point_in_time_levels(
        VersionStore("TSM", versions), make_panel("TSM")
    )
    assert np.isnan(out["revenue"][:, 0]).all()
    np.testing.assert_allclose(out["revenue_growth"][:, 0], 1.0e12 / 8.0e11 - 1.0)
