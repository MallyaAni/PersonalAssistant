"""The LLM statement-reading study (A2): plan the calls, score, evaluate.

    python -m backend.cli.market_statements plan --root data/market
    python -m backend.cli.market_statements score --root data/market \\
        --llm-url http://127.0.0.1:8000 --llm-model deepseek-v4-flash --concurrency 4
    python -m backend.cli.market_statements evaluate --root data/market \\
        --out docs/research/scorecards/llm-statements/llm_statements.json
    python -m backend.cli.market_statements status --root data/market

Registered in `docs/research/llm-statements-plan-2026-10-01.md` before any
of this was written. `plan` counts the observations the stored filing
versions allow per name (one model call each) and writes nothing. `score`
builds each name's anonymised blocks (`backend.market.statements`), calls
the statement reader on each, and stores the answers as an immutable
`edgar_statements` frame per name in the as-of partition, resumably: a
name already in the partition is skipped, a name interrupted mid-way
resumes from its partial file, and a change of prompt version or model
starts the name over. The model endpoint is the structured role from
settings, overridable with --llm-url and --llm-model, one client per
worker thread as the tone run does.

`evaluate` reads the stored frames, turns them into a carried-forward
stance (probability less one half, dated by availability), and measures
it beside the fundamental analyst (corrected source) and the value
analyst on their shared cells of the book with `harness.evaluate_scores`
at 20 and 60 sessions, in the plan's windows; the paired per-period IC
against the fundamental analyst, the mean per-session rank correlation
with both, the plan's criteria and the verdict. The null test runs first:
a constant 0.5 probability must read as a scoreless signal (no defined
period IC, an empty stance table). The direction-accuracy report follows,
deciding nothing. The step writes the stance table for the book gate and
prints the follow-up command.
"""

import argparse
import json
import math
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.agents.trading.statement_reader import (
    PROMPT_VERSION,
    StatementCall,
    StatementReader,
)
from backend.config.settings import settings
from backend.core.llm import OpenAICompatibleInferenceProvider
from backend.market import fundamentals_asof as fa
from backend.market import statements
from backend.market.baselines import average_rank
from backend.market.harness import evaluate_scores
from backend.market.store import MarketStore
from backend.market.universe import build_universe, tickers_with_role

# The plan's windows and horizons.
IN_WINDOW: tuple[date, date] = (date(2018, 1, 1), date(2025, 5, 31))
POST_WINDOW: tuple[date, date | None] = (date(2025, 6, 1), None)
WINDOWS: dict[str, tuple[date, date | None]] = {
    "in_window": IN_WINDOW,
    "post_window": POST_WINDOW,
}
HORIZONS: tuple[int, ...] = (20, 60)
PRIMARY_HORIZON = 20
# The panel's first session: an observation available before it earns no
# IC, so plan and score skip it by default.
SINCE = date(2015, 1, 1)
# The harness settings the tone and text-surprise studies measured with.
COST_BPS = 10.0
MIN_NAMES = 15
# The plan's criteria.
IC_FLOOR = 0.02
T_FLOOR = 2.0
NOT_NEGATIVE_T = -1.0
SIXTH_ANALYST_CORRELATION = 0.3
PAPER_ACCURACY = 0.604
ARM_A2 = "A2 statement reader"
ARM_NULL = "A2-0 constant 0.5 (null)"
ARM_FUNDAMENTAL = "fundamental analyst"
ARM_VALUE = "value analyst"
STANCE_DIR = "stances"
# The book gate is a separate scorecard run that still needs a stance-table
# flag (the follow-up A1 recorded); the command is printed, not run.
SCORECARD_FOLLOW_UP = (
    "python -m backend.cli.market_pit_scorecard --graded-cap 0.25 --rank-ic "
    "--stance-table {table} --output {output}  "
    "(needs a --stance-table flag on the scorecard; the T-S1 gate: +2 bp of "
    "equity a session at 25 bp over graded-equal-weight/5, NW t >= 2 on the "
    "model window, not negative after, 15 of 20 offsets, deflated Sharpe at "
    "the cumulative count >= 0.95)"
)


@dataclass(frozen=True, slots=True)
class StatementRecord:
    """One scored observation, as stored."""

    quarter_end: date
    available: date
    direction: str
    probability: float
    rationale: str
    block_sha256: str
    lines_present: int
    anchor: str
    model: str
    prompt_version: str
    consistent: bool

    # The stance the study scores.
    @property
    def stance(self) -> float:
        return self.probability - 0.5


