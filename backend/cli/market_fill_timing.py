"""The fill-timing trial: the `/4` policy's orders under seven fill conventions.

    python -m backend.cli.market_fill_timing --root data/market --workers 8
    python -m backend.cli.market_fill_timing --tickers AVGO,NVDA --offsets 5 --json
    python -m backend.cli.market_fill_timing --root data/market --workers 8 \
        --forecasts docs/research/scorecards/vol_forecasts.npz \
        --only next_open,dip_or_close,vol_dip_0.5,vol_dip_1.0,vol_limit_0.5,trail_dip

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file), loads one SIP
session cube per name (`market_session_anatomy.load_cubes`, cached under
`<root>/research/sip_cubes/`), and runs `fill_timing.study`: the plain
simulator's orders for `graded-equal-weight/4` priced at each of the seven
conventions fixed in `docs/research/execution-timing-plan-2026-09-27.md`,
from every start offset, at one cost. Prints a table (convention x window:
median CAGR, bp a day against `next_open`, its Newey-West t, offsets above
the control, deferrals and fallbacks), the best convention's deflated
Sharpe, the gap between this engine's control and `simulate.run`, and the
verdict under the plan's kill criteria. Writes `<root>/desk/fill_timing.json`.

`--forecasts <npz>` (the file `market_vol_forecast` writes) adds the four
entry-level conventions of `docs/research/ml-entry-level-plan-2026-09-28.md`:
levels k * sigma from the open with sigma the CNN's next-session volatility
forecast (or the trailing baseline, `trail_dip`), judged against the board's
`dip_or_close`. `--only` prices the conventions named plus the controls the
verdicts read. With a level convention priced the table gains the
entry-level block (bp a day against `dip_or_close`, `next_open` and
`trail_dip`, offsets above `dip_or_close`, the dip fill rate, the gain per
dip fill and per order over the session's close, the sigma fallbacks), the
payload records the forecast file's sha256, and it is written to
`<root>/desk/ml_entry_level.json` so the fill-timing payload is left alone.

`--only level_dip,level_dip_confluence` prices the support/resistance
trial of `docs/research/sr-levels-plan-2026-09-29.md`. It needs no forecasts.
A buy waits for a bar close inside the zone of one of 22 point-in-time levels
below the prior bar's close while below the session open, else it fills at the
close. The confluence variant needs at least two distinct levels in the zone.
Both are judged against `dip_or_close` (added automatically). The table gains
the SR block: bp a day against `dip_or_close` and `next_open`, the fill rate
at a level, and the gain per level fill and per order over the session's
close. The payload goes to `<root>/desk/sr_level_fill.json`.

    python -m backend.cli.market_fill_timing --root data/market --workers 8 \
        --offsets 20 --cost 10 --only level_dip,level_dip_confluence

`--stage3-forecast <family>=<npz>` (repeatable; `lgbm` or `seq`, each a
T-I `stage3_io.Stage3Forecast`) prices the stage-3 T-I trial of
`docs/research/stage3-plan-2026-09-29.md`: `<family>_filter` (the board's
1% trigger with the model's veto) and `<family>_free` (the model picks the
slot), each paired against `dip_or_close` (added automatically). The table
gains the T-I block per window - the model window from the family's first
forecast session through 2023, 2016-2023 and 2024-2026 - and the payload
records each file's path and sha256 and this run's reading. `--next-bar`
is the plan's robustness run (every bar-close fill moves to the next bar's
open, candidate and control alike); `--seed-column K` prices seed K's
column of every forecast instead of the ensemble (the seed-stability runs).
The payload goes to `--out`, or by default to
`<root>/desk/stage3_ti_fill_<cost>bp[_next_bar][_seed<K>].json`, so the
runs the verdict reads (10, 16 and 25 bp, the next-bar run and five seeds,
`stage3_verdict.ti_verdict`) do not overwrite each other.

    python -m backend.cli.market_fill_timing --root data/market --workers 8 \
        --offsets 20 --cost 10 \
        --stage3-forecast lgbm=research/stage3/ti_lgbm.npz \
        --stage3-forecast seq=research/stage3/ti_seq.npz \
        --only dip_or_close,lgbm_filter,lgbm_free,seq_filter,seq_free

Nothing here trades or changes the executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from backend.agents.trading.desk import point_in_time
from backend.cli.market_session_anatomy import DEFAULT_WORKERS, load_cubes
from backend.market import fill_timing, stage3_io, universe, vol_forecast
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "fill_timing.json"
# Where a run with a level convention writes, beside the fill-timing payload.
LEVEL_FILE = "ml_entry_level.json"
# Where a run with an SR convention writes, beside both.
SR_FILE = "sr_level_fill.json"
# Where a stage-3 T-I run writes by default: one file per cost, fill mode
# and seed column, so the runs the verdict reads sit side by side.
TI_FILE = "stage3_ti_fill_{cost}bp{mode}{seed}.json"


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the fill-timing trial."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--tickers",
        default="",
        help="comma-separated names to load cubes for; default: every panel name",
    )
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="processes building cubes in parallel (1 = in this process)",
    )
    parser.add_argument(
        "--offsets", type=int, default=20, help="start offsets on the 20-session clock"
    )
    parser.add_argument(
        "--cost",
        type=float,
        default=fill_timing.COST_BPS[0],
        help="one-way cost in basis points on every fill",
    )
    parser.add_argument(
        "--forecasts",
        type=Path,
        default=None,
        help="volatility forecast npz (market_vol_forecast): adds the level trial",
    )
    parser.add_argument(
        "--only",
        default="",
        help=(
            "comma-separated conventions to price (the controls the verdicts read "
            "are always added); default: the fill-timing seven, plus the level four "
            "with --forecasts and the T-I pair of every --stage3-forecast family; "
            "the SR pair (level_dip, level_dip_confluence) only when named"
        ),
    )
    parser.add_argument(
        "--stage3-forecast",
        action="append",
        default=[],
        metavar="FAMILY=NPZ",
        help=(
            "a stage-3 T-I forecast file for a family (lgbm or seq), repeatable: "
            "adds <family>_filter and <family>_free against dip_or_close"
        ),
    )
    parser.add_argument(
        "--next-bar",
        action="store_true",
        help=(
            "robustness run: every fill at a bar close moves to the next bar's "
            "open (a fill at the last bar goes to the official close)"
        ),
    )
    parser.add_argument(
        "--seed-column",
        type=int,
        default=None,
        help="price seed K's column of every stage-3 forecast instead of the ensemble",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="where to write the payload (default: under <root>/desk/)",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# The `--stage3-forecast FAMILY=NPZ` values as {family: path}; a malformed
# value or a family given twice is refused.
def _stage3_files(values: list[str]) -> dict[str, Path]:
    """Return {family: forecast path} from the repeated option."""
    files: dict[str, Path] = {}
    for value in values or []:
        family, sep, path = str(value).partition("=")
        family = family.strip()
        if not sep or not family or not path.strip():
            raise ValueError(f"--stage3-forecast wants FAMILY=NPZ, not {value!r}")
        if family in files:
            raise ValueError(f"--stage3-forecast gives {family} twice")
        files[family] = Path(path.strip())
    return files


# The file a run writes: `--out` when given; a stage-3 T-I run's own name
# by cost, fill mode and seed column; else the trial's file, as before.
def _target(args: argparse.Namespace, root: Path, payload: dict[str, Any]) -> Path:
    """Return the payload's destination path."""
    if getattr(args, "out", None) is not None:
        return Path(args.out)
    if "stage3_ti" in payload:
        seed = payload["stage3_ti"].get("seed_column")
        return (
            root
            / "desk"
            / TI_FILE.format(
                cost=f"{float(payload['cost_bps']):g}",
                mode="_next_bar" if payload.get("next_bar") else "",
                seed="" if seed is None else f"_seed{int(seed)}",
            )
        )
    if "sr_level" in payload:
        return root / "desk" / SR_FILE
    return root / "desk" / (LEVEL_FILE if "level" in payload else FILE)


