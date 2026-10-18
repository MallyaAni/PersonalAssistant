# SOURCE ONLY: new upstream identity; no runtime or model admission.
"""UNEXECUTED private capacity input source; public execute always refuses.

This private load prototype is not an admitted capacity entrypoint. It must be
bound to a NEW map transition/finder/generated/phase/native-runtime contract,
all original archive/configuration/economic/calendar/producer admissions and
full before/after byte receipts before any scoped synthetic or genuine call.
It retains a new class identity; original model/source receipts stay distinct.
"""
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from backend.market import direct_daily_arithmetic, forward_arithmetic, holding_risk_bank
from backend.market.capacity_original_archives_v2 import CapacityOriginalArchivesV2
from backend.market.capacity_original_daily_inputs_v1 import daily_prefix
from backend.market.capacity_original_economics_v1 import ECONOMIC_INPUT_PROOF_SHA, economic_paths, reviewed_economics
from backend.market.capacity_original_evidence_v1 import authenticate_file, pinned, require, strict_json
from backend.market.capacity_original_frozen_readers_v1 import CapacityFrozenMarketReaderV1, CapacityFrozenRiskReaderV1
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.live_execution_inputs import DAILY_BASIS, RawExecutionInputs

SCHEMA = 'capacity-original-inputs/2'

OBSERVATION_METADATA_SHA256 = (
    "97a3a9893da942211ccc584ea664b377d4826e1710ee0b36e3b0d0838862601c"
)

OBSERVATION_ARRAYS_SHA256 = (
    "3598ab539d37c48c58bfe823d607377243731aa1db3d650a92cb7f1a9a525d79"
)

ORIGINAL_CONFIG_SHA256 = (
    "1a14980a66a1cb5994f0bb82667dd46fce40ec7eb0705728d93e36b18faf5901"
)

OVERLAY_SHA256 = "5d0640d321ba97ab7d1e37b3e1c680c21af68fc355a905842ace50d808db988c"

DEPENDENCIES = (
    "backend/cli/market_strategy_continue.py",
    "backend/cli/market_actual_policy_timing.py",
    "backend/market/live_execution_inputs.py",
    "backend/market/live_model_history.py",
    "backend/market/forward_arithmetic.py",
    "backend/market/holding_risk_bank.py",
    "backend/market/calendar.py",
    "backend/market/panel.py",
    "backend/market/store.py",
)


# Retain all six original loaded fields under a separate capacity result type.
@dataclass(frozen=True, slots=True)
class CapacityAuditInputsV2:
    panel: object
    raw: RawExecutionInputs
    reader: CapacityFrozenMarketReaderV1
    holding: dict
    overlay: dict
    source_sha256: dict


# Reject arbitrary predictor objects without replacing the original numeric factory or copying arrays.
def require_factory_head(head, model):
    require(head is None or type(head) is direct_daily_arithmetic.NumericHead, "EXACT_NUMERIC_FACTORY_HEAD_REQUIRED")
    require((head is not None) == (model["status"] == "fitted"), "NUMERIC_FACTORY_STATUS_REQUIRED")


# Preserve the original readonly transitions after constructing raw execution inputs.
def readonly(raw):
    for name in raw.__dataclass_fields__:
        value = getattr(raw, name)
        if isinstance(value, np.ndarray):
            value.setflags(write=False)
    if raw.passive is not None:
        for name in ("dates", "session_open", "observation_close", "daily_close"):
            getattr(raw.passive, name).setflags(write=False)
    return raw


