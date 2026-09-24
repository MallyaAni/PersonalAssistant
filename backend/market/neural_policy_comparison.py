"""Research-only neural ranking comparison through the unchanged live account rules.

This tests a ranking substitution. It is neither a replay of the original neural
shadow portfolio nor evidence that reconstructed grades were published historically.
"""

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import paper, simulate
from backend.market import baselines

POLICY_NEURAL = "neural-ranking-live-rules/1-research"
POLICY_BLEND = "incumbent-neural-rank-blend/1-research"
POLICY = POLICY_NEURAL
POLICIES = (POLICY_NEURAL, POLICY_BLEND)


@dataclass(frozen=True)
class ForecastEvidence:
    """Predictions with dated fitting, selection and feature-availability boundaries."""

    dates: np.ndarray
    tickers: tuple[str, ...]
    values: np.ndarray
    fit_on: np.ndarray
    training_label_end: np.ndarray
    selection_label_end: np.ndarray
    feature_available_on: np.ndarray
    model_sha256: str
    input_sha256: str
    evidence_basis: str = "reconstructed-research"


# Keep daily availability assertions distinct from finer publication timestamps.
def _daily(values):
    result = np.asarray(values)
    if result.dtype != np.dtype("datetime64[D]"):
        raise ValueError(
            "daily session dates required; timestamps must be resolved upstream"
        )
    return result


# Refuse missing, misaligned or temporally contaminated predictions before simulation.
def validate(report, evidence: ForecastEvidence, since: date) -> int:
    panel = report.panel
    dates = _daily(panel.dates)
    if len(dates) < 2 or np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("a strictly increasing decision calendar is required")
    if (
        not np.array_equal(_daily(evidence.dates), dates)
        or evidence.tickers != panel.tickers
    ):
        raise ValueError("forecast dates and ticker order must match the report")
    if evidence.evidence_basis != "reconstructed-research":
        raise ValueError(
            "this adapter is restricted to explicitly reconstructed research"
        )
    for digest in (evidence.model_sha256, evidence.input_sha256):
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("exact model and input SHA256 fingerprints are required")
    shape = (len(dates), len(panel.tickers))
    values = np.asarray(evidence.values, dtype=float)
    available = _daily(evidence.feature_available_on)
    if values.shape != shape or available.shape != shape:
        raise ValueError("forecasts and availability must cover the full report grid")
    start = int(np.searchsorted(dates, np.datetime64(since)))
    if start >= len(dates) - 1:
        raise ValueError("at least one subsequent execution session is required")
    active = slice(start, len(dates) - 1)
    if not np.isfinite(values[active]).all():
        raise ValueError("missing forecasts invalidate the common comparison window")
    if np.isnat(available[active]).any() or np.any(
        available[active] > dates[active, None]
    ):
        raise ValueError("features were unavailable at a decision")
    _validate_model_dates(evidence, dates, active)
    return start


# Enforce outcome maturity separately from each observation's feature availability.
def _validate_model_dates(evidence, dates, active):
    fit, train, selection = (
        _daily(value)
        for value in (
            evidence.fit_on,
            evidence.training_label_end,
            evidence.selection_label_end,
        )
    )
    if any(value.shape != dates.shape for value in (fit, train, selection)):
        raise ValueError("fit and label boundaries must cover every decision date")
    if any(np.isnat(value[active]).any() for value in (fit, train, selection)):
        raise ValueError("missing model fitting or selection boundary")
    if np.any(fit[active] > dates[active]):
        raise ValueError("a later model cannot predict an earlier decision")
    if np.any(train[active] >= fit[active]) or np.any(selection[active] >= fit[active]):
        raise ValueError(
            "training and model-selection outcomes must end before fitting"
        )


# Build the selected candidate score without widening the incumbent's coverage.
def candidate_scores(report, evidence: ForecastEvidence, policy: str) -> np.ndarray:
    """Return neural-only or equal-rank-blend scores for the research adapter."""
    if policy not in POLICIES:
        raise ValueError("unknown neural comparison policy")
    incumbent = np.asarray(report.scores, dtype=float)
    neural = np.asarray(evidence.values, dtype=float)
    if neural.shape != incumbent.shape:
        raise ValueError("candidate scores must match the incumbent score grid")
    if policy == POLICY_BLEND:
        common = np.isfinite(incumbent) & np.isfinite(neural)
        scores = baselines.rank_blend(
            np.where(common, incumbent, np.nan),
            np.where(common, neural, np.nan),
        )
    else:
        scores = neural.copy()
    return np.where(np.isfinite(incumbent), scores, np.nan)


# Replace only the ranking values while retaining the actual risk-sizing implementation.
def _allocator_for(evidence: ForecastEvidence, policy: str = POLICY):
    scores = None

    # Let the simulator decide on its current row with its usual trailing price window.
    def allocate(report, panel, config, t):
        nonlocal scores
        if scores is None:
            scores = candidate_scores(report, evidence, policy)
        ranking = SimpleNamespace(
            scores=scores,
            graded=report.graded,
            regime=report.regime,
        )
        return simulate._targets(ranking, panel, config, t)

    return allocate


# Run matched accounts with identical live rules, funding, events and costs.
def compare(
    report,
    evidence: ForecastEvidence,
    *,
    since: date,
    event_exposure: np.ndarray,
    cost_bps: float,
    policy: str = POLICY,
):
    validate(report, evidence, since)
    if policy not in POLICIES:
        raise ValueError("unknown neural comparison policy")
    events = np.asarray(event_exposure, dtype=float)
    if events.shape != (len(report.panel.dates),):
        raise ValueError("one shared event exposure is required for every session")
    if not np.isfinite(events).all() or np.any(~np.isin(events, (0.5, 1.0))):
        raise ValueError("the recorded live FOMC path must use half or full exposure")
    if not np.isfinite(cost_bps) or not 0 <= cost_bps < 1000:
        raise ValueError("a finite nonnegative execution cost is required")
    options = dict(
        since=since,
        rebalance=paper.REBALANCE_EVERY,
        use_exits=False,
        cost_bps=float(cost_bps),
        event_exposure=events,
        event_lifecycle=True,
        **simulate.LIVE_POLICY,
    )
    incumbent = simulate.run(report, **options)
    candidate = simulate.run(
        report, allocator=_allocator_for(evidence, policy), **options
    )
    return {
        "policy": policy,
        "adoption_eligible": False,
        "evidence_basis": evidence.evidence_basis,
        "comparison": (
            "equal cross-sectional rank blend with unchanged live grades and "
            "account rules"
            if policy == POLICY_BLEND
            else "ranking substitution with unchanged live grades and account rules"
        ),
        "model_sha256": evidence.model_sha256,
        "input_sha256": evidence.input_sha256,
        "limitations": [
            "Availability dates and hashes are supplied assertions, not a source audit",
            "Reconstructed grades are not archived live decisions",
            "Only scheduled ranking changes; midcycle entries retain live rules",
            "Fractional NAV1 paper account, not personal holdings or midpoint fills",
        ],
        "incumbent": incumbent,
        "candidate": candidate,
    }
