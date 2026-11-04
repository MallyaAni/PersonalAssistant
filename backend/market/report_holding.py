"""Report-bound holding reader for the installed grade-led leader rule.

The grade-led leader rule sizes from the report's own trailing closes and never
reads the learned scenario distribution or the learned fifteen-minute timing.
Its live path therefore binds the authenticated nightly report to the installed
risk bank's calendar and symbol universe instead of requiring the October-only
monthly holding model, timing publication and residual month, which expired on
2026-11-01 and cannot be refitted locally.

The reader exposes only what the funded decision needs: the report's dates and
symbols, the same clock guard as the learned close, and a byte-level report
comparison. It refuses the learned distribution rather than fabricating one.
"""

import json
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.market import forward_arithmetic as forward
from backend.market import learned_entry_models as base
from backend.market.direct_error_band import VolatilityHoldingReader

POLICY = "report-holding-reader/1"
BENCHMARKS = ("SPY", "QQQ")


# Bind one authenticated report to the installed risk bank without a monthly model.
class ReportHoldingReader:
    def __init__(
        self,
        original,
        report,
        provenance,
        *,
        risk_receipt_sha256,
        observed_at,
    ):
        if not isinstance(original, VolatilityHoldingReader):
            raise ValueError("Authenticated installed risk bank required")
        if (
            not isinstance(provenance, dict)
            or not isinstance(provenance.get("data_as_of"), str)
            or not isinstance(provenance.get("daily_published_at"), str)
            or not isinstance(provenance.get("grade_sha256"), str)
            or len(provenance["grade_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in provenance["grade_sha256"])
        ):
            raise ValueError("Authenticated current report provenance required")
        observed = forward.reference._as_of(observed_at)
        data_as_of = forward.reference._as_of(provenance["data_as_of"])
        daily_published = forward.reference._as_of(provenance["daily_published_at"])
        if data_as_of > observed or daily_published > data_as_of:
            raise ValueError("Current report observation clock differs")
        dates = np.asarray(report.panel.dates)
        symbols = tuple(report.panel.tickers)
        prices = np.asarray(report.panel.adj_close)
        grades = np.asarray(report.graded.grades)
        if (
            dates.dtype != np.dtype("datetime64[D]")
            or dates.ndim != 1
            or len(dates) < 2
            or np.isnat(dates).any()
            or np.any(dates[1:] <= dates[:-1])
            or not 2 <= len(symbols) <= 512
            or len(set(symbols)) != len(symbols)
            or prices.shape != (len(dates), len(symbols))
            or grades.shape != prices.shape
            or not np.isin(grades, (-1, 0, 1, 2, 3)).all()
        ):
            raise ValueError("Aligned authenticated current report required")
        if any(name not in original.symbols for name in symbols):
            raise ValueError("Current report has a stock outside the installed risk bank")
        if dates[0] != original.dates[0] or not np.array_equal(
            dates[: len(original.dates)], original.dates
        ):
            raise ValueError(
                "Installed risk-bank calendar is not a prefix of the current report"
            )
        eligible = grades >= 0
        for benchmark in BENCHMARKS:
            if benchmark in symbols:
                eligible[:, symbols.index(benchmark)] = False
        forward._close_window(dates[-1], observed)
        prefix = {
            "dates": forward.reference._hash(dates),
            "prices": forward.reference._hash(prices),
            "grades": forward.reference._hash(grades),
            "eligible": forward.reference._hash(eligible),
        }
        identity = {
            "policy": POLICY,
            "risk_receipt_sha256": risk_receipt_sha256,
            "data_as_of": data_as_of.isoformat(),
            "daily_published_at": daily_published.isoformat(),
            "observed_at": observed.isoformat(),
            "published_at": observed.isoformat(),
            "session": str(dates[-1]),
            "symbols": list(symbols),
            "prefix_sha256": prefix,
            "grade_sha256": provenance["grade_sha256"],
            "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        receipt = {
            "identity": identity,
            "identity_sha256": base._json_hash(identity),
            "status": "report_bound",
            "adoption_eligible": False,
        }
        # Freeze the exact report rows the funded decision was admitted against.
        self._dates = dates.copy()
        self._prices = prices.copy()
        self._grades = grades.copy()
        self._eligible = eligible.copy()
        for value in (self._dates, self._prices, self._grades, self._eligible):
            value.flags.writeable = False
        self.dates = self._dates
        self.symbols = symbols
        self.current = None
        self.receipt = receipt

    # Refuse a cached report at the actual funded decision instant.
    def validate_clock(self, instant):
        forward._close_window(self.dates[-1], instant)

    # Bind funded planning to the same grades, prices and complete report prefix.
    def validate_report(self, report):
        if tuple(report.panel.tickers) != self.symbols:
            raise ValueError(
                "Funded report differs from published current report: symbols"
            )
        prefix = self.receipt["identity"]["prefix_sha256"]
        if forward.reference._hash(np.asarray(report.panel.dates)) != prefix["dates"]:
            raise ValueError(
                "Funded report differs from published current report: dates"
            )
        if not np.array_equal(
            np.asarray(report.panel.adj_close), self._prices, equal_nan=True
        ):
            raise ValueError(
                "Funded report differs from published current report: prices"
            )
        if not np.array_equal(np.asarray(report.graded.grades), self._grades):
            raise ValueError(
                "Funded report differs from published current report: grades"
            )

    # The leader rule never reads a learned scenario distribution.
    def distribution(self, day, symbols):
        raise ValueError(
            "Grade-led leader policy does not read the learned distribution"
        )
