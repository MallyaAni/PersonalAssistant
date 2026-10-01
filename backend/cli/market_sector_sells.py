"""Sector-aware sells S2: three peer-group sell rules against the board's sell rule.

    python -m backend.cli.market_sector_sells --root data/market --null-test

    python -m backend.cli.market_sector_sells --root data/market \\
        --offsets 20 --out docs/research/scorecards/sector-sells/sector_sells.json

    python -m backend.cli.market_sector_sells --root data/market \\
        --peers COHR,AAOI,NVDA,OKLO --on 2026-09-30

`docs/research/sector-sells-plan-2026-10-01.md` registers the study;
`backend/market/sector_sells.py` computes and judges it. The study runs
the desk as the structure-rules study does (`market_stage4_decisions.
load_inputs`: the desk report and the SIP cubes; the EDGAR records it also
loads are not read), restricts it to the point-in-time book, computes the
peer groups with the same membership, builds the sell fill grids, runs the
control executor under `graded-equal-weight/5` from each of the
`--offsets` start offsets (`--max-offsets` prices fewer, a smoke run),
writes the payload (`--out`, with the git revision and the membership
file's sha256) and prints one verdict line per candidate, the named peer
groups and the COHR case.

`--null-test` builds the grids with rules that never fire and checks that
they reproduce the control to the bit on every cell in both fill modes,
and that every candidate's gain is exactly zero on one offset's sells; it
prints "PASS, reproduced to the bit" or the mismatches (exit 3) and reads
no result.

`--peers` prints the peer groups of the named tickers on `--on` from the
daily store only (the book's panel and the membership history; no cube,
no desk run, nothing written). Nothing here trades or changes the
executor.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.agents.trading.desk import point_in_time, policy_v5
from backend.cli.market_stage4_decisions import _sha256, load_inputs, revision
from backend.market import sector_sells as ss
from backend.market import stage3_io as io
from backend.market import stage4_orders as so
from backend.market import universe
from backend.market.store import MarketStore

FILE = "research/sector_sells/sector_sells.json"
NULL_PASS = "PASS, reproduced to the bit"


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
        "--offsets", type=int, default=ss.OFFSETS, help="the registered offsets"
    )
    parser.add_argument(
        "--max-offsets", type=int, default=None, help="price only this many (smoke)"
    )
    parser.add_argument(
        "--cost", type=float, default=so.COST_BPS, help="the control run's cost, bp"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, default=None, help=f"the payload (default <root>/{FILE})"
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    parser.add_argument(
        "--null-test",
        action="store_true",
        help="check that rules which never fire reproduce the control, then stop",
    )
    parser.add_argument(
        "--peers",
        default=None,
        help="comma-separated tickers: print their peer groups on --on and stop",
    )
    parser.add_argument(
        "--on",
        type=date.fromisoformat,
        default=ss.CASE_DATE,
        help="the session --peers reads (default the plan's 2026-09-30)",
    )
    return parser


# The run's record: the store, the code revision, the cost, the membership
# file's sha256, the panel and the cube coverage.
def run_record(
    args: argparse.Namespace, panel: Any, coverage: dict[str, Any]
) -> dict[str, Any]:
    """Return the payload's "run" block."""
    tickers = [t for t in panel.tickers if t != panel.benchmark]
    return {
        "root": str(args.root),
        "revision": revision(),
        "cost_bps": float(args.cost),
        "basis": so.EXECUTED,
        "policy": policy_v5.POLICY_VERSION,
        "inputs": {
            "membership": {
                "file": str(args.membership),
                "sha256": _sha256(args.membership),
            }
        },
        "panel": {
            "sessions": len(panel.dates),
            "names": len(tickers),
            "benchmark": panel.benchmark,
            "first": str(panel.dates[0]),
            "last": str(panel.dates[-1]),
        },
        "cubes": coverage,
    }