# Retain original load statement order with explicit capacity identities and exact factory path.
def _load_capacity_inputs(archives, market, *, observed_at):
    require(type(archives) is CapacityOriginalArchivesV2, "EXACT_CAPACITY_ARCHIVE_CONTEXT_REQUIRED")
    market = Path(market)
    archives.authenticate_sources()
    for name in DEPENDENCIES:
        authenticate_file(archives.source_root / name, archives.sources[name])
    capture = archives.authenticate_inputs(market)
    holding = strict_json(
        pinned(market / "desk/learned-holding/config.json", ORIGINAL_CONFIG_SHA256)
    )
    require(
        archives.completion["holding_config_sha256"] == ORIGINAL_CONFIG_SHA256,
        "ORIGINAL_CONFIG_NOT_SERVING_CONFIG_REQUIRED",
    )
    folder = market / "desk/learned-holding"
    original, _ = holding_risk_bank.load_bank(
        folder / holding["risk_directory"],
        receipt_sha256=holding["risk_receipt_sha256"],
        observed_at=observed_at,
    )
    head, model = forward_arithmetic.load_publication(
        folder / holding["model_directory"],
        receipt_sha256=holding["model_receipt_sha256"],
        observed_at=observed_at,
    )
    require_factory_head(head, model)
    panel, grades, eligible, factors, events, sources = daily_prefix(
        market, original, date.fromisoformat(capture["through"])
    )
    overlay = strict_json(pinned(market / "grade-overlay-proof.json", OVERLAY_SHA256))
    for name, expected in sources.items():
        relative = str(Path(name).relative_to(market))
        require(
            capture["files"].get(relative, overlay["histories"].get(Path(name).stem))
            == expected,
            "UNAUTHENTICATED_DAILY_INPUT",
        )
    meta = strict_json(
        pinned(Path("/observation/close.json"), OBSERVATION_METADATA_SHA256)
    )
    authenticate_file(Path("/observation/close.npz"), OBSERVATION_ARRAYS_SHA256)
    require(
        meta["arrays_sha256"] == OBSERVATION_ARRAYS_SHA256,
        "ORIGINAL_BENCHMARK_ARRAYS_REQUIRED",
    )
    with np.load("/observation/close.npz", allow_pickle=False) as values:
        require(
            np.array_equal(values["dates"], panel.dates)
            and tuple(values["symbols"].tolist()) == panel.tickers,
            "ORIGINAL_BENCHMARK_COORDINATES_REQUIRED",
        )
        history_grades = values["history_grades"]
        require(
            _hash(history_grades) == meta["identity"]["array_sha256"]["history_grades"],
            "ORIGINAL_BENCHMARK_GRADES_REQUIRED",
        )
        for name in ("SPY", "QQQ"):
            column = panel.tickers.index(name)
            grades[:, column] = history_grades[:, column]
    eligible = grades >= 0
    actions, passive, inherited = reviewed_economics(
        panel, factors, events, economic_paths()
    )
    raw = readonly(
        RawExecutionInputs(
            panel.dates,
            panel.tickers,
            grades,
            eligible,
            panel.open * factors,
            panel.high * factors,
            panel.low * factors,
            panel.close * factors,
            None,
            None,
            None,
            None,
            None,
            None,
            factors,
            actions,
            {
                "daily_price_basis": DAILY_BASIS,
                "supplied": {"capture_sha256": archives.completion["capture_sha256"]},
                "grade_sha256": _hash(grades),
                "eligible_sha256": _hash(eligible),
                "daily_source_arrays": {
                    name: _hash(getattr(panel, name))
                    for name in ("dates", "open", "high", "low", "close", "adj_close")
                },
                "reviewed_economic_proof_sha256": ECONOMIC_INPUT_PROOF_SHA,
            },
            passive,
            inherited,
        )
    )
    reader = CapacityFrozenMarketReaderV1(
        CapacityFrozenRiskReaderV1(
            original, panel, grades, eligible, head, model, observed_at
        )
    )
    return CapacityAuditInputsV2(panel, raw, reader, holding, overlay, sources)


# Refuse public execution until a distinct complete source, phase and runtime contract is admitted.
def execute(*args, **kwargs):
    raise RuntimeError("CAPACITY_MODEL_ENTRY_UNADMITTED")
