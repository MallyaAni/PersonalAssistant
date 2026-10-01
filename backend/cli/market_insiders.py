"""The insider-stance study (A4): fetch the SEC insider data sets, build
the signal tables, evaluate them against the desk.

    python -m backend.cli.market_insiders fetch --root data/market
    python -m backend.cli.market_insiders build --root data/market \\
        --out work/insider-stance
    python -m backend.cli.market_insiders evaluate --root data/market \\
        --tables work/insider-stance --out work/insider-stance/insider_stance.json

Registered in `docs/research/insider-stance-plan-2026-10-01.md` before
any of this was written. Two arms (`backend.market.insiders`): A4-opp,
net open-market dollars bought by officers and directors whose trading
is not routine in the sense of Cohen, Malloy and Pomorski (2012); A4-all,
the same over every officer and director. Both over the trailing 90
sessions, scaled by the name's median daily dollar volume, dated by the
filing date (the first session after it).

`fetch` reads the index page once, then one zip per quarter from 2006q1
to the current quarter, paced by the EDGAR pacer, skipping every
quarter the as-of partition already holds, so a throttled run resumes.
Each zip is kept under `<root>/edgar_insiders_zips/`, its SHA-256 is
computed, its archive is tested, and the purchase and sale rows of
every issuer are stored as one immutable `edgar_insiders` frame per
quarter (the quarter label in the ticker slot) with the SHA-256, the URL
and the fetch time in the metadata. A quarter whose zip is already on
disk is parsed from disk; a SHA-256 that differs from the one an earlier
partition recorded is reported (the SEC regenerates a quarter now and
then) and the new frame carries the new one.

`build` reads the book panel, maps each name to its CIK from the stored
`edgar_events` metadata (the symbol in the data set is the fallback),
admits the rows the plan admits, classifies each under the routine
rule, and writes `insider_rows.parquet` (one row per admitted trade on
the panel: ticker, known session, signed dollars, classification),
`signals.npz` (the (T, N) signal per arm) and `build.json` (the counts).

`evaluate` measures both arms as the text-surprise study measured its
own: on the (session, name) cells shared with the desk's five analysts
(the plain rule's summed conviction, `desk.run(inputs=())`), at 20 and
60 sessions, in the plan's windows (2018-2025, its two halves, 2026 as
out-of-window), with the paired IC against the desk and the mean
per-session rank correlation with it. Before either arm is read, the
null test: an empty row table through the same pipeline must give a
zero signal, a rank of 0.5, no stance and no defined IC. The verdict
lines apply the plan's criteria; the T-S1 book gate is a separate
scorecard run, and the step writes each arm's stance table
(`stances/<arm>.parquet`) for it and prints the command.

Nothing here calls a model server; only `fetch` touches the network.
"""

import argparse
import hashlib
import io
import json
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.cli.market_release_eval import COST_BPS, MIN_NAMES
from backend.config.settings import settings
from backend.market import edgar, insiders
from backend.market.baselines import average_rank
from backend.market.harness import evaluate_scores, rank_correlation
from backend.market.store import MarketStore

# The plan's windows.
IN_WINDOW: tuple[date, date | None] = (date(2018, 1, 1), date(2025, 12, 31))
FIRST_HALF: tuple[date, date | None] = (date(2018, 1, 1), date(2021, 12, 31))
SECOND_HALF: tuple[date, date | None] = (date(2022, 1, 1), date(2025, 12, 31))
OUT_WINDOW: tuple[date, date | None] = (date(2026, 1, 1), None)
WINDOWS: dict[str, tuple[date, date | None]] = {
    "in_window": IN_WINDOW,
    "first_half": FIRST_HALF,
    "second_half": SECOND_HALF,
    "out_of_window": OUT_WINDOW,
}
HORIZONS: tuple[int, ...] = (20, 60)
PRIMARY_HORIZON = 20
# The plan's criteria.
IC_FLOOR = 0.02
T_FLOOR = 2.0
PAIRED_T_FLOOR = -1.0
SIXTH_ANALYST_CORRELATION = 0.3
ARM_DESK = "D desk (five analysts)"
ARM_NULL = "A4-0 empty table (null)"
ARMS = (insiders.ARM_OPPORTUNISTIC, insiders.ARM_ALL)
ROWS_TABLE = "insider_rows.parquet"
SIGNALS = "signals.npz"
BUILD_SUMMARY = "build.json"
STANCE_DIR = "stances"
EVENTS_KIND = "edgar_events"
# The follow-up the book gate needs: the scorecard has no sixth-stance
# flag yet (`market_pit_scorecard` grades exactly five stances), so the
# stance table is written here and the command is recorded for the run
# that adds one, as the text-surprise study recorded it.
SCORECARD_FOLLOW_UP = (
    "python -m backend.cli.market_pit_scorecard --graded-cap 0.25 --rank-ic "
    "--stance-table {table} --output {output}  "
    "(needs a --stance-table flag on the scorecard, a follow-up like "
    "research/structure-rules' --structure-notch; the T-S1 gate: +2 bp of "
    "equity a session at 25 bp over graded-equal-weight/5, NW t >= 2 on the "
    "model window, not negative after, 15 of 20 offsets, deflated Sharpe at "
    "the cumulative count >= 0.95)"
)


