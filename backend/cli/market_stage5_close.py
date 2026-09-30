"""Stage 5: buying at the decision day's close, decided at 15:30 - the registered test.

    python -m backend.cli.market_stage5_close --root data/market --null-test-only \\
        --out <scratch>/stage5_close_null.json
    python -m backend.cli.market_stage5_close --root data/market --offsets 20 \\
        --out data/market/research/stage5/stage5_close.json

`docs/research/stage5-plan-2026-09-29.md` registers the test and
`backend/market/stage5_close.py` computes it. The command loads what stage
4's decision test loads - the default desk (`market_profit_taking.
default_desk`), the point-in-time restriction, the SIP cubes
(`market_session_anatomy.load_cubes`, with the benchmark's, which the
proxy's regime reads) and the EDGAR records (`stage3_export`) - plus the
release tone records and the filing levels the value analyst reads (as the
desk read them, and strictly before each session).

It runs the null test first: row t set to the final row must reproduce the
report (grades, stances, gate, blocker, band z) and, at every offset
priced, the control journal's submitted units. `--null-test-only` stops
there: it loads no cubes, computes no fill, writes the null payload and
prints the result. Otherwise a failed null test also stops the run before
any fill is read (the verdict is then RECORD by criterion 4); a passing
one goes on to the 15:30 and 15:45 proxies, the fills, the offsets
(`--offsets`, `--max-offsets` prices fewer: a smoke run), the payload
(`--out`, with every input's sha256 and the git revision) and the verdict.
Nothing here trades or changes the executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.cli.market_stage4_decisions import _sha256, revision
from backend.market import stage3_io as io
from backend.market import stage4_orders as so
from backend.market import stage5_close as s5
from backend.market import universe
from backend.market.store import MarketStore

FILE = "research/stage5/stage5_close.json"
NULL_FILE = "research/stage5/stage5_close_null.json"
# Exit codes: done, a file is missing, an argument is refused, the null
# test failed (nothing was priced).
DONE, MISSING, REFUSED, NULL_FAILED = 0, 1, 2, 3


@dataclass
class Loaded:
    """What the test reads from the store."""

    report: Any  # the desk report, unrestricted (`default_desk`)
    cubes: dict[str, Any]  # ticker -> SessionCube; empty for the null test
    edgar: dict[str, Any]  # ticker -> EDGAR record (release acceptance times)
    tone: dict[str, tuple[Any, ...]]  # ticker -> tone records, as the desk read them
    levels: dict[
        str, np.ndarray
    ]  # the value analyst's filing levels, as the desk read them
    strict_levels: dict[str, np.ndarray] = field(
        default_factory=dict
    )  # strictly before t


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--offsets", type=int, default=s5.OFFSETS, help="the registered offsets"
    )
    parser.add_argument(
        "--max-offsets", type=int, default=None, help="price only this many (smoke)"
    )
    parser.add_argument(
        "--null-test-only",
        action="store_true",
        help="run only the null test (no cubes, no fills)",
    )
    parser.add_argument(
        "--cost", type=float, default=s5.COST_BPS, help="the control run's cost, bp"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, default=None, help=f"the payload (default <root>/{FILE})"
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# The desk report, the cubes (the benchmark's too), the EDGAR records, the
# tone records and the filing levels, from the store. With `full` False
# (the null test) no cube, EDGAR record or strict level is loaded.
def load_inputs(
    store: MarketStore, workers: int, log: Callable[[str], None], full: bool = True
) -> Loaded:
    """Return the Loaded inputs."""
    from backend.cli.market_profit_taking import default_desk
    from backend.cli.market_session_anatomy import load_cubes
    from backend.market import language, stage3_export
    from backend.market.levels_pit import point_in_time_levels

    began = time.perf_counter()
    report = default_desk(store)
    panel = report.panel
    log(f"desk: {len(panel.dates)} sessions x {len(panel.tickers)} names")
    tone = {
        str(ticker): language.records_from_frame(frame[0])
        for ticker in panel.tickers
        if (frame := store.read_frame(language.TONE_KIND, ticker, None)) is not None
    }
    levels = point_in_time_levels(store, panel, None)
    log(f"tone: {len(tone)} names; levels read ({time.perf_counter() - began:.0f} s)")
    if not full:
        return Loaded(report, {}, {}, tone, levels)
    cubes, _ = load_cubes(store, tuple(str(t) for t in panel.tickers), workers=workers)
    log(f"cubes: {len(cubes)} of {len(panel.tickers)} names")
    edgar = stage3_export._edgar_records(store, panel, None)
    strict = point_in_time_levels(store, panel, None, strict_publication=True)
    log(f"edgar: {len(edgar)} names ({time.perf_counter() - began:.0f} s)")
    return Loaded(report, cubes, edgar, tone, levels, strict)


# The sha256 of arrays, their dtypes and shapes, in order.
def digest(*arrays: Any) -> str:
    """Return the hex sha256 of the arrays."""
    h = hashlib.sha256()
    for array in arrays:
        a = np.ascontiguousarray(np.asarray(array))
        if a.dtype.kind == "O":
            a = a.astype(str)
        h.update(f"{a.dtype.str}{a.shape}".encode())
        h.update(a.tobytes())
    return h.hexdigest()


# The sha256 of every loaded input: the membership file, the panel, the
# report's grades, the cubes, the tone records, the release acceptance
# times and the filing levels.
def input_digests(args: argparse.Namespace, loaded: Loaded) -> dict[str, Any]:
    """Return {input: sha256}."""
    panel = loaded.report.panel
    cubes = [
        digest(
            np.array([ticker]),
            c.dates,
            c.open,
            c.high,
            c.low,
            c.close,
            c.volume,
            c.auction_open,
        )
        for ticker, c in sorted(loaded.cubes.items())
    ]
    tone = [
        f"{t}|{r.accession}|{r.reaction_date}|{r.guidance}|{r.demand}|{r.pricing}|"
        f"{r.capex}|{r.supply_constrained}"
        for t, records in sorted(loaded.tone.items())
        for r in records
    ]
    accepted = [
        f"{t}|{accession}|{when.isoformat()}"
        for t, times in sorted(s5.acceptance_times(loaded.edgar).items())
        for accession, when in sorted(times.items())
    ]
    return {
        "membership": {
            "file": str(args.membership),
            "sha256": _sha256(args.membership),
        },
        "panel": digest(
            panel.dates,
            np.array(panel.tickers),
            panel.open,
            panel.high,
            panel.low,
            panel.close,
            panel.adj_close,
            panel.volume,
        ),
        "grades": digest(loaded.report.graded.grades),
        "cubes": digest(np.array(cubes)) if cubes else None,
        "tone": digest(np.array(tone)) if tone else None,
        "acceptance": digest(np.array(accepted)) if accepted else None,
        "levels": digest(*(loaded.levels[k] for k in sorted(loaded.levels))),
        "strict_levels": digest(
            *(loaded.strict_levels[k] for k in sorted(loaded.strict_levels))
        )
        if loaded.strict_levels
        else None,
    }


# The run's record: the store, the code revision, the cost, every input's
# sha256, the panel and the cube coverage.
def run_record(args: argparse.Namespace, loaded: Loaded) -> dict[str, Any]:
    """Return the payload's "run" block."""
    panel = loaded.report.panel
    return {
        "root": str(args.root),
        "revision": revision(),
        "cost_bps": float(args.cost),
        "inputs": input_digests(args, loaded),
        "panel": {
            "sessions": len(panel.dates),
            "names": len(panel.tickers),
            "benchmark": panel.benchmark,
            "first": str(panel.dates[0]),
            "last": str(panel.dates[-1]),
        },
        # The null test loads no cube (it reads none), so it has no coverage.
        "cubes": {
            "names": len(loaded.cubes),
            "names_without_cube": sorted(
                str(t) for t in panel.tickers if str(t) not in loaded.cubes
            ),
        }
        if loaded.cubes
        else "not loaded",
        "edgar_names": len(loaded.edgar),
        "tone_names": len(loaded.tone),
    }


