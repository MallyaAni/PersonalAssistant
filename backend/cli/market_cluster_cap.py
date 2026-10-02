"""The peer-cluster exposure cap (R1): score, null test, verdict, a session's clusters.

    python -m backend.cli.market_cluster_cap null-test --root data/market
    python -m backend.cli.market_cluster_cap score --root data/market \\
        --offsets 20 --costs 10 25 --null \\
        --output-dir docs/research/scorecards/cluster-cap
    python -m backend.cli.market_cluster_cap verdict \\
        --control docs/research/scorecards/cluster-cap/control.json \\
        --arms docs/research/scorecards/cluster-cap/cc35_r60.json \\
               docs/research/scorecards/cluster-cap/cc50_r60.json \\
               docs/research/scorecards/cluster-cap/cc35_r50.json \\
        --output docs/research/scorecards/cluster-cap/cluster_cap_verdict.json
    python -m backend.cli.market_cluster_cap clusters --root data/market \\
        --session 2026-09-30

The plan is `docs/research/cluster-cap-plan-2026-10-02.md`; the method is
`backend/market/cluster_cap.py`.

`score` runs the desk once (as live: `market_pit_scorecard`'s own report,
the tone expiry in the live desk's mode), prices the point-in-time
scorecard's lines once per offset and cost with the control arm
(`ew_graded_cap25`, the `/5` policy), and for each arm re-runs only the two
rule lines with the capped allocator (`cluster_cap.capped_arm`) on the same
sessions, costs and offsets; the equal-weight and index lines are shared.
It writes `control.json` and one `<tag>.json` per arm (with `--null`, also
`cc100_r60.json`, the C = 100% payload the check compares to the control),
each with the arm's binding record (`cluster_cap.binding_record`).

`null-test` runs the book through the capped path at C = 100% (rho* 0.6)
and through the plain path at two offsets and both costs, asserts every
line's dates and returns are equal to the bit, and that the capped
allocator returned the base allocator's targets on every session of the
point-in-time book; exit 1 on any mismatch.

`verdict` pairs each arm's payload with the control's and prints the
registered lines (`cluster_cap.verdict`), with SPY and QQQ beside them.

`clusters` reads one recorded session from the store, read-only: the
record's `/5` targets, the book panel as of that session (refused unless it
ends on it), the clusters at each registered rho* and each arm's capped
targets. With `--output` it writes them as JSON there; it never writes
into the store.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import paper, point_in_time, simulate
from backend.cli import market_pit_scorecard as sc
from backend.market import cluster_cap as cc
from backend.market import universe

# The control arm: `/5`, every A/A+ name at equal weight under a 25% cap.
BASE_CAP = 0.25
CONTROL = "control"
CONTROL_ARM = "ew_graded_cap25"


# The `/5` arm the scorecard prices as `--graded-cap 0.25`.
def base_arm():
    """Return the control's allocator factory."""
    return sc.graded_arm(BASE_CAP)


# The desk report the scorecard's control run reads: the live desk (the
# tone expiry in the live mode), the same call `market_pit_scorecard.main`
# makes without flags.
def desk_report(store):
    """Return the desk's unrestricted report."""
    from backend.agents.trading.desk import desk

    run = dict(inputs=(desk.EXPECTATIONS_GAP,), signed_rotation=False)
    return sc._desk_with_expiry(desk, store, run, sc._expiry_mode(None))


# The two rule lines of one priced offset run again with `arm` on the same
# sessions and cost (`price_offset`'s arm options); the other lines are the
# base's, shared.
def rule_lines(report, restricted, mask, since, cost_bps: float, arm, base: dict):
    """Return the base's lines with the two rule lines priced under `arm`."""
    out = dict(base)
    everyone = np.ones_like(mask)
    everyone[:, report.panel.index(report.panel.benchmark)] = False
    plain = dict(use_exits=False, rebalance=paper.REBALANCE_EVERY, cost_bps=cost_bps)
    for label, rep, book_mask in (
        (sc.RULE_TODAY, report, everyone),
        (sc.RULE_PIT, restricted, mask),
    ):
        sim = simulate.run(rep, since=since, allocator=arm(rep, book_mask), **plain)
        out[label] = sc.Curve(label, sim.dates, sim.returns)
    return out


# The empty payload for one arm: the scorecard's own header (its `build`
# with no cost priced), then the costs this run prices.
def _skeleton(report, store, offsets: int, costs, history) -> dict:
    """Return a payload with the scorecard's header and empty rows."""
    payload = sc.build(report, store, offsets, (), history_path=history)
    payload["costs_bps"] = list(costs)
    payload["cap"] = BASE_CAP
    payload["tone_expiry_mode"] = sc._expiry_mode(None)
    return payload


