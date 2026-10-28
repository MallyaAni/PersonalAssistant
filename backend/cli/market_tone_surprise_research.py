"""Does the change in release tone predict returns? The registered S-only arm.

    python -m backend.cli.market_tone_surprise_research --root data/market \
        --output docs/research/scorecards/tone-surprise/result.json

Implements `docs/research/tone-surprise-preregistration-2026-10-28.md`:
for every name and session, the surprise is the sum over the five release
tone fields of the current release minus the previous one, carried forward
from the reaction session. A name with no release, or with only its first
release, has no view (NaN), not a neutral zero. The score is evaluated with
the desk's own harness against beta-adjusted residual forward returns at
20 and 60 sessions, on the point-in-time book membership, with 2016-2023
the choosing window and 2024-2026 reported only. The placebo shuffles the
signal across names within each session and preserves the missing mask.

Research only: no file the desk serves is written.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk, point_in_time
from backend.market import harness, language, universe
from backend.market.store import MarketStore

HORIZONS = (20, 60)
CHOOSING = (2016, 2023)
REPORTED = (2024, 2026)


# Sum the five tone changes from the previous release, carried to the next one.
def surprise_matrix(panel, records, strict: bool = False) -> np.ndarray:
    """Return (T, N) tone surprise; NaN where a name has no previous release.

    `strict` makes a release first count on the session after its reaction
    date instead of on the reaction date itself; it is the pre-registered
    sensitivity, not a second trial.
    """
    out = np.full((len(panel.dates), len(panel.tickers)), np.nan, dtype=float)
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    for column, ticker in enumerate(panel.tickers):
        rows = sorted(records.get(ticker, ()), key=lambda row: row.reaction_date)
        if len(rows) < 2:
            continue
        starts = np.searchsorted(
            days,
            np.asarray([row.reaction_date for row in rows], dtype="datetime64[D]"),
            side="right" if strict else "left",
        )
        for index in range(1, len(rows)):
            start = int(starts[index])
            if start >= len(days):
                break
            end = int(starts[index + 1]) if index + 1 < len(rows) else len(days)
            end = min(max(end, start), len(days))
            value = sum(
                getattr(rows[index], name) - getattr(rows[index - 1], name)
                for name in language.SCORE_NAMES
            )
            out[start:end, column] = value
    return out


# Mean IC, plain t and Newey-West t over the periods inside a year window.
def period_stats(report, start_year: int, end_year: int, lag: int = 1) -> dict:
    """Return the IC summary for periods whose date falls in [start, end]."""
    ics = np.asarray(
        [
            period.rank_ic
            for period in report.periods
            if start_year <= int(str(period.date)[:4]) <= end_year
            and np.isfinite(period.rank_ic)
        ],
        dtype=float,
    )
    if not len(ics):
        return {"n": 0, "mean_ic": None, "t": None, "t_nw": None, "hit": None}
    mean = float(ics.mean())
    spread = float(np.ptp(ics))
    plain = (
        float(mean / (ics.std(ddof=1) / math.sqrt(len(ics))))
        if len(ics) > 1 and spread > 0
        else None
    )
    return {
        "n": int(len(ics)),
        "mean_ic": mean,
        "t": plain,
        "t_nw": _newey_west_t(ics, lag),
        "hit": float((ics > 0).mean()),
    }


# Newey-West t of the mean, with `lag` periods of overlap.
def _newey_west_t(values: np.ndarray, lag: int) -> float | None:
    """Return the HAC t-statistic of the mean of `values`."""
    if len(values) < 2 or float(np.ptp(values)) == 0:
        return None
    centred = values - values.mean()
    variance = float(centred @ centred) / len(values)
    for k in range(1, min(lag, len(values) - 1) + 1):
        covariance = float(centred[k:] @ centred[:-k]) / len(values)
        variance += 2.0 * (1.0 - k / (lag + 1.0)) * covariance
    if variance <= 0:
        return None
    return float(values.mean() / math.sqrt(variance / len(values)))


# Change future records and the newest past record to prove no look-ahead.
def perturbation_check(panel, records, cutoff: int) -> dict:
    """Return whether the signal ignores future releases and reads the newest.

    Every release after `cutoff` is changed; the matrix up to `cutoff` must be
    identical. The newest release on or before `cutoff` is then changed for
    one name; the matrix from that release on must change.
    """
    from dataclasses import replace

    cutoff_date = panel.dates[cutoff].astype("datetime64[D]").astype(object)
    future = {
        ticker: [
            replace(row, guidance=row.guidance + 1)
            if row.reaction_date > cutoff_date
            else row
            for row in rows
        ]
        for ticker, rows in records.items()
    }
    baseline = surprise_matrix(panel, records)
    shifted = surprise_matrix(panel, future)
    same = np.array_equal(
        np.nan_to_num(baseline[: cutoff + 1], nan=99.0),
        np.nan_to_num(shifted[: cutoff + 1], nan=99.0),
    )

    newest: dict[str, list] = {}
    changed_name = None
    for ticker, rows in records.items():
        past = [row for row in rows if row.reaction_date <= cutoff_date]
        if not past:
            continue
        newest_row = max(past, key=lambda row: row.reaction_date)
        changed_name = ticker
        newest[ticker] = [
            replace(row, guidance=row.guidance + 1) if row is newest_row else row
            for row in rows
        ]
        break
    changed = surprise_matrix(panel, newest) if newest else baseline
    moved = not np.array_equal(
        np.nan_to_num(baseline, nan=99.0), np.nan_to_num(changed, nan=99.0)
    )
    return {
        "future_identical": bool(same),
        "newest_changes": bool(moved),
        "name": changed_name,
    }


# Shuffle the signal across names within each session, preserving the mask.
def placebo_ceiling(scores, panel, horizon: int, draws: int, seed: int) -> dict:
    """Return the 95th percentile and mean of the shuffled-signal ICs."""
    rng = np.random.default_rng(seed)
    finite = np.isfinite(scores)
    means: list[float] = []
    for _ in range(draws):
        shuffled = scores.copy()
        for session in range(len(panel.dates)):
            columns = np.flatnonzero(finite[session])
            if len(columns) > 1:
                shuffled[session, columns] = scores[session, rng.permutation(columns)]
        report = harness.evaluate_scores(
            shuffled, panel, horizon, beta_adjusted=True, min_names=20
        )
        stats = period_stats(report, *CHOOSING)
        if stats["mean_ic"] is not None:
            means.append(stats["mean_ic"])
    if not means:
        return {"draws": 0, "mean_ic": None, "p95": None}
    return {
        "draws": len(means),
        "mean_ic": float(np.mean(means)),
        "p95": float(np.percentile(means, 95)),
    }


# Run the registered arm and return the payload written beside the note.
def study(store: MarketStore, membership: Path, draws: int, seed: int) -> dict:
    """Return the S-only result for the preregistered gate."""
    report = desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))
    panel = report.panel
    mask = point_in_time.eligibility(panel.dates, tuple(panel.tickers), membership)
    records = language.stored_records(store, panel.tickers, None)
    surprise = surprise_matrix(panel, records)

    # Only point-in-time members are ranked; indices are not candidates.
    scores = np.where(mask, surprise, np.nan)
    for name in universe.MARKET_INDICES:
        if name in panel.tickers:
            scores[:, panel.index(name)] = np.nan

    eligible = mask.copy()
    for name in universe.MARKET_INDICES:
        if name in panel.tickers:
            eligible[:, panel.index(name)] = False
    coverage = float((np.isfinite(scores) & eligible).sum())
    coverage = coverage / max(1.0, float(eligible.sum()))

    strict_scores = np.where(mask, surprise_matrix(panel, records, strict=True), np.nan)
    for name in universe.MARKET_INDICES:
        if name in panel.tickers:
            strict_scores[:, panel.index(name)] = np.nan

    out: dict = {
        "arm": "S-only",
        "signal": "sum of five tone changes from the previous release",
        "coverage": coverage,
        "releases": int(sum(len(rows) for rows in records.values())),
        "perturbation": perturbation_check(panel, records, int(len(panel.dates) * 0.6)),
        "by_horizon": {},
        "strict": {},
        "placebo": {},
        "null": {},
        "caveats": [
            "The release reader is a modern model reading historical text.",
            "The store holds bars only for today's names; the book membership "
            "is point in time but the universe is still survivor-biased.",
            "A name's first release has no previous release and no view.",
        ],
    }
    for horizon in HORIZONS:
        harness_report = harness.evaluate_scores(
            scores, panel, horizon, beta_adjusted=True, min_names=20
        )
        out["by_horizon"][str(horizon)] = {
            "choosing": period_stats(harness_report, *CHOOSING),
            "reported": period_stats(harness_report, *REPORTED),
        }
        strict_report = harness.evaluate_scores(
            strict_scores, panel, horizon, beta_adjusted=True, min_names=20
        )
        out["strict"][str(horizon)] = {
            "choosing": period_stats(strict_report, *CHOOSING),
            "reported": period_stats(strict_report, *REPORTED),
        }
        out["placebo"][str(horizon)] = placebo_ceiling(
            scores, panel, horizon, draws, seed
        )

    # A zero signal is constant and must produce no defined IC, not a fake one.
    zeros = np.where(np.isfinite(scores), 0.0, np.nan)
    zero_report = harness.evaluate_scores(
        zeros, panel, 20, beta_adjusted=True, min_names=20
    )
    out["null"] = period_stats(zero_report, *CHOOSING)
    return out


# CLI entry point.
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--membership", default=str(universe.MEMBERSHIP_HISTORY_PATH))
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261028)
    args = parser.parse_args(argv)

    store = MarketStore(Path(args.root))
    result = study(store, Path(args.membership), args.draws, args.seed)
    result["inputs"] = {
        "root": str(args.root),
        "membership": str(args.membership),
        "draws": args.draws,
        "seed": args.seed,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(result, indent=1, sort_keys=True, allow_nan=False)
    )
    for horizon in HORIZONS:
        choosing = result["by_horizon"][str(horizon)]["choosing"]
        placebo = result["placebo"][str(horizon)]
        print(
            f"{horizon} sessions: IC {choosing['mean_ic']} "
            f"(t {choosing['t']}, NW {choosing['t_nw']}, n {choosing['n']}); "
            f"placebo p95 {placebo['p95']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