# The command line: `fetch`, `build` and `evaluate`.
def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser with one subcommand per step."""
    parser = argparse.ArgumentParser(description="Insider-stance study (A4).")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="fetch the quarterly data sets into the store")
    f.add_argument("--root", type=Path, default=Path(settings.MARKET_DATA_ROOT))
    f.add_argument("--asof", type=date.fromisoformat, default=None)
    f.add_argument(
        "--through",
        default=None,
        help="the last quarter label to fetch (default: the current quarter)",
    )
    f.add_argument("--quarters", default="", help="only these labels, comma-joined")
    b = sub.add_parser("build", help="write the per-row table and the signals")
    b.add_argument("--root", required=True, type=Path, help="the market store")
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--asof", type=date.fromisoformat, default=None)
    e = sub.add_parser("evaluate", help="measure the arms on shared cells")
    e.add_argument("--root", required=True, type=Path)
    e.add_argument("--tables", required=True, type=Path, help="the build output")
    e.add_argument("--out", required=True, type=Path, help="the payload (JSON)")
    e.add_argument("--asof", type=date.fromisoformat, default=None)
    e.add_argument(
        "--stances",
        type=Path,
        default=None,
        help="where the stance tables go (default: <tables>/stances)",
    )
    return parser


# --- fetch -------------------------------------------------------------------


# GET one URL through the EDGAR transport with the pacer and bounded
# retries on throttling; returns the body.
def _get_bytes(
    url: str,
    transport: edgar.Transport,
    pacer: edgar.Pacer,
    sleep: Callable[[float], None],
) -> bytes:
    last = "no attempt"
    for attempt in range(1, 4):
        pacer.wait()
        try:
            status, body = transport(url)
        except Exception as exc:  # network layer
            last = f"transport error: {exc}"
            sleep(5.0 * attempt)
            continue
        if status == 200:
            return body
        last = f"HTTP {status}"
        if status in (403, 429, 500, 502, 503):
            sleep(5.0 * attempt)
            continue
        break
    raise edgar.EdgarUnavailableError(f"{url}: refused ({last})")


# The SHA-256 of a zip's bytes, as hex.
def sha256_of(data: bytes) -> str:
    """Return the hex SHA-256 of `data`."""
    return hashlib.sha256(data).hexdigest()


# The SHA-256 an earlier partition recorded for a quarter, if any.
def prior_sha(store: MarketStore, quarter: str, asof: date) -> str | None:
    """Return the stored SHA-256 of the quarter's newest earlier frame."""
    frame = store.read_frame(insiders.INSIDERS_KIND, quarter, asof)
    if frame is None:
        return None
    return frame[1].get("sha256") or None


# The quarter labels a run applies to: 2006q1 to the current quarter,
# cut at `through` and restricted to `only` when given.
def _labels(today: date, through: str | None, only: Sequence[str]) -> list[str]:
    labels = insiders.quarter_labels(today)
    if through:
        labels = [q for q in labels if q <= through.lower()]
    if only:
        wanted = {q.lower() for q in only}
        labels = [q for q in labels if q in wanted]
    return labels


