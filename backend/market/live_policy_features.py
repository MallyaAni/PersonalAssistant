"""Reuse exact nightly prefix features across private comparison accounts.

Only account-independent outputs are cached; no alternate arithmetic, shortened
lookback or scale-invariance shortcut is used. The launcher must authenticate
the immutable source tree identified by source_sha256 before creating this cache.
The cache neither certifies historical availability nor changes account sizing.
"""

import copy
import hashlib
import json

import numpy as np

from backend.market.daily_arithmetic_bridge import _hash
from backend.market.live_policy_report import NightlyReport

KINDS = frozenset(("event", "blocked", "entries"))
FIELDS = ("dates", "open", "high", "low", "close", "adj_close", "volume")


# Bind all consumed prefix bytes and metadata without retaining the price matrices.
def fingerprint(report):
    if not isinstance(report, NightlyReport):
        raise ValueError("Private authenticated nightly report required")
    panel = report.panel
    shape = (len(panel.dates), len(panel.tickers))
    if (
        not shape[0]
        or len(set(panel.tickers)) != shape[1]
        or panel.benchmark not in panel.tickers
        or np.asarray(panel.dates).dtype != np.dtype("datetime64[D]")
        or not np.all(np.diff(panel.dates) > np.timedelta64(0, "D"))
        or np.asarray(report.graded.grades).shape != shape
        or any(np.asarray(getattr(panel, name)).shape != shape for name in FIELDS[1:])
    ):
        raise ValueError("Aligned causal nightly prefix required")
    identity = {
        "tickers": panel.tickers,
        "benchmark": panel.benchmark,
        "themes": dict(panel.themes),
        "provenance": report.provenance,
        "excluded": report.excluded,
        "arrays": {name: _hash(getattr(panel, name)) for name in FIELDS},
        "grades": _hash(report.graded.grades),
    }
    payload = json.dumps(identity, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


# Cache only real nightly feature results for a launcher-authenticated source tree.
class FeatureCache:
    # Require an explicit source identity and initialize a small output-only cache.
    def __init__(self, source_sha256):
        if (
            not isinstance(source_sha256, str)
            or len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)
        ):
            raise ValueError("Authenticated source SHA256 required")
        self.source_sha256 = source_sha256
        self._outputs = {}
        self.computations = {kind: 0 for kind in KINDS}
        self.hits = {kind: 0 for kind in KINDS}

    # Evaluate lazily in the exact supplied basis and return detached cached outputs.
    def __call__(self, kind, report):
        if kind not in KINDS:
            raise ValueError("Unsupported nightly feature")
        key = (self.source_sha256, kind, fingerprint(report))
        if key not in self._outputs:
            from backend.agents.trading.desk import event_risk
            from backend.cli import market_daily

            if kind == "event":
                value = event_risk.decision(report.panel)
            elif kind == "blocked":
                value = market_daily._band_blocked(report)
            else:
                value = market_daily._price_entries(report)
            self._outputs[key] = copy.deepcopy(value)
            self.computations[kind] += 1
        else:
            self.hits[kind] += 1
        return copy.deepcopy(self._outputs[key])

    # Publish cache usage without exposing or mutating saved feature verdicts.
    def receipt(self):
        return {
            "source_sha256": self.source_sha256,
            "entries": len(self._outputs),
            "computations": dict(self.computations),
            "hits": dict(self.hits),
            "arithmetic": "exact_current_basis_full_prefix_original_functions",
        }