# The command line: plan, score, evaluate, status.
def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser with one subcommand per step."""
    parser = argparse.ArgumentParser(description="LLM statement reading (A2).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("plan", "count the model calls the stored facts allow"),
        ("score", "call the model on every unscored block, resumably"),
        ("status", "report what is stored"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--root", type=Path, default=Path(settings.MARKET_DATA_ROOT))
        p.add_argument("--tickers", default="")
        p.add_argument("--roles", default="")
        p.add_argument("--asof", type=date.fromisoformat, default=None)
        if name != "status":
            p.add_argument(
                "--since",
                type=date.fromisoformat,
                default=SINCE,
                help="skip observations available before this date",
            )
        if name == "plan":
            p.add_argument(
                "--blocks",
                type=Path,
                default=None,
                help="also write every block as JSONL here, for inspection",
            )
        if name == "score":
            p.add_argument("--concurrency", type=int, default=4)
            p.add_argument("--llm-url", default="")
            p.add_argument("--llm-model", default="")
            p.add_argument(
                "--deadline-minutes",
                type=float,
                default=None,
                help="stop between names once this many minutes have passed",
            )
    e = sub.add_parser("evaluate", help="measure the stance on the book")
    e.add_argument("--root", type=Path, default=Path(settings.MARKET_DATA_ROOT))
    e.add_argument("--out", required=True, type=Path, help="the payload (JSON)")
    e.add_argument(
        "--stances",
        type=Path,
        default=None,
        help="where the stance table goes (default: <out dir>/stances)",
    )
    return parser


# The tickers a run applies to: the listed ones, the roles, or the book.
def select_tickers(args: argparse.Namespace) -> tuple[str, ...]:
    """Return the tickers named by --tickers, --roles, or the book."""
    if args.tickers:
        return tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    if args.roles:
        roles = tuple(r.strip() for r in args.roles.split(",") if r.strip())
        return tickers_with_role(build_universe(), *roles)
    from backend.market.universe import book_sides

    return tuple(sorted(book_sides(build_universe())))


# One reader per concurrent call against the configured runtime: the
# provider serialises requests per instance, so concurrency needs
# instances. The endpoint resolution is the tone run's.
def clients(
    llm_url: str = "", llm_model: str = "", concurrency: int = 4
) -> tuple[list[StatementReader], str]:
    """Return (readers, model name) for the runtime."""
    url = (
        llm_url
        or settings.ROUTING_LLM_BASE_URL
        or settings.MAIN_LLM_BASE_URL
        or settings.LLM_BASE_URL
    )
    model = (
        llm_model
        or settings.ROUTING_LLM_MODEL
        or settings.MAIN_LLM_MODEL
        or settings.LLM_MODEL
    )
    return [
        StatementReader(
            OpenAICompatibleInferenceProvider(
                url, model, settings.LLM_API_KEY, timeout_seconds=600.0
            )
        )
        for _ in range(max(1, concurrency))
    ], model


# --- observations ------------------------------------------------------------


# The observations of one name from its stored versions, or None when the
# store holds no versions frame for it.
def observations_for(
    store: MarketStore,
    ticker: str,
    asof: date | None = None,
    since: date | None = None,
) -> list[statements.Observation] | None:
    """Return the name's point-in-time observations, or None without versions.

    `since` keeps only observations available on or after it: the panel's
    bars start in 2015, so an earlier observation can earn no IC and is
    not worth a model call.
    """
    frame = store.read_frame(fa.KIND, ticker, asof)
    if frame is None:
        return None
    rows = statements.observations(fa.versions_from_frame(frame[0]))
    if since is not None:
        rows = [r for r in rows if r.available >= since]
    return rows


# --- storage -----------------------------------------------------------------


# Serialise records for the store's frames.
def statement_frame(records: Sequence[StatementRecord]) -> dict[str, list]:
    """Return the columns of a statements frame."""
    return {
        "quarter_end": [r.quarter_end.isoformat() for r in records],
        "available": [r.available.isoformat() for r in records],
        "direction": [r.direction for r in records],
        "probability": [r.probability for r in records],
        "rationale": [r.rationale for r in records],
        "block_sha256": [r.block_sha256 for r in records],
        "lines_present": [r.lines_present for r in records],
        "anchor": [r.anchor for r in records],
        "model": [r.model for r in records],
        "prompt_version": [r.prompt_version for r in records],
        "consistent": [r.consistent for r in records],
    }


# Rebuild records from a stored frame, oldest quarter first.
def records_from_frame(columns: Mapping[str, list]) -> tuple[StatementRecord, ...]:
    """Return the StatementRecords a frame encodes."""
    rows = [
        StatementRecord(
            quarter_end=date.fromisoformat(str(columns["quarter_end"][i])),
            available=date.fromisoformat(str(columns["available"][i])),
            direction=str(columns["direction"][i]),
            probability=float(columns["probability"][i]),
            rationale=str(columns["rationale"][i]),
            block_sha256=str(columns["block_sha256"][i]),
            lines_present=int(columns["lines_present"][i]),
            anchor=str(columns["anchor"][i]),
            model=str(columns["model"][i]),
            prompt_version=str(columns["prompt_version"][i]),
            consistent=bool(columns["consistent"][i]),
        )
        for i in range(len(columns.get("quarter_end", [])))
    ]
    return tuple(sorted(rows, key=lambda r: (r.quarter_end, r.available)))


# The partial file a long run appends to, one JSON record per line.
def partial_path(root: Path, asof: date, ticker: str) -> Path:
    """Return the path of a ticker's in-progress statements file."""
    return (
        root / statements.KIND / f"asof={asof.isoformat()}" / f"{ticker}.partial.jsonl"
    )