# One quarter: the zip from disk or the network, tested, parsed, kept on
# disk and stored as a frame with its SHA-256. Returns the log line, or
# raises on a refused or corrupt file (a corrupt file on disk is removed
# so the next run fetches it again).
def _fetch_quarter(
    store: MarketStore,
    asof: date,
    quarter: str,
    url: str,
    path: Path,
    transport: edgar.Transport,
    pacer: edgar.Pacer,
    sleep: Callable[[float], None],
    now: datetime,
) -> str:
    source = "disk" if path.exists() else "fetched"
    try:
        data = (
            path.read_bytes()
            if source == "disk"
            else _get_bytes(url, transport, pacer, sleep)
        )
        bad = zipfile.ZipFile(io.BytesIO(data)).testzip()
        if bad is not None:
            raise ValueError(f"corrupt member {bad}")
        rows = insiders.parse_zip(data)
    except (zipfile.BadZipFile, ValueError):
        if source == "disk":
            path.unlink()
        raise
    if source == "fetched":
        path.write_bytes(data)
    digest = sha256_of(data)
    earlier = prior_sha(store, quarter, asof)
    note = ""
    if earlier and earlier != digest:
        note = f"  (SHA-256 changed from an earlier partition: {earlier[:12]}...)"
    meta = {
        "sha256": digest,
        "url": url,
        "source_time": now.isoformat(),
        "bytes": str(len(data)),
        "rows": str(len(rows)),
    }
    store.write_frame(
        insiders.INSIDERS_KIND, asof, quarter, insiders.transactions_frame(rows), meta
    )
    return (
        f"{quarter} ok      {len(rows):6d} P/S rows, {len(data) / 1e6:5.1f} MB "
        f"({source}) sha {digest[:12]}{note}"
    )


