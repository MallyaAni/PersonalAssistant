"""Load frozen nightly audit inputs without allocating historical execution grids."""

import ast
import inspect
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.cli import market_actual_policy_timing as economics
from backend.cli import market_strategy_continue as continuation
from backend.market import forward_arithmetic, holding_risk_bank
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.live_execution_inputs import (
    DAILY_BASIS,
    PassiveMarks,
    RawExecutionInputs,
    _actions,
    _dates_by_name,
    _inherited_actions,
    review_action_export,
)
from backend.market.live_model_history import (
    FrozenCurrentMarketReader,
    FrozenCurrentRiskReader,
)
from backend.market.live_model_history_receipts import require
from backend.market.live_model_history_stream_audit import (
    authenticate_file,
    pinned,
    strict_json,
)

DAILY_FUNCTION_SHA256 = (
    "40d0d7cf482591ba28e6426ca87d23d3ed1b1cf42e31fd74a24a1287129221d9"
)
ECONOMIC_RECEIPT_SHA256 = (
    "afa4edc554a6a2548e2558077833eb53239494dd685f990f685ac63de8b15a30"
)
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


# Keep loaded model inputs together without implying timing or publication acceptance.
@dataclass(frozen=True, slots=True)
class AuditInputs:
    panel: object
    raw: RawExecutionInputs
    reader: FrozenCurrentMarketReader
    holding: dict
    overlay: dict
    source_sha256: dict


# Execute only the hash-pinned original daily prefix, before its first cube allocation.
def daily_prefix(market, original, through):
    source = inspect.getsource(continuation.inputs)
    require(
        sha256(source.encode()).hexdigest() == DAILY_FUNCTION_SHA256,
        "EXACT_ORIGINAL_DAILY_LOADER_REQUIRED",
    )
    tree = ast.parse(source)
    function = tree.body[0]
    stops = [
        index
        for index, node in enumerate(function.body)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(item, ast.Name) and item.id == "shape" for item in node.targets
        )
    ]
    require(len(stops) == 1, "EXACT_DAILY_GRID_BOUNDARY_REQUIRED")
    function.body = function.body[: stops[0]] + [
        ast.Return(
            ast.Tuple(
                [
                    ast.Name(name, ast.Load())
                    for name in (
                        "panel",
                        "grades",
                        "eligible",
                        "factors",
                        "actions",
                        "sources",
                    )
                ],
                ast.Load(),
            )
        )
    ]
    namespace = dict(vars(continuation))
    exec(
        compile(ast.fix_missing_locations(tree), "<pinned daily prefix>", "exec"),
        namespace,
    )
    return namespace["inputs"](market, original, through)


# Select exact original economic paths from the authenticated study receipt.
def economic_paths(receipt=Path("/economic-receipt.json")):
    command = strict_json(pinned(receipt, ECONOMIC_RECEIPT_SHA256))["commands"]["study"]
    require(
        type(command) is list and all(type(item) is str for item in command),
        "EXACT_ECONOMIC_COMMAND_REQUIRED",
    )
    result = {}
    for name in (
        "actions",
        "action_review",
        "passive_arrays",
        "passive_receipt",
        "economic_input_proof",
    ):
        option = "--" + name.replace("_", "-")
        require(command.count(option) == 1, "UNIQUE_ECONOMIC_INPUT_REQUIRED")
        index = command.index(option) + 1
        require(index < len(command), "ECONOMIC_INPUT_PATH_REQUIRED")
        path = Path(command[index])
        require(
            path.is_absolute() and ".." not in path.parts,
            "ABSOLUTE_ECONOMIC_PATH_REQUIRED",
        )
        result[name] = path
    return SimpleNamespace(**result)