# The `--only` list as convention names, or None when it names none.
def _only(text: str) -> tuple[str, ...] | None:
    """Return the names in the comma-separated `text`, None when empty."""
    names = tuple(dict.fromkeys(c.strip() for c in text.split(",") if c.strip()))
    return names or None


# The sha256 of a file's bytes, read in chunks.
def _sha256(path: Path) -> str:
    """Return the hex sha256 of the file at `path`."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# The desk report for the store, the way every published curve gets it.
def default_desk(store: MarketStore) -> Any:
    """Return the desk report for the store."""
    from backend.agents.trading.desk import desk

    return desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))


# A fraction as a percentage string, "n/a" for NaN.
def _pct(x: float | None) -> str:
    return "n/a" if x is None or x != x else f"{x * 100:.1f}%"


# A signed number to two decimals, "n/a" for NaN.
def _num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:+.{digits}f}"


# The entry-level block: per window, the controls and the level
# conventions against the board's rule, the open and the trailing twin,
# with what their orders did; the deflated best; the verdict lines.
def _render_level(payload: dict[str, Any]) -> list[str]:
    """Return the entry-level trial's lines."""
    level = payload["level"]
    shown = (fill_timing.CONTROL, level["control"], *level["conventions"])
    lines = [
        f"\nentry-level trial: levels k * sigma from the open against "
        f"{level['control']} (the board's rule); twin {level['twin']}; forecasts from "
        f"{level['first_forecast_session'] or 'never'}"
    ]
    for window in payload["windows"]:
        lines.append(f"\n{window}")
        lines.append(
            f"  {'convention':<15}{'CAGR':>7}{'vs dip':>8}{'bp/d':>7}{'t':>7}"
            f"{'>dip':>6}{'vs open':>9}{'t':>7}{'vs twin':>9}{'dip%':>7}"
            f"{'bp/fill':>9}{'bp/ord':>8}{'no-sig':>8}"
        )
        for row in payload["rows"]:
            if row["window"] != window or row["convention"] not in shown:
                continue
            lines.append(
                f"  {row['convention']:<15}{_pct(row['median_cagr']):>7}"
                f"{_pct(row['median_cagr_vs_dip']):>8}"
                f"{_num(row['mean_daily_bp_vs_dip'], 1):>7}"
                f"{_num(row['hac_t_vs_dip']):>7}"
                f"{row['offsets_above_dip']:>6}"
                f"{_num(row['mean_daily_bp_vs_open'], 1):>9}"
                f"{_num(row['hac_t_vs_open']):>7}"
                f"{_num(row['mean_daily_bp_vs_twin'], 1):>9}"
                f"{_pct(row['dip_fill_rate']):>7}"
                f"{_num(row['gain_bp_per_dip_fill'], 1):>9}"
                f"{_num(row['gain_bp_per_order'], 1):>8}"
                f"{_pct(row['sigma_fallback_share']):>8}"
            )
        best = level["best"].get(window, {})
        if best.get("convention"):
            lines.append(
                f"  best: {best['convention']} "
                f"{_num(best['mean_daily_bp_vs_dip'], 1)} bp/d over "
                f"{level['control']}, "
                f"t {_num(best['hac_t_vs_dip'])}, deflated Sharpe "
                f"{_num(best['deflated_sharpe'])} against {best['trials']} trials"
            )
    lines.append(
        "  (bp/d and t: paired daily difference at the median offset, Newey-West; "
        "dip%: orders filled at the level before the close; bp/fill, bp/ord: gain "
        "over that session's close per dip fill and per order; no-sig: orders "
        "with no sigma, filled as dip_or_close)"
    )
    return lines


