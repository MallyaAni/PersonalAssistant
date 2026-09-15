"""Old versus corrected: two opportunity-learning runs on the same metrics.

    python -m backend.cli.market_opportunity_compare --old A --new B --report OUT

Both runs must have been produced by `market_opportunity_learning`. For
every policy at both costs the table carries the validation net log
growth, the test period's net return and worst drawdown, turnover (the sum
of the decisions' traded fraction, and its mean per decision), cash
exposure (the mean of the decisions' target cash, held between decisions
because positions only drift), gross exposure as one minus that, and the
excess net return against SPY and against the equal-weight control from
the same run. Every test-period number is labelled retrospective: the
period was examined by the original research and by the selection of the
neural epoch. Fingerprints of source, features, prices and fundamental
versions are copied from each manifest so the two runs are identifiable.
Nothing here trains, promotes or deploys.
"""

import argparse
import json
from pathlib import Path

import numpy as np

COSTS = ("10bps", "30bps")


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    return parser


# One run's summary per policy@cost.
def summarize(run: Path) -> dict:
    """Return {policy@cost: metrics} plus fingerprints for a run directory."""
    results = json.loads((run / "results.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    out = {}
    for key, result in results["results"].items():
        decisions = result["decisions"]
        turnover = [float(d["turnover"]) for d in decisions]
        cash = [float(d["target_cash"]) for d in decisions]
        out[key] = {
            "net_return": float(result["metrics"]["total_return"]),
            "log_growth": float(result["metrics"]["log_growth"]),
            "drawdown": float(result["metrics"]["drawdown"]),
            "transitions": int(result["metrics"]["transitions"]),
            "decisions": len(decisions),
            "turnover_total": float(sum(turnover)),
            "turnover_per_decision": float(np.mean(turnover)) if turnover else 0.0,
            "cash_exposure": float(np.mean(cash)) if cash else 1.0,
            "gross_exposure": 1.0 - float(np.mean(cash)) if cash else 0.0,
        }
    for cost in COSTS:
        spy = out.get(f"SPY@{cost}", {}).get("net_return")
        equal = out.get(f"equal@{cost}", {}).get("net_return")
        for key, row in out.items():
            if key.endswith(cost):
                row["excess_vs_spy"] = (
                    row["net_return"] - spy if spy is not None else None
                )
                row["excess_vs_equal"] = (
                    row["net_return"] - equal if equal is not None else None
                )
    return {
        "policies": out,
        "validation_log_growth": results["validation_log_growth"],
        "validation_winner": results["validation_winner"],
        "neural_selected_epoch": results["neural_selection"]["selected_epoch"],
        "fingerprints": {
            "source": manifest.get("source"),
            "feature_sha256": manifest.get("feature_sha256"),
            "price_sha256": manifest.get("price_sha256"),
            "fundamentals": manifest.get("fundamentals", "frozen"),
            "fundamental_versions_sha256": manifest.get("fundamental_versions_sha256"),
            "financial_coverage": manifest.get("financial_coverage"),
            "train_examples": manifest.get("train_examples"),
            "test_first": manifest.get("test_first"),
            "test_last": manifest.get("test_last"),
        },
    }


def _pct(v) -> str:
    return "     n/a" if v is None else f"{100 * v:+7.1f}%"


def render(old: dict, new: dict) -> str:
    """Return the comparison as text."""
    lines = ["RETROSPECTIVE: the test period was examined by the original research."]
    for tag, run in (("old", old), ("new", new)):
        f = run["fingerprints"]
        short = {k: str(v)[:12] for k, v in f.items()}
        lines.append(
            f"{tag:3} source {short['source']} features {short['feature_sha256']} "
            f"prices {short['price_sha256']} fundamentals {f['fundamentals']} "
            f"versions {short['fundamental_versions_sha256']} coverage "
            f"{f['financial_coverage']:.4f} train {f['train_examples']} "
            f"test {f['test_first']}..{f['test_last']}"
        )
    lines.append("")
    lines.append("validation net log growth (2024): old -> new")
    for name in sorted(
        set(old["validation_log_growth"]) | set(new["validation_log_growth"])
    ):
        a = old["validation_log_growth"].get(name)
        b = new["validation_log_growth"].get(name)
        left = "n/a" if a is None else f"{a:+.4f}"
        right = "n/a" if b is None else f"{b:+.4f}"
        lines.append(f"  {name:16} {left:>9} -> {right:>9}")
    lines.append(
        f"  winner {old['validation_winner']} (epoch {old['neural_selected_epoch']})"
        f" -> {new['validation_winner']} (epoch {new['neural_selected_epoch']})"
    )
    for cost in COSTS:
        lines.append("")
        heads = (
            "net old",
            "net new",
            "DD old",
            "DD new",
            "turn old",
            "turn new",
            "cash old",
            "cash new",
            "xSPY new",
            "xEQ new",
            "n",
        )
        lines.append(
            f"test at {cost}: {'policy':26} " + " ".join(f"{h:>9}" for h in heads)
        )
        keys = [k for k in new["policies"] if k.endswith(cost)]
        for key in sorted(keys):
            a = old["policies"].get(key, {})
            b = new["policies"][key]
            cells = (
                _pct(a.get("net_return")),
                _pct(b["net_return"]),
                _pct(a.get("drawdown")),
                _pct(b["drawdown"]),
                f"{a.get('turnover_total', float('nan')):9.2f}",
                f"{b['turnover_total']:9.2f}",
                _pct(a.get("cash_exposure")),
                _pct(b["cash_exposure"]),
                _pct(b.get("excess_vs_spy")),
                _pct(b.get("excess_vs_equal")),
                f"{b['transitions']:9d}",
            )
            lines.append(f"  {key.split('@')[0]:26} " + " ".join(cells))
    return "\n".join(lines)


def main() -> None:
    """Run the comparison."""
    args = build_parser().parse_args()
    old, new = summarize(args.old), summarize(args.new)
    print(render(old, new))
    if args.report:
        args.report.write_text(
            json.dumps({"old": old, "new": new}, indent=1, sort_keys=True)
        )
        print("report written:", args.report)


if __name__ == "__main__":
    main()