# Align original passive marks without carrying a quote into a missing later row.
def align_passive(panel_dates, passive):
    indices = np.searchsorted(panel_dates, passive.dates)
    require(
        np.all(indices < len(panel_dates))
        and np.array_equal(panel_dates[indices], passive.dates),
        "EXACT_PASSIVE_CALENDAR_REQUIRED",
    )
    shape = (len(panel_dates), len(passive.tickers))
    opening, closing = np.full(shape, np.nan), np.full(shape, np.nan)
    observed = np.full((len(panel_dates), 26, len(passive.tickers)), np.nan)
    opening[indices], closing[indices], observed[indices] = (
        passive.session_open,
        passive.daily_close,
        passive.observation_close,
    )
    return PassiveMarks(
        panel_dates,
        passive.tickers,
        opening,
        observed,
        closing,
        {**dict(passive.provenance), "later_marks": "missing_not_invented"},
    )


# Restore reviewed event order and inherited declarations without opening any cube.
def reviewed_economics(panel, factors, events, paths):
    proof = strict_json(
        pinned(paths.economic_input_proof, economics.ECONOMIC_INPUT_PROOF_SHA)
    )
    require(
        proof["status"] == "VERIFIED_INDEPENDENT_REVIEWED_ORIGINAL_INPUTS",
        "REVIEWED_ECONOMIC_PROOF_REQUIRED",
    )
    action_bytes = pinned(paths.actions, economics.ACTIONS_SHA)
    review_bytes = pinned(paths.action_review, economics.ACTION_REVIEW_SHA)
    original, compiled = (
        strict_json(action_bytes),
        review_action_export(action_bytes, review_bytes),
    )
    require(
        not compiled["unresolved"]
        and dict(compiled["scope"])
        == {"first_session": "2018-02-01", "last_session": "2026-09-30"}
        and compiled["execution_readiness"] == "pending_declaration_receipts",
        "EXACT_REVIEWED_ECONOMIC_SCOPE_REQUIRED",
    )
    authenticate_file(paths.passive_arrays, economics.PASSIVE_ARRAYS_SHA)
    pinned(paths.passive_receipt, economics.PASSIVE_RECEIPT_SHA)
    with np.load(paths.passive_arrays, allow_pickle=False) as archive:
        dates = archive["dates"]
    passive = economics.load_passive_inputs(paths, dates, panel.tickers)
    cutoff = dates[-1]
    selected = panel.dates <= cutoff
    require(
        np.array_equal(panel.dates[selected], dates),
        "EXACT_REVIEWED_DAILY_CALENDAR_REQUIRED",
    )
    old_factors, reviewed = _actions(
        compiled["actions"],
        panel.tickers,
        dates,
        _dates_by_name(
            original["basis_as_of"], panel.tickers, "split-adjustment basis"
        ),
        _dates_by_name(
            original["complete_through"], panel.tickers, "action completeness"
        ),
        "split_adjusted_archive_share_dollars",
        passive.tickers,
    )
    require(
        np.allclose(factors[selected], old_factors, rtol=0, atol=1e-12),
        "REVIEWED_ARCHIVE_FACTORS_DIFFER",
    )
    actions = {
        name: [dict(row) for row in reviewed[name]]
        + [row for row in events[name] if row["date"] > str(cutoff)]
        for name in panel.tickers
    }
    inherited = _inherited_actions(compiled.get("inherited_actions"), passive, dates)
    return actions, align_passive(panel.dates, passive), inherited


# Make every audit-owned array readonly after preserving its original missing cells.
def readonly(raw):
    for name in raw.__dataclass_fields__:
        value = getattr(raw, name)
        if isinstance(value, np.ndarray):
            value.setflags(write=False)
    if raw.passive is not None:
        for name in ("dates", "session_open", "observation_close", "daily_close"):
            getattr(raw.passive, name).setflags(write=False)
    return raw


# Build complete daily/model context while retaining the frozen original configuration.
def load(archives, market, *, observed_at):
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
                "reviewed_economic_proof_sha256": economics.ECONOMIC_INPUT_PROOF_SHA,
            },
            passive,
            inherited,
        )
    )
    reader = FrozenCurrentMarketReader(
        FrozenCurrentRiskReader(
            original, panel, grades, eligible, head, model, observed_at
        )
    )
    return AuditInputs(panel, raw, reader, holding, overlay, sources)
