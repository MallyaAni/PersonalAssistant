"""Fixed-candidate funded allocation evaluation, run from the trusted cache.

This CLI produces the evaluation role's artifacts: one aligned npz per
candidate (`dates`, `daily`, `equity`, `exposure`), the candidate's complete
funded trace as JSON when the runner produced one, and a combined scorecard
payload with every metric, period, rolling-252, exposure-matched and
false-exit diagnostic the acceptance asks for.

The cached inputs live under `--inputs` (default
`/tmp/codex-trading-evaluation-inputs-20260921`) and are read only through
explicit local paths. The `common-window-reference` NPZ is the authoritative
independent control for the common dates and is cross-checked against its own
JSON; the independent benchmark reference JSON is cross-checked against the
aligned price npz.

Modes:

* `--baseline` (default): the incumbent candidate from the authoritative
  reference, cross-checked against `common-window-reference.json`.
* `--synthetic` (default): deterministic synthetic candidates that validate
  the scorecard machinery, clearly labelled and never promoted.
* `--final`: the incumbent and the two funded policies (`vol`, `vol_trend`)
  through the integrated simulator's shared funded execution path
  (`simulate.run` with `funded_allocation=True`). This is the post-review
  step; it is gated and is not run until root has accepted the shared
  execution path.

No commit, deploy, fetch, model recomputation or training happens here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from backend.market import allocation_evaluation as ev


# Pin the exact sources and cached inputs before any candidate is evaluated.
def _provenance(inputs: Path, report: Path | None, opens: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    names = [
        "backend/agents/trading/desk/" + name + ".py"
        for name in (
            "allocation",
            "funded_execution",
            "simulate",
            "risk",
            "paper",
            "event_risk",
        )
    ]
    names += [
        "backend/market/allocation_evaluation.py",
        "backend/market/allocation_controls.py",
        "backend/cli/market_allocation_compare.py",
    ]
    files = [
        inputs / name
        for name in (
            "allocation-benchmark-prices.npz",
            "common-window-reference.npz",
            "common-window-reference.json",
            "independent-benchmark-reference.json",
        )
    ]
    if report is not None:
        files.append(report)
    files.append(opens)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    return {
        "revision": revision.stdout.strip()
        if revision.returncode == 0
        else "unavailable",
        "source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in names
        },
        "input_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files
        },
        "note": "Working-file hashes pin source beyond the base revision.",
    }


# Locate the explicit trusted cache without contacting any provider.
def _default_inputs() -> Path:
    """Return the default cached-inputs directory."""
    return Path("/tmp/codex-trading-evaluation-inputs-20260921")


# Load the frozen benchmarks and independent reference accounts.
def _load_inputs(inputs: Path) -> dict[str, object]:
    """Return the validated cached inputs (prices, reference, independent ref)."""
    benchmark_npz = inputs / "allocation-benchmark-prices.npz"
    reference_npz = inputs / "common-window-reference.npz"
    reference_json = inputs / "common-window-reference.json"
    independent_json = inputs / "independent-benchmark-reference.json"
    for path in (benchmark_npz, reference_npz, reference_json, independent_json):
        if not path.is_file():
            raise FileNotFoundError(f"missing cached input: {path}")
    prices = ev.load_benchmark_prices(benchmark_npz)
    reference = ev.load_common_window_reference(reference_npz)
    reference_metrics = ev.load_independent_reference(reference_json)
    independent = ev.load_independent_reference(independent_json)
    return {
        "prices": prices,
        "reference": reference,
        "reference_metrics": reference_metrics,
        "independent": independent,
    }


# Cross-check the incumbent against the independently checked reference JSON.
def cross_check_incumbent(
    reference: ev.ReferenceControls, reference_metrics: dict
) -> None:
    """Assert the incumbent metrics reproduce the checked reference exactly."""
    incumbent = ev.metrics(reference.incumbent_daily[1:])
    expected = reference_metrics["metrics"]["incumbent"]
    if abs(incumbent["annual"] - expected["annual"]) >= 1e-12:
        raise AssertionError(
            f"incumbent annual {incumbent['annual']} != reference {expected['annual']}"
        )
    if abs(incumbent["drawdown"] + expected["drawdown"]) >= 1e-12:
        raise AssertionError(
            f"incumbent drawdown {incumbent['drawdown']} != reference "
            f"{expected['drawdown']}"
        )
    if abs(incumbent["worst_day"] - expected["worst_day"]) >= 1e-10:
        raise AssertionError(
            f"incumbent worst day {incumbent['worst_day']} != reference "
            f"{expected['worst_day']}"
        )
    if abs(incumbent["worst_five_sessions"] - expected["worst_five_sessions"]) >= 1e-10:
        raise AssertionError(
            f"incumbent worst five {incumbent['worst_five_sessions']} "
            f"!= reference {expected['worst_five_sessions']}"
        )
    if (
        incumbent["longest_underwater_sessions"]
        != expected["longest_underwater_sessions"]
    ):
        raise AssertionError(
            f"incumbent longest underwater "
            f"{incumbent['longest_underwater_sessions']} != reference "
            f"{expected['longest_underwater_sessions']}"
        )


# Cross-check the aligned price npz against the independent benchmark reference.
def cross_check_benchmarks(prices: ev.BenchmarkInputs, independent: dict) -> None:
    """Assert the price npz reproduces the independent benchmark conventions."""
    series = {ev.SPY: prices.spy, ev.QQQ: prices.qqq}
    for symbol, arr in series.items():
        benchmark = independent["benchmarks"][symbol]
        if benchmark["calendar_sessions"] != len(prices.dates):
            raise AssertionError(
                f"{symbol} sessions {len(prices.dates)} != "
                f"independent {benchmark['calendar_sessions']}"
            )
        if str(prices.dates[0]) != benchmark["from"]:
            raise AssertionError(
                f"{symbol} start {prices.dates[0]} != independent {benchmark['from']}"
            )
        if str(prices.dates[1]) != benchmark["fill"]:
            raise AssertionError(
                f"{symbol} fill {prices.dates[1]} != independent {benchmark['fill']}"
            )
        units = 1.0 / (
            benchmark["adjusted_fill_price"] * (1.0 + benchmark["initial_fee"])
        )
        ending = units * float(arr[-1])
        # The npz stores float32-quantized closes (761.69 as 761.6900024...),
        # so the reproduction of the independent reference's ending equity is
        # checked at float32 precision (~1e-6 relative), far below any real
        # basis error: a series that was not dividend-adjusted would differ by
        # tens of percent here.
        if not np.isclose(ending, benchmark["ending_equity"], rtol=1e-4, atol=0.0):
            raise AssertionError(
                f"{symbol} ending equity {ending} from these closes != "
                f"independent {benchmark['ending_equity']}"
            )


# Build a deterministic synthetic candidate series for machinery validation.
def _synthetic_candidates(
    reference: ev.ReferenceControls,
) -> list[ev.CandidateResult]:
    """Return labelled synthetic candidate series that validate the scorecard."""
    dates = reference.dates
    n = len(dates)
    cash_daily = np.full(n, np.nan)
    cash_daily[1:] = 0.0
    cash_equity = np.ones(n)
    full_daily = np.concatenate([[np.nan], reference.spy_daily[1:]])
    full_equity = np.concatenate([[1.0], reference.spy_equity[1:]])
    double = np.concatenate([[np.nan], 2.0 * reference.spy_daily[1:]])
    double_equity = np.concatenate(
        [[1.0], np.cumprod(1.0 + 2.0 * reference.spy_daily[1:])]
    )
    return [
        ev.CandidateResult(
            name="synthetic-cash",
            dates=dates,
            daily=cash_daily,
            equity=cash_equity,
            exposure=np.zeros(n),
            trace=None,
            method="synthetic: all cash, zero return",
        ),
        ev.CandidateResult(
            name="synthetic-full-spy",
            dates=dates,
            daily=full_daily,
            equity=full_equity,
            exposure=np.ones(n),
            trace=None,
            method="synthetic: holds SPY fully (equals the SPY control)",
        ),
        ev.CandidateResult(
            name="synthetic-double-spy",
            dates=dates,
            daily=double,
            equity=double_equity,
            exposure=np.ones(n),
            trace=None,
            method="synthetic: two times SPY daily return (cost-free)",
        ),
    ]


# The common-window price slices used by the exposure-matched diagnostic.
def _common_prices(prices: ev.BenchmarkInputs) -> dict[str, np.ndarray]:
    """Return {SPY, QQQ} adjusted closes over the common window."""
    lo = prices.common_start
    return {ev.SPY: prices.spy[lo:], ev.QQQ: prices.qqq[lo:]}


# Write one candidate's npz artifact (dates, daily, equity, exposure).
def _write_candidate_npz(candidate: ev.CandidateResult, directory: Path) -> Path:
    """Write the candidate's aligned npz artifact and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{candidate.name}.npz"
    kwargs: dict[str, np.ndarray] = {
        "dates": candidate.dates,
        "daily": candidate.daily,
        "equity": candidate.equity,
    }
    if candidate.exposure is not None:
        kwargs["exposure"] = candidate.exposure
    np.savez(path, **kwargs)
    return path