# One cost's rows, paired evidence and median-offset curves onto a payload.
def _score(payload: dict, priced: list[dict], cost: float) -> None:
    """Extend the payload with this cost's pricing."""
    payload["rows"].extend(sc.summarise(priced, cost))
    payload["paired"].extend(sc.paired(priced, cost))
    payload["curves"][f"{cost:g}"] = sc.median_offset_curves(priced)


# The control's payload and one per arm, on shared base pricing; each arm
# carries its spec and binding record.
def build(report, store, offsets: int, costs, history, specs) -> dict[str, dict]:
    """Return {"control": payload, tag: payload, ...}."""
    panel = report.panel
    restricted, mask = point_in_time.point_in_time(report, history)
    base = base_arm()
    payloads = {CONTROL: _skeleton(report, store, offsets, costs, history)}
    payloads[CONTROL]["arm"] = CONTROL_ARM
    for spec in specs:
        payload = _skeleton(report, store, offsets, costs, history)
        payload["arm"] = f"{CONTROL_ARM} + {spec.tag}"
        payload["cluster_cap"] = {
            "spec": spec.record(),
            "binding": cc.binding_record(
                restricted, mask, base, spec, sc.WINDOWS, point_in_time.window
            ),
        }
        payloads[spec.tag] = payload
    for cost in costs:
        priced = [
            sc.price_offset(
                report, restricted, mask, store, sc._since(panel, k), cost, base
            )
            for k in range(offsets)
        ]
        _score(payloads[CONTROL], priced, cost)
        for spec in specs:
            arm = cc.capped_arm(base, spec)
            capped = [
                rule_lines(report, restricted, mask, sc._since(panel, k), cost, arm, b)
                for k, b in enumerate(priced)
            ]
            _score(payloads[spec.tag], capped, cost)
    return payloads


# The null test: the C = 100% path against the plain path at `offsets`
# offsets and every cost, line by line to the bit, plus the allocator's
# targets on every session of the point-in-time book.
def null_test(report, store, history, offsets: int, costs) -> dict:
    """Return {"ok", "lines": [...], "sessions_compared", "sessions_differing"}."""
    panel = report.panel
    restricted, mask = point_in_time.point_in_time(report, history)
    base = base_arm()
    arm = cc.capped_arm(base, cc.NULL)
    lines = []
    for cost in costs:
        for k in range(offsets):
            since = sc._since(panel, k)
            plain = sc.price_offset(report, restricted, mask, store, since, cost, base)
            through = rule_lines(report, restricted, mask, since, cost, arm, plain)
            again = sc.price_offset(report, restricted, mask, store, since, cost, arm)
            for label, curve in plain.items():
                other = again[label]
                lines.append(
                    {
                        "cost_bps": cost,
                        "offset": k,
                        "line": label,
                        "dates_equal": bool(np.array_equal(curve.dates, other.dates)),
                        "returns_equal": bool(
                            np.array_equal(
                                np.asarray(curve.daily, dtype=float),
                                np.asarray(other.daily, dtype=float),
                                equal_nan=True,
                            )
                            and np.array_equal(
                                np.asarray(through[label].daily, dtype=float),
                                np.asarray(other.daily, dtype=float),
                                equal_nan=True,
                            )
                        ),
                    }
                )
    plain_alloc = base(restricted, mask)
    capped_alloc = arm(restricted, mask)
    differing = 0
    for t in range(len(panel.dates)):
        a = plain_alloc(restricted, panel, None, t)
        b = capped_alloc(restricted, panel, None, t)
        differing += not np.array_equal(a, b)
    return {
        "ok": differing == 0
        and all(r["dates_equal"] and r["returns_equal"] for r in lines),
        "spec": cc.NULL.record(),
        "lines": lines,
        "sessions_compared": int(len(panel.dates)),
        "sessions_differing": int(differing),
    }


# The null test as text: one line per mismatch, or the all-clear.
def render_null_test(verdict: dict) -> str:
    """Return the null test as text."""
    compared = verdict["sessions_compared"]
    equal = compared - verdict["sessions_differing"]
    lines = [
        "null test: the book through the cluster-cap path at C = 100% "
        f"(rho* {verdict['spec']['rho']:g}) against the plain path",
        f"  allocator targets equal on {equal} of {compared} sessions",
        f"  lines compared: {len(verdict['lines'])}",
    ]
    for row in verdict["lines"]:
        if not (row["dates_equal"] and row["returns_equal"]):
            lines.append(
                f"  MISMATCH {row['cost_bps']:g} bp offset {row['offset']} "
                f"{row['line']}: dates {row['dates_equal']}, "
                f"returns {row['returns_equal']}"
            )
    passed = "PASS, reproduced to the bit" if verdict["ok"] else "FAIL"
    lines.append(f"  verdict: {passed}")
    return "\n".join(lines)


