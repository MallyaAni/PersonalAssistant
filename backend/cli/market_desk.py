"""Run the trading desk on the AI-and-software book and print what it says.

python -m backend.cli.market_desk                 # today's regime, grades, book
python -m backend.cli.market_desk --calibrate     # what each grade earned
python -m backend.cli.market_desk --brief SNDK    # one name's evidence
"""

import argparse
from datetime import date

import numpy as np

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
    parser.add_argument(
        "--history", nargs="*", default=[], help="tickers to print the grade history of"
    )
    parser.add_argument(
        "--since", type=date.fromisoformat, default=None, help="history start date"
    )
    parser.add_argument(
        "--backtest", nargs="*", default=[], help="tickers to run the trade backtest on"
    )
    parser.add_argument(
        "--book-backtest",
        action="store_true",
        help="simulate the graded book since --since against the references",
    )
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


# Print one name's grade history since a date: every grade change with the
# stances behind it and what the name did over the next 20 sessions, then
# the hold-while-graded backtest against buy-and-hold.
def _print_history(report, ticker: str, since, horizon: int = 20) -> None:
    if ticker not in report.panel.tickers:
        print(f"\n{ticker}: not in the book")
        return
    rows = trading_desk.history(report, ticker, horizon, since)
    if not rows:
        print(f"\n{ticker}: no sessions since {since}")
        return
    print(f"\n{ticker} grade history since {rows[0].date} ({len(rows)} sessions)")
    print(
        f"{'date':11} {'grade':5} {'votes':>5}  F  T  S  R  {'exp':>4} {'conf':>4} "
        f"{'next 20d':>9} {'beta-adj':>9}"
    )
    previous = None
    for row in rows:
        key = (row.grade, tuple(sorted(row.stances.items())))
        if key == previous and not row.earnings:
            continue
        previous = key
        marks = "  ".join(
            {1: "+", 0: ".", -1: "-"}[row.stances.get(k, 0)]
            for k in ("fundamental", "technical", "sentiment", "rotation")
        )
        fwd = f"{row.forward * 100:+8.1f}%" if np.isfinite(row.forward) else "        ?"
        res = (
            f"{row.forward_residual * 100:+8.1f}%"
            if np.isfinite(row.forward_residual)
            else "        ?"
        )
        tag = " earnings reaction day" if row.earnings else ""
        print(
            f"{str(row.date):11} {row.grade:5} {row.votes:5.1f}  {marks}  "
            f"{row.exposure:4.2f} {row.confidence:4.2f} {fwd:>9} {res:>9}{tag}"
        )
    print(f"\nper grade, next {horizon} sessions (beta-adjusted), {ticker} only:")
    for letter in GRADES:
        vals = [r.forward_residual for r in rows if r.grade == letter]
        vals = [v for v in vals if np.isfinite(v)]
        if vals:
            print(
                f"  {letter:3} {len(vals):4d} sessions  mean "
                f"{np.mean(vals) * 100:+.1f}%  "
                f"hit {np.mean(np.array(vals) > 0):.2f}"
            )
    for min_grade in ("A+", "A", "B"):
        bt = trading_desk.name_backtest(report, ticker, min_grade, since)
        print(
            f"hold while >= {min_grade:2}: in {bt.sessions_in}/{bt.sessions} sessions, "
            f"{bt.switches} switches, rule {bt.rule_return * 100:+.1f}% vs hold "
            f"{bt.hold_return * 100:+.1f}% vs SPY {bt.benchmark_return * 100:+.1f}%; "
            f"annualised in {bt.in_annualised * 100:+.0f}% "
            f"/ out {bt.out_annualised * 100:+.0f}%"
        )


# Print the trade-by-trade backtest of the desk's rules for some names, with
# each rule switched off in turn so its contribution shows.
def _print_backtest(report, tickers, since) -> None:
    from backend.agents.trading.desk import backtest, entry
    from backend.market import levels

    location = levels.level_features(report.panel)
    entries = entry.entries(report.panel, location)
    for ticker in tickers:
        if ticker not in report.panel.tickers:
            print(f"\n{ticker}: not in the book")
            continue
        print(f"\n{ticker} backtest since {since or report.panel.dates[0]}")
        print(
            f"{'rules':30} {'trades':>6} {'hit':>5} {'in':>9} "
            f"{'rule':>8} {'hold':>8} {'SPY':>8}"
        )
        results = {}
        for rules in backtest.variants():
            bt = backtest.run_name(report, entries, ticker, rules, since, location)
            results[rules.label] = bt
            print(
                f"{rules.label:30} {len(bt.trades):6d} {bt.hit_rate():5.2f} "
                f"{bt.sessions_in:4d}/{bt.sessions:<4d} {bt.equity * 100:+7.1f}% "
                f"{bt.hold * 100:+7.1f}% {bt.benchmark * 100:+7.1f}%"
            )
        main_run = results["desk rules (no stop, 10-day grade exit)"]
        print("  trades under the desk rules:")
        print(
            f"  {'entry':11} {'exit':11} {'kind':9} {'grade':5} {'size':>5} "
            f"{'days':>4} {'return':>8} {'worst':>7} reason"
        )
        for trade in main_run.trades:
            exit_date = str(trade.exit_date) if trade.exit_date is not None else "open"
            print(
                f"  {str(trade.entry_date):11} {exit_date:11} {trade.entry_kind:9} "
                f"{trade.entry_grade:5} {trade.size:5.2f} {trade.sessions:4d} "
                f"{trade.log_return * 100:+7.1f}% {trade.worst * 100:+6.1f}% "
                f"{trade.exit_reason}"
            )


# Print the graded book's simulation against the references.
def _print_book_backtest(report, since) -> None:
    print(f"\nbook backtest since {since or report.panel.dates[0]}")
    print(
        f"{'book':36} {'annual':>7} {'vol':>6} {'Sharpe':>6} {'max DD':>7} {'total':>8}"
    )
    for stat in trading_desk.book_backtest(report, since):
        print(
            f"{stat.label:36} {stat.annual_return * 100:+6.1f}% "
            f"{stat.annual_volatility * 100:5.1f}% {stat.sharpe:6.2f} "
            f"{stat.max_drawdown * 100:6.1f}% {stat.total_return * 100:+7.1f}%"
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
    for ticker in args.history:
        _print_history(report, ticker, args.since)
    if args.backtest:
        _print_backtest(report, args.backtest, args.since)
    if args.book_backtest:
        _print_book_backtest(report, args.since)
    if args.calibrate:
        _print_calibration(report)


if __name__ == "__main__":
    main()
