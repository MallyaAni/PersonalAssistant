"""Run the registered A2 statement-reading study.

    python -m backend.cli.market_statement_reading_research \
        --output docs/research/scorecards/statement-reading/result.json

Implements `docs/research/statement-reading-preregistration-2026-11-01.md`.
The model reads an anonymised eight-quarter packet per name and commits to
the direction of the next reported quarter's net income against the same
quarter a year earlier. The accuracy arm is one decision date; the stance
arm is every session from 2026-08-03 through the last session with a
complete 20-session forward residual, on the dated S&P 500 membership. The
book arm is the same stance on the live book names. The pre-cutoff
diagnostic repeats the accuracy arm at 2024-08-01. The null test runs
before any real answer is read.

Research only: no live file is written and no live path is touched.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.core.llm import OpenAICompatibleInferenceProvider
from backend.market import fundamentals_asof as fa
from backend.market import statement_reading as sr
from backend.market import universe
from backend.market.panel import Panel, build_panel
from backend.market.store import MarketStore

REPO = Path(__file__).resolve().parents[2]
START = date(2025, 9, 2)
ASOF = date(2026, 10, 30)
DECISION = date(2026, 8, 3)
LABEL_ASOF = date(2026, 10, 30)
LOOKAHEAD_DECISION = date(2024, 8, 1)
LOOKAHEAD_ASOF = date(2024, 12, 31)
HORIZON = 20
SHOCK_DAYS = (date(2026, 10, 29), date(2026, 10, 30))
TECH_SECTORS = ("Information Technology", "Communication Services")


# The calendar date of one panel session.
def session_date(value: np.datetime64) -> date:
    """Return the date of a panel session."""
    return date.fromisoformat(str(np.datetime64(value, "D")))


# Build the PIT and book panels and read the cached sector map.
def load_panels(
    root: Path, cache_path: Path
) -> tuple[MarketStore, Panel, Panel, dict[str, str], Any]:
    """Return (store, PIT panel, book panel, sectors, cached metadata)."""
    cached = np.load(cache_path, allow_pickle=True)
    tickers = [str(ticker) for ticker in cached["tickers"]]
    store = MarketStore(root)
    pit = build_panel(store, tickers, "SPY", {}, asof=ASOF, start=START)
    book_names = sorted(universe.book_sides(universe.build_universe()))
    book = build_panel(store, book_names, "SPY", {}, asof=ASOF, start=START)
    sectors = {
        str(ticker): str(sector)
        for ticker, sector in zip(
            cached["tickers"], cached["sector"], strict=True
        )
    }
    return store, pit, book, sectors, cached


# Read the versioned facts for each ticker as of a date.
def read_versions(
    store: MarketStore, tickers: list[str], asof: date
) -> dict[str, list[fa.Version]]:
    """Return {ticker: versions} for the tickers the store holds."""
    out: dict[str, list[fa.Version]] = {}
    for ticker in tickers:
        found = store.read_frame(fa.KIND, ticker, asof)
        if found is not None:
            out[ticker] = fa.versions_from_frame(found[0])
    return out


# The dated membership mask, benchmark excluded.
def pit_mask(panel: Panel, history_path: Path) -> np.ndarray:
    """Return the (T, N) Boolean membership mask."""
    mask = point_in_time.eligibility(
        panel.dates, tuple(panel.tickers), history_path
    )
    mask[:, panel.index(panel.benchmark)] = False
    return mask


# The packet for every session and name, rebuilt only when a version becomes
# available. The strict variant reads the packet from the day before the
# session; it is the registered sensitivity.
def packet_series(
    panel: Panel,
    versions: dict[str, list[fa.Version]],
    start_index: int,
    end_index: int,
    strict: bool = False,
) -> dict[tuple[int, str], sr.Packet]:
    """Return {(session, ticker): Packet} over [start_index, end_index]."""
    out: dict[tuple[int, str], sr.Packet] = {}
    for ticker in panel.tickers:
        rows = versions.get(ticker)
        if not rows:
            continue
        events = sorted({row.available for row in rows})
        current: sr.Packet | None = None
        seen = -1
        for index in range(start_index, end_index + 1):
            day = session_date(panel.dates[index])
            decision = day - timedelta(days=1) if strict else day
            count = bisect.bisect_right(events, decision)
            if count != seen:
                current = sr.build_packet(rows, decision)
                seen = count
            if current is not None:
                out[(index, ticker)] = current
    return out


# The registered accuracy sample: PIT members with a packet and a label.
def accuracy_rows(
    panel: Panel,
    packets: dict[tuple[int, str], sr.Packet],
    versions: dict[str, list[fa.Version]],
    mask: np.ndarray,
    index: int,
    decision: date,
    asof: date,
) -> list[dict[str, object]]:
    """Return the accuracy sample rows."""
    rows: list[dict[str, object]] = []
    for column, ticker in enumerate(panel.tickers):
        if not mask[index, column]:
            continue
        packet = packets.get((index, ticker))
        if packet is None:
            continue
        label = sr.build_label(versions.get(ticker, ()), packet, decision, asof)
        if label is None:
            continue
        rows.append({"ticker": ticker, "packet": packet, "label": label})
    return rows


# The pre-cutoff diagnostic sample from the cached dated membership.
def precutoff_rows(
    cached: Any,
    versions: dict[str, list[fa.Version]],
    decision: date,
    asof: date,
) -> list[dict[str, object]]:
    """Return the 2024-08-01 accuracy sample rows."""
    days = [str(value) for value in cached["dates"]]
    tickers = [str(value) for value in cached["tickers"]]
    row = max(
        index
        for index, value in enumerate(days)
        if value <= decision.isoformat()
    )
    members = [
        ticker
        for ticker, member in zip(
            tickers, cached["member"][row], strict=True
        )
        if member and ticker not in universe.MARKET_INDICES
    ]
    rows: list[dict[str, object]] = []
    for ticker in members:
        if ticker not in versions:
            continue
        packet = sr.build_packet(versions[ticker], decision)
        if packet is None:
            continue
        label = sr.build_label(versions[ticker], packet, decision, asof)
        if label is None:
            continue
        rows.append({"ticker": ticker, "packet": packet, "label": label})
    return rows


# Load the cache entries keyed by cache key, ignoring corrupt files.
def load_cache(directory: Path) -> dict[str, dict[str, object]]:
    """Return the valid cached call entries."""
    entries: dict[str, dict[str, object]] = {}
    if not directory.exists():
        return entries
    for path in directory.glob("*.json"):
        try:
            entry = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        key = entry.get("cache_key")
        if key and entry.get("packet_digest") and entry.get("answer"):
            entries[str(key)] = entry
    return entries


# Write one call entry atomically.
def write_cache(
    directory: Path, key: str, packet: sr.Packet, result: dict[str, object]
) -> None:
    """Write the cache entry for one call."""
    entry = {
        "cache_key": key,
        "packet_digest": packet.digest(),
        "packet": packet.view(),
        "prompt": result["prompt"],
        "answer": result["answer"],
        "content": result["content"],
        "finish_reason": result["finish_reason"],
        "served_model": result["served_model"],
        "latency": result["latency"],
        "usage": result["usage"],
        "model": sr.MODEL,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path = directory / f"{key}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(entry, allow_nan=False))
    temporary.replace(path)


# Call the model once per unique packet, reusing the cache. Each worker
# owns one provider because the provider serialises requests.
def run_model(
    packets: dict[str, sr.Packet],
    directory: Path,
    workers: int,
) -> tuple[dict[str, dict[str, object]], int, int, list[dict[str, str]]]:
    """Return (answers by digest, cache hits, calls, failures)."""
    directory.mkdir(parents=True, exist_ok=True)
    cached = load_cache(directory)
    answers: dict[str, dict[str, object]] = {}
    pending: list[tuple[str, sr.Packet]] = []
    hits = 0
    for key, packet in packets.items():
        entry = cached.get(key)
        if (
            entry is not None
            and entry.get("packet_digest") == packet.digest()
            and entry.get("prompt") == sr.render_prompt(packet)
        ):
            answers[packet.digest()] = entry["answer"]  # type: ignore[assignment]
            hits += 1
        else:
            pending.append((key, packet))
    local = threading.local()

    # One provider per worker thread.
    def provider() -> OpenAICompatibleInferenceProvider:
        if not hasattr(local, "provider"):
            local.provider = OpenAICompatibleInferenceProvider(
                sr.BASE_URL,
                sr.MODEL,
                timeout_seconds=300.0,
                reasoning_effort="none",
            )
        return local.provider

    # One call, returning the cache key, packet and result.
    def work(item: tuple[str, sr.Packet]) -> tuple[str, sr.Packet, dict[str, object]]:
        key, packet = item
        return key, packet, sr.ask(provider(), packet)

    failures: list[dict[str, str]] = []
    calls = 0
    if pending:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, item): item for item in pending}
            for future in as_completed(futures):
                key, packet = futures[future]
                try:
                    key, packet, result = future.result()
                except Exception as error:  # noqa: BLE001 - recorded, not hidden
                    failures.append({"cache_key": key, "error": repr(error)})
                    continue
                calls += 1
                answers[packet.digest()] = result["answer"]  # type: ignore[assignment]
                write_cache(directory, key, packet, result)
                if calls % 50 == 0:
                    print(
                        f"model calls: {calls}/{len(pending)}; "
                        f"failures: {len(failures)}"
                    )
    return answers, hits, calls, failures


# The (T, N) stance matrix from the packet answers. The confidence variant
# weights the sign by the answer's confidence.
def stance_matrix(
    panel: Panel,
    packets: dict[tuple[int, str], sr.Packet],
    answers: dict[str, dict[str, object]],
    weighted: bool = False,
) -> np.ndarray:
    """Return the stance matrix."""
    columns = {ticker: index for index, ticker in enumerate(panel.tickers)}
    out = np.full((len(panel.dates), len(panel.tickers)), np.nan, dtype=float)
    for (index, ticker), packet in packets.items():
        answer = answers.get(packet.digest())
        if answer is None:
            continue
        value = sr.confidence_stance(answer) if weighted else sr.stance(answer)
        if np.isfinite(value):
            out[index, columns[ticker]] = value
    return out


# Count the stance values over the selected rows and the membership mask.
def stance_distribution(
    matrix: np.ndarray, mask: np.ndarray, indices: range | list[int]
) -> dict[str, int]:
    """Return the stance counts, including missing."""
    counts: Counter[str] = Counter()
    for index in indices:
        for value in matrix[index][mask[index]]:
            if not np.isfinite(value):
                counts["missing"] += 1
            elif value > 0:
                counts["up"] += 1
            elif value < 0:
                counts["down"] += 1
            else:
                counts["flat"] += 1
    return dict(counts)


# The registered stance statistics: mean daily IC, Newey-West t, weekly
# bootstrap, within-day placebo and the stance distribution.
def score_stance(
    panel: Panel,
    matrix: np.ndarray,
    mask: np.ndarray,
    start_index: int,
    end_index: int,
) -> dict[str, object]:
    """Return the stance statistics over the window."""
    forward = panel.forward_residual(HORIZON)
    benchmark = panel.index(panel.benchmark)
    ics = sr.daily_ic(matrix, forward, benchmark)
    window = np.zeros(len(panel.dates), dtype=bool)
    window[start_index : end_index + 1] = True
    selected = ics[window]
    finite = selected[np.isfinite(selected)]
    days = [
        session_date(panel.dates[index])
        for index in range(start_index, end_index + 1)
    ]
    weeks = sr.week_ids(days)
    return {
        "sessions": int(window.sum()),
        "defined_sessions": int(len(finite)),
        "weeks": len(set(weeks)),
        "mean_ic": float(finite.mean()) if len(finite) else None,
        "newey_west_t": sr.newey_west_t(finite, HORIZON) if len(finite) else None,
        "bootstrap": sr.block_bootstrap(selected, weeks),
        "placebo": sr.stance_placebo(matrix, forward, benchmark, window),
        "distribution": stance_distribution(
            matrix, mask, list(range(start_index, end_index + 1))
        ),
        "ics": [float(value) if np.isfinite(value) else None for value in selected],
    }


# The descriptive calm and earnings mean ICs inside the stance window.
def stance_splits(
    panel: Panel,
    stance: dict[str, object],
    start_index: int,
    end_index: int,
) -> dict[str, object]:
    """Return the calm and earnings mean ICs from the stance window."""
    days = [
        session_date(panel.dates[index])
        for index in range(start_index, end_index + 1)
    ]
    ics = np.asarray(
        [np.nan if value is None else float(value) for value in stance["ics"]],
        dtype=float,
    )
    bounds = {
        "calm": (date(2026, 8, 3), date(2026, 9, 15)),
        "earnings": (date(2026, 9, 16), date(2026, 10, 2)),
    }
    out: dict[str, object] = {}
    for name, (low, high) in bounds.items():
        selected = np.array([low <= day <= high for day in days], dtype=bool)
        values = ics[selected]
        values = values[np.isfinite(values)]
        out[name] = {
            "start": low.isoformat(),
            "end": high.isoformat(),
            "sessions": int(selected.sum()),
            "defined_sessions": int(values.size),
            "mean_ic": float(values.mean()) if values.size else None,
        }
    return out


# The shock rows: stance distribution and next-session residual by stance.
def shock_stats(
    panel: Panel, matrix: np.ndarray, mask: np.ndarray
) -> dict[str, object]:
    """Return the stance and next-session return for the shock sessions."""
    own = panel.forward_log_returns(1)
    benchmark = panel.index(panel.benchmark)
    residual = own - panel.rolling_beta(120) * own[:, benchmark][:, None]
    indices = [
        index
        for index in range(len(panel.dates))
        if session_date(panel.dates[index]) in SHOCK_DAYS
    ]
    by_stance: dict[str, list[float]] = defaultdict(list)
    for index in indices:
        for column in np.flatnonzero(mask[index] & np.isfinite(matrix[index])):
            value = matrix[index, column]
            if not np.isfinite(residual[index, column]):
                continue
            key = "up" if value > 0 else "down" if value < 0 else "flat"
            by_stance[key].append(float(residual[index, column]))
    return {
        "sessions": [session_date(panel.dates[index]).isoformat() for index in indices],
        "distribution": stance_distribution(matrix, mask, indices),
        "next_session_residual": {
            key: {
                "count": len(values),
                "mean": float(np.mean(values)) if values else None,
            }
            for key, values in by_stance.items()
        },
    }


# Attach the answers to the sample rows and score them.
def score_accuracy(
    rows: list[dict[str, object]],
    answers: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    """Return the scored rows, the accuracy stats and the placebo."""
    scored = [
        {**row, "answer": answers.get(row["packet"].digest())}  # type: ignore[union-attr]
        for row in rows
    ]
    return scored, sr.accuracy_stats(scored), sr.accuracy_placebo(scored)


# Accuracy by the next quarter's filing month and by sector group.
def accuracy_splits(
    scored: list[dict[str, object]], sectors: dict[str, str]
) -> dict[str, object]:
    """Return the descriptive accuracy splits."""
    months: dict[str, list[dict[str, object]]] = defaultdict(list)
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in scored:
        label = row["label"]
        month = label["next_available"].month  # type: ignore[index]
        months[str(month)].append(row)
        sector = sectors.get(str(row["ticker"]), "")
        group = "technology_communication" if sector in TECH_SECTORS else "other"
        groups[group].append(row)

    # The accuracy of one split, with the same coverage denominator.
    def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
        stats = sr.accuracy_stats(rows)
        return {
            "labelled": stats["labelled"],
            "answered": stats["answered"],
            "accuracy": stats["accuracy"],
        }

    return {
        "by_filing_month": {
            month: summarize(rows) for month, rows in sorted(months.items())
        },
        "by_sector": {
            group: summarize(rows) for group, rows in sorted(groups.items())
        },
    }


# The registered null test: schema shape plus the packet perturbation on
# the first accuracy name.
def null_test(
    rows: list[dict[str, object]],
    versions: dict[str, list[fa.Version]],
    decision: date,
) -> dict[str, object]:
    """Return the null-test result."""
    schema_ok = (
        sr.SCHEMA.get("additionalProperties") is False
        and set(sr.SCHEMA.get("required", [])) == {
            "analysis",
            "direction",
            "confidence",
        }
        and sr.SCHEMA["properties"]["direction"].get("enum") == list(sr.DIRECTIONS)
    )
    if not rows:
        return {
            "ticker": None,
            "schema_ok": schema_ok,
            "future_identical": False,
            "newest_changes": False,
            "missing_is_na": False,
            "reason": "no accuracy sample",
        }
    ticker = str(rows[0]["ticker"])
    result = sr.perturbation_check(versions.get(ticker, ()), decision)
    result["ticker"] = ticker
    result["schema_ok"] = schema_ok
    return result


# The registered G1-G5 booleans and the verdict.
def gate_result(
    accuracy: dict[str, object],
    accuracy_placebo: dict[str, object],
    stance: dict[str, object],
    book: dict[str, object],
    null: dict[str, object],
    runtime: dict[str, object],
) -> dict[str, object]:
    """Return the gate booleans and the verdict."""
    labelled = int(accuracy["labelled"] or 0)
    answered = int(accuracy["answered"] or 0)
    accuracy_value = accuracy["accuracy"]
    binomial = accuracy["binomial_p"]
    coverage = accuracy["coverage"]
    placebo_p95 = accuracy_placebo["p95"]
    g1 = (
        labelled >= sr.MIN_ACCURACY_NAMES
        and accuracy_value is not None
        and float(accuracy_value) >= 0.55
        and binomial is not None
        and float(binomial) < 0.05
        and coverage is not None
        and float(coverage) >= 0.80
        and placebo_p95 is not None
        and float(accuracy_value) > float(placebo_p95)
    )
    mean_ic = stance["mean_ic"]
    newey = stance["newey_west_t"]
    bootstrap = stance["bootstrap"]
    stance_placebo = stance["placebo"]
    g2 = (
        int(stance["defined_sessions"] or 0) >= sr.MIN_STANCE_DAYS
        and mean_ic is not None
        and float(mean_ic) >= sr.BENCHMARK_IC
        and newey is not None
        and float(newey) >= 2.0
        and bootstrap["lower"] is not None
        and float(bootstrap["lower"]) > 0.0
        and stance_placebo["p95"] is not None
        and float(mean_ic) > float(stance_placebo["p95"])
    )
    g3 = book["mean_ic"] is not None and float(book["mean_ic"]) >= 0.0
    g4 = (
        bool(null.get("future_identical"))
        and bool(null.get("newest_changes"))
        and bool(null.get("missing_is_na"))
        and bool(null.get("schema_ok"))
    )
    failure_rate = runtime["failure_rate"]
    g5 = failure_rate is not None and float(failure_rate) < 0.02
    gates = {
        "G1": bool(g1),
        "G2": bool(g2),
        "G3": bool(g3),
        "G4": bool(g4),
        "G5": bool(g5),
    }
    if (
        labelled < sr.MIN_ACCURACY_NAMES
        or int(stance["defined_sessions"] or 0) < sr.MIN_STANCE_DAYS
    ):
        verdict = "INCONCLUSIVE"
    elif all(gates.values()):
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return {"gates": gates, "verdict": verdict, "answered": answered}


# Convert non-finite floats and dates to JSON-safe values.
def json_safe(value: Any) -> Any:
    """Return a JSON-safe copy of `value`."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