# The SR block: per window, the board's rule and the SR conventions against
# dip_or_close and the open, with what their orders did at a level; the
# deflated best; the verdict comes with the other verdict lines.
def _render_sr(payload: dict[str, Any]) -> list[str]:
    """Return the SR trial's lines."""
    block = payload["sr_level"]
    shown = (fill_timing.CONTROL, block["control"], *block["conventions"])
    lines = [
        "\nsupport/resistance trial: a buy at the first 10:15-on close inside a "
        "level's zone below the open (sells mirror), against "
        f"{block['control']} (the board's rule)"
    ]
    for window in payload["windows"]:
        lines.append(f"\n{window}")
        lines.append(
            f"  {'convention':<22}{'CAGR':>7}{'vs dip':>8}{'bp/d':>7}{'t':>7}"
            f"{'>dip':>6}{'vs open':>9}{'t':>7}{'at lvl':>8}"
            f"{'bp/fill':>9}{'bp/ord':>8}"
        )
        for row in payload["rows"]:
            if row["window"] != window or row["convention"] not in shown:
                continue
            lines.append(
                f"  {row['convention']:<22}{_pct(row['median_cagr']):>7}"
                f"{_pct(row['median_cagr_vs_dip']):>8}"
                f"{_num(row['mean_daily_bp_vs_dip'], 1):>7}"
                f"{_num(row['hac_t_vs_dip']):>7}"
                f"{row['offsets_above_dip']:>6}"
                f"{_num(row['mean_daily_bp_vs_open'], 1):>9}"
                f"{_num(row['hac_t_vs_open']):>7}"
                f"{_pct(row['dip_fill_rate']):>8}"
                f"{_num(row['gain_bp_per_dip_fill'], 1):>9}"
                f"{_num(row['gain_bp_per_order'], 1):>8}"
            )
        best = block["best"].get(window, {})
        if best.get("convention"):
            lines.append(
                f"  best: {best['convention']} "
                f"{_num(best['mean_daily_bp_vs_dip'], 1)} bp/d over "
                f"{block['control']}, t {_num(best['hac_t_vs_dip'])}, deflated "
                f"Sharpe {_num(best['deflated_sharpe'])} against "
                f"{best['trials']} trials"
            )
    lines.append(
        "  (bp/d and t: paired daily difference at the median offset, Newey-West; "
        "at lvl: orders filled at a level (for dip_or_close, at its 1% dip) before "
        "the close; bp/fill, bp/ord: gain over that session's close per level fill "
        "and per order)"
    )
    return lines