# Write one candidate's complete trace as JSON, when present.
def _write_candidate_trace(
    candidate: ev.CandidateResult, directory: Path
) -> Path | None:
    """Write the candidate's trace JSON and return its path, or None."""
    if candidate.trace is None:
        return None
    path = directory / f"{candidate.name}.trace.json"
    path.write_text(
        json.dumps(candidate.trace, indent=1, allow_nan=False), encoding="utf-8"
    )
    return path


# Run one candidate and record its payload plus artifacts.
def _run_candidate(
    candidate: ev.CandidateResult,
    controls: dict[str, np.ndarray],
    common_prices: dict[str, np.ndarray],
    artifact_dir: Path,
    common_opens: dict[str, np.ndarray],
) -> dict[str, object]:
    """Return the candidate's scorecard payload and write its artifacts."""
    ev.validate_candidate_series(
        candidate.name, candidate.dates, candidate.daily, candidate.equity
    )
    payload = ev.evaluate_candidate(candidate, controls, common_prices, common_opens)
    npz = _write_candidate_npz(candidate, artifact_dir)
    trace = _write_candidate_trace(candidate, artifact_dir)
    payload["artifacts"] = {
        "npz": str(npz),
        "trace": str(trace) if trace is not None else None,
    }
    return payload


# The fixed yearly convention note the payload carries.
def _yearly_convention() -> str:
    """Return the fixed yearly-convention note for the scorecard payload."""
    return (
        "First return of each calendar year includes the change from the "
        "preceding close; no account restart."
    )


