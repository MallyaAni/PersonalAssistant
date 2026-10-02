"""Export the frozen October-1 research protocol without fetching market data."""

import argparse
import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from backend.agents.trading.desk import grading, point_in_time
from backend.market import calendar, universe
from backend.market.store import MarketStore

CUTOFF = date(2026, 9, 30)
COHORT = (
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "AMZN", "META", "GOOGL",
    "TSLA", "AAOI", "SPY", "QQQ",
)


# Bind an artifact to its exact source bytes rather than a dataframe description.
def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Extend a known calendar with reviewed future dates, never future prices.
def future_sessions():
    years, exchange = calendar.reviewed_sessions()
    day, result = CUTOFF + timedelta(days=1), []
    while day <= date(2026, 10, 16):
        if day.year not in years:
            raise ValueError("Calendar year is not reviewed")
        if np.is_busday(np.datetime64(day, "D"), busdaycal=exchange):
            result.append(str(day))
        day += timedelta(days=1)
    return result


# Read stable market vintages while retaining original publication metadata.
def source_inputs(root):
    store = MarketStore(root)
    signals = sorted((root / "history").glob("*.json"))
    symbols = sorted({p.stem for p in signals} | set(COHORT))
    histories, hashes, origins, grades = {}, {}, {}, {}
    for symbol in sorted(set(symbols) | set(COHORT)):
        asof = store.latest_asof(symbol, CUTOFF)
        if asof is None:
            continue
        path = root / "bars" / f"asof={asof}" / f"{symbol}.parquet"
        before = digest(path)
        item = store.read(symbol, CUTOFF)
        if before != digest(path):
            raise RuntimeError("Source changed while reading " + str(path))
        histories[symbol], hashes[str(path)] = item, before
        origins[symbol] = {
            "partition": str(asof), "source_time": item.source_time.isoformat(),
            "source": item.source, "complete_through": str(item.complete_through),
        }
    for path in signals:
        raw = path.read_bytes()
        before = hashlib.sha256(raw).hexdigest()
        grades[path.stem] = json.loads(raw)
        if before != digest(path):
            raise RuntimeError("Signal source changed while reading " + str(path))
        hashes[str(path)] = before
    hashes[str(universe.MEMBERSHIP_HISTORY_PATH)] = digest(
        universe.MEMBERSHIP_HISTORY_PATH
    )
    return symbols, histories, hashes, origins, grades


# Preserve missing prices and unknown grades on one declared source calendar.
def portfolio_arrays(symbols, histories, signal_rows):
    sessions = [
        b.session_date for b in histories["SPY"].bars
        if date(2015, 1, 1) <= b.session_date <= CUTOFF
    ]
    if sessions != sorted(set(sessions)):
        raise ValueError("SPY source calendar must be unique and sorted")
    days = np.array(sessions, dtype="datetime64[D]")
    row_of = {str(day): i for i, day in enumerate(sessions)}
    shape = len(sessions), len(symbols)
    fields = ("open", "high", "low", "close", "adj_close", "volume")
    arrays = {key: np.full(shape, np.nan) for key in fields}
    grades = np.full(shape, -1, dtype=np.int16)
    for j, symbol in enumerate(symbols):
        item = histories.get(symbol)
        for bar in item.bars if item is not None else ():
            i = row_of.get(str(bar.session_date))
            if i is None:
                continue
            for key in fields:
                value = getattr(bar, "adjusted_close" if key == "adj_close" else key)
                if value is not None:
                    arrays[key][i, j] = float(value)
        for row in signal_rows.get(symbol, {}).get("rows", []):
            i = row_of.get(row.get("date"))
            if i is not None and row.get("grade") in grading.ORDINAL:
                grades[i, j] = grading.ORDINAL[row["grade"]]
    eligible = point_in_time.eligibility(days, tuple(symbols))
    eligible[:, [symbols.index("SPY"), symbols.index("QQQ")]] = False
    return days, {"grades": grades, "eligible": eligible, **arrays}


# Apply the daily store's dividend factor consistently without changing volumes.
def forecast_rows(histories):
    rows, ny = [], ZoneInfo("America/New_York")
    for symbol in COHORT:
        item = histories.get(symbol)
        for bar in item.bars if item is not None else ():
            if not date(2025, 1, 1) <= bar.session_date <= CUTOFF:
                continue
            values = (bar.open, bar.high, bar.low, bar.close,
                      bar.adjusted_close, bar.volume)
            if any(v is None or not np.isfinite(v) for v in values) or bar.close <= 0:
                continue
            factor = bar.adjusted_close / bar.close
            rows.append({
                "symbol": symbol, "session": str(bar.session_date),
                "available_at": datetime.combine(
                    bar.session_date, time(16), ny
                ).isoformat(),
                "open": bar.open * factor, "high": bar.high * factor,
                "low": bar.low * factor, "close": bar.adjusted_close,
                "volume": bar.volume,
            })
    return rows