# The payload as a table people can read.
def render(payload: dict[str, Any]) -> str:
    """Return the trial's table, best lines, gap and verdict as text."""
    lines = [
        f"fill-timing trial for {payload['policy']} at {payload['cost_bps']:g} bp, "
        f"{payload['offsets']} offsets (paired statistics at offset "
        f"{payload['median_offset']})"
    ]
    cover = payload["cube_coverage"]
    lines.append(
        f"cubes: {cover['names_with_cube']} of {cover['names_in_panel']} panel names"
    )
    # The fill-timing trial is judged only on its whole registered set.
    judged = set(fill_timing.CONVENTIONS) <= set(payload["conventions"])
    for window in payload["windows"]:
        lines.append(f"\n{window}")
        lines.append(
            f"  {'convention':<17}{'CAGR':>8}{'vs open':>9}{'bp/d':>8}{'t':>7}"
            f"{'>open':>7}{'defer':>7}{'fallbk':>8}{'fills':>7}"
        )
        for row in payload["rows"]:
            if row["window"] != window:
                continue
            lines.append(
                f"  {row['convention']:<17}{_pct(row['median_cagr']):>8}"
                f"{_pct(row['median_cagr_vs_open']):>9}"
                f"{_num(row['mean_daily_bp_vs_open'], 1):>8}"
                f"{_num(row['hac_t_vs_open']):>7}"
                f"{row['offsets_above_open']:>7}{row['deferrals']:>7}"
                f"{row['fallbacks']:>8}{row['fills']:>7}"
            )
        best = payload["best"].get(window, {})
        if judged and best.get("convention"):
            lines.append(
                f"  best: {best['convention']} "
                f"{_num(best['mean_daily_bp_vs_open'], 1)} bp/d, "
                f"t {_num(best['hac_t_vs_open'])}, deflated Sharpe "
                f"{_num(best['deflated_sharpe'])} against {best['trials']} trials"
            )
    lines.extend(_trial_tables(payload))
    gap = payload["simulator_gap"]
    lines.append(
        f"\nnext_open against simulate.run at offset {gap['offset']}: mean |gap| "
        f"{_num(gap['mean_abs_bp'], 3)} bp/d, max {_num(gap['max_abs_bp'], 3)} bp/d, "
        f"{gap['nan_mismatch']} NaN mismatches over {gap['sessions']} sessions"
    )
    if judged:
        lines.append(f"\nverdict: {payload['verdict']}")
        lines.append(payload["breakout_gate"])
    else:
        lines.append(f"\nfill-timing verdict: {payload['verdict']}")
    lines.extend(_trial_verdicts(payload))
    return "\n".join(lines)


