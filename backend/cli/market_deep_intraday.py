"""Deep intraday, stage 1: a small sequence model on five sessions of bars.

    python -m backend.cli.market_deep_intraday --root data/market
    python -m backend.cli.market_deep_intraday --models ridge --json

Loads one session cube per book name from the raw-basis SIP store
(`market_session_anatomy.load_cubes`, cached under
`<root>/research/sip_cubes/`), builds the point-in-time membership mask
from the dated history, runs the desk once for the grades (the A/A+
restriction of the portfolio test), assembles the dataset
(`deep_intraday.dataset`), walks each requested model forward on both
targets, prints one table row per (window, model, target) and the verdict
the plan fixes, and writes `<root>/desk/deep_intraday.json`.

The protocol and the kill criteria are the pre-registration
`docs/research/deep-intraday-plan-2026-09-27.md`, implemented in
`backend/market/deep_intraday.py`. The choosing window is 2016-2023;
2024-2026 is reported, never tuned on. Nothing here trades.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.agents.trading.desk import grading
from backend.cli.market_intraday_sip import select_tickers
from backend.cli.market_session_anatomy import (
    DEFAULT_WORKERS,
    load_cubes,
    membership_mask,
)
from backend.market import deep_intraday, session_anatomy, universe
from backend.market.deep_intraday import Dataset
from backend.market.store import MarketStore

FILE = "deep_intraday.json"
# The desk grade the A/A+ portfolio test keeps.
A_MIN_GRADE = grading.ORDINAL[grading.A]
# A grade unknown to the desk (name or date outside its panel).
NO_GRADE = -1


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the stage-1 study."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--tickers", default="", help="comma-separated; default: the book"
    )
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time mask",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="processes building cubes in parallel (1 = in this process)",
    )
    parser.add_argument(
        "--models",
        default=",".join(deep_intraday.MODELS),
        help="comma-separated subset of ridge,cnn",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# The requested models, validated.
def parse_models(spec: str) -> tuple[str, ...]:
    """Return the model names in `spec`, in order, each once."""
    models = tuple(
        dict.fromkeys(m.strip().lower() for m in spec.split(",") if m.strip())
    )
    unknown = [m for m in models if m not in deep_intraday.MODELS]
    if unknown or not models:
        raise SystemExit(
            "--models must name a subset of"
            f" {','.join(deep_intraday.MODELS)}, got {spec!r}"
        )
    return models


# The desk as the study reads it: the live rule's report on the store.
def default_desk(store: MarketStore) -> Any:
    """Return the desk report for the store."""
    from backend.agents.trading.desk import desk

    return desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))


# The desk grade of every dataset row: `report.graded.grades[t, name]` on
# the row's session, `NO_GRADE` where the desk has no column or session.
def grades_for(ds: Dataset, report: Any) -> np.ndarray:
    """Return the (M,) grade ordinals."""
    panel = report.panel
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    column = {t: j for j, t in enumerate(panel.tickers)}
    out = np.full(len(ds), NO_GRADE, dtype=int)
    position = np.searchsorted(days, ds.dates)
    inside = position < len(days)
    found = np.zeros(len(ds), dtype=bool)
    found[inside] = days[position[inside]] == ds.dates[inside]
    for ticker in np.unique(ds.tickers):
        j = column.get(str(ticker))
        if j is None:
            continue
        rows = (ds.tickers == ticker) & found
        out[rows] = report.graded.grades[position[rows], j]
    return out


# A signed number, or a dash.
def _f(value: float | None, digits: int = 2, sign: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"


# One table row of the results.
def _row(r: dict[str, Any]) -> str:
    ic = r["ic"] or {}
    portfolio = r["portfolio"] or {}
    a_only = r["portfolio_a"] or {}
    control = r["control"] or {}
    vol = r["vol_r2"] or {}
    return (
        f"  {r['window']:<10}{r['model']:<7}{r['target']:<6}{r['rows']:>8}"
        f"{_f(ic.get('mean'), 4):>9}{_f(ic.get('t')):>7}"
        f"{_f(portfolio.get('mean_bp'), 1):>9}{_f(portfolio.get('hurdle_bp'), 1):>9}"
        f"{_f(portfolio.get('t')):>7}"
        f"{_f(a_only.get('mean_bp'), 1):>9}{_f(a_only.get('hurdle_bp'), 1):>9}"
        f"{_f(a_only.get('t')):>7}"
        f"{_f(control.get('t')):>8}{_f(vol.get('r2'), 4):>9}"
    )


# The payload as readable text: the dataset line, the table, the verdict.
def render(payload: dict[str, Any]) -> str:
    """Return the study as text."""
    ds = payload["dataset"]
    lines = [
        f"deep intraday, stage 1 (study v{payload['version']}; choosing window"
        f" {payload['choosing_window']}; trials {payload['trials']})",
        f"  dataset: {ds['rows']:,} rows, {ds['names']} names,"
        f" {ds['sessions']:,} sessions"
        f" {ds['first']}..{ds['last']}; per window "
        + ", ".join(f"{k} {v:,}" for k, v in ds["rows_per_window"].items())
        + (
            f"; graded A/A+ rows {ds['graded_rows']:,}"
            if ds.get("graded_rows") is not None
            else "; no desk grades"
        ),
    ]
    for name, count in payload.get("parameters", {}).items():
        lines.append(f"  {name} parameters: {count:,}")
    for key, fits in payload.get("fits", {}).items():
        if fits:
            seconds = sum(f["seconds"] for f in fits)
            lines.append(
                f"  {key}: {len(fits)} fits, {seconds:.0f} s in all,"
                f" first test {fits[0]['test_start']}"
            )
    lines.append(
        f"  {'window':<10}{'model':<7}{'tgt':<6}{'rows':>8}{'IC':>9}{'IC t':>7}"
        f"{'top bp/d':>9}{'hurdle':>9}{'t':>7}{'A bp/d':>9}{'A hurdle':>9}{'t':>7}"
        f"{'ctrl t':>8}{'vol R2':>9}"
    )
    for r in payload["results"]:
        lines.append(_row(r))
    lines.append(
        f"  (top: equal weight of the top {payload['constants']['top_quantile']:.0%} by"
        f" forecast, next-session open to close,"
        f" {payload['constants']['cost_bps']:.0f} bp one way on entries and exits,"
        " minus equal weight of every eligible name; t is Newey-West at lag"
        f" {payload['constants']['hac_lag']} on the daily series)"
    )
    for line in payload.get("verdict_detail", []):
        lines.append(f"  {line}")
    lines.append(f"verdict: {payload['verdict']}")
    return "\n".join(lines)


# The A/A+ row mask from the desk's grades, or None with a note when the
# desk could not run: the study then scores without the A-only line and
# the payload says so, rather than stopping a night's run on a data fault.
def graded_rows(
    ds: Dataset,
    store: MarketStore,
    desk_run: Callable[[MarketStore], Any],
    say: Callable[[str], None],
) -> tuple[np.ndarray | None, str | None]:
    """Return (keep_a mask or None, note or None)."""
    try:
        report = desk_run(store)
        grades = grades_for(ds, report)
    except Exception as exc:  # noqa: BLE001 - reported, and the A-only line left unscored
        note = f"desk not run ({type(exc).__name__}: {exc}); A/A+ portfolio not scored"
        say(note)
        return None, note
    keep_a = grades >= A_MIN_GRADE
    say(
        f"desk grades: {int((grades != NO_GRADE).sum()):,} rows graded,"
        f" {int(keep_a.sum()):,} A/A+"
    )
    return keep_a, None


# Walk every requested model forward on both targets; the CNN is skipped
# with a note where torch cannot be imported. Returns (forecasts, notes).
def forecast_all(
    ds: Dataset, models: tuple[str, ...], say: Callable[[str], None]
) -> tuple[dict[tuple[str, str], deep_intraday.Forecast], list[str]]:
    """Return {(model, target): Forecast} and the skipped-model notes."""
    forecasts: dict[tuple[str, str], deep_intraday.Forecast] = {}
    skipped: list[str] = []
    for model in models:
        if model == "cnn":
            try:
                import torch  # noqa: F401
            except ImportError:
                skipped.append("cnn: torch is not importable here")
                say(skipped[-1])
                continue
        for target in deep_intraday.TARGETS:
            say(f"{model}/{target}: walking forward")
            forecasts[(model, target)] = deep_intraday.walk_forward(
                ds, model, target, log=say
            )
    return forecasts, skipped


# Load, mask, grade, build, walk forward, score, write, print. `desk_run`
# returns the desk report for a store; the default runs the live rule.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the study for the parsed arguments; return the exit code."""
    root = Path(args.root)
    store = MarketStore(root)
    models = parse_models(args.models)
    tickers = tuple(
        t for t in select_tickers(args.tickers) if t not in session_anatomy.BENCHMARKS
    )
    quiet = bool(args.json)

    # Progress lines, silenced under --json so the output stays JSON.
    def say(text: str) -> None:
        if not quiet:
            print(text, file=out)

    cubes, lines = load_cubes(store, tickers, workers=max(1, args.workers))
    say(f"cubes from {root} ({len(tickers)} tickers requested):")
    for line in lines:
        say(line)
    if not cubes:
        print("no complete sessions in the store; nothing to study", file=out)
        return 1
    mask = membership_mask(cubes, args.membership)
    began = time.perf_counter()
    ds = deep_intraday.dataset(cubes, mask)
    say(
        f"dataset: {len(ds):,} rows,"
        f" {len(np.unique(ds.tickers)) if len(ds) else 0} names,"
        f" {len(ds.sessions):,} sessions, {time.perf_counter() - began:.1f} s"
    )
    if len(ds) == 0:
        print(
            "no rows after the membership and completeness rules; nothing to study",
            file=out,
        )
        return 1
    keep_a, grade_note = graded_rows(ds, store, desk_run or default_desk, say)
    forecasts, skipped = forecast_all(ds, models, say)
    payload = deep_intraday.study(ds, forecasts, keep_a)
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["models"] = list(models)
    payload["skipped"] = skipped
    payload["grade_note"] = grade_note
    payload["exclusions"] = {t: c.excluded for t, c in cubes.items()}
    payload["sessions_per_ticker"] = {t: len(c) for t, c in cubes.items()}
    payload["asof"] = str(max(c.dates[-1] for c in cubes.values()))
    path = root / "desk" / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    if quiet:
        print(json.dumps(payload, indent=2, allow_nan=False), file=out)
    else:
        print(render(payload), file=out)
        print(f"\nwrote {path}", file=out)
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