# Validate opening prices against the calendar and independent account curves.
def _verified_opens(path, prices, reference) -> dict[str, np.ndarray]:
    from backend.market.allocation_controls import constant_exposure

    open_prices = ev.load_benchmark_prices(path)
    if not np.array_equal(open_prices.dates, prices.dates):
        raise ValueError("adjusted-open calendar differs from benchmark closes")
    common_opens = _common_prices(open_prices)
    common_prices = _common_prices(prices)
    for symbol, expected in (
        (ev.SPY, reference.spy_equity),
        (ev.QQQ, reference.qqq_equity),
    ):
        reproduced = constant_exposure(common_prices[symbol], common_opens[symbol], 1.0)
        if not np.allclose(reproduced, expected, rtol=1e-12, atol=1e-12):
            raise ValueError(f"{symbol} next-open control does not reproduce reference")
    return common_opens


# The main entry point.
def main(argv: list[str] | None = None) -> int:
    """Run the requested evaluation modes and write their artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=_default_inputs())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--opens",
        type=Path,
        required=True,
        help="verified adjusted-open npz on the benchmark calendar",
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="trusted desk report pickle"
    )
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--final", action="store_true")
    parser.add_argument(
        "--index-eligible",
        action="store_true",
        help="allow SPY in hypothetical research accounts; grants no live permission",
    )
    args = parser.parse_args(argv)
    if not (args.baseline or args.synthetic or args.final):
        args.baseline = True
        args.synthetic = True
    loaded = _load_inputs(args.inputs)
    prices = loaded["prices"]
    reference = loaded["reference"]
    reference_metrics = loaded["reference_metrics"]
    independent = loaded["independent"]
    controls = ev.controls_from_reference(reference)
    common_prices = _common_prices(prices)
    common_opens = _verified_opens(args.opens, prices, reference)
    artifact_dir = args.out / "artifacts"
    payload: dict[str, object] = {
        "provenance": _provenance(args.inputs, args.report, args.opens),
        "from": str(reference.dates[0]),
        "to": str(reference.dates[-1]),
        "cost_bps": ev.COST_BPS,
        "cash_income": ev.CASH_INCOME,
        "research_index_eligible": args.index_eligible,
        "status": (
            "Retrospective reused survivor-biased data; not independent "
            "holdout evidence"
        ),
        "yearly_convention": _yearly_convention(),
        "accounts": {},
    }
    if args.baseline:
        cross_check_incumbent(reference, reference_metrics)
        cross_check_benchmarks(prices, independent)
        payload["accounts"]["incumbent"] = _run_candidate(
            ev.run_incumbent(reference),
            controls,
            common_prices,
            artifact_dir,
            common_opens,
        )
        print("BASELINE: incumbent matches the independent reference")
    if args.synthetic:
        for candidate in _synthetic_candidates(reference):
            payload["accounts"][candidate.name] = _run_candidate(
                candidate, controls, common_prices, artifact_dir, common_opens
            )
        print("SYNTHETIC: scorecard machinery validated on labelled candidates")
    if args.final:
        if args.report is None:
            print(
                "ERROR: --final requires --report <trusted desk report pickle>",
                file=sys.stderr,
            )
            return 2
        report, _ = ev.load_cached_report(args.report)
        for policy in ("vol", "vol_trend"):
            candidate = ev.run_funded_candidate(
                report,
                prices,
                policy,
                index_eligible=args.index_eligible,
            )
            if not np.array_equal(candidate.dates, reference.dates):
                raise ValueError(
                    "candidate calendar differs from the independent controls"
                )
            payload["accounts"][policy] = _run_candidate(
                candidate, controls, common_prices, artifact_dir, common_opens
            )
        print("FINAL: funded candidates ran through the fixed ledger")
    names = "-".join(payload["accounts"])
    destination = args.out / f"allocation-evaluation-{names}.json"
    args.out.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {"artifact": str(destination), "accounts": list(payload["accounts"])}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