# The stage-3 T-I block: per window, each T-I convention against
# dip_or_close (bp a day at the median offset, its Newey-West t, offsets
# above dip_or_close, the median CAGR), what its orders did (the share
# filled before the close, buys and sells apart, the gain per such fill
# over the close), candidate minus control per differing order with its
# date-clustered t, and the no-forecast and late-trigger counts; then this
# run's reading (the verdict needs the other runs).
def _render_ti(payload: dict[str, Any]) -> list[str]:
    """Return the stage-3 T-I block's lines."""
    block = payload["stage3_ti"]
    mode = "next-bar robustness run" if block.get("next_bar") else "registered fills"
    seed = block.get("seed_column")
    lines = [
        f"\nstage-3 T-I trial against {block['control']} (the board's rule) at "
        f"{payload['cost_bps']:g} bp, {mode}, "
        + ("seed ensemble" if seed is None else f"seed column {seed}")
    ]
    for family, info in block["families"].items():
        lines.append(
            f"  {family}: {info.get('file', 'forecast')} "
            f"(sha256 {str(info.get('sha256') or 'n/a')[:12]}), forecasts from "
            f"{info.get('first_forecast_session') or 'never'}, "
            f"{info.get('vectors_with_forecast', 0)} name-sessions, "
            f"{info.get('partial_vectors', 0)} partial"
        )
    for window in fill_timing.TI_WINDOWS:
        lines.append(f"\n{window}")
        lines.append(
            f"  {'convention':<13}{'CAGR':>7}{'ctl':>7}{'bp/d':>7}{'t':>8}{'>dip':>6}"
            f"{'pre%':>7}{'buy%':>7}{'sell%':>7}{'bp/fill':>8}{'bp/diff':>9}{'t':>9}"
            f"{'diff':>7}{'no-fc':>7}{'late':>6}"
        )
        for row in block["rows"]:
            if row["window"] != window:
                continue
            orders = row["orders"]
            versus = row["versus_control"]["all"]
            lines.append(
                f"  {row['convention']:<13}{_pct(row['median_cagr']):>7}"
                f"{_pct(row['control_median_cagr']):>7}"
                f"{_num(row['mean_daily_bp_vs_dip'], 1):>7}"
                f"{_num(row['hac_t_vs_dip']):>8}{row['offsets_above_dip']:>6}"
                f"{_pct(orders['all']['before_close_share']):>7}"
                f"{_pct(orders['buy']['before_close_share']):>7}"
                f"{_pct(orders['sell']['before_close_share']):>7}"
                f"{_num(orders['all']['gain_bp_per_fill'], 1):>8}"
                f"{_num(versus['bp_per_differing_order'], 1):>9}"
                f"{_num(versus['clustered_t']):>9}{versus['differing']:>7}"
                f"{orders['all']['no_forecast']:>7}{orders['all']['late_triggers']:>6}"
            )
    lines.append(
        "  (bp/d and t: paired daily difference against dip_or_close at the median "
        "offset, Newey-West; pre%, buy%, sell%: orders filled at a bar before the "
        "close; bp/fill: gain over that session's close per such fill; bp/diff and "
        "t: candidate minus dip_or_close per order the two fill differently, t "
        "clustered by date; diff: those orders; no-fc: orders with no forecast, "
        "filled as dip_or_close; late: filter triggers after 15:30)"
    )
    lines.append(
        "\nthis run's reading (the verdict reads the 10/16/25 bp, next-bar and "
        "seed runs):"
    )
    for convention, reading in block["reading"].items():
        deflated = block["deflated"].get(convention, {})
        lines.append(
            f"  {convention}: model window {_num(reading['model_bp'], 1)} bp/d "
            f"(t {_num(reading['model_t'])}), floor "
            f"{'cleared' if reading['passes_floor'] else 'not cleared'}; 2024-2026 "
            f"{_num(reading['reported_bp'], 1)}; per differing order "
            f"{_num(reading['per_order_bp'], 1)} bp (t {_num(reading['per_order_t'])})"
            + ("; real but immaterial" if reading["real_but_immaterial"] else "")
            + f"; deflated Sharpe {_num(deflated.get('dsr'))} at N = "
            f"{deflated.get('trials', 'n/a')}"
        )
    return lines