# Create new, hash-bound research artifacts while refusing prior output replacement.
def export(root, output, revision):
    output = Path(output)
    if output.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Research artifacts must be outside the source store")
    output.mkdir(parents=True, exist_ok=False)
    symbols, histories, hashes, origins, signals = source_inputs(Path(root))
    days, arrays = portfolio_arrays(symbols, histories, signals)
    np.savez_compressed(output / "portfolio.npz", dates=days,
                        symbols=np.array(symbols), **arrays)
    limitations = [
        "Historical grades are current-vintage reconstructions, not original advice.",
        "Dated membership is research eligibility, not a complete delisted universe.",
        "Later vendor vintages do not attest original historical availability.",
    ]
    provenance = {
        "price_basis": "close-ratio-adjusted",
        "eligibility_mode": "recomputed-current-vintage",
        "source_hashes": hashes,
        "snapshot_sha256": digest(output / "portfolio.npz"),
        "source_cutoff": str(CUTOFF), "source_revision": revision,
        "grade_sources": {
            s: {"asof": x.get("asof"), "policy": x.get("policy")}
            for s, x in signals.items()
        },
        "original_vendor_metadata": origins, "limitations": limitations,
    }
    (output / "portfolio.json").write_text(
        json.dumps(provenance, indent=2, allow_nan=False) + "\n"
    )
    forecast = {
        "price_basis": "adjusted_ohlcv", "volume_basis": "provider_reported",
        "availability_mode": "session_close_assumed",
        "data_mode": "reconstructed_snapshot", "source_revision": revision,
        "source_cutoff": str(CUTOFF),
        "calendar": days.astype(str).tolist() + future_sessions(),
        "decisions": [str(d) for d in days if str(d) >= "2026-09-03"],
        "rows": forecast_rows(histories),
        "original_vendor_metadata": {s: origins.get(s) for s in COHORT},
        "source_hashes": hashes, "limitations": limitations,
        "calendar_sources": {
            str(p): digest(p) for p in (
                calendar.HOLIDAYS_PATH, calendar.EARLY_CLOSES_PATH,
                calendar.HISTORICAL_SESSIONS_PATH,
            )
        },
    }
    (output / "forecasts.json").write_text(
        json.dumps(forecast, separators=(",", ":"), allow_nan=False)
    )
    return provenance["snapshot_sha256"], digest(output / "forecasts.json")


# Align frozen cohort prices without fabricating missing grades or book membership.
def cohort_arrays(source, panel, grades, eligible):
    days = np.array(source["decisions"], dtype="datetime64[D]")
    if list(source["decisions"]) != sorted(set(source["decisions"])):
        raise ValueError("Ordered unique decision sessions required")
    shape = len(days), len(COHORT)
    arrays = {key: np.full(shape, np.nan) for key in ("open", "close", "adj_close")}
    new_grades = np.full(shape, -1, dtype=np.int16)
    membership = point_in_time.eligibility(days, COHORT)
    membership[:, -2:] = False
    indexed = {(row["session"], row["symbol"]): row for row in source["rows"]}
    if len(indexed) != len(source["rows"]):
        raise ValueError("Duplicate frozen price row")
    for i, day in enumerate(days):
        old_rows = np.flatnonzero(panel.dates == day)
        if len(old_rows) != 1:
            raise ValueError("Cohort calendar is absent from original snapshot")
        old_row = int(old_rows[0])
        for j, symbol in enumerate(COHORT):
            row = indexed.get((str(day), symbol))
            if row is None:
                raise ValueError("Missing frozen cohort price")
            arrays["open"][i, j] = row["open"]
            arrays["close"][i, j] = arrays["adj_close"][i, j] = row["close"]
            if symbol not in panel.tickers:
                continue
            old_col = panel.tickers.index(symbol)
            new_grades[i, j] = grades[old_row, old_col]
            if membership[i, j] != eligible[old_row, old_col]:
                raise ValueError("Original and supplied membership masks disagree")
            if not np.isclose(
                row["close"], panel.adj_close[old_row, old_col], rtol=1e-9
            ):
                raise ValueError("Frozen price vintages disagree")
    return days, arrays, new_grades, membership


# Add forecast-only names using frozen prices and explicit archived membership rules.
def cohort_snapshot(forecast_path, portfolio_path, provenance_path, output, revision):
    from backend.market.open_source_portfolio import load_snapshot

    panel, grades, eligible, provenance = load_snapshot(portfolio_path, provenance_path)
    source = json.loads(Path(forecast_path).read_bytes())
    if source.get("price_basis") != "adjusted_ohlcv":
        raise ValueError("Frozen forecast prices must be adjusted OHLCV")
    membership_hashes = [
        value for key, value in provenance["source_hashes"].items()
        if Path(key).name == "membership_history.csv"
    ]
    if membership_hashes != [digest(universe.MEMBERSHIP_HISTORY_PATH)]:
        raise ValueError("Membership bytes differ from the original frozen snapshot")
    days, arrays, new_grades, membership = cohort_arrays(
        source, panel, grades, eligible
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(
        output / "portfolio.npz", dates=days, symbols=np.array(COHORT),
        grades=new_grades, eligible=membership, **arrays,
    )
    manifest = {
        **provenance,
        "snapshot_sha256": digest(output / "portfolio.npz"),
        "source_revision": revision,
        "parent_snapshot_sha256": provenance["snapshot_sha256"],
        "forecast_snapshot_sha256": digest(forecast_path),
        "price_representation": "already adjusted; close equals adjusted_close",
        "absent_original_grade_symbols": [s for s in COHORT if s not in panel.tickers],
        "membership_rule": "Original hashed intervals; no interval means excluded",
    }
    (output / "portfolio.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n"
    )
    return manifest["snapshot_sha256"]


# Run the frozen export explicitly; the live store remains read-only throughout.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=Path)
    source.add_argument("--cohort-from", type=Path)
    parser.add_argument("--portfolio", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    if not args.source_revision.strip():
        parser.error("source revision is required")
    if args.cohort_from:
        if not args.portfolio or not args.provenance:
            parser.error("cohort mode requires --portfolio and --provenance")
        result = cohort_snapshot(
            args.cohort_from, args.portfolio, args.provenance,
            args.output, args.source_revision,
        )
    else:
        result = export(args.root, args.output, args.source_revision)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