# Check the arguments, then run the mode asked for: the peer printout, the
# null test, or the study. `loader` replaces `load_inputs` and
# `panel_loader` the book's daily panel (tests). Exit codes: 0 done, 1 an
# input file is missing, 2 an argument is refused - both before the desk
# runs - and 3 a failed null test.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., tuple[Any, dict[str, Any], dict[str, Any]]] | None = None,
    panel_loader: Callable[..., Any] | None = None,
) -> int:
    """Run the command; return the exit code."""
    began = time.perf_counter()

    # Print one timed progress line.
    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    if not Path(args.membership).exists():
        print(f"file not found: {args.membership}", file=out)
        return 1
    if args.offsets < 1 or (args.max_offsets is not None and args.max_offsets < 1):
        print("--offsets and --max-offsets must be at least 1", file=out)
        return 2
    root = Path(args.root)
    store = MarketStore(root)
    if args.peers is not None:
        names = [t.strip().upper() for t in args.peers.split(",") if t.strip()]
        if not names:
            print("--peers needs at least one ticker", file=out)
            return 2
        return run_peers(store, args, names, out, panel_loader)
    load = loader or load_inputs
    report, cubes, _ = load(store, args.workers, say)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    panel = restricted.panel
    if args.null_test:
        return run_null(restricted, mask, cubes, args, say, out)
    fills, next_bar, block, coverage = ss.fill_grids(panel, cubes, mask)
    say(
        f"fills: {coverage['names_with_cube']} names with a cube; "
        f"{coverage['name_sessions_with_peers']} name-sessions with a peer group; "
        f"{coverage['name_sessions_with_morning']} with R_g"
    )
    market = ss.build_market(panel, restricted.graded.grades, fills, next_bar, block)
    priced = args.offsets if args.max_offsets is None else args.max_offsets
    priced = min(args.offsets, priced)
    runs = so.run_offsets(
        restricted,
        mask,
        priced,
        args.cost,
        so.EXECUTED,
        say,
        allocator=policy_v5.allocator(mask),
    )
    payload = ss.evaluate(runs, market, registered=args.offsets)
    payload["run"] = run_record(args, panel, coverage)
    payload["run"]["seconds"] = time.perf_counter() - began
    target = Path(args.out) if args.out is not None else root / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(io.clean_json(payload), indent=2, allow_nan=False)
    target.write_text(text, encoding="utf-8")
    print(text if args.json else render(json.loads(text)), file=out)
    print(f"wrote {target}", file=out)
    return 0


# The null test: grids whose rules never fire must equal the control's on
# every cell in both modes, and on offset 0's sells every candidate's gain
# is exactly zero with a zero session series. Prints the verdict line.
def run_null(
    restricted: Any,
    mask: np.ndarray,
    cubes: dict[str, Any],
    args: argparse.Namespace,
    say: Callable[[str], None],
    out: TextIO,
) -> int:
    """Run the null test; return 0 on a pass, 3 on a failure."""
    panel = restricted.panel
    fills, next_bar, block, coverage = ss.fill_grids(panel, cubes, mask, never=True)
    bad = ss.null_mismatches(fills, next_bar)
    if int(block["fire"][ss.PEER_DEFER].sum() + block["fire"][ss.PEER_CLOSE].sum()):
        bad.append("a never-firing rule fired")
    market = ss.build_market(panel, restricted.graded.grades, fills, next_bar, block)
    runs = so.run_offsets(
        restricted, mask, 1, args.cost, so.EXECUTED, say, policy_v5.allocator(mask)
    )
    sells = int((runs[0].side == ss.SELL).sum())
    for c in ss.CANDIDATES:
        for mode in (False, True):
            book = ss.price_book(runs[0], market, c, next_bar=mode)
            series = ss.sd.session_series(book, book.gain)
            if np.any(book.gain != 0.0) or np.any(series != 0.0):
                bad.append(f"{c} next_bar={mode}: a non-zero gain")
            if np.any(book.wait != 0) or np.any(book.acted):
                bad.append(f"{c} next_bar={mode}: a wait or an action")
    cells = int(np.isfinite(fills.price[ss.CONTROL]).sum())
    print(
        f"null test ({ss.PLAN}): rules that never fire against the control on "
        f"{cells} priced cells x 2 fill modes and {sells} sells of offset 0; "
        f"{coverage['names_with_cube']} names with a cube",
        file=out,
    )
    if bad:
        print("null test verdict: FAIL - " + "; ".join(bad), file=out)
        return 3
    print(f"null test verdict: {NULL_PASS}", file=out)
    return 0


# The book's daily panel and its point-in-time membership, no desk run.
def _daily_panel(store: MarketStore) -> Any:
    """Return the book's panel from the store's daily bars."""
    from backend.agents.trading.desk import desk

    panel, _ = desk.book_panel(store)
    return panel