# Parse the CLI and run the registered study.
def main(argv: list[str] | None = None) -> int:
    """Run the study and write the result JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / "data/market")
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("/home/animallya96/dsv41/pit2/cache.npz"),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/home/animallya96/dsv41/a2_cache"),
    )
    parser.add_argument(
        "--membership",
        type=Path,
        default=REPO
        / "data/market/research/universe-hindsight/sp500_membership_history.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "docs/research/scorecards/statement-reading/result.json",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="debug only: cap the unique packets sent to the model",
    )
    args = parser.parse_args(argv)

    store, pit, book, sectors, cached = load_panels(args.root, args.cache)
    versions = read_versions(
        store,
        sorted(
            set(pit.tickers)
            | set(book.tickers)
            | {str(ticker) for ticker in cached["tickers"]}
        ),
        ASOF,
    )
    mask = pit_mask(pit, args.membership)
    start = int(np.searchsorted(pit.dates, np.datetime64(DECISION, "D"), side="left"))
    last = len(pit.dates) - 1 - HORIZON
    decision = session_date(pit.dates[start])
    print(
        f"PIT panel {len(pit.dates)} sessions x {len(pit.tickers)} names; "
        f"decision {decision}; usable window ends {session_date(pit.dates[last])}"
    )
    book_start = int(
        np.searchsorted(book.dates, np.datetime64(DECISION, "D"), side="left")
    )
    book_last = len(book.dates) - 1 - HORIZON

    pit_packets = packet_series(pit, versions, start, len(pit.dates) - 1)
    strict_packets = packet_series(
        pit, versions, start, last, strict=True
    )
    book_packets = packet_series(book, versions, book_start, len(book.dates) - 1)
    accuracy_sample = accuracy_rows(
        pit, pit_packets, versions, mask, start, decision, LABEL_ASOF
    )
    lookahead_sample = precutoff_rows(
        cached, versions, LOOKAHEAD_DECISION, LOOKAHEAD_ASOF
    )
    print(
        f"accuracy sample {len(accuracy_sample)}; "
        f"pre-cutoff sample {len(lookahead_sample)}; "
        f"packet rows {len(pit_packets)} PIT, {len(book_packets)} book"
    )

    packets: dict[str, sr.Packet] = {}
    for mapping in (pit_packets, strict_packets, book_packets):
        for packet in mapping.values():
            packets.setdefault(sr.cache_key(packet), packet)
    for row in accuracy_sample + lookahead_sample:
        packet = row["packet"]
        packets.setdefault(sr.cache_key(packet), packet)  # type: ignore[arg-type]
    if args.limit is not None:
        packets = dict(list(packets.items())[: args.limit])
        print(f"debug limit: {len(packets)} unique packets")

    answers, hits, calls, failures = run_model(
        packets, args.cache_dir, args.workers
    )
    attempts = calls + len(failures)
    runtime = {
        "unique_packets": len(packets),
        "cache_hits": hits,
        "calls": calls,
        "failures": len(failures),
        "attempts": attempts,
        "failure_rate": (len(failures) / attempts) if attempts else 0.0,
        "failure_examples": failures[:20],
    }
    print(
        f"runtime: {len(packets)} unique, {hits} cached, {calls} calls, "
        f"{len(failures)} failures"
    )

    scored, accuracy, accuracy_placebo = score_accuracy(accuracy_sample, answers)
    scored_2024, accuracy_2024, placebo_2024 = score_accuracy(
        lookahead_sample, answers
    )
    pit_matrix = stance_matrix(pit, pit_packets, answers)
    pit_matrix = np.where(mask, pit_matrix, np.nan)
    confidence_matrix = stance_matrix(pit, pit_packets, answers, weighted=True)
    confidence_matrix = np.where(mask, confidence_matrix, np.nan)
    strict_matrix = stance_matrix(pit, strict_packets, answers)
    strict_matrix = np.where(mask, strict_matrix, np.nan)
    book_matrix = stance_matrix(book, book_packets, answers)
    book_mask = np.ones_like(book_matrix, dtype=bool)
    book_mask[:, book.index(book.benchmark)] = False

    stance = score_stance(pit, pit_matrix, mask, start, last)
    book_stance = score_stance(book, book_matrix, book_mask, book_start, book_last)
    confidence = score_stance(pit, confidence_matrix, mask, start, last)
    strict = score_stance(pit, strict_matrix, mask, start, last)
    regimes = stance_splits(pit, stance, start, last)
    shock = shock_stats(pit, pit_matrix, mask)
    null = null_test(accuracy_sample, versions, decision)
    gates = gate_result(accuracy, accuracy_placebo, stance, book_stance, null, runtime)
    lookahead = {
        "decision": LOOKAHEAD_DECISION.isoformat(),
        "label_asof": LOOKAHEAD_ASOF.isoformat(),
        "accuracy": accuracy_2024,
        "placebo": placebo_2024,
        "difference": (
            float(accuracy["accuracy"]) - float(accuracy_2024["accuracy"])
            if accuracy["accuracy"] is not None
            and accuracy_2024["accuracy"] is not None
            else None
        ),
    }
    result = {
        "study": "statement-reading",
        "registered": "docs/research/statement-reading-preregistration-2026-11-01.md",
        "generated_at": datetime.now(UTC).isoformat(),
        "model": sr.MODEL,
        "prompt_version": sr.PROMPT_VERSION,
        "schema_version": sr.SCHEMA_VERSION,
        "packet_version": sr.PACKET_VERSION,
        "decision": decision.isoformat(),
        "label_asof": LABEL_ASOF.isoformat(),
        "window": {
            "start": session_date(pit.dates[start]).isoformat(),
            "end": session_date(pit.dates[last]).isoformat(),
            "sessions": int(last - start + 1),
        },
        "runtime": runtime,
        "accuracy": accuracy,
        "accuracy_placebo": accuracy_placebo,
        "accuracy_splits": accuracy_splits(scored, sectors),
        "stance": stance,
        "book": book_stance,
        "confidence": confidence,
        "strict": strict,
        "regimes": regimes,
        "shock": shock,
        "lookahead": lookahead,
        "null_test": null,
        "gates": gates,
        "partial": args.limit is not None,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(json_safe(result), indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    )
    print(f"verdict: {gates['verdict']}; gates: {gates['gates']}")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