# Append one record to the partial file.
def append_partial(path: Path, record: StatementRecord) -> None:
    """Append a record to the partial file, creating it if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(record)
    payload["quarter_end"] = record.quarter_end.isoformat()
    payload["available"] = record.available.isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


# Read the records already scored into a partial file, keyed by quarter end.
def read_partial(path: Path) -> dict[date, StatementRecord]:
    """Return {quarter_end: record} from a partial file, empty if absent."""
    if not path.exists():
        return {}
    out: dict[date, StatementRecord] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        payload["quarter_end"] = date.fromisoformat(payload["quarter_end"])
        payload["available"] = date.fromisoformat(payload["available"])
        record = StatementRecord(**payload)
        out[record.quarter_end] = record
    return out


# The records already stored for a ticker in the newest partition before
# `asof`, so a new day scores only the quarters it has not seen. A change of
# prompt version or model starts over: those answers are not comparable.
def prior_records(
    store: MarketStore, ticker: str, asof: date, model: str
) -> dict[date, StatementRecord]:
    """Return {quarter_end: record} carried forward from earlier partitions."""
    frame = store.read_frame(statements.KIND, ticker, asof - timedelta(days=1))
    if frame is None:
        return {}
    columns, meta = frame
    if meta.get("prompt_version") != PROMPT_VERSION or meta.get("model") != model:
        return {}
    return {
        r.quarter_end: r
        for r in records_from_frame(columns)
        if r.prompt_version == PROMPT_VERSION and r.model == model
    }


# Keep only compatible completed frames; historical partitions are never rewritten.
def current_frame_exists(
    store: MarketStore, ticker: str, asof: date, model: str
) -> bool:
    """Return True when the partition holds a compatible frame for the name."""
    if not store.has_frame(statements.KIND, asof, ticker):
        return False
    columns, metadata = store.read_frame(statements.KIND, ticker, asof)
    records = records_from_frame(columns)
    # A name with no observations stores an empty frame: no model answered
    # anything in it, so it is compatible with every model and prompt
    # (a run under the wrong model must not leave it blocking the rerun).
    if not records:
        return True
    if (
        metadata.get("prompt_version") != PROMPT_VERSION
        or metadata.get("model") != model
        or any(
            r.prompt_version != PROMPT_VERSION or r.model != model
            for r in records
        )
    ):
        raise RuntimeError(
            f"{ticker}: incompatible statements frame at {asof}; "
            "use a new as-of partition to preserve history"
        )
    return True


# The stored record of one scored observation.
def statement_record(
    row: statements.Observation, call: StatementCall, model: str
) -> StatementRecord:
    """Return the StatementRecord for `row` answered as `call`."""
    return StatementRecord(
        quarter_end=row.quarter_end,
        available=row.available,
        direction=call.direction,
        probability=call.probability,
        rationale=call.rationale,
        block_sha256=row.sha256,
        lines_present=row.lines_present,
        anchor=row.anchor,
        model=model,
        prompt_version=PROMPT_VERSION,
        consistent=call.consistent,
    )


# --- score -------------------------------------------------------------------


# Score one ticker's unscored observations and store the frame when complete.
# Returns (scored, failed, stored): stored is -1 without versions, else the
# record count of the frame written.
def score_ticker(
    store: MarketStore,
    ticker: str,
    asof: date,
    readers: Sequence[StatementReader],
    model: str,
    deadline: float | None = None,
    since: date | None = SINCE,
) -> tuple[int, int, int]:
    """Score a name's observations into the as-of partition, resumably."""
    if current_frame_exists(store, ticker, asof, model):
        columns, _meta = store.read_frame(statements.KIND, ticker, asof)
        return 0, 0, len(columns.get("quarter_end", []))
    rows = observations_for(store, ticker, asof, since)
    if rows is None:
        return 0, 0, -1
    partial = partial_path(store.root, asof, ticker)
    done = prior_records(store, ticker, asof, model)
    done.update(
        {
            key: r
            for key, r in read_partial(partial).items()
            if r.prompt_version == PROMPT_VERSION and r.model == model
        }
    )
    todo = [r for r in rows if r.quarter_end not in done]

    # Past the budget a block is not called and counts as a failure, so the
    # name is retried next run and its frame is not stored as complete.
    def work(item: tuple[int, statements.Observation]):
        index, row = item
        if deadline is not None and time.monotonic() > deadline:
            return row, None
        return row, readers[index % len(readers)].call_sync(row.block)

    scored = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, len(readers))) as pool:
        for row, call in pool.map(work, enumerate(todo)):
            if call is None:
                failed += 1
                continue
            record = statement_record(row, call, model)
            append_partial(partial, record)
            done[record.quarter_end] = record
            scored += 1
    if failed:
        raise RuntimeError(
            f"{ticker}: statements incomplete ({failed} failures); "
            "partial results retained for retry"
        )
    records = sorted(done.values(), key=lambda r: (r.quarter_end, r.available))
    stored = store.write_frame(
        statements.KIND,
        asof,
        ticker,
        statement_frame(records),
        {
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "observations": str(len(rows)),
            "inconsistent": str(sum(1 for r in records if not r.consistent)),
        },
    )
    if not stored:
        raise RuntimeError(
            f"{ticker}: statements frame already exists; partial results retained"
        )
    if partial.exists():
        partial.unlink()
    return scored, 0, len(records)