# Write a payload as strict JSON and return its text.
def _write(target: Path, payload: Mapping[str, Any]) -> str:
    """Write `payload` to `target`; return the JSON text."""
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(io.clean_json(dict(payload)), indent=2, allow_nan=False)
    target.write_text(text, encoding="utf-8")
    return text


# Check the arguments, load, run the null test, then (unless only the null
# test is asked for, or it failed) the proxies, the fills and the offsets;
# write the payload and print the verdict. `loader` replaces `load_inputs`
# (tests). Exit codes: DONE, MISSING (a file), REFUSED (an argument),
# NULL_FAILED (the null test failed; nothing was priced).
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., Loaded] | None = None,
) -> int:
    """Run the test; return the exit code."""
    began = time.perf_counter()

    # Print one timed progress line.
    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    if not Path(args.membership).exists():
        print(f"file not found: {args.membership}", file=out)
        return MISSING
    if args.offsets < 1 or (args.max_offsets is not None and args.max_offsets < 1):
        print("--offsets and --max-offsets must be at least 1", file=out)
        return REFUSED
    root = Path(args.root)
    load = loader or load_inputs
    loaded = load(MarketStore(root), args.workers, say, full=not args.null_test_only)
    report = loaded.report
    panel = report.panel
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    final = s5.final_state(report)
    start, stop = s5.proxy_span(final.dates)
    sentiment = s5.sentiment_raw(panel, loaded.tone)
    null_grid = s5.null_grid(final, loaded.levels, sentiment, start, stop)
    check = s5.null_check(final, null_grid)
    say(
        f"null grid: {check['sessions']} sessions from {check['first']}; "
        f"{'reproduces' if check['passes'] else 'DOES NOT reproduce'} the report"
    )
    priced = min(args.offsets, args.max_offsets or args.offsets)
    runs = s5.run_offsets(restricted, mask, priced, args.cost, so.EXECUTED, say)
    given = (final.blocked, final.z)
    null_replays = [
        s5.replay(
            r,
            restricted,
            mask,
            null_grid,
            compare=True,
            cost_bps=args.cost,
            given=given,
        )
        for r in runs
    ]
    result = s5.null_test(check, null_replays)
    record = run_record(args, loaded)
    if args.null_test_only or not result["passes"]:
        payload = {
            "study": s5.STUDY,
            "plan": s5.PLAN,
            "asof": str(final.dates[-1]),
            "policy": s5.POLICY,
            "offsets": {"registered": int(args.offsets), "priced": priced},
            "null_test": result,
            "priced": False,
            "run": {**record, "seconds": time.perf_counter() - began},
        }
        target = Path(args.out) if args.out is not None else root / NULL_FILE
        text = _write(target, payload)
        print(text if args.json else render_null(json.loads(text)), file=out)
        print(f"wrote {target}", file=out)
        if not result["passes"]:
            print(
                f"{s5.RECORD}: the null test failed; no fill was read (criterion 4)",
                file=out,
            )
            return NULL_FAILED
        return DONE
    early = s5.early_closes(final.dates)
    acceptance = s5.acceptance_times(loaded.edgar)
    grids = {}
    for when in (s5.REGISTERED, s5.VARIANT):
        bars = s5.bars(panel, loaded.cubes, when)
        tone, moved = s5.tone_cutoff(loaded.tone, acceptance, when.tone_cutoff)
        grids[when.label] = s5.proxy_grid(
            final,
            bars,
            loaded.strict_levels,
            s5.sentiment_raw(panel, tone),
            start,
            stop,
            meta={
                "tone_moved": moved,
                "tone_coverage": s5.tone_coverage(loaded.tone, acceptance),
                "bar_coverage": float(bars.have[start:stop][mask[start:stop]].mean())
                if mask[start:stop].any()
                else None,
            },
        )
        say(f"{when.label} proxy: {len(moved)} releases after the tone cutoff")
    fills = s5.fill_grid(panel, loaded.cubes)
    say(f"fills: {fills.coverage['names_with_cube']} names with a cube")
    context = s5.Context(
        restricted=restricted,
        mask=mask,
        final_grid=null_grid,
        fills=fills,
        early=early,
        cost_bps=args.cost,
        given=given,
    )
    payload = s5.evaluate(
        runs,
        null_replays,
        result,
        grids,
        context,
        registered=args.offsets,
        log=say,
    )
    payload["priced"] = True
    payload["fills_coverage"] = fills.coverage
    payload["run"] = {**record, "seconds": time.perf_counter() - began}
    target = Path(args.out) if args.out is not None else root / FILE
    text = _write(target, payload)
    print(text if args.json else render(json.loads(text)), file=out)
    print(f"wrote {target}", file=out)
    return DONE