# The entry-level, SR and stage-3 T-I blocks' tables, for the blocks the
# payload has.
def _trial_tables(payload: dict[str, Any]) -> list[str]:
    """Return the tables of the payload's level, SR and T-I blocks."""
    lines: list[str] = []
    if "level" in payload:
        lines.extend(_render_level(payload))
    if "sr_level" in payload:
        lines.extend(_render_sr(payload))
    if "stage3_ti" in payload:
        lines.extend(_render_ti(payload))
    return lines


# The entry-level and SR verdict lines with each convention's label, for
# the blocks the payload has.
def _trial_verdicts(payload: dict[str, Any]) -> list[str]:
    """Return the verdict lines of the payload's level and SR blocks."""
    lines: list[str] = []
    if "level" in payload:
        level = payload["level"]
        lines.append(f"\nentry-level verdict: {level['verdict']}")
        lines.append(level["twin_line"])
        for convention, criteria in level["criteria"].items():
            lines.append(f"  {convention}: {criteria['label']}")
    if "sr_level" in payload:
        block = payload["sr_level"]
        lines.append(f"\nsupport/resistance verdict: {block['verdict']}")
        for convention, criteria in block["criteria"].items():
            lines.append(f"  {convention}: {criteria['label']}")
    return lines


class _RefusedError(Exception):
    """A run refused before the desk runs, with the exit code it returns."""

    # The message printed and the exit code: 2 for a bad argument or file,
    # 1 for a file that is not there.
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


# The checks a run makes before the desk runs, and the stage-3 T-I
# forecasts it prices: the convention list against the files given, a seed
# column only with stage-3 files, every file present, and each T-I file of
# the family it is given for, read at the seed column asked for. Raises
# _RefusedError with the exit code.
def _preflight(
    args: argparse.Namespace, only: tuple[str, ...] | None, forecasts_file: Path | None
) -> dict[str, fill_timing.TiForecast]:
    """Return {family: TiForecast} for the run, or raise _RefusedError."""
    seed_column = getattr(args, "seed_column", None)
    try:
        stage3_files = _stage3_files(getattr(args, "stage3_forecast", []))
        fill_timing.select_conventions(
            only, forecasts_file is not None, tuple(stage3_files)
        )
        if seed_column is not None and not stage3_files:
            raise ValueError(
                "--seed-column picks a column of the --stage3-forecast files"
            )
    except ValueError as error:
        raise _RefusedError(2, str(error)) from error
    if forecasts_file is not None and not forecasts_file.exists():
        raise _RefusedError(1, f"forecast file not found: {forecasts_file}")
    for family, path in stage3_files.items():
        if not path.exists():
            raise _RefusedError(1, f"stage-3 {family} forecast file not found: {path}")
    try:
        return _load_stage3(stage3_files, seed_column)
    except ValueError as error:
        raise _RefusedError(2, str(error)) from error


