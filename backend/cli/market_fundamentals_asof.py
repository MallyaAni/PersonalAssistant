"""Versioned as-of fundamentals: fetch every filing, then audit the frozen path.

    python -m backend.cli.market_fundamentals_asof --refresh --tickers ADBE NVDA
    python -m backend.cli.market_fundamentals_asof --refresh --bundle
    python -m backend.cli.market_fundamentals_asof --audit --bundle

`--refresh` stores one `edgar_facts_versions` frame per name per day under
the market store: every filed value of every candidate tag with its
filing date and accession, nothing collapsed. `--audit` builds the as-of
levels from those frames on the store's panel and compares them, session
by session, with the frozen path's levels: how many periods carry more
than one filing, on how many sessions the as-of tag differs from the
frozen whole-history choice, and on how many sessions each level differs.
Research only; the frozen production experiment reads none of this.
"""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from backend.market import edgar
from backend.market import fundamentals_asof as fa
from backend.market.panel import build_panel
from backend.market.store import MarketStore


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data/market")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--tickers", nargs="*", default=[])
    parser.add_argument(
        "--bundle", action="store_true", help="the frozen bundle's names"
    )
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--report", type=Path, default=None)
    return parser


def _names(args) -> tuple[str, ...]:
    names = list(args.tickers)
    if args.bundle:
        from backend.market.opportunity_shadow import BUNDLE

        with np.load(BUNDLE, allow_pickle=False) as w:
            names += [t for t in w["tickers"].tolist() if t != "SPY"]
    return tuple(dict.fromkeys(names))


# Fetch and store the versions for the names; return the failures.
def refresh(
    store: MarketStore, names, asof: date, transport=edgar.sec_transport
) -> list[str]:
    """Store every filing of every name; return the names that failed."""
    pacer = edgar.Pacer()
    cik_map = edgar.fetch_cik_map(transport=transport, pacer=pacer)
    failed = []
    for ticker in names:
        cik = cik_map.get(ticker) or cik_map.get(ticker.replace("-", ""))
        if cik is None:
            print(f"{ticker:6} no CIK")
            failed.append(ticker)
            continue
        try:
            versions = fa.fetch_versions(cik, transport=transport, pacer=pacer)
        except edgar.EdgarUnavailableError as exc:
            print(f"{ticker:6} FAILED {exc}")
            failed.append(ticker)
            continue
        written = store.write_frame(
            fa.KIND,
            asof,
            ticker,
            fa.frame(versions),
            {
                "cik": str(cik),
                "source_time": datetime.now(UTC).isoformat(timespec="seconds"),
                "version": fa.VERSION,
            },
        )
        print(f"{ticker:6} {'ok' if written else 'kept'} {len(versions):5d} versions")
    return failed


