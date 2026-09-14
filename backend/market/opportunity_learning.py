"""Research inputs for price-sensitive forecasts; no production model loading."""

from dataclasses import replace

import numpy as np

from backend.market import growth_pilot as gp
from backend.market.levels_pit import trailing_levels

FUNDAMENTAL_NAMES = (
    "log_sales_yield",
    "earnings_yield",
    "book_yield",
    "cash_flow_yield",
    "revenue_growth",
    "net_margin",
    "gross_margin",
    "cash_flow_margin",
    "cash_to_cap",
    "debt_to_cap",
)


# Convert dated levels into price-sensitive ratios without treating losses as profits.
def ratios(prices, levels):
    with np.errstate(all="ignore"):
        cap = prices * levels["shares"]
        cap = np.where(cap > 0, cap, np.nan)
        revenue = np.where(levels["revenue"] > 0, levels["revenue"], np.nan)
        return np.stack(
            (
                np.log(revenue / cap),
                levels["earnings"] / cap,
                levels["equity"] / cap,
                levels["operating_cash_flow"] / cap,
                levels["revenue_growth"],
                levels["earnings"] / revenue,
                levels["gross_profit"] / revenue,
                levels["operating_cash_flow"] / revenue,
                levels["cash"] / cap,
                levels["debt"] / cap,
            ),
            axis=-1,
        )


# Delay date-only filings a day to avoid after-close leaks.
def features(panel, store, asof):
    data = gp.dataset(panel)
    dated = replace(panel, dates=panel.dates - np.timedelta64(1, "D"))
    levels = trailing_levels(store, dated, asof)
    fundamentals = ratios(panel.close, levels)
    # Keep the stock universe; missing financials get explicit indicators.
    values = np.concatenate((data.features, fundamentals), axis=-1)
    names = (*gp.FEATURE_NAMES, *FUNDAMENTAL_NAMES)
    return data, values, names


# Fit imputation and scaling on training examples and retain missingness.
def normalize(values, training, fitted=None):
    if fitted is None:
        known = np.where(np.isfinite(training), training, np.nan)
        medians = np.array(
            [
                np.median(col[np.isfinite(col)]) if np.isfinite(col).any() else 0
                for col in known.T
            ]
        )
        clean = np.where(np.isfinite(training), training, medians)
        scale = np.maximum(np.std(clean, axis=0), 1e-5)
    else:
        medians, scale = fitted
    missing = ~np.isfinite(values)
    clean = np.where(missing, medians, values)
    normalized = np.clip((clean - medians) / scale, -5, 5)
    return np.concatenate((normalized, missing.astype(float)), axis=-1).astype(
        np.float32
    ), (medians, scale)


# Match a twenty-session holding from next-close entry to the next rebalance execution.
def labels(prices, stride=20):
    result = np.full(prices.shape, np.nan)
    with np.errstate(all="ignore"):
        result[: -(stride + 1)] = 100 * np.log(prices[stride + 1 :] / prices[1:-stride])
    return result


# Compare return forecasts through one funded, capped portfolio and identical execution.
def chooser(data, predictions):
    # Buy only positive forecasts, leaving unallocated capital in cash.
    def choose(t, holdings, cash):
        return gp.basket(
            predictions[t], data.eligible[t] & (predictions[t] > 0)
        ), "forecast_top10"

    return choose