# Read each T-I forecast file for its family, refusing one of another
# family, as the lookup the engine reads at `seed_column` (None: the
# ensemble); each file's path and sha256 are taken beside the read the run
# uses.
def _load_stage3(
    files: dict[str, Path], seed_column: int | None
) -> dict[str, fill_timing.TiForecast]:
    """Return {family: TiForecast} read from the files."""
    out: dict[str, fill_timing.TiForecast] = {}
    for family, path in files.items():
        loaded = stage3_io.load_forecast(path)
        if loaded.family != family:
            raise ValueError(f"{path} holds a {loaded.family} forecast, not {family}")
        out[family] = fill_timing.ti_forecast(
            loaded,
            seed_column,
            identity={
                "file": str(path),
                "sha256": _sha256(path),
                "meta": loaded.meta,
                "rows": int(len(loaded.dates)),
            },
        )
    return out


# Run the desk, restrict, load the cubes, study, write and print.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the trial for the parsed arguments; return the exit code."""
    root = Path(args.root)
    only = _only(args.only)
    forecasts_file = Path(args.forecasts) if args.forecasts is not None else None
    # Refuse a bad convention list, family, seed column or forecast file, or
    # a missing file, before the desk runs.
    try:
        ti_forecasts = _preflight(args, only, forecasts_file)
    except _RefusedError as refusal:
        print(str(refusal), file=out)
        return refusal.code
    store = MarketStore(root)
    report = (desk_run or default_desk)(store)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    panel = restricted.panel
    aligned = None
    identity: dict[str, Any] = {}
    if forecasts_file is not None:
        # The file's identity is taken beside the read the run uses, and the
        # rows are aligned exactly as `vol_forecast.aligned_to_panel` does.
        loaded = vol_forecast.load_forecasts(forecasts_file)
        identity = {
            "forecast_file": str(forecasts_file),
            "forecast_sha256": _sha256(forecasts_file),
            "forecast_meta": loaded.meta,
        }
        aligned = vol_forecast.align(loaded, panel.dates, tuple(panel.tickers))
    if args.tickers:
        tickers = tuple(
            dict.fromkeys(
                t.strip().upper() for t in args.tickers.split(",") if t.strip()
            )
        )
    else:
        tickers = tuple(t for t in panel.tickers if t != panel.benchmark)
    cubes, lines = load_cubes(store, tickers, workers=max(1, args.workers))
    if not args.json:
        print(f"cubes from {root} ({len(tickers)} tickers requested):", file=out)
        for line in lines:
            print(line, file=out)
    if not cubes:
        print("no complete sessions in the store; nothing to price", file=out)
        return 1
    payload = fill_timing.study(
        restricted,
        cubes,
        mask,
        offsets=max(1, args.offsets),
        cost=args.cost,
        conventions=only,
        forecasts=aligned,
        ti_forecasts=ti_forecasts or None,
        next_bar=bool(getattr(args, "next_bar", False)),
    )
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["exclusions"] = {t: c.excluded for t, c in cubes.items()}
    payload["sessions_per_ticker"] = {t: len(c) for t, c in cubes.items()}
    payload["asof"] = str(panel.dates[-1])
    payload.update(identity)
    if ti_forecasts:
        payload["stage3_forecasts"] = {
            family: {
                key: forecast.identity[key] for key in ("file", "sha256", "seed_column")
            }
            for family, forecast in ti_forecasts.items()
        }
    payload = json_ready(payload)
    target = _target(args, root, payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, allow_nan=False), file=out)
    else:
        print(render(payload), file=out)
        print(f"\nwrote {target}", file=out)
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