# A payload's binding record in a few lines.
def render_binding(tag: str, binding: dict) -> str:
    """Return how often the arm's cap binds, per window."""
    out = [f"{tag}: how often the cap binds"]
    for window, w in binding["windows"].items():
        share = w["share_binding"]
        out.append(
            f"  {window}: {w['sessions_binding']} of {w['sessions_with_targets']} "
            f"sessions ({'n/a' if share != share else f'{share * 100:.1f}%'}); "
            f"when binding {_num(w['mean_clusters_capped_when_binding'])} clusters "
            f"capped, {_pct(w['mean_weight_moved_when_binding'])} moved, "
            f"{_pct(w['mean_cash_when_binding'])} to cash; largest cluster median "
            f"{_pct(w['median_largest_cluster_before'])} -> "
            f"{_pct(w['median_largest_cluster_after'])}"
        )
    return "\n".join(out)


# A fraction as a percentage, "n/a" for NaN.
def _pct(x) -> str:
    """Return x as a percentage string."""
    return "n/a" if x is None or x != x else f"{x * 100:.1f}%"


# A number to two places, "n/a" for NaN.
def _num(x) -> str:
    """Return x to two places."""
    return "n/a" if x is None or x != x else f"{x:.2f}"


# Read a payload (NaN comes back as NaN).
def _load(path: Path) -> dict:
    """Return the JSON payload at `path`."""
    return json.loads(path.read_text(encoding="utf-8"))


# Every arm against the control: the verdict record.
def verdict_record(control: dict, arms: dict[str, dict]) -> dict:
    """Return the verdict record: control, trials, indexes, arms by tag."""
    variance = cc.trial_variance(arms, control)
    out = {
        "plan": cc.PLAN,
        "study": cc.STUDY,
        "trials": cc.TRIALS,
        "trial_variance": variance,
        "cost_bps": cc.COST_BPS,
        "control": {
            "arm": control.get("arm"),
            "asof": control.get("asof"),
            "offsets": control.get("offsets"),
            "membership": control.get("membership"),
        },
        "indexes": cc.indexes(control),
        "arms": {},
    }
    for tag, payload in arms.items():
        out["arms"][tag] = cc.verdict(payload, control, variance)
    return out


# The verdict as text: the header, the control and the indexes, each arm.
def render_verdict(record: dict, control: dict) -> str:
    """Return the verdict lines."""
    variance = record["trial_variance"]
    lines = [
        f"cluster cap (R1) against {record['control']['arm']} as of "
        f"{record['control']['asof']}, {record['control']['offsets']} offsets, "
        f"{record['cost_bps']:g} bp; trials {record['trials']['cumulative']} "
        f"cumulative, trial variance "
        f"{'nan' if variance != variance else f'{variance:.6f}'}"
    ]
    for window in cc.WINDOWS:
        row = cc._row(control, window)
        parts = [
            f"control {_pct(row['median_cagr'])} / {_pct(row['median_drawdown'])} / "
            f"{row['median_sharpe']:.2f}"
        ]
        for symbol, by_window in record["indexes"].items():
            v = by_window.get(window)
            if v:
                parts.append(
                    f"{symbol} {_pct(v['cagr'])} / {_pct(v['drawdown'])} / "
                    f"{v['sharpe']:.2f}"
                )
        lines.append(
            f"  {window} (CAGR / worst drawdown / Sharpe): " + "; ".join(parts)
        )
    for reading in record["arms"].values():
        lines.extend(reading["lines"])
    return "\n".join(lines)


# One recorded session's clusters and capped targets from the store.
def session_clusters(root: Path, session: str, specs) -> dict:
    """Return the session report (`cluster_cap.session_report`) with its provenance."""
    from backend.agents.trading.desk.desk import book_panel
    from backend.market import deskrecord
    from backend.market.store import MarketStore

    record = deskrecord.load(root, session)
    if record is None:
        raise FileNotFoundError(f"no desk record for {session}")
    targets = (record.get("targets") or {}).get("weights") or {}
    panel, _ = book_panel(MarketStore(root), date.fromisoformat(session))
    last = str(panel.dates[-1])
    if last != session:
        raise ValueError(f"the store's panel ends on {last}, not on {session}")
    tickers = [str(t) for t in panel.tickers]
    weights = np.zeros(len(tickers))
    missing = []
    for ticker, w in targets.items():
        if ticker in tickers:
            weights[tickers.index(ticker)] = float(w)
        elif float(w) > 0:
            missing.append(ticker)
    t = len(panel.dates) - 1
    market = panel.index(panel.benchmark)
    out = cc.session_report(tickers, panel.adj_close, market, weights, t, specs)
    out.update(
        {
            "session": session,
            "policy": (record.get("targets") or {}).get("policy"),
            "targets_not_in_panel": missing,
            "source": "desk record targets; book panel as of the session",
        }
    )
    return out