# Score every listed ticker; return how many observations were scored.
def score_tickers(
    store: MarketStore,
    tickers: Sequence[str],
    asof: date,
    *,
    llm_url: str = "",
    llm_model: str = "",
    concurrency: int = 4,
    deadline: float | None = None,
    since: date | None = SINCE,
) -> int:
    """Score the names into the as-of partition; a failed name is retried next run."""
    readers, model = clients(llm_url, llm_model, concurrency)
    started = time.time()
    total = 0
    incomplete: list[str] = []
    for position, ticker in enumerate(tickers):
        if deadline is not None and time.monotonic() > deadline:
            left = len(tickers) - position
            print(
                f"statements: time budget exhausted after {position} names; "
                f"{left} names not reached",
                flush=True,
            )
            break
        if current_frame_exists(store, ticker, asof, model):
            print(f"{ticker:6} kept", flush=True)
            continue
        t0 = time.time()
        try:
            scored, _failed, stored = score_ticker(
                store, ticker, asof, readers, model, deadline, since
            )
        except RuntimeError as exc:
            print(f"statements: {exc}", flush=True)
            incomplete.append(ticker)
            continue
        if stored < 0:
            print(f"{ticker:6} no filing versions stored; run market_fundamentals_asof")
            continue
        total += scored
        print(
            f"{ticker:6} ok      {scored:3d} scored, {stored:3d} stored, "
            f"{time.time() - t0:5.0f}s",
            flush=True,
        )
    if incomplete:
        print(
            f"statements: {len(incomplete)} names incomplete "
            f"({', '.join(incomplete)}); retried next run",
            flush=True,
        )
    print(
        f"partition {asof}: {total} observations scored in "
        f"{(time.time() - started) / 60:.1f} min"
    )
    return total


# --- plan and status ---------------------------------------------------------


# Count the observations per name, optionally writing every block.
def run_plan(
    store: MarketStore,
    tickers: Sequence[str],
    asof: date | None,
    blocks: Path | None,
    since: date | None = SINCE,
) -> dict[str, int]:
    """Return {ticker: observations}; -1 where no versions are stored."""
    out: dict[str, int] = {}
    handle = None
    if blocks is not None:
        blocks.parent.mkdir(parents=True, exist_ok=True)
        handle = blocks.open("w", encoding="utf-8")
    try:
        for ticker in tickers:
            rows = observations_for(store, ticker, asof, since)
            if rows is None:
                out[ticker] = -1
                print(f"{ticker:6} no filing versions stored")
                continue
            out[ticker] = len(rows)
            first = rows[0].quarter_end.isoformat() if rows else "-"
            last = rows[-1].quarter_end.isoformat() if rows else "-"
            print(f"{ticker:6} {len(rows):3d} observations {first} .. {last}")
            if handle is not None:
                for row in rows:
                    handle.write(
                        json.dumps(
                            {
                                "ticker": ticker,
                                "quarter_end": row.quarter_end.isoformat(),
                                "available": row.available.isoformat(),
                                "anchor": row.anchor,
                                "lines_present": row.lines_present,
                                "sha256": row.sha256,
                                "block": row.block,
                            }
                        )
                        + "\n"
                    )
    finally:
        if handle is not None:
            handle.close()
    calls = sum(n for n in out.values() if n > 0)
    names = sum(1 for n in out.values() if n > 0)
    print(f"{calls} model calls over {names} names")
    return out