# Compare as-of levels with the frozen path on the store's panel.
def audit(store: MarketStore, names, asof: date | None) -> dict:
    """Return the audit as plain data."""
    panel = build_panel(store, names, "SPY", {}, asof=asof)
    versions_by = {}
    for ticker in panel.tickers:
        found = store.read_frame(fa.KIND, ticker, asof)
        if found is not None:
            versions_by[ticker] = fa.versions_from_frame(found[0])
    frozen = fa.frozen_levels(store, panel, asof)
    per_name = {}
    for column, ticker in enumerate(panel.tickers):
        if ticker not in versions_by or ticker == panel.benchmark:
            continue
        versions = versions_by[ticker]
        trace: dict = {}
        fresh = fa.levels_for(versions, panel.dates, trace)
        # The same selector restricted to the frozen path's year-to-date rule:
        # its differences from the frozen path are availability, revision and
        # tag corrections; the full selector's differences from it are coverage.
        narrow = fa.levels_for(versions, panel.dates, None, fa.FROZEN_YTD_NAMES)
        # Periods refiled with a different value are restatements; the same
        # value refiled as a later filing's comparative is not.
        values_by_period: dict = {}
        for v in versions:
            values_by_period.setdefault((v.name, v.tag, v.start, v.end), set()).add(
                round(v.value, 6)
            )
        restated = sum(1 for vals in values_by_period.values() if len(vals) > 1)
        whole = {name: fa.snapshot_tag(name, versions) for name in trace}
        differing = {}
        for name in fa.LEVEL_NAMES:
            a, b = fresh[name], frozen[name][:, column]
            both = np.isfinite(a) & np.isfinite(b)
            with np.errstate(all="ignore"):
                rel = np.abs(a - b) / np.maximum(np.abs(b), 1e-9)
            differ = both & (rel > 1e-9)
            n = narrow[name]
            both_n = np.isfinite(n) & np.isfinite(b)
            with np.errstate(all="ignore"):
                rel_n = np.abs(n - b) / np.maximum(np.abs(b), 1e-9)
                rel_c = np.abs(a - n) / np.maximum(np.abs(n), 1e-9)
            corrections = both_n & (rel_n > 1e-9)
            coverage = (np.isfinite(a) & ~np.isfinite(n)) | (
                np.isfinite(a) & np.isfinite(n) & (rel_c > 1e-9)
            )
            source = {"revenue": "revenue", "earnings": "net_income"}.get(name, name)
            tags = trace.get(source)
            tag_differs = (
                np.array([tag is not None and tag != whole.get(source) for tag in tags])
                if tags
                else np.zeros(len(a), dtype=bool)
            )
            differing[name] = {
                "sessions_both_known": int(both.sum()),
                "sessions_differ": int(differ.sum()),
                "correction_sessions": int(corrections.sum()),
                "coverage_sessions": int(coverage.sum()),
                "differ_with_same_tag": int((differ & ~tag_differs).sum()),
                "differ_with_other_tag": int((differ & tag_differs).sum()),
                "only_asof_known": int((np.isfinite(a) & ~np.isfinite(b)).sum()),
                "only_frozen_known": int((~np.isfinite(a) & np.isfinite(b)).sum()),
            }
        per_name[ticker] = {
            "versions": len(versions),
            "periods": len(values_by_period),
            "periods_restated_with_a_different_value": restated,
            "levels": differing,
        }
    totals = {
        "names": len(per_name),
        "periods_restated_with_a_different_value": sum(
            v["periods_restated_with_a_different_value"] for v in per_name.values()
        ),
        "revenue_correction_sessions": sum(
            v["levels"]["revenue"]["correction_sessions"] for v in per_name.values()
        ),
        "revenue_coverage_sessions": sum(
            v["levels"]["revenue"]["coverage_sessions"] for v in per_name.values()
        ),
        "earnings_correction_sessions": sum(
            v["levels"]["earnings"]["correction_sessions"] for v in per_name.values()
        ),
        "earnings_coverage_sessions": sum(
            v["levels"]["earnings"]["coverage_sessions"] for v in per_name.values()
        ),
        "revenue_differ_with_same_tag": sum(
            v["levels"]["revenue"]["differ_with_same_tag"] for v in per_name.values()
        ),
        "revenue_differ_with_other_tag": sum(
            v["levels"]["revenue"]["differ_with_other_tag"] for v in per_name.values()
        ),
        "revenue_only_asof_known": sum(
            v["levels"]["revenue"]["only_asof_known"] for v in per_name.values()
        ),
        "revenue_only_frozen_known": sum(
            v["levels"]["revenue"]["only_frozen_known"] for v in per_name.values()
        ),
        "names_with_any_revenue_difference": sum(
            1 for v in per_name.values() if v["levels"]["revenue"]["sessions_differ"]
        ),
        "revenue_sessions_differ": sum(
            v["levels"]["revenue"]["sessions_differ"] for v in per_name.values()
        ),
        "revenue_sessions_both_known": sum(
            v["levels"]["revenue"]["sessions_both_known"] for v in per_name.values()
        ),
        "earnings_sessions_differ": sum(
            v["levels"]["earnings"]["sessions_differ"] for v in per_name.values()
        ),
        "shares_sessions_differ": sum(
            v["levels"]["shares"]["sessions_differ"] for v in per_name.values()
        ),
    }
    return {
        "panel": [str(panel.dates[0]), str(panel.dates[-1])],
        "totals": totals,
        "names": per_name,
    }


def main() -> None:
    """Run the tool."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.data_dir))
    names = _names(args)
    if args.refresh:
        failed = refresh(store, names, args.asof or datetime.now(UTC).date())
        print(
            f"versions refresh: {len(names) - len(failed)} stored, {len(failed)} failed"
        )
    if args.audit:
        report = audit(store, names, args.asof)
        print(json.dumps(report["totals"], indent=1))
        if args.report:
            args.report.write_text(json.dumps(report, indent=1, sort_keys=True))
            print("report written:", args.report)


if __name__ == "__main__":
    main()