# The null payload as the lines people read.
def render_null(payload: Mapping[str, Any]) -> str:
    """Return the null test's text."""
    null = payload["null_test"]
    report = null["report"]
    held = "PASSES" if null["passes"] else "FAILS"
    bad = {k: v for k, v in report["mismatches"].items() if v}
    largest = max(report["max_abs_diff"].values(), default=0.0)
    lines = [
        f"stage-5 null test ({payload['plan']}) as of {payload['asof']}: {held}",
        f"  report: {report['sessions']} sessions {report['first']}..{report['last']}; "
        f"mismatching cells {sum(report['mismatches'].values())}"
        + (f" ({bad})" if bad else "")
        + f"; largest score difference {largest}",
    ]
    for j in null["journal"]:
        lines.append(
            f"  offset {j['offset']}: {j['checked']} decisions replayed, "
            f"{j['mismatched']} differ from the journal (largest {j['max_abs_diff']}); "
            f"skipped {j['skipped']}"
        )
    return "\n".join(lines)


# The payload as the lines people read: what was run, the null test, the
# orders, then the verdict and one line per reading.
def render(payload: Mapping[str, Any]) -> str:
    """Return the verdict text of a payload."""
    offsets = payload["offsets"]
    control = payload["control"]
    deciding = payload["windows"][s5.DECIDING]
    head = (
        f"stage-5 close test ({payload['plan']}) as of {payload['asof']}: "
        f"{payload['policy']} under {control['executor']}, {control['basis']} buys, "
        f"candidate at t's close on the {payload['decision']['registered']['time']} "
        f"decision against {control['fills']} in t + 1; {offsets['priced']} of "
        f"{offsets['registered']} offsets, statistics at offset {offsets['median']}; "
        f"deciding window {deciding[0]}..{deciding[1]}; "
        f"Newey-West lag {payload['hac_lag']}"
    )
    lines = [head, "", payload["verdict"]["text"]]
    lines += [f"  {line}" for line in payload["verdict"]["lines"]]
    return "\n".join(lines)


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