# Fetch every quarter not already in the partition. Returns the labels
# whose fetch failed.
def fetch(
    store: MarketStore,
    asof: date,
    through: str | None = None,
    only: Sequence[str] = (),
    transport: edgar.Transport = edgar.sec_transport,
    pacer: edgar.Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Fetch the quarterly data sets into the as-of partition; return failures."""
    pacer = pacer or edgar.Pacer(sleep=sleep)
    stamp = now or datetime.now(tz=UTC)
    labels = _labels(stamp.date(), through, only)
    pending = [
        q for q in labels if not store.has_frame(insiders.INSIDERS_KIND, asof, q)
    ]
    skipped = len(labels) - len(pending)
    if not pending:
        print(f"partition {asof}: all {skipped} quarters present; nothing to fetch")
        return ()
    index: dict[str, str] = {}
    try:
        page = _get_bytes(insiders.INDEX_URL, transport, pacer, sleep)
        index = insiders.parse_index(page.decode("utf-8", "replace"))
    except edgar.EdgarUnavailableError as exc:
        print(f"index page unavailable ({exc}); using the URL pattern", flush=True)
    zip_dir = store.root / insiders.ZIP_DIR
    zip_dir.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    started = time.time()
    for quarter in pending:
        path = zip_dir / f"{quarter}_form345.zip"
        url = index.get(quarter) or insiders.ZIP_URL.format(quarter=quarter)
        try:
            line = _fetch_quarter(
                store, asof, quarter, url, path, transport, pacer, sleep, stamp
            )
        except (edgar.EdgarUnavailableError, zipfile.BadZipFile, ValueError) as exc:
            print(f"{quarter} FAILED  {exc}", flush=True)
            failed.append(quarter)
            continue
        print(line, flush=True)
    minutes = (time.time() - started) / 60
    stored = len(pending) - len(failed)
    print(
        f"partition {asof}: {stored} stored, {skipped} kept, {len(failed)} failed "
        f"in {minutes:.1f} min"
    )
    return tuple(failed)


# --- build -------------------------------------------------------------------


# Every stored P/S row across the quarters, from the newest partition
# of each quarter on or before `asof`.
def stored_rows(
    store: MarketStore, asof: date | None, today: date | None = None
) -> tuple[list[insiders.Transaction], list[str]]:
    """Return (rows, quarters found) from the `edgar_insiders` frames."""
    rows: list[insiders.Transaction] = []
    found: list[str] = []
    for quarter in insiders.quarter_labels(today or asof or date.today()):
        frame = store.read_frame(insiders.INSIDERS_KIND, quarter, asof)
        if frame is None:
            continue
        found.append(quarter)
        rows.extend(insiders.transactions_from_frame(frame[0]))
    return rows, found


# {cik: ticker} for the panel's names from the stored `edgar_events`
# metadata; names without a stored record fall back to the trading
# symbol the data set carries, when exactly one issuer CIK uses it.
def ticker_ciks(
    store: MarketStore,
    tickers: Sequence[str],
    rows: Sequence[insiders.Transaction],
    asof: date | None,
) -> dict[int, str]:
    """Return {issuer cik: ticker} for the book's names."""
    out: dict[int, str] = {}
    unresolved: list[str] = []
    for ticker in tickers:
        frame = store.read_frame(EVENTS_KIND, ticker, asof)
        cik = None
        if frame is not None:
            try:
                cik = int(frame[1].get("cik") or 0) or None
            except ValueError:
                cik = None
        if cik is None:
            unresolved.append(ticker)
            continue
        out[cik] = ticker
    if unresolved:
        by_symbol: dict[str, set[int]] = {}
        for row in rows:
            if row.symbol:
                by_symbol.setdefault(row.symbol, set()).add(row.issuer_cik)
        for ticker in unresolved:
            ciks = by_symbol.get(ticker) or by_symbol.get(ticker.replace("-", ""))
            if ciks and len(ciks) == 1:
                out[next(iter(ciks))] = ticker
    return out


# Write a column table as parquet (pyarrow, imported here as the store does).
def write_table(path: Path, columns: Mapping[str, list]) -> None:
    """Write `columns` to `path` as one parquet file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({k: pa.array(v) for k, v in columns.items()}), path)


# Read a parquet table back as columns.
def read_table(path: Path) -> dict[str, list]:
    """Return the columns of the parquet file at `path`."""
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pydict()


# The book panel as the desk builds it.
def _panel(root: Path, asof: date | None):
    from backend.agents.trading.desk.desk import book_panel

    return book_panel(MarketStore(root), asof)


# Build the per-row table and the signals under `out`.
def run_build(root: Path, out: Path, asof: date | None) -> dict[str, Any]:
    """Write the row table, the signals and the summary; return the summary."""
    store = MarketStore(root)
    panel, sides = _panel(root, asof)
    book = [t for t in panel.tickers if t in sides]
    rows, quarters = stored_rows(store, asof)
    if not rows:
        raise SystemExit(f"no {insiders.INSIDERS_KIND} frames under {root}")
    ticker_by_cik = ticker_ciks(store, book, rows, asof)
    own = [r for r in rows if r.issuer_cik in ticker_by_cik]
    admitted, refused = insiders.admit(own)
    labels = insiders.classify(admitted, own)
    signals, dated = insiders.arm_signals(panel, admitted, own, ticker_by_cik)
    out.mkdir(parents=True, exist_ok=True)
    write_table(out / ROWS_TABLE, insiders.dated_frame(panel, dated, labels))
    np.savez_compressed(
        out / SIGNALS,
        dates=np.asarray(panel.dates).astype("datetime64[D]").astype(str),
        tickers=np.asarray(panel.tickers),
        **{_slug(arm): signals[arm] for arm in ARMS},
    )
    per_name = {
        t: {
            "rows": sum(1 for d in dated if d.ticker == t),
            "opportunistic": sum(1 for d in dated if d.ticker == t and d.opportunistic),
            "purchases": sum(1 for d in dated if d.ticker == t and d.row.code == "P"),
        }
        for t in book
    }
    summary: dict[str, Any] = {
        "quarters": quarters,
        "stored_rows": len(rows),
        "book_rows": len(own),
        "admitted": len(admitted),
        "refused": refused,
        "dated": len(dated),
        "classification": {
            k: sum(1 for v in labels.values() if v == k)
            for k in ("opportunistic", "routine", "unclassified")
        },
        "names_mapped": len(ticker_by_cik),
        "names_unmapped": sorted(set(book) - set(ticker_by_cik.values())),
        "names_without_rows": sorted(t for t in book if per_name[t]["rows"] == 0),
        "per_name": per_name,
        "window": insiders.WINDOW,
        "min_volume_sessions": insiders.MIN_VOLUME_SESSIONS,
    }
    (out / BUILD_SUMMARY).write_text(json.dumps(summary, indent=2, default=float))
    print(
        f"A4: {len(quarters)} quarters, {len(own)} book rows, {len(admitted)} admitted "
        f"({summary['classification']}), {len(dated)} dated on the panel; "
        f"{len(summary['names_unmapped'])} names unmapped, "
        f"{len(summary['names_without_rows'])} without a row",
        flush=True,
    )
    return summary


# An arm name as a file stem.
def _slug(arm: str) -> str:
    return arm.replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")


# --- evaluate ----------------------------------------------------------------


# One arm's harness numbers plus its per-period ICs, keyed by date.
def _arm_result(scores, cells, panel, horizon) -> dict[str, Any]:
    masked = np.where(cells, scores, np.nan)
    report = evaluate_scores(
        masked, panel, horizon, cost_bps=COST_BPS, min_names=MIN_NAMES
    )
    return {
        "ic": report.mean_ic,
        "t": report.ic_tstat,
        "net_sharpe": report.net_sharpe,
        "periods": report.count,
        "defined_periods": int(len(report.defined_ics)),
        "period_ics": {str(p.date): p.rank_ic for p in report.periods},
    }


# The paired difference of two arms' per-period ICs on their common periods.
def paired(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, Any]:
    """Return mean and t of IC(b) - IC(a) over the periods both define."""
    keys = [k for k in a if k in b and np.isfinite(a[k]) and np.isfinite(b[k])]
    diffs = np.array([b[k] - a[k] for k in keys], dtype=float)
    if len(diffs) < 2 or diffs.std(ddof=1) == 0:
        return {
            "delta": float(diffs.mean()) if len(diffs) else float("nan"),
            "t": float("nan"),
            "periods": int(len(diffs)),
        }
    t = float(diffs.mean() / (diffs.std(ddof=1) / np.sqrt(len(diffs))))
    return {"delta": float(diffs.mean()), "t": t, "periods": int(len(diffs))}


# A (T,) mask of the sessions inside a window.
def window_mask(dates: np.ndarray, start: date, end: date | None) -> np.ndarray:
    """Return True for sessions in [start, end], end open when None."""
    stamps = np.asarray(dates).astype("datetime64[D]")
    mask = stamps >= np.datetime64(start)
    if end is not None:
        mask &= stamps <= np.datetime64(end)
    return mask


# The mean per-session Spearman correlation of two rank matrices on the
# cells both score, over sessions with at least `min_names` of them.
def mean_cross_sectional_correlation(
    a: np.ndarray, b: np.ndarray, cells: np.ndarray, min_names: int
) -> dict[str, float]:
    """Return {"mean": mean per-session Spearman, "sessions": count, "pooled": ...}."""
    both = cells & np.isfinite(a) & np.isfinite(b)
    values: list[float] = []
    pooled_a: list[np.ndarray] = []
    pooled_b: list[np.ndarray] = []
    for t in range(a.shape[0]):
        columns = np.flatnonzero(both[t])
        if len(columns) < min_names:
            continue
        rho = rank_correlation(a[t, columns], b[t, columns])
        if np.isfinite(rho):
            values.append(rho)
        pooled_a.append(average_rank(a[t, columns]) / (len(columns) - 1))
        pooled_b.append(average_rank(b[t, columns]) / (len(columns) - 1))
    pooled = float("nan")
    if pooled_a:
        pooled = rank_correlation(np.concatenate(pooled_a), np.concatenate(pooled_b))
    return {
        "mean": float(np.mean(values)) if values else float("nan"),
        "sessions": int(len(values)),
        "pooled": pooled,
    }


# Every arm on the cells all of them score, inside one window: the
# harness numbers per arm, each arm's paired difference against the
# desk, and its rank correlation with the desk on the same cells.
def _measure_window(
    scored: Mapping[str, np.ndarray], inside: np.ndarray, panel, horizon: int
) -> dict[str, Any]:
    cells = inside.copy()
    for scores in scored.values():
        cells &= np.isfinite(scores)
    results = {
        arm: _arm_result(scores, cells, panel, horizon)
        for arm, scores in scored.items()
    }
    pairs = {
        arm: paired(results[ARM_DESK]["period_ics"], results[arm]["period_ics"])
        for arm in results
        if arm != ARM_DESK
    }
    correlation = {
        arm: mean_cross_sectional_correlation(
            scored[ARM_DESK], scores, cells, MIN_NAMES
        )
        for arm, scores in scored.items()
        if arm != ARM_DESK
    }
    return {
        "cells": int(cells.sum()),
        "arms": results,
        "paired_vs_desk": pairs,
        "correlation_with_desk": correlation,
    }


# The desk's five analysts as the comparison arm: the plain rule's
# summed conviction, as `desk.run` builds it, on the same panel.
def desk_scores(root: Path, asof: date | None, panel) -> np.ndarray:
    """Return the (T, N) desk scores aligned to `panel`."""
    from backend.agents.trading.desk import desk

    report = desk.run(MarketStore(root), asof, inputs=())
    if report.panel.dates.shape != panel.dates.shape or not np.array_equal(
        report.panel.dates, panel.dates
    ):
        raise SystemExit("the desk's panel does not match the build's panel")
    if tuple(report.panel.tickers) != tuple(panel.tickers):
        raise SystemExit("the desk's tickers do not match the build's")
    return np.asarray(report.scores, dtype=float)


# The null test: an empty row table through the pipeline gives a zero
# signal wherever the denominator exists, a rank of 0.5 there, an empty
# stance table and no defined IC in any window at the primary horizon.
def null_test(panel, in_book: np.ndarray) -> dict[str, Any]:
    """Return {"pass": bool, "checks": {...}} for the empty-table null."""
    signal = insiders.window_signal(panel, [])
    scale = insiders.dollar_volume_scale(panel)
    with_denominator = np.isfinite(scale) & (scale > 0) & in_book[None, :]
    with_denominator[:, panel.index(panel.benchmark)] = False
    zero_where_scaled = bool(np.all(signal[with_denominator] == 0.0))
    nan_only_without = bool(
        np.all(np.isfinite(signal[:, in_book]) == with_denominator[:, in_book])
    )
    ranks = Opinion("null", np.where(in_book[None, :], signal, np.nan)).ranks()
    finite = np.isfinite(ranks)
    half_everywhere = bool(np.all(ranks[finite] == 0.5)) if finite.any() else True
    stances = int(np.count_nonzero(stance_table(panel, ranks)["stance"]))
    defined = 0
    for start, end in WINDOWS.values():
        inside = window_mask(panel.dates, start, end)[:, None] & in_book[None, :]
        defined += _arm_result(ranks, inside, panel, PRIMARY_HORIZON)["defined_periods"]
    checks = {
        "zero_where_denominator": zero_where_scaled,
        "nan_only_without_denominator": nan_only_without,
        "rank_half_everywhere": half_everywhere,
        "stances": stances,
        "defined_ics": defined,
    }
    ok = (
        zero_where_scaled
        and nan_only_without
        and half_everywhere
        and stances == 0
        and defined == 0
    )
    return {"pass": bool(ok), "checks": checks}


# Measure both arms with the desk on their shared cells, per horizon and
# window; the criteria and verdicts at the primary horizon.
def evaluate_arms(
    panel, sides: Mapping[str, str], arms: Mapping[str, np.ndarray]
) -> dict[str, Any]:
    """Return the study payload: windows per horizon, the null, criteria, verdicts."""
    in_book = np.array([t in sides for t in panel.tickers])
    payload: dict[str, Any] = {
        "windows": {
            k: [s.isoformat(), e.isoformat() if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "horizons": {},
    }
    for horizon in HORIZONS:
        per_window: dict[str, Any] = {}
        for name, (start, end) in WINDOWS.items():
            inside = window_mask(panel.dates, start, end)[:, None] & in_book[None, :]
            per_window[name] = _measure_window(arms, inside, panel, horizon)
        payload["horizons"][str(horizon)] = per_window
    payload["null_test"] = null_test(panel, in_book)
    payload["criteria"] = criteria(
        payload["horizons"][str(PRIMARY_HORIZON)], payload["null_test"]["pass"]
    )
    payload["verdicts"] = {arm: verdict(c) for arm, c in payload["criteria"].items()}
    return payload


# The plan's criteria per arm at the primary horizon: the IC floor on
# the in-window period, the halves not opposite in sign, the paired IC
# against the desk not negative at t <= -1, the role from the
# correlation with the desk. The book gate is a separate run.
def criteria(windows: Mapping[str, Any], null_pass: bool) -> dict[str, Any]:
    """Return {arm: criteria} from the primary horizon's window results."""
    out: dict[str, Any] = {}
    block = windows["in_window"]
    for arm, r in block["arms"].items():
        if arm == ARM_DESK:
            continue
        pair = block["paired_vs_desk"][arm]
        corr = block["correlation_with_desk"][arm]["mean"]
        ic, t = r["ic"], r["t"]
        first = windows["first_half"]["arms"][arm]["ic"]
        second = windows["second_half"]["arms"][arm]["ic"]
        clears = bool(
            np.isfinite(ic) and ic >= IC_FLOOR and np.isfinite(t) and t >= T_FLOOR
        )
        halves_agree = not bool(
            np.isfinite(first) and np.isfinite(second) and first * second < 0
        )
        not_worse = not bool(
            np.isfinite(pair["delta"])
            and pair["delta"] < 0
            and np.isfinite(pair["t"])
            and pair["t"] <= PAIRED_T_FLOOR
        )
        out_of = windows["out_of_window"]["arms"].get(arm, {})
        proposed = clears and halves_agree and not_worse and null_pass
        out[arm] = {
            "window": "in_window",
            "ic": ic,
            "t": t,
            "ic_first_half": first,
            "ic_second_half": second,
            "ic_out_of_window": out_of.get("ic", float("nan")),
            "t_out_of_window": out_of.get("t", float("nan")),
            "paired_delta_vs_desk": pair["delta"],
            "paired_t_vs_desk": pair["t"],
            "correlation_with_desk": corr,
            "clears_ic_floor": clears,
            "halves_not_opposite": halves_agree,
            "not_worse_than_desk": not_worse,
            "null_test_pass": bool(null_pass),
            "role": (
                "sixth analyst"
                if np.isfinite(corr) and corr < SIXTH_ANALYST_CORRELATION
                else "replacement candidate"
            ),
            "book_gate": "pending: " + SCORECARD_FOLLOW_UP
            if proposed
            else "not run: the IC criteria were not cleared",
        }
    return out


# The one-line reading of one arm's criteria.
def verdict(crit: Mapping[str, Any]) -> str:
    """Return the arm's verdict line per the plan."""
    if not crit["null_test_pass"]:
        return "INVALID: the null test failed; nothing here is comparable with the desk"
    if (
        crit["clears_ic_floor"]
        and crit["halves_not_opposite"]
        and crit["not_worse_than_desk"]
    ):
        return (
            f"CANDIDATE ({crit['role']}): clears the IC floor on {crit['window']}; "
            "proposed as a stance only if the T-S1 book gate holds (pending)"
        )
    return "RECORD"


# Each arm's stance table in long form: (session, ticker, stance) for every
# non-zero stance under the analyst's own rule (top and bottom 30%, three
# sessions' persistence), for the scorecard follow-up.
def stance_table(panel, ranks: np.ndarray) -> dict[str, list]:
    """Return the columns of one arm's stance table."""
    scores = np.where(np.isfinite(ranks), ranks, np.nan)
    stances = Opinion("arm", scores).stances()
    t_index, n_index = np.nonzero(stances != 0)
    return {
        "session": [str(panel.dates[t]) for t in t_index],
        "ticker": [panel.tickers[n] for n in n_index],
        "stance": [int(stances[t, n]) for t, n in zip(t_index, n_index, strict=True)],
    }


# The payload, printed.
def print_payload(payload: Mapping[str, Any]) -> None:
    """Print the arms per horizon and window, the null test and the verdicts."""
    null = payload["null_test"]
    print(
        f"null test (empty table: zero signal, rank 0.5, no stance, no IC): "
        f"{'PASS' if null['pass'] else 'FAIL'} {null['checks']}"
    )
    for horizon in HORIZONS:
        for name, window in payload["horizons"][str(horizon)].items():
            print(f"\n=== horizon {horizon}, {name}: {window['cells']:,} cells ===")
            header = f"{'arm':32} {'rank IC':>9} {'t':>7} {'net Sharpe':>11}"
            print(f"{header} {'periods':>8}")
            for arm, r in window["arms"].items():
                print(
                    f"{arm:32} {r['ic']:+9.4f} {r['t']:+7.2f} "
                    f"{r['net_sharpe']:+11.2f} {r['periods']:8d}"
                )
            for arm, p in window["paired_vs_desk"].items():
                corr = window["correlation_with_desk"][arm]
                print(
                    f"  {arm} - desk: {p['delta']:+.4f} (paired t {p['t']:+.2f}); "
                    f"rank correlation with the desk {corr['mean']:+.3f}"
                )
    print("\n=== criteria (primary horizon) ===")
    for arm, crit in payload["criteria"].items():
        print(
            f"{arm}: IC {crit['ic']:+.4f} (t {crit['t']:+.2f}) on {crit['window']}, "
            f"halves {crit['ic_first_half']:+.4f} / {crit['ic_second_half']:+.4f}, "
            f"2026 {crit['ic_out_of_window']:+.4f}, paired vs desk "
            f"{crit['paired_delta_vs_desk']:+.4f} (t {crit['paired_t_vs_desk']:+.2f}), "
            f"corr {crit['correlation_with_desk']:+.3f} -> {crit['role']}"
        )
    print("\n=== verdicts ===")
    for arm, line in payload["verdicts"].items():
        print(f"{arm}: {line}")


# The arms' (T, N) percentile ranks from the build's signals and the desk.
def arm_ranks(
    panel, signals: Mapping[str, np.ndarray], desk: np.ndarray
) -> dict[str, np.ndarray]:
    """Return {arm name: (T, N) ranks} for the desk and both arms."""
    arms = {ARM_DESK: Opinion("desk", desk).ranks()}
    for arm in ARMS:
        arms[arm] = Opinion(arm, np.asarray(signals[arm], dtype=float)).ranks()
    return arms


# Read the build's signals back, checked against the panel.
def load_signals(path: Path, panel) -> dict[str, np.ndarray]:
    """Return {arm: (T, N) signal} from `signals.npz`."""
    with np.load(path, allow_pickle=False) as data:
        dates = np.asarray(data["dates"]).astype("datetime64[D]")
        tickers = tuple(str(t) for t in data["tickers"])
        if not np.array_equal(dates, np.asarray(panel.dates).astype("datetime64[D]")):
            raise SystemExit("the signals were built on a different calendar")
        if tickers != tuple(panel.tickers):
            raise SystemExit("the signals were built on different tickers")
        return {arm: np.asarray(data[_slug(arm)], dtype=float) for arm in ARMS}


# Read the tables, measure, write the payload and the stance tables.
def run_evaluate(
    root: Path, tables: Path, out: Path, stances: Path | None, asof: date | None
) -> dict[str, Any]:
    """Evaluate the built signals; return the payload."""
    panel, sides = _panel(root, asof)
    signals = load_signals(tables / SIGNALS, panel)
    arms = arm_ranks(panel, signals, desk_scores(root, asof, panel))
    payload = evaluate_arms(panel, sides, arms)
    summary_path = tables / BUILD_SUMMARY
    if summary_path.exists():
        build = json.loads(summary_path.read_text())
        payload["build"] = {k: v for k, v in build.items() if k != "per_name"}
    stance_root = stances or tables / STANCE_DIR
    payload["stance_tables"] = {}
    for arm in ARMS:
        path = stance_root / (_slug(arm) + ".parquet")
        write_table(path, stance_table(panel, arms[arm]))
        payload["stance_tables"][arm] = str(path)
    payload["scorecard_follow_up"] = SCORECARD_FOLLOW_UP
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print_payload(payload)
    return payload


# Run the tool.
def main() -> None:
    """Entry point: one subcommand per step of the study."""
    args = build_parser().parse_args()
    if args.command == "fetch":
        asof = args.asof or datetime.now(tz=UTC).date()
        only = tuple(q.strip() for q in args.quarters.split(",") if q.strip())
        failed = fetch(MarketStore(args.root), asof, args.through, only)
        if failed:
            raise SystemExit(1)
    elif args.command == "build":
        summary = run_build(args.root, args.out, args.asof)
        print(json.dumps({k: v for k, v in summary.items() if k != "per_name"}))
    elif args.command == "evaluate":
        run_evaluate(args.root, args.tables, args.out, args.stances, args.asof)


if __name__ == "__main__":
    main()