# The peer groups of `names` on `args.on` from the daily store only:
# membership from the history, the groups through `sector_sells.
# peer_groups`, printed with each peer's residual correlation and sigma_g.
def run_peers(
    store: MarketStore,
    args: argparse.Namespace,
    names: list[str],
    out: TextIO,
    panel_loader: Callable[..., Any] | None = None,
) -> int:
    """Print the peer groups; return the exit code."""
    panel = (panel_loader or _daily_panel)(store)
    tickers = tuple(str(t) for t in panel.tickers)
    mask = point_in_time.eligibility(panel.dates, tickers, args.membership)
    market = tickers.index(str(panel.benchmark))
    mask[:, market] = False
    groups = ss.peer_groups(panel.dates, tickers, panel.adj_close, market, mask)
    report = ss.peer_report(groups, names, args.on)
    last = str(panel.dates[-1])
    print(
        f"peer groups on {args.on} (store through {last}; k = {ss.K_PEERS}, "
        f"{ss.CORR_SESSIONS}-session residual-to-{panel.benchmark} correlation, "
        f"point-in-time members of {args.membership.name})",
        file=out,
    )
    for name in names:
        entry = report[name]
        if entry is None:
            print(f"  {name}: not in the panel on {args.on}", file=out)
        elif not entry["peers"]:
            print(f"  {name}: no peer group on {args.on}", file=out)
        else:
            peers = ", ".join(f"{p} {c:+.2f}" for p, c in entry["peers"])
            print(
                f"  {name}: {peers}; mean corr {entry['mean_corr']:+.2f}; "
                f"sigma_g {entry['sigma_g'] * 100:.2f}%",
                file=out,
            )
    if args.json:
        print(
            json.dumps(io.clean_json({"date": str(args.on), "groups": report})),
            file=out,
        )
    return 0


# A number to `digits` decimals with its sign, "n/a" when missing.
def _num(x: Any, digits: int = 2) -> str:
    """Return `x` signed, "n/a" for None or NaN."""
    return "n/a" if x is None or x != x else f"{float(x):+.{digits}f}"


# The named peer groups and the COHR case as lines.
def _peer_lines(payload: dict[str, Any]) -> list[str]:
    """Return the peer and case lines of a payload."""
    named = payload["peers"]["named"]
    lines = [f"peer groups on {named['date']}:"]
    for name, entry in named["groups"].items():
        if not entry or not entry.get("peers"):
            lines.append(f"  {name}: none")
            continue
        peers = ", ".join(f"{p} {_num(c)}" for p, c in entry["peers"])
        lines.append(
            f"  {name}: {peers}; sigma_g {_num(entry['sigma_g'] * 100)}%; "
            f"R_g {_num((entry.get('morning') or float('nan')) * 100)}%"
        )
    c = payload.get("case")
    if c is None:
        lines.append(f"case {ss.CASE_TICKER} {ss.CASE_DATE}: not in the panel")
        return lines
    rules = "; ".join(
        f"{rule} fired {v['fired']} fill {_num(v['fill'])} g {_num(v['g_bp'], 1)} bp"
        for rule, v in c["rules"].items()
    )
    lines.append(
        f"case {c['ticker']} decided {c['decision']} (grade {c['grade']}), executed "
        f"{c['execution']}: control {_num(c['control']['fill'])} (bar "
        f"{c['control']['slot']}); {rules}"
    )
    lines.append(
        f"2026 sells changed at the median offset: {len(payload['changed_2026'])}"
    )
    return lines


# The payload as the lines people read: what was run, the orders, the
# drift, the verdict and one line per candidate, the peers and the case.
def render(payload: dict[str, Any]) -> str:
    """Return the verdict text of a payload."""
    offsets = payload["offsets"]
    control = payload["control"]
    median = payload["orders"]["median_by_window"]
    model = payload["windows"][ss.MODEL][0]
    head = (
        f"sector sells ({payload['plan']}) as of {payload['asof']}: "
        f"{len(ss.CANDIDATES)} candidates on the {control['basis']} sells of "
        f"{control['executor']} under {control['policy']} against {control['fills']}; "
        f"{offsets['priced']} of {offsets['registered']} offsets, statistics at "
        f"offset {offsets['median']}; model window {model}..2023-12-29; Newey-West "
        f"lag {payload['hac_lag']}"
    )
    orders = "; ".join(
        f"{w} {m['sells']} sells over {m['decision_sessions']} sessions"
        for w, m in median.items()
    )
    drift = "; ".join(
        f"{w} {_num(d['mu_bp'])} bp/session over {d['name_days']} A/A+ name-days"
        for w, d in payload["drift"].items()
    )
    summary = "; ".join(
        f"{w}: mean peer corr {_num(s['mean_corr'])}, kept {_num(s['turnover_kept'])}, "
        f"defer fires {_num(s['fire_share'][ss.PEER_DEFER])}, close fires "
        f"{_num(s['fire_share'][ss.PEER_CLOSE])} of {s['name_sessions_with_morning']} "
        "name-sessions"
        for w, s in payload["peers"]["summary"].items()
    )
    lines = [
        head,
        f"orders at the median offset: {orders}",
        f"drift: {drift}",
        f"peers: {summary}",
        "",
        payload["verdict"]["text"],
    ]
    lines += [f"  {line}" for line in payload["verdict"]["lines"]]
    lines += [""] + _peer_lines(payload)
    return "\n".join(lines)


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