# Report what the store holds per name.
def run_status(store: MarketStore, tickers: Sequence[str], asof: date | None) -> None:
    """Print one line per name from the newest statements frame."""
    for ticker in tickers:
        frame = store.read_frame(statements.KIND, ticker, asof)
        if frame is None:
            print(f"{ticker:6} MISSING")
            continue
        records = records_from_frame(frame[0])
        last = records[-1] if records else None
        print(
            f"{ticker:6} quarters={len(records):3d} "
            f"last={last.quarter_end if last else '-'} "
            f"p_up={last.probability if last else 0:.2f} "
            f"inconsistent={frame[1].get('inconsistent', '?')}"
        )


# --- evaluate ----------------------------------------------------------------


# The stored records of every name, from the newest frames.
def stored_records(
    store: MarketStore, tickers: Sequence[str]
) -> dict[str, tuple[StatementRecord, ...]]:
    """Return {ticker: records} for every name with a statements frame."""
    out: dict[str, tuple[StatementRecord, ...]] = {}
    for ticker in tickers:
        frame = store.read_frame(statements.KIND, ticker)
        if frame is not None:
            out[ticker] = records_from_frame(frame[0])
    return out


# The arm's (T, N) stance from the records: probability less one half,
# carried forward from the availability date.
def arm_stances(panel, records: Mapping[str, Sequence[StatementRecord]]) -> np.ndarray:
    """Return the (T, N) carried-forward stance of the arm."""
    return statements.aligned_stances(
        panel.dates,
        panel.tickers,
        {t: [(r.available, r.stance) for r in rs] for t, rs in records.items()},
    )


# One arm's harness numbers plus its per-period ICs, keyed by date (the
# tone-validity study's `_arm_result`).
def arm_result(scores, cells, panel, horizon) -> dict[str, Any]:
    """Return the harness report of `scores` on `cells` as a payload block."""
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


