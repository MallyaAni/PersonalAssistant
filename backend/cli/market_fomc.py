"""Compare predeclared FOMC risk windows; read-only, never changes live targets.

python -m backend.cli.market_fomc --asof 2026-09-11

All candidates use 50% exposure for 1/3/5/10 sessions before the event and
through its decision session, restoring at the following open. Conditional
candidates wait for negative five-session SPY performance, then stay reduced
through the meeting. Event changes execute at the next open even on a green
day; other orders retain LIVE_POLICY. Output includes costs, full-history
results and a separate post-policy-change slice. The latter has very few
meetings and cannot establish causation or an out-of-sample trading edge.
The evaluation starts in 2021: the older event list includes unscheduled
2020 actions and does not preserve when cancellations became known, so it
cannot support an honest pre-event strategy over that year.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk, event_risk, simulate
from backend.config.settings import settings
from backend.market.calendar import fomc_decisions
from backend.market.store import MarketStore


# Bound even nested readers that omit asof, including the expectations-gap loader.
class ResearchStore(MarketStore):
    # Pin every partition lookup to the evaluation's requested input cut.
    def __init__(self, root: Path, asof: date):
        super().__init__(root)
        self.cutoff = asof

    # Hide later bar partitions from readers that ask for the latest available one.
    def asofs(self) -> list[date]:
        return [day for day in super().asofs() if day <= self.cutoff]

    # Apply the same bound to all generic filing, tone and macro frames.
    def _latest_of_kind(self, kind: str, ticker: str, asof: date | None):
        return super()._latest_of_kind(
            kind, ticker, min(asof or self.cutoff, self.cutoff)
        )


# Measure candidate exposure on an immutable data cut without publishing it.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    parser.add_argument("--asof", type=date.fromisoformat, required=True)
    parser.add_argument("--since", type=date.fromisoformat, default=date(2021, 1, 1))
    parser.add_argument(
        "--selected",
        action="store_true",
        help="Evaluate only the adopted three-session conditional lifecycle",
    )
    args = parser.parse_args()
    if args.since < date(2021, 1, 1) or args.since >= args.asof:
        parser.error("--since must be at least 2021-01-01 and earlier than --asof")
    report = desk.run(ResearchStore(args.data_dir, args.asof), asof=args.asof)
    decisions = [d for d in fomc_decisions() if d >= date(2021, 1, 1)]
    for since in (args.since, date(2026, 6, 18)):
        # Count independent completed events, not the many names or days around each.
        completed = [
            str(d)
            for d in decisions
            if since <= d < report.panel.dates[-1].astype(object)
        ]
        for cost in (10, 25):
            base = simulate.run(
                report,
                since=since,
                use_exits=False,
                cost_bps=cost,
                **simulate.LIVE_POLICY,
            )
            for window in (3,) if args.selected else (1, 3, 5, 10):
                for conditional in (True,) if args.selected else (False, True):
                    path = event_risk.exposure_path(
                        report.panel, decisions, window, require_weakness=conditional
                    )
                    result = simulate.run(
                        report,
                        since=since,
                        use_exits=False,
                        cost_bps=cost,
                        event_exposure=path,
                        event_lifecycle=args.selected,
                        **simulate.LIVE_POLICY,
                    )
                    delta = result.stats()["total"] - base.stats()["total"]
                    print(
                        json.dumps(
                            {
                                "asof": str(args.asof),
                                "last_session": str(report.panel.dates[-1]),
                                "since": str(since),
                                "cost_bps": cost,
                                "pre_sessions": window,
                                "require_weakness": conditional,
                                "completed_meetings": completed,
                                "baseline": base.stats(),
                                "candidate": result.stats(),
                                "total_return_difference": delta,
                                "protected_decisions": int(
                                    np.sum(
                                        path[
                                            np.searchsorted(
                                                report.panel.dates, np.datetime64(since)
                                            ) :
                                        ]
                                        < 1
                                    )
                                ),
                                "live_enabled": args.selected,
                                "execution_lifecycle": event_risk.VERSION
                                if args.selected
                                else "research scale-only",
                                "evaluation_periods": event_risk.evaluation_slices(
                                    result
                                ),
                                "qualification": (
                                    "exploratory; current universe; revised inputs; "
                                    "no causal or out-of-sample claim"
                                ),
                            }
                        ),
                        flush=True,
                    )


if __name__ == "__main__":
    main()