# The session report as text.
def render_clusters(report: dict) -> str:
    """Return the clusters and capped targets as lines."""
    lines = [
        f"clusters on {report['session']} ({report.get('policy')}): "
        f"{len(report['targets'])} target names"
    ]
    for rho, clusters in report["by_rho"].items():
        lines.append(f"  rho* {rho}:")
        for g in clusters:
            corr = g["mean_corr"]
            mean = "" if corr != corr else f", mean residual corr {corr:+.2f}"
            lines.append(f"    {' '.join(g['names'])} ({_pct(g['weight'])}{mean})")
    for tag, arm in report["arms"].items():
        moved = ", ".join(
            f"{name} {_pct(report['targets'][name])}->{_pct(w)}"
            for name, w in arm["weights"].items()
            if not math.isclose(w, report["targets"][name])
        )
        lines.append(
            f"  {tag}: {'binds' if arm['binds'] else 'does not bind'}"
            + (f"; {moved}; cash {_pct(arm['cash'])}" if arm["binds"] else "")
        )
    if report.get("targets_not_in_panel"):
        lines.append(f"  targets not in the panel: {report['targets_not_in_panel']}")
    return "\n".join(lines)


# The arms a run names: the registered three unless `--arms` lists C:RHO.
def _specs(texts) -> tuple:
    """Return the specs to run."""
    return tuple(cc.parse_spec(x) for x in texts) if texts else cc.REGISTERED


# The command line.
def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="the control and the arms' payloads")
    score.add_argument("--root", default="data/market")
    score.add_argument("--offsets", type=int, default=20)
    score.add_argument("--costs", type=float, nargs="+", default=[10.0, 25.0])
    score.add_argument("--membership", type=Path)
    score.add_argument(
        "--arms", nargs="+", metavar="C:RHO", help="default: the registered three"
    )
    score.add_argument(
        "--null", action="store_true", help="also write the C = 100%% payload"
    )
    score.add_argument("--output-dir", type=Path, required=True)
    null = sub.add_parser("null-test", help="C = 100%% against the plain path")
    null.add_argument("--root", default="data/market")
    null.add_argument("--costs", type=float, nargs="+", default=[10.0, 25.0])
    null.add_argument("--offsets", type=int, default=2)
    null.add_argument("--membership", type=Path)
    verdict = sub.add_parser("verdict", help="each arm against the control")
    verdict.add_argument("--control", type=Path, required=True)
    verdict.add_argument("--arms", type=Path, nargs="+", required=True)
    verdict.add_argument("--output", type=Path, required=True)
    clusters = sub.add_parser("clusters", help="a recorded session's clusters")
    clusters.add_argument("--root", default="data/market")
    clusters.add_argument("--session", required=True)
    clusters.add_argument("--output", type=Path)
    return parser


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Run the subcommand; return the exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "verdict":
        control = _load(args.control)
        arms = {}
        for path in args.arms:
            payload = _load(path)
            tag = payload.get("cluster_cap", {}).get("spec", {}).get("tag") or path.stem
            if tag in arms:
                raise SystemExit(f"two payloads carry the tag {tag!r}")
            arms[tag] = payload
        record = verdict_record(control, arms)
        record["sources"] = {
            "control": str(args.control),
            "arms": {tag: str(p) for tag, p in zip(arms, args.arms, strict=True)},
        }
        _write(args.output, record)
        print(render_verdict(record, control))
        print(f"\nwrote {args.output}")
        return 0
    if args.command == "clusters":
        report = session_clusters(Path(args.root), args.session, cc.REGISTERED)
        print(render_clusters(report))
        if args.output:
            _write(args.output, report)
            print(f"\nwrote {args.output}")
        return 0
    from backend.market.store import MarketStore

    store = MarketStore(Path(args.root))
    history = args.membership or universe.MEMBERSHIP_HISTORY_PATH
    report = desk_report(store)
    if args.command == "null-test":
        result = null_test(report, store, history, args.offsets, tuple(args.costs))
        print(render_null_test(result))
        return 0 if result["ok"] else 1
    specs = _specs(args.arms) + ((cc.NULL,) if args.null else ())
    payloads = build(report, store, args.offsets, tuple(args.costs), history, specs)
    for key, payload in payloads.items():
        path = args.output_dir / f"{key}.json"
        _write(path, payload)
        print(sc.render(payload))
        if "cluster_cap" in payload:
            print(render_binding(key, payload["cluster_cap"]["binding"]))
        print(f"wrote {path}\n")
    return 0


# Write a JSON file (NaN allowed, as the scorecard writes).
def _write(path: Path, payload: dict) -> None:
    """Write `payload` to `path`, creating the folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