# Spearman correlation of two 1-D arrays, ties averaged, NaN when constant.
def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    ra, rb = average_rank(a), average_rank(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denominator = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    if denominator == 0:
        return float("nan")
    return float((ra * rb).sum() / denominator)


# The mean per-session Spearman correlation of two (T, N) scores over the
# cells both define, on sessions with at least `min_names` such cells.
def mean_cross_sectional_correlation(
    a: np.ndarray, b: np.ndarray, cells: np.ndarray, min_names: int = MIN_NAMES
) -> dict[str, float]:
    """Return {"mean": per-session mean, "sessions": count}."""
    both = cells & np.isfinite(a) & np.isfinite(b)
    values: list[float] = []
    for t in range(a.shape[0]):
        columns = np.flatnonzero(both[t])
        if len(columns) < min_names:
            continue
        rho = _spearman(a[t, columns], b[t, columns])
        if np.isfinite(rho):
            values.append(rho)
    return {
        "mean": float(np.mean(values)) if values else float("nan"),
        "sessions": int(len(values)),
    }


# Every arm on the cells all of them score inside one window: the harness
# numbers per arm, each arm's paired difference against the fundamental
# analyst, and the arm's correlation with both comparators.
def measure_window(
    arms: Mapping[str, np.ndarray], inside: np.ndarray, panel, horizon: int
) -> dict[str, Any]:
    """Return the window's results for `arms` on their shared cells."""
    cells = inside.copy()
    for scores in arms.values():
        cells &= np.isfinite(scores)
    results = {
        arm: arm_result(scores, cells, panel, horizon) for arm, scores in arms.items()
    }
    pairs = {}
    if ARM_FUNDAMENTAL in results:
        pairs = {
            arm: paired(
                results[ARM_FUNDAMENTAL]["period_ics"], results[arm]["period_ics"]
            )
            for arm in results
            if arm != ARM_FUNDAMENTAL
        }
    correlations = {}
    for comparator in (ARM_FUNDAMENTAL, ARM_VALUE):
        if comparator in arms:
            correlations[comparator] = {
                arm: mean_cross_sectional_correlation(arms[comparator], scores, cells)
                for arm, scores in arms.items()
                if arm not in (ARM_FUNDAMENTAL, ARM_VALUE)
            }
    return {
        "cells": int(cells.sum()),
        "arms": results,
        "paired_vs_fundamental": pairs,
        "correlation_with": correlations,
    }


# The null test: a constant 0.5 probability everywhere the arm is observed
# must read as a scoreless signal in every window and horizon (no defined
# period IC) and produce an empty stance table.
def null_test(panel, observed: np.ndarray, in_book: np.ndarray) -> dict[str, Any]:
    """Return {"pass": bool, "checks": [...]} for the constant arm."""
    constant = np.where(observed, 0.0, np.nan)
    ranks = Opinion(ARM_NULL, constant).ranks()
    checks: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        for name, (start, end) in WINDOWS.items():
            inside = window_mask(panel.dates, start, end)[:, None] & in_book[None, :]
            result = arm_result(ranks, inside & np.isfinite(ranks), panel, horizon)
            checks.append(
                {
                    "horizon": horizon,
                    "window": name,
                    "periods": result["periods"],
                    "defined_periods": result["defined_periods"],
                    "mean_ic_is_nan": bool(np.isnan(result["ic"])),
                    "ok": result["defined_periods"] == 0
                    and bool(np.isnan(result["ic"])),
                }
            )
    table = stance_table(panel, ranks)
    empty = len(table["ticker"]) == 0
    checks.append({"stance_table_empty": empty, "ok": empty})
    return {"pass": all(c["ok"] for c in checks), "checks": checks}


# The plan's criteria at the primary horizon, and the role.
def criteria(windows: Mapping[str, Any]) -> dict[str, Any]:
    """Return the evaluated criteria from the primary horizon's windows."""
    inside = windows["in_window"]
    post = windows["post_window"]
    r = inside["arms"][ARM_A2]
    r_post = post["arms"].get(ARM_A2, {})
    pair = inside["paired_vs_fundamental"].get(
        ARM_A2, {"delta": float("nan"), "t": float("nan")}
    )
    ic, t = r["ic"], r["t"]
    ic_post, t_post = r_post.get("ic", float("nan")), r_post.get("t", float("nan"))
    clears = bool(
        np.isfinite(ic) and ic >= IC_FLOOR and np.isfinite(t) and t >= T_FLOOR
    )
    post_ok = not bool(
        np.isfinite(ic_post)
        and ic_post < 0
        and np.isfinite(t_post)
        and t_post <= NOT_NEGATIVE_T
    )
    not_worse = not bool(
        np.isfinite(pair["delta"])
        and pair["delta"] < 0
        and np.isfinite(pair["t"])
        and pair["t"] <= NOT_NEGATIVE_T
    )
    corr = {
        comparator: block.get(ARM_A2, {}).get("mean", float("nan"))
        for comparator, block in inside["correlation_with"].items()
    }
    low = [
        c for c, v in corr.items() if np.isfinite(v) and v < SIXTH_ANALYST_CORRELATION
    ]
    if len(low) == len(corr) and corr:
        role = "sixth analyst"
    elif corr:
        high = [c for c in corr if c not in low]
        role = f"replacement candidate for the {' and '.join(high)}"
    else:
        role = "undetermined (no comparator)"
    return {
        "ic_in_window": ic,
        "t_in_window": t,
        "ic_post_window": ic_post,
        "t_post_window": t_post,
        "paired_delta_vs_fundamental": pair["delta"],
        "paired_t_vs_fundamental": pair["t"],
        "correlation_with": corr,
        "1_clears_ic_floor": clears,
        "2_post_window_not_negative": post_ok,
        "3_not_worse_than_fundamental": not_worse,
        "role": role,
        "ic_post_evaluable": bool(np.isfinite(ic_post)),
    }


# The one-line reading of the criteria, in the plan's order.
def verdict(crit: Mapping[str, Any], null_pass: bool) -> str:
    """Return the verdict line per the plan."""
    if not null_pass:
        return "INVALID: the null test failed; nothing here is comparable"
    if (
        crit["1_clears_ic_floor"]
        and crit["2_post_window_not_negative"]
        and crit["3_not_worse_than_fundamental"]
    ):
        return (
            f"CANDIDATE ({crit['role']}): clears the IC floor in-window, the "
            "post-cutoff window does not contradict it, not worse than the "
            "fundamental analyst; proposed as a stance only if the T-S1 book "
            "gate holds (pending)"
        )
    return "RECORD"


# The direction-accuracy report: the model's call against the realised
# year-over-year sign of the anchor one quarter on, overall and post-cutoff,
# beside the paper's number and the persistence baseline; sequential too.
def accuracy_report(
    records: Mapping[str, Sequence[StatementRecord]],
    rows: Mapping[str, Sequence[statements.Observation]],
) -> dict[str, Any]:
    """Return the accuracy payload; decides nothing."""
    tallies: dict[str, dict[str, int]] = {
        "all": _tally(),
        "post_window": _tally(),
        "in_window": _tally(),
    }
    for ticker, stored in records.items():
        found = {r.quarter_end: r for r in rows.get(ticker, ())}
        realised = dict(
            zip(
                [r.quarter_end for r in rows.get(ticker, ())],
                statements.realised_directions(list(rows.get(ticker, ()))),
                strict=True,
            )
        )
        for record in stored:
            row = found.get(record.quarter_end)
            yoy, seq = realised.get(record.quarter_end, (None, None))
            if row is None or yoy is None or yoy == 0:
                continue
            call = 1 if record.direction == "up" else -1
            persist = statements.persistence_direction(row)
            windows = [
                "all",
                "post_window" if record.available >= POST_WINDOW[0] else "in_window",
            ]
            for name in windows:
                tally = tallies[name]
                tally["n"] += 1
                tally["correct"] += int(call == yoy)
                tally["up_calls"] += int(call == 1)
                tally["realised_up"] += int(yoy == 1)
                if persist is not None and persist != 0:
                    tally["persistence_n"] += 1
                    tally["persistence_correct"] += int(persist == yoy)
                if seq is not None and seq != 0:
                    tally["sequential_n"] += 1
                    tally["sequential_correct"] += int(call == seq)
    out: dict[str, Any] = {"paper_accuracy": PAPER_ACCURACY, "windows": {}}
    for name, tally in tallies.items():
        out["windows"][name] = {
            **tally,
            "accuracy": _ratio(tally["correct"], tally["n"]),
            "persistence_accuracy": _ratio(
                tally["persistence_correct"], tally["persistence_n"]
            ),
            "sequential_accuracy": _ratio(
                tally["sequential_correct"], tally["sequential_n"]
            ),
            "share_up_calls": _ratio(tally["up_calls"], tally["n"]),
            "share_realised_up": _ratio(tally["realised_up"], tally["n"]),
        }
    return out


# An empty tally.
def _tally() -> dict[str, int]:
    return {
        "n": 0,
        "correct": 0,
        "up_calls": 0,
        "realised_up": 0,
        "persistence_n": 0,
        "persistence_correct": 0,
        "sequential_n": 0,
        "sequential_correct": 0,
    }


# A fraction, NaN when the denominator is zero.
def _ratio(a: int, b: int) -> float:
    return float(a) / b if b else float("nan")


# The arm's stance table in long form: (session, ticker, stance) for every
# non-zero stance under the analyst's own rule, for the scorecard follow-up.
def stance_table(panel, ranks: np.ndarray) -> dict[str, list]:
    """Return the columns of the arm's stance table."""
    scores = np.where(np.isfinite(ranks), ranks, np.nan)
    stances = Opinion("arm", scores).stances()
    t_index, n_index = np.nonzero(stances != 0)
    return {
        "session": [str(panel.dates[t]) for t in t_index],
        "ticker": [panel.tickers[n] for n in n_index],
        "stance": [int(stances[t, n]) for t, n in zip(t_index, n_index, strict=True)],
    }


# Write a column table as parquet (pyarrow, imported here as the store does).
def write_table(path: Path, columns: Mapping[str, list]) -> None:
    """Write `columns` to `path` as one parquet file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({k: pa.array(v) for k, v in columns.items()}), path)


# The comparators as the desk builds them: the fundamental analyst on the
# corrected source and the value analyst on the point-in-time levels.
def comparator_ranks(store: MarketStore, panel, sides) -> dict[str, np.ndarray]:
    """Return {arm: (T, N) ranks} for the fundamental and value analysts."""
    from backend.agents.trading.desk import desk, value
    from backend.market.levels_pit import point_in_time_levels

    fundamental = desk._fundamental_opinion(
        store, panel, None, desk.FUNDAMENTALS_CORRECTED
    )
    valuation = value.opine(panel, point_in_time_levels(store, panel, None), sides)
    return {ARM_FUNDAMENTAL: fundamental.ranks(), ARM_VALUE: valuation.ranks()}


# Measure the arm with its comparators; return the payload.
def evaluate_arm(
    panel,
    sides: Mapping[str, str],
    arm: np.ndarray,
    comparators: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    """Return the study payload: null test, windows per horizon, criteria, verdict."""
    in_book = np.array([t in sides for t in panel.tickers])
    observed = np.isfinite(arm) & in_book[None, :]
    null = null_test(panel, observed, in_book)
    arms = {ARM_A2: Opinion(ARM_A2, arm).ranks(), **comparators}
    payload: dict[str, Any] = {
        "windows": {
            k: [s.isoformat(), e.isoformat() if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "null_test": null,
        "horizons": {},
    }
    for horizon in HORIZONS:
        per_window: dict[str, Any] = {}
        for name, (start, end) in WINDOWS.items():
            inside = window_mask(panel.dates, start, end)[:, None] & in_book[None, :]
            per_window[name] = measure_window(arms, inside, panel, horizon)
        payload["horizons"][str(horizon)] = per_window
    payload["criteria"] = criteria(payload["horizons"][str(PRIMARY_HORIZON)])
    payload["verdict"] = verdict(payload["criteria"], null["pass"])
    return payload


# The payload, printed.
def print_payload(payload: Mapping[str, Any]) -> None:
    """Print the null test, the arms per horizon and window, the criteria."""
    null = payload["null_test"]
    print(
        f"null test (constant 0.5 reads as scoreless): "
        f"{'PASS' if null['pass'] else 'FAIL'} over {len(null['checks'])} checks"
    )
    for horizon in HORIZONS:
        for name, window in payload["horizons"][str(horizon)].items():
            print(f"\n=== horizon {horizon}, {name}: {window['cells']:,} cells ===")
            print(
                f"{'arm':24} {'rank IC':>9} {'t':>7} {'net Sharpe':>11} {'periods':>8}"
            )
            for arm, r in window["arms"].items():
                print(
                    f"{arm:24} {r['ic']:+9.4f} {r['t']:+7.2f} "
                    f"{r['net_sharpe']:+11.2f} {r['periods']:8d}"
                )
            for arm, p in window["paired_vs_fundamental"].items():
                print(
                    f"  {arm} - fundamental: {p['delta']:+.4f} (paired t {p['t']:+.2f})"
                )
            for comparator, block in window["correlation_with"].items():
                for arm, c in block.items():
                    print(
                        f"  rank correlation of {arm} with {comparator}: "
                        f"{c['mean']:+.3f}"
                    )
    crit = payload["criteria"]
    print("\n=== criteria (primary horizon) ===")
    print(
        f"IC in-window {crit['ic_in_window']:+.4f} (t {crit['t_in_window']:+.2f}); "
        f"post {crit['ic_post_window']:+.4f} (t {crit['t_post_window']:+.2f}); "
        f"paired vs fundamental {crit['paired_delta_vs_fundamental']:+.4f} "
        f"(t {crit['paired_t_vs_fundamental']:+.2f}); role {crit['role']}"
    )
    acc = payload.get("accuracy")
    if acc:
        print("\n=== direction accuracy (decides nothing) ===")
        for name, block in acc["windows"].items():
            print(
                f"{name:12} n={block['n']:4d} model {block['accuracy']:.3f} "
                f"persistence {block['persistence_accuracy']:.3f} "
                f"sequential {block['sequential_accuracy']:.3f} "
                f"(paper {acc['paper_accuracy']:.3f})"
            )
    print(f"\nVERDICT: {payload['verdict']}")


# Read the store, measure, write the payload and the stance table.
def run_evaluate(root: Path, out: Path, stances: Path | None) -> dict[str, Any]:
    """Evaluate the stored statements frames; return the payload."""
    from backend.agents.trading.desk.desk import book_panel

    store = MarketStore(root)
    panel, sides = book_panel(store)
    book = [t for t in panel.tickers if t in sides]
    records = stored_records(store, book)
    if not records:
        raise SystemExit("no edgar_statements frames in the store")
    arm = arm_stances(panel, records)
    payload = evaluate_arm(panel, sides, arm, comparator_ranks(store, panel, sides))
    rows = {t: observations_for(store, t) or [] for t in records}
    payload["accuracy"] = accuracy_report(records, rows)
    payload["names_scored"] = len(records)
    payload["observations_scored"] = sum(len(r) for r in records.values())
    payload["inconsistent_answers"] = sum(
        1 for rs in records.values() for r in rs if not r.consistent
    )
    stance_root = stances or out.parent / STANCE_DIR
    table_path = stance_root / "A2.parquet"
    write_table(table_path, stance_table(panel, Opinion(ARM_A2, arm).ranks()))
    payload["stance_table"] = str(table_path)
    payload["scorecard_follow_up"] = SCORECARD_FOLLOW_UP.format(
        table=table_path, output=out.parent / "pit_scorecard_A2.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print_payload(payload)
    return payload


# Run the tool.
def main() -> None:
    """Entry point: one subcommand per step of the study."""
    args = build_parser().parse_args()
    if args.command == "evaluate":
        run_evaluate(args.root, args.out, args.stances)
        return
    store = MarketStore(args.root)
    tickers = select_tickers(args)
    if args.command == "plan":
        run_plan(store, tickers, args.asof, args.blocks, args.since)
    elif args.command == "score":
        asof = args.asof or datetime.now(tz=UTC).date()
        deadline = (
            time.monotonic() + args.deadline_minutes * 60
            if args.deadline_minutes is not None
            else None
        )
        score_tickers(
            store,
            tickers,
            asof,
            llm_url=args.llm_url,
            llm_model=args.llm_model,
            concurrency=args.concurrency,
            deadline=deadline,
            since=args.since,
        )
    elif args.command == "status":
        run_status(store, tickers, args.asof)


if __name__ == "__main__":
    main()
