"""Run the trading desk on the AI-and-software book and print what it says.

python -m backend.cli.market_desk                 # today's regime, grades, book
python -m backend.cli.market_desk --calibrate     # what each grade earned
python -m backend.cli.market_desk --brief SNDK    # one name's evidence
"""

import argparse
from datetime import date

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk.grading import GRADES
from backend.config.settings import settings
from backend.market.store import MarketStore


# Build the CLI parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=settings.MARKET_DATA_ROOT)
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="print the forward beta-adjusted return of each grade at 20 and 60",
    )
    parser.add_argument(
        "--brief", nargs="*", default=[], help="tickers to print the evidence for"
    )
    parser.add_argument("--top", type=int, default=25)
    return parser


# Print the regime state and its flags.
def _print_regime(state) -> None:
    print(
        f"regime: AI participation {state.ai_participation:+.2f} "
        f"(pct {state.participation_percentile:.2f}), software "
        f"{state.software_participation:+.2f}; AI-vs-software corr "
        f"{state.ai_vs_software_correlation:+.2f} (z {state.correlation_z:+.1f}); "
        f"novelty z {state.novelty_z:+.1f}; leader {state.rotation_leader} "
        f"({state.rotation_spread:+.3f}); AI drawdown {state.ai_drawdown:+.3f}"
    )
    print(
        f"        selection confidence {state.selection_confidence:.2f}, "
        f"exposure {state.exposure:.2f}"
    )
    for flag in state.flags:
        print(f"        ! {flag}")


# Print the grade counts and the top names with their stances.
def _print_grades(report, top: int) -> None:
    panel = report.panel
    last = len(panel.dates) - 1
    counts = dict.fromkeys(GRADES, 0)
    rows = []
    for column, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        counts[report.graded.letter(last, column)] += 1
        rows.append((report.scores[last, column], column, ticker))
    print("grades today:", ", ".join(f"{g} {n}" for g, n in counts.items()))
    header = f"{'ticker':7} {'side':9} {'grade':5} {'votes':>5}  F  T  S  R  "
    print(f"\n{header}{'score':>6}")
    rows.sort(reverse=True)
    stances = report.graded.stances
    for score, column, ticker in rows[:top]:
        marks = "  ".join(
            {1: "+", 0: ".", -1: "-"}[int(stances[k][last, column])]
            for k in ("fundamental", "technical", "sentiment", "rotation")
        )
        print(
            f"{ticker:7} {report.sides.get(ticker, '?'):9} "
            f"{report.graded.letter(last, column):5} "
            f"{report.graded.votes[last, column]:5.1f}  {marks}  {score:6.2f}"
        )


# Print the sized book.
def _print_book(report) -> None:
    print(f"\nbook (gross {trading_desk.risk.gross(report.book):.2f}):")
    for sized in report.book:
        p = sized.position
        print(
            f"  {p.ticker:6} {sized.grade:3} {sized.weight:6.3f} "
            f"(engine {p.weight:.3f} x grade {sized.multiplier:.2f} "
            f"x exposure {sized.exposure:.2f}; vol {p.volatility:.0%}) {p.note}"
        )


# Print one name's grade and every analyst's evidence.
def _print_brief(report, ticker: str) -> None:
    if ticker not in report.panel.tickers:
        print(f"\n{ticker}: not in the book")
        return
    brief = report.brief(ticker)
    print(f"\n{ticker} ({brief['side']}): grade {brief['grade']}, ", end="")
    print(f"votes {brief['votes']:.1f}")
    for analyst, evidence in brief["evidence"].items():
        stance = brief["stances"].get(analyst, 0)
        cited = ", ".join(f"{k} {v:+.3f}" for k, v in evidence.items())
        print(f"  {analyst:12} stance {stance:+d}: {cited or 'no view'}")


# Print what each grade earned at 20 and 60 sessions.
def _print_calibration(report) -> None:
    print(f"\n{'grade':6} {'h':>3} {'periods':>7} {'names':>6} {'mean bp':>8} {'t':>6}")
    for horizon in (20, 60):
        stats, harness = trading_desk.calibrate(report, horizon)
        for s in stats:
            print(
                f"{s.grade:6} {s.horizon:3d} {s.periods:7d} {s.names_per_period:6.1f}"
                f" {s.mean_bp:8.0f} {s.tstat:6.2f}"
            )
        print(
            f"graded score h{horizon}: rank IC {harness.mean_ic:.4f} "
            f"(t {harness.ic_tstat:.2f}), net Sharpe {harness.net_sharpe:.2f}"
        )


# Run the desk and print everything asked for.
def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(args.data_dir), args.asof)
    panel = report.panel
    print(f"desk as of {panel.dates[-1]} on {len(panel.tickers) - 1} names")
    _print_regime(report.regime.today())
    _print_grades(report, args.top)
    _print_book(report)
    for ticker in args.brief:
        _print_brief(report, ticker)
    if args.calibrate:
        _print_calibration(report)


if __name__ == "__main__":
    main()
