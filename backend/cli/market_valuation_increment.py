"""Do price-sensitive valuation inputs predict returns beyond momentum and risk?

    python -m backend.cli.market_valuation_increment --run-dir RUN_DIR

One bounded experiment on corrected as-of fundamentals, run once, no
tuning. Everything below was fixed before execution.

Two fixed specifications, ridge alpha 10 each, fitted once on 2018-2023:
  baseline    the eight price and volume features already in the run's
              inputs (returns over 5, 20, 60 and 120 sessions, 20-session
              volatility, distances to the 20 and 60-day averages,
              relative volume): momentum and risk are in.
  +valuation  the same eight plus three as-of valuation inputs: the
              cross-sectional value rank of cheapness against the side,
              the relative valuation magnitude, and the strictly trailing
              history reference (the name's own log price-to-sales
              against the median of its previous three years, today's
              observation excluded), the one input independent of the
              other names' prices today.

Label: the 20-session log return from the next close to the close twenty
sessions later, beta-adjusted against the benchmark with the trailing
120-session beta known at the decision, so market exposure is removed
from the target rather than fitted. Each training row's label endpoint
is checked against the first validation date, and the label is checked
against the price arithmetic of a next-close fill, not assumed.

Normalisation and imputation are fitted on training rows only, for both
models alike. Both models score the same rows: eligible, with a finite
label, finite price features, and a finite history reference, so a name
too young for the reference is out of both. Coverage is reported.

Uncertainty: per session, the rank correlation of each model's
out-of-sample prediction with the label across the eligible names; the
paired difference is a time series, and its mean, Newey-West t at the
label's overlap (lag 20) and effective sample size are reported for
2024, 2025 and partial 2026 separately and for the combined
out-of-sample period. The advancement gate applies to the combined
difference: t above 2 with a positive mean in at least two of the three
periods, 2026 being partial and not a full independent year. Failure is
"insufficient evidence to advance this specification", not proof that
valuation has no value.

Net benefit: both models through the same funded top-ten book (10% cap,
20-session decisions, next-close fills) at 10 and 30 basis points, with
SPY and equal weight at the same execution; net return, drawdown,
turnover, top weight and cash exposure. Point-in-time membership is not
available: the 93 names were chosen in 2026 with hindsight, and every
number carries that selection bias. 2024 to 2026-09-11 has been examined
by earlier work; nothing here is untouched.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import rankdata
from sklearn.linear_model import Ridge

from backend.cli.market_growth_pilot import fixed_chooser
from backend.market import attractiveness as att
from backend.market import baselines, valuation
from backend.market import growth_pilot as gp
from backend.market import opportunity_learning as ol
from backend.market.universe import book_sides, build_universe

ALPHA = 10.0
HORIZON = 20
BETA_LOOKBACK = 120
OVERLAP_LAG = 20
PRICE_FEATURES = 8
PERIODS = (
    ("2024", "2024-01-01", "2025-01-01"),
    ("2025", "2025-01-01", "2026-01-01"),
    ("2026 (partial)", "2026-01-01", "2027-01-01"),
)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    return parser


# Rank correlation across one session's eligible names, NaN below three.
def rank_corr(a: np.ndarray, b: np.ndarray) -> float:
    """Return the Spearman correlation of two vectors, NaN where too few."""
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra = rankdata(a[ok])
    rb = rankdata(b[ok])
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


# Newey-West mean, t and effective sample size of a series.
def hac(series: np.ndarray, lag: int = OVERLAP_LAG) -> dict:
    """Return mean, t (HAC at `lag`), n and the effective n."""
    d = series[np.isfinite(series)]
    n = len(d)
    if n < 10:
        return {
            "mean": float("nan"),
            "t": float("nan"),
            "n": n,
            "n_effective": float("nan"),
        }
    c = d - d.mean()
    var = float(c @ c) / n
    hac_var = var
    for k in range(1, min(lag, n - 1) + 1):
        hac_var += 2.0 * (1.0 - k / (lag + 1)) * float(c[:-k] @ c[k:]) / n
    hac_var = max(hac_var, 1e-12)
    return {
        "mean": float(d.mean()),
        "t": float(d.mean() / np.sqrt(hac_var / n)),
        "n": n,
        "n_effective": float(n * var / hac_var) if var > 0 else float("nan"),
    }


# The beta-adjusted twenty-session forward label from a next-close fill.
def labels(prices: np.ndarray, benchmark: int) -> np.ndarray:
    """Return (T, N) 100 x log return from t+1 close to t+21 close, beta-adjusted."""
    own = ol.labels(prices, stride=HORIZON)
    with np.errstate(all="ignore"):
        daily = np.diff(np.log(prices), axis=0)
    market = daily[:, benchmark]
    beta = np.ones(prices.shape)
    for t in range(BETA_LOOKBACK, prices.shape[0]):
        m = market[t - BETA_LOOKBACK : t]
        x = daily[t - BETA_LOOKBACK : t]
        ok = np.isfinite(x) & np.isfinite(m)[:, None]
        with np.errstate(all="ignore"):
            cov = np.nansum(
                np.where(
                    ok,
                    (x - np.nanmean(np.where(ok, x, np.nan), axis=0))
                    * (m - m.mean())[:, None],
                    0.0,
                ),
                axis=0,
            )
            var = float(((m - m.mean()) ** 2).sum())
        beta[t] = np.clip(cov / var, 0.0, 3.0) if var > 0 else 1.0
    return own - beta * own[:, benchmark][:, None]


def main() -> None:
    """Run the experiment once."""
    args = build_parser().parse_args()
    with np.load(args.run_dir / "inputs.npz", allow_pickle=False) as w:
        raw, dates, prices, eligible = w["raw"], w["dates"], w["prices"], w["eligible"]
    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    tickers = tuple(manifest["tickers"])
    names = tuple(manifest["feature_names"])
    benchmark = tickers.index("SPY")
    sides = book_sides(build_universe())
    side_ids = np.array(
        [("ai", "software").index(sides[t]) if t in sides else -1 for t in tickers]
    )
    # ---- the valuation inputs, all as-of and strictly trailing where they look back
    log_ps = -raw[:, :, names.index("log_sales_yield")]
    groups = np.broadcast_to(side_ids[None, :], log_ps.shape)
    in_book = np.array([t in sides for t in tickers])
    with np.errstate(all="ignore"):
        cheap = -valuation.relative_to_group(
            np.where(in_book[None, :], log_ps, np.nan), groups
        )
    rank = baselines.percentile_rank(np.where(in_book[None, :], cheap, np.nan))
    magnitude = att.magnitude(cheap, np.broadcast_to(in_book[None, :], cheap.shape))
    history = att.trailing_reference(log_ps)
    price_block = raw[:, :, :PRICE_FEATURES]
    with_valuation = np.concatenate(
        (price_block, rank[:, :, None], magnitude[:, :, None], history[:, :, None]),
        axis=-1,
    )
    # ---- label and its endpoints
    y = labels(prices, benchmark)
    data = gp.Dataset(
        dates,
        prices,
        raw[:, :, :PRICE_FEATURES],
        eligible,
        np.zeros((len(dates), 1)),
        tickers,
        benchmark,
    )
    train = gp.split_rows(data, "2018-01-01", "2024-01-01", horizon=HORIZON + 1)[::5]
    oos = gp.split_rows(data, "2024-01-01", "2027-01-01", horizon=1)
    first_val = int(np.searchsorted(dates, np.datetime64("2024-01-01")))
    last_train_endpoint = int(train[-1]) + HORIZON + 1
    assert last_train_endpoint < first_val, "a training label reaches into validation"
    # The label is the price arithmetic of a next-close fill held twenty sessions.
    t0, j0 = int(train[10]), int(np.flatnonzero(np.isfinite(y[train[10]]) & in_book)[0])
    fill, exit_ = prices[t0 + 1, j0], prices[t0 + HORIZON + 1, j0]
    own_check = 100 * np.log(exit_ / fill)
    assert abs(ol.labels(prices, stride=HORIZON)[t0, j0] - own_check) < 1e-9
    # ---- identical rows for both models
    common = (
        eligible
        & in_book[None, :]
        & np.isfinite(y)
        & np.isfinite(price_block).all(axis=-1)
        & np.isfinite(history)
        & np.isfinite(rank)
    )
    train_mask = np.zeros(common.shape, dtype=bool)
    train_mask[train] = common[train]
    oos_mask = np.zeros(common.shape, dtype=bool)
    oos_mask[oos] = common[oos]
    coverage = {
        "train_rows": int(train_mask.sum()),
        "oos_rows": int(oos_mask.sum()),
        "oos_rows_eligible_before_history_requirement": int(
            (eligible & in_book[None, :] & np.isfinite(y))[oos].sum()
        ),
    }
    # ---- fit once each, normalisation on training rows only
    predictions = {}
    for label, values in (("baseline", price_block), ("+valuation", with_valuation)):
        x, _fitted = ol.normalize(values, values[train_mask])
        model = Ridge(alpha=ALPHA).fit(x[train_mask], y[train_mask])
        pred = np.full(y.shape, np.nan)
        pred[common] = model.predict(x[common])
        predictions[label] = pred
        if label == "+valuation":
            coef = dict(
                zip(
                    (
                        *names[:PRICE_FEATURES],
                        "value_rank",
                        "magnitude",
                        "history_reference",
                    ),
                    model.coef_[: values.shape[-1]].tolist(),
                    strict=False,
                )
            )
    # ---- per-session rank correlations, paired differences
    ic = {label: np.full(len(dates), np.nan) for label in predictions}
    for t in oos:
        for label, pred in predictions.items():
            row = np.where(common[t], pred[t], np.nan)
            ic[label][t] = rank_corr(row, np.where(common[t], y[t], np.nan))
    diff = ic["+valuation"] - ic["baseline"]
    periods = {}
    for name, start, stop in PERIODS:
        span = (dates >= np.datetime64(start)) & (dates < np.datetime64(stop))
        periods[name] = {
            "sessions": int(np.isfinite(diff[span]).sum()),
            "baseline_ic": hac(ic["baseline"][span]),
            "valuation_ic": hac(ic["+valuation"][span]),
            "difference": hac(diff[span]),
        }
    combined_span = dates >= np.datetime64("2024-01-01")
    combined = {
        "sessions": int(np.isfinite(diff[combined_span]).sum()),
        "baseline_ic": hac(ic["baseline"][combined_span]),
        "valuation_ic": hac(ic["+valuation"][combined_span]),
        "difference": hac(diff[combined_span]),
    }
    positive_periods = sum(1 for p in periods.values() if p["difference"]["mean"] > 0)
    gate = combined["difference"]["t"] > 2.0 and positive_periods >= 2
    # ---- the funded book on the out-of-sample rows, both costs
    books = {}
    for cost in (0.001, 0.003):
        tag = f"@{round(cost * 10000)}bps"
        for label, pred in predictions.items():
            masked = np.where(common, pred, np.nan)
            books[label + tag] = _book(data, oos, ol.chooser(data, masked), cost)
        books["SPY" + tag] = _book(data, oos, fixed_chooser(data, benchmark=True), cost)
        books["equal" + tag] = _book(data, oos, fixed_chooser(data, 5), cost)
    report = {
        "specification": {
            "alpha": ALPHA,
            "horizon": HORIZON,
            "beta_lookback": BETA_LOOKBACK,
            "overlap_lag": OVERLAP_LAG,
            "train": "2018-01-01..2024-01-01 every fifth session, endpoint purged",
            "last_training_label_endpoint": str(dates[last_train_endpoint]),
            "first_validation_session": str(dates[first_val]),
            "history_reference": (
                f"strictly trailing {att.WINDOW} sessions, "
                f"at least {att.MIN_KNOWN} known, today excluded"
            ),
            "membership": (
                "not point in time; 93 names chosen in 2026; "
                "selection bias applies to every number"
            ),
            "examined": "2024..2026-09-11 examined by earlier work; not untouched",
        },
        "coverage": coverage,
        "coefficients_valuation_model": coef,
        "periods": periods,
        "combined_out_of_sample": combined,
        "gate": {
            "rule": (
                "combined difference t > 2 and mean > 0 in at least "
                "two of three periods (2026 partial)"
            ),
            "passed": bool(gate),
            "reading": (
                "sufficient evidence to advance this specification"
                if gate
                else "insufficient evidence to advance this specification; "
                "not proof that valuation has no value"
            ),
        },
        "books_out_of_sample": books,
    }
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "books_out_of_sample"}, indent=1
        )
    )
    print(json.dumps(report["books_out_of_sample"], indent=1))
    if args.report:
        args.report.write_text(json.dumps(report, indent=1))
        print("report written:", args.report)


# One funded book on the out-of-sample rows: the chooser is wrapped so the
# largest single weight it ever asked for is recorded alongside the result.
def _book(data, rows, chooser, cost: float) -> dict:
    """Return net return, drawdown, volatility, turnover, top weight, cash."""
    top = [0.0]

    def recording(t, holdings, cash):
        target, name = chooser(t, holdings, cash)
        top[0] = max(top[0], float(np.max(target)) if len(target) else 0.0)
        return target, name

    result = gp.evaluate(data, rows, recording, cost, stride=HORIZON)
    decisions = result["decisions"]
    nav = np.asarray(result["nav"], dtype=float)
    daily = np.diff(np.log(nav))
    return {
        "net_return": float(result["metrics"]["total_return"]),
        "drawdown": float(result["metrics"]["drawdown"]),
        "volatility": float(daily.std() * np.sqrt(252)),
        "turnover_total": float(sum(d["turnover"] for d in decisions)),
        "top_weight": top[0],
        "cash_exposure": (
            float(np.mean([d["target_cash"] for d in decisions])) if decisions else 1.0
        ),
        "decisions": len(decisions),
        "first_execution": decisions[0]["execution"] if decisions else None,
        "last_session": result["dates"][-1],
    }


if __name__ == "__main__":
    main()
