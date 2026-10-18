"""Unused CURRENT private nightly adapter; never a historical account runner.

Native planning, reconciliation and submission are reused without modification.
Standalone reservations do not advance the packet Store's stage or head. They
must be composed by a later coordinator before any connected-account claim.
"""

import io
import math
import os
import stat
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock, get_ident

import numpy as np

from backend.agents.trading.desk import intraday_orders, paper
from backend.cli import market_daily
from backend.market import (
    calendar,
    forward_arithmetic,
    holding_risk_bank,
    learned_live_holding,
    live_policy_replay,
    live_policy_report,
)
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_forecast as admitted
from backend.market import historical_conditional_market as market
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.historical_packet_store import Store, StorePause
from backend.market.live_model_history import (
    FrozenCurrentGradePolicy,
    FrozenCurrentMarketReader,
    FrozenCurrentRiskReader,
)

CAP = 256 * 1024
LOCK = Lock()
SAVE_STATE = paper.save_state
SUBMIT = native.ReplayBroker._submit
CYCLE = "883c44e82a573a06979a22123ada022cd21c63f99277467977b5a96a69c5b657"
SOURCES = {
    "backend/market/live_model_history.py": (
        "fa8ecdb9c0c32d2f034ece8c7da57fec9f198d8d8427a0273d5b59dc4ca6b37b"
    ),
    "backend/market/live_model_history_audit_inputs.py": (
        "fae5bfc7d7438071094f31f42e884cb48e3709c55f364954e51c28302d3c3e30"
    ),
    "backend/market/live_model_history_stream_audit.py": (
        "f404e15be6e97caf856a4ba6db22eedef51ff5a4e3304dcbed90cf8e0abac2ff"
    ),
    "backend/market/original_history_json.py": (
        "de29c1017f4c9eadd874b2fbe0d85b4c80ced8e7a43fb6bd4f779c3d726cb2eb"
    ),
    "backend/market/live_model_history_nightly_model.py": (
        "ae35feda683debb13e83bbcd9d5c75a35b71b10b1417d571cc7c3fcdd3f3cde9"
    ),
    "backend/market/live_model_history_pending_audit.py": (
        "74e7d9800bf1bdeb51655f09ae2846bfb0dbbcc67afdcad705405a849eb0cf02"
    ),
    "backend/market/live_model_history_nightly_audit.py": (
        "4289bc4f44e0f622681457e81317d00429c735d89801012493605ffd34ed3581"
    ),
    "backend/market/live_model_history_observation_context.py": (
        "cd2fab769ef75ab719b3c4e9162ce6a44a9e980b9f5ecd72283a44f6ddfd205c"
    ),
    "backend/market/live_model_history_receipts.py": (
        "1e9d72e817caa5470842aa50936b3f004f48fbfde77deb0fa5617b72972fea9f"
    ),
    "backend/market/live_policy_report.py": (
        "d16e4fbdf194c11f98c28539487da12dbd0210bc7911213f76990b54d5f5e7e2"
    ),
    "backend/market/live_policy_replay.py": (
        "b6ef95f0c5eaa53bd732f0ee5baa55f21ef875d07c69e5abbbb236aafd0586e9"
    ),
    "backend/market/counterfactual_holding.py": (
        "af8b06a13f9ffeb6f8635cf35852051ed10fb267e3d2d861dd87d9ee984e2fad"
    ),
    "backend/cli/market_strategy_continue.py": (
        "14357ed7b87618ee514dd3cd4e4a71e2c27290875c3df257e692773e524cfaaf"
    ),
    "backend/cli/market_actual_policy_timing.py": (
        "58d481f6fa4b0ec5d997c612c701a8706ee167cc1e4fe19856caf04e02342d7e"
    ),
    "backend/market/live_execution_inputs.py": (
        "4756673840814a02d5d0a341d54cbbec9e3a855b8cd8a163cc5f0a9c31b44a86"
    ),
    "backend/market/calendar.py": (
        "f5ceca3cd12484f66a13f75026c4466970c8810496bf7b7871f5973d749f05f4"
    ),
    "backend/market/data/fomc_decisions.csv": (
        "860329334e6be3e1b8c4e6eb0069ec579e704d7a575634aa6f58bf450b25b5fb"
    ),
    "backend/market/historical_packet_store.py": (
        "be90098bf2c64e7e8da390f2b40db646b50c7d0be659e1a3c9391b8b5595fdbf"
    ),
    "backend/market/historical_broker_checkpoint.py": (
        "703db0680497d2cf7ea78a5902c2d7d7d6cd4777355ac953c999763fe22b9f08"
    ),
    "backend/market/historical_conditional_market.py": (
        "b990e4f6c21dd8e9973257801211b23df4caee067ff2ef2d04023ef467dd9b28"
    ),
    "backend/market/historical_timing_packet.py": (
        "54763a69c3a0f7f7a6c8fa90fc7ff278ade0eec93e9b4872afa9c8a5f055377d"
    ),
    "backend/market/historical_conditional_forecast.py": (
        "68536cfef1d27e5a612cd4ddbd1b5e87f725e1c0f6e06bf5bc20cd051d0ea29c"
    ),
    "docs/research/conditional-holding-calibration-plan-2026-10-05.md": (
        "ac7c7a8aed9edefee13126d0d8b3be3665172691ac961ce1bfffd5b361b7524d"
    ),
    "docs/research/market-conditioned-holding-plan-2026-10-05.md": (
        "92c41c5f8a58eb2c7c851561e874b422180d144d6be69e137b76c8a4dc4c32d4"
    ),
    "docs/research/grade-led-sizing-contract-2026-10-13.md": (
        "51e4f718ed73a29188cb134a342615927a48c12f4647b30307cb996efd1393c6"
    ),
    "docs/research/joint-probability-timing-plan-2026-10-05.md": (
        "e9d39b07603a1379c17cd1a2867f19ea4898f0cfc262841c1ff875a4caf8a942"
    ),
    "docs/research/joint-distribution-allocation-plan-2026-10-04.md": (
        "db48217d2e44e312cca774b6e7c1fa5c378b48f4e2124c3b15c54aeba5980cc1"
    ),
    "docs/research/learned-held-exits-plan-2026-10-03.md": (
        "61512be36be1beae85d5a6fd5a9eaa30b8163815209c9af1c4dc527157a6c0f9"
    ),
    "docs/research/holding-volatility-correction-plan-2026-10-04.md": (
        "8f80a0ca6cb8c8494ec5b02219e817be7a8e576a3c28f283adba92f8dc401db6"
    ),
    "docs/research/direct-feature-support-plan-2026-10-03.md": (
        "75a58441e82714606460280c871cf33d30751273c321392aeacca96af322a57d"
    ),
    "docs/research/direct-error-band-plan-2026-10-03.md": (
        "05ab4ca01cff49bd7c4756705d54bc8801eaf2113423288a4000202609d45f73"
    ),
    "docs/research/forward-arithmetic-publication-2026-10-04.md": (
        "b8bb8bae2f5d8f69ba14038274fed4828de57a82f9e98bab41d324cf81523dfc"
    ),
}


# Reauthenticate the exact native and existing helper source used by this adapter.
def sources():
    root = Path(__file__).resolve().parents[2]
    for name, expected in SOURCES.items():
        admitted.authenticate(root / name, expected)
    return {
        **SOURCES,
        str(Path(__file__).relative_to(root)): sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }


# Detach immutable action metadata without changing keys, numbers or missing values.
def action_primitives(value):
    if isinstance(value, Mapping):
        admitted.require(
            all(type(key) in (str, np.str_) for key in value),
            "Action metadata requires string keys",
        )
        return {key: action_primitives(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [action_primitives(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    admitted.require(
        type(value) is float and math.isfinite(value),
        "Action metadata requires finite JSON primitives",
    )
    return value


# Preserve the existing canonical hash for equivalent plain or frozen action metadata.
def action_digest(value):
    return packet._digest(action_primitives(value))


# Admit only the untouched zero-account prior close and record earlier entitlements.
def pre_inception_actions(
    client, state, *, prior_kind, prior, previous, birth, birth_record, session, due
):
    admitted.require(
        prior_kind == "NIGHTLY"
        and prior["phase"] == "BIRTH"
        and previous == birth
        and session == prior["session"] == "2019-02-28"
        and birth_record["first"] == "2019-03-01"
        and session < birth_record["first"],
        "Exact original prior-close birth boundary required",
    )
    mappings = ("_held", "_average", "_orders", "_actions", "_marks", "_mark_times")
    sequences = ("_attempts", "_fills", "_dividends", *codec.CLAIMS)
    admitted.require(
        type(client) is native.ReplayBroker
        and set(client.__dict__) == codec.FIELDS
        and all(
            type(getattr(client, name)) is dict and not getattr(client, name)
            for name in mappings
        )
        and all(
            type(getattr(client, name)) is list and not getattr(client, name)
            for name in sequences
        )
        and type(client._cash) is float
        and client._cash == 100000.0
        and type(client.cost_bps) is float
        and client.cost_bps == 10.0
        and type(client._last_equity) is float
        and client._last_equity == 100000.0
        and client._now is client._observed_at is None
        and client._market_open is False
        and client._batch_open is False
        and type(state) is paper.PaperState
        and admitted.encoded(asdict(state))
        == admitted.encoded(asdict(paper.PaperState())),
        "Untouched native zero-account birth components required",
    )
    return {
        "status": "PRE_INCEPTION_NOT_APPLIED",
        "session": session,
        "first_account_session": birth_record["first"],
        "actions": [
            {
                "symbol": symbol,
                "declaration": action_primitives(row),
                "effective_at": effective.isoformat(),
            }
            for symbol, row, effective in due
        ],
    }


# Bind consumed arrays and passive identities independently of the selected model row.
def arrays(panel, raw, reader):
    values = {
        "panel." + name: getattr(panel, name)
        for name in ("dates", "open", "high", "low", "close", "adj_close", "volume")
    }
    values.update(
        {
            "raw." + name: getattr(raw, name)
            for name in (
                "grades",
                "eligible",
                "split_factors",
                "daily_open",
                "daily_high",
                "daily_low",
                "daily_close",
            )
        }
    )
    parent = reader._parent
    values.update(
        {
            "model." + name: getattr(parent, name)
            for name in (
                "_frozen_dates",
                "_features",
                "_forecasts",
                "_support",
                "_prices",
                "_history_prices",
                "_history_grades",
            )
        }
    )
    values.update({"bank." + name: value for name, value in parent._bank.items()})
    values["market.context"] = reader._market
    if raw.passive is not None:
        values.update(
            {
                "passive." + name: getattr(raw.passive, name)
                for name in (
                    "dates",
                    "session_open",
                    "observation_close",
                    "daily_close",
                )
            }
        )
    return {
        **{name: _hash(value) for name, value in values.items()},
        "passive.metadata": packet._digest(
            None
            if raw.passive is None
            else live_policy_replay.plain(
                {"tickers": raw.passive.tickers, "provenance": raw.passive.provenance}
            )
        ),
    }


# Preserve full archive admission while binding the native report to its causal prefix.
def prefix_report(context, index, admission):
    panel, raw, reader = context.panel, context.raw, context.reader
    report = live_policy_report.build(panel, raw, raw.grades, raw.eligible, index)
    names = ("dates", "open", "high", "low", "close", "adj_close")
    full = dict(raw.provenance["daily_source_arrays"])
    admitted.require(
        report.provenance["raw_source_arrays"]
        == full
        == {name: admission["array_sha256"]["panel." + name] for name in names},
        "Authenticated full report source identities differ",
    )
    prefix = {name: _hash(getattr(panel, name)[: index + 1]) for name in names}
    model_prefix = reader.current.receipt["identity"]["prefix_sha256"]
    admitted.require(
        prefix["dates"] == model_prefix["dates"]
        and prefix["adj_close"] == model_prefix["prices"],
        "Report source prefix differs from selected frozen model",
    )
    report = replace(
        report,
        provenance={
            **report.provenance,
            "full_source_arrays": full,
            "raw_source_arrays": prefix,
            "source_prefix_identity": {
                "first_session": str(panel.dates[0]),
                "session": str(panel.dates[index]),
                "rows": index + 1,
                "cohort": list(panel.tickers),
                "cohort_sha256": packet._digest(list(panel.tickers)),
                "dates_sha256": prefix["dates"],
            },
        },
    )
    reader.validate_report(report)
    return report


# Keep actual model restoration separate from hypothetical historical close decisions.
@dataclass(frozen=True, slots=True, init=False)
class HoldingContext:
    approval: admitted.AdmittedTiming
    panel: object
    raw: object
    reader: FrozenCurrentMarketReader
    provenance: bytes

    # Refuse changed files, source, economic declarations, arrays or model month.
    def validate(self):
        self.approval.validate()
        value = admitted.decoded(self.provenance)
        admitted.require(
            sources() == value["source_sha256"], "Nightly helper source changed"
        )
        for path, expected in value["input_sha256"].items():
            admitted.authenticate(path, expected)
        admitted.require(
            arrays(self.panel, self.raw, self.reader) == value["array_sha256"],
            "Nightly input/model arrays changed",
        )
        admitted.require(
            tuple(self.panel.tickers)
            == tuple(self.raw.tickers)
            == tuple(self.reader.symbols)
            == tuple(value["symbols"]),
            "Nightly cohort/order changed",
        )
        admitted.require(
            action_digest(self.raw.actions) == value["actions_sha256"]
            and action_digest(self.raw.inherited_actions)
            == value["inherited_actions_sha256"],
            "Economic action declarations changed",
        )
        admitted.require(
            np.datetime64(datetime.now(UTC).date(), "M")
            == np.datetime64(value["model_fit_date"], "M"),
            "Frozen current holding model month changed",
        )
        return value

    # Select the native historical report and policy without replacing its allocator.
    def select(self, session):
        value = self.validate()
        day = date.fromisoformat(session)
        admitted.require(
            day.isoformat() == session
            and date(2019, 2, 28) <= day <= date(2026, 10, 12),
            "Explicit account close outside contract",
        )
        hits = np.flatnonzero(self.panel.dates == np.datetime64(session))
        admitted.require(len(hits) == 1, "Exact reviewed historical session required")
        index = int(hits[0])
        self.reader.select(index)
        report = prefix_report(self, index, value)
        policy = FrozenCurrentGradePolicy(self.reader, 10)
        admitted.require(
            tuple(self.panel.tickers) == tuple(value["symbols"]),
            "Nightly cohort changed",
        )
        return report, policy, index


# Load the unchanged full current bank and daily context; never call installed prepare.
def load_context(approval, observation_root, economic_receipt):
    admitted.require(
        type(approval) is admitted.AdmittedTiming,
        "Current authenticated approval required",
    )
    started, tick = datetime.now(UTC), time.monotonic_ns()
    source = sources()
    holding = approval.validate()
    model_root = learned_live_holding._folder(approval.root, holding["model_directory"])
    risk_root = learned_live_holding._folder(approval.root, holding["risk_directory"])
    original, bank = holding_risk_bank.load_bank(
        risk_root, receipt_sha256=holding["risk_receipt_sha256"], observed_at=started
    )
    head, model = forward_arithmetic.load_publication(
        model_root, receipt_sha256=holding["model_receipt_sha256"], observed_at=started
    )
    learned_live_holding._timing(approval.root, holding, original, started)
    from backend.market import live_model_history_audit_inputs as inputs
    from backend.market.live_execution_inputs import DAILY_BASIS, RawExecutionInputs

    root = approval.artifact_root
    capture = admitted.decoded(
        admitted.metadata(root / "capture.json", admitted.CAPTURE).raw
    )
    overlay = admitted.decoded(
        admitted.metadata(root / "grade-overlay-proof.json", admitted.OVERLAY).raw
    )
    files = {
        str(root / "capture.json"): admitted.CAPTURE,
        str(root / "grade-overlay-proof.json"): admitted.OVERLAY,
    }
    files.update(
        {
            str(risk_root / "bank.json"): holding["risk_receipt_sha256"],
            str(risk_root / "bank.npz"): bank["arrays_sha256"],
            str(model_root / "publication.json"): holding["model_receipt_sha256"],
            str(model_root / "model.npz"): model["model_file"]["sha256"],
        }
    )
    files.update(
        {
            str(approval.root / "desk/learned-timing" / name): expected
            for name, expected in admitted.TIMING_FILES.items()
        }
    )
    files.update(
        {
            str(root / name): expected
            for name, expected in capture["files"].items()
            if name.startswith(("bars/", "actions/"))
        }
    )
    files.update(
        {
            str(root / "history" / (name + ".json")): expected
            for name, expected in overlay["histories"].items()
        }
    )
    observation = Path(observation_root)
    files.update(
        {
            str(observation / "close.json"): admitted.CLOSE,
            str(observation / "close.npz"): admitted.CLOSE_ARRAYS,
        }
    )
    for path, expected in files.items():
        admitted.authenticate(path, expected)
    panel, grades, eligible, factors, events, daily_sources = inputs.daily_prefix(
        root, original, date.fromisoformat(capture["through"])
    )
    meta = admitted.decoded(
        admitted.metadata(observation / "close.json", admitted.CLOSE).raw
    )
    with np.load(observation / "close.npz", allow_pickle=False) as archive:
        dates, symbols, benchmark = (
            archive["dates"],
            tuple(archive["symbols"].tolist()),
            archive["history_grades"],
        )
    admitted.require(
        np.array_equal(dates, panel.dates)
        and symbols == panel.tickers == tuple(capture["symbols"])
        and len(symbols) == 96
        and _hash(benchmark)
        == meta["identity"]["array_sha256"]["history_grades"]
        == overlay["original_grade_array_sha256"],
        "Authenticated full96 benchmark/calendar context required",
    )
    for name in ("SPY", "QQQ"):
        column = panel.tickers.index(name)
        grades[:, column] = benchmark[:, column]
    for path, expected in daily_sources.items():
        admitted.require(
            files.get(path) == expected, "Daily source not in authenticated capture"
        )
    paths = inputs.economic_paths(Path(economic_receipt))
    files[str(Path(economic_receipt))] = inputs.ECONOMIC_RECEIPT_SHA256
    for name, path in vars(paths).items():
        expected = {
            "actions": inputs.economics.ACTIONS_SHA,
            "action_review": inputs.economics.ACTION_REVIEW_SHA,
            "passive_arrays": inputs.economics.PASSIVE_ARRAYS_SHA,
            "passive_receipt": inputs.economics.PASSIVE_RECEIPT_SHA,
            "economic_input_proof": inputs.economics.ECONOMIC_INPUT_PROOF_SHA,
        }[name]
        files[str(path)] = expected
        admitted.authenticate(path, expected)
    actions, passive, inherited = inputs.reviewed_economics(
        panel, factors, events, paths
    )
    eligible = grades >= 0
    raw = inputs.readonly(
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
                "supplied": {"capture_sha256": admitted.CAPTURE},
                "grade_sha256": _hash(grades),
                "eligible_sha256": _hash(eligible),
                "daily_source_arrays": {
                    name: _hash(getattr(panel, name))
                    for name in ("dates", "open", "high", "low", "close", "adj_close")
                },
            },
            passive,
            inherited,
        )
    )
    reader = FrozenCurrentMarketReader(
        FrozenCurrentRiskReader(original, panel, grades, eligible, head, model, started)
    )
    finished = datetime.now(UTC)
    provenance = {
        "schema": "conditional-current-holding-context/1",
        "source": admitted.CURRENT_SOURCE,
        "config_sha256": admitted.CURRENT_CONFIG,
        "release_sha256": admitted.CURRENT_RELEASE,
        "source_sha256": source,
        "input_sha256": files,
        "symbols": list(panel.tickers),
        "array_sha256": arrays(panel, raw, reader),
        "actions_sha256": action_digest(actions),
        "inherited_actions_sha256": action_digest(inherited),
        "model_fit_date": model["training"]["fit_date"],
        "model_receipt_sha256": holding["model_receipt_sha256"],
        "risk_receipt_sha256": holding["risk_receipt_sha256"],
        "actual_model_publication": model["identity"],
        "risk_identity": bank["identity"],
        "actual_compute_started_at": started.isoformat(),
        "actual_compute_finished_at": finished.isoformat(),
        "actual_elapsed_ns": time.monotonic_ns() - tick,
        "availability_is_assumed": True,
        "historical_actual_inference": None,
        "new_base_models_fitted": 0,
        "native_current_calibration": "UNCHANGED_FULL_BANK_NO_HISTORICAL_TRUNCATION",
        "publication_barrier": "CLOSED",
    }
    result = object.__new__(HoldingContext)
    for name, value in {
        "approval": approval,
        "panel": panel,
        "raw": raw,
        "reader": reader,
        "provenance": admitted.encoded(provenance),
    }.items():
        object.__setattr__(result, name, value)
    result.validate()
    return result


# Read bounded private physical bytes without normalizing the native paper state.
def physical(path):
    path = Path(path)
    before = admitted.identity(path)
    admitted.require(before[2] <= CAP, "Physical paper/marker256KiB cap; PAUSED")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        admitted.require(
            stat.S_ISREG(opened.st_mode) and opened.st_size <= CAP,
            "Bounded regular physical file required",
        )
        admitted.require(
            physical_identity(opened) == before, "Physical file replaced before reading"
        )
        raw = stream.read(CAP + 1)
        after = os.fstat(stream.fileno())
    admitted.require(
        len(raw) <= CAP
        and physical_identity(opened) == physical_identity(after)
        and admitted.identity(path) == before,
        "Physical bytes changed; PAUSED",
    )
    return raw


# Exclude access time while retaining every file-content and replacement identity.
def physical_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


# Distinguish repeatable frozen model/input identity from actual restoration clocks.
def context_identity(value):
    return packet._digest(
        {
            key: item
            for key, item in value.items()
            if key
            not in {
                "actual_compute_started_at",
                "actual_compute_finished_at",
                "actual_elapsed_ns",
            }
        }
    )


# Persist exclusive private metadata and synchronize it before allowing effects.
def write_once(path, raw):
    admitted.require(
        type(raw) is bytes and len(raw) <= CAP, "Private bounded bytes required"
    )
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(Path(path).parent)


# Make new reservation-directory links durable before any native effect can occur.
def sync_directory(path):
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


# Keep raw components in the existing CAS without altering its packet stages.
def put(store, raw, cap=CAP):
    return store.put_stream(
        io.BytesIO(raw), limit=cap, expected_sha256=sha256(raw).hexdigest()
    )[0]


# Retain broker and paper, optionally using a separately tagged opaque raw component.
def components(store, client, root, pins, *, raw_checkpoint=None):
    broker = codec.encode(client, **pins)
    if raw_checkpoint is not None:
        from backend.market import historical_paper_component

        admitted.require(
            store.identity == pins["identity_sha256"],
            "Raw paper Store identity differs",
        )
        reference = historical_paper_component.capture(
            raw_checkpoint, paper.state_path(root), expected_identity=store.identity
        )
        return {"broker": put(store, broker, codec.CAPS["bytes"]), "paper": reference}
    raw = physical(paper.state_path(root))
    paper_ref = put(store, raw)
    try:
        value = admitted.decoded(raw)
    except ValueError as error:
        raise StorePause(
            "Native physical paper nonfinite/ambiguous; exact bytes retained:"
            + paper_ref
        ) from error
    admitted.require(
        set(value) == {field.name for field in fields(paper.PaperState)},
        "Exact native physical paper fields required",
    )
    return {"broker": put(store, broker, codec.CAPS["bytes"]), "paper": paper_ref}


# Observe native writes, model decisions and raw submissions without rewriting them.
class NativeCapture:
    # Bind one policy/broker/root, with an optional separately receipted raw-only sink.
    def __init__(self, store, root, client, policy, *, raw_checkpoint=None):
        admitted.require(
            type(client) is native.ReplayBroker
            and type(policy) is FrozenCurrentGradePolicy,
            "Exact native lifecycle capture required",
        )
        if raw_checkpoint is not None:
            from backend.market.historical_physical_checkpoint import PhysicalCheckpoint

            admitted.require(
                type(raw_checkpoint) is PhysicalCheckpoint
                and raw_checkpoint.header["identity_sha256"] == store.identity,
                "Exact same-account raw checkpoint required",
            )
        self.raw_checkpoint, self.raw_writes = raw_checkpoint, []
        self.store, self.root, self.client, self.policy = (
            store,
            Path(root),
            client,
            policy,
        )
        self.owner, self.writes, self.submissions, self.decisions = (
            get_ident(),
            [],
            [],
            [],
        )
        self.recording_failures = []

    # Encode after native persistence; a recording failure leaves uncertainty.
    def finish(self):
        references = []
        for decision in self.decisions:
            try:
                references.append(put(self.store, admitted.encoded(decision)))
            except (ValueError, TypeError, OSError) as error:
                self.recording_failures.append("decision evidence: " + str(error))
        if self.recording_failures:
            raise StorePause(
                "Native recording failure; physical writes retained; never replay: "
                + "; ".join(self.recording_failures)
            )
        return references

    # Refuse concurrency or replaced hooks inside the synchronous observer scope.
    def owned(self):
        admitted.require(
            LOCK.locked()
            and get_ident() == self.owner
            and paper.save_state is self.save
            and native.ReplayBroker._submit is self.submit
            and self.policy.__dict__.get("decide") is self.decide,
            "Changed/concurrent native observation scope",
        )

    # Install passthrough observers only in this unused private process.
    def __enter__(self):
        admitted.require(
            LOCK.locked()
            and paper.save_state is SAVE_STATE
            and native.ReplayBroker._submit is SUBMIT
            and "decide" not in self.policy.__dict__,
            "Original native observer functions required",
        )
        original_decide = self.policy.decide

        # Capture each persisted state; raw-only mode cannot continue into submission.
        def save(root, state):
            self.owned()
            admitted.require(
                Path(root) == self.root, "Unexpected paper writer in observer"
            )
            result = SAVE_STATE(root, state)
            if self.raw_checkpoint is None:
                raw = physical(result)
                self.writes.append(put(self.store, raw))
            else:
                reference = self.raw_checkpoint.capture(result)
                completion = self.raw_checkpoint.completed(reference)
                self.raw_writes.append(
                    {
                        "schema": "native-observer-raw-write/1",
                        "checkpoint": reference,
                        "raw_sha256": completion["root"]["raw_sha256"],
                        "raw_bytes": completion["root"]["raw_bytes"],
                        "identity_sha256": completion["root"]["identity_sha256"],
                        "local_capture_committed": True,
                        "native_operation_committed": False,
                        "durable_simulator_adoption": False,
                    }
                )
            return result

        # Persist original request/outcome evidence before the caller can overwrite it.
        def submit(client, *args, **kwargs):
            self.owned()
            admitted.require(
                self.raw_checkpoint is None,
                "Raw write observer has no submission receipt; PAUSED before submit",
            )
            admitted.require(
                client is self.client, "Unexpected native broker in observer"
            )
            offset = len(client.attempt_history)
            response, problem = None, None
            try:
                response = SUBMIT(client, *args, **kwargs)
                return response
            except AlpacaTradingError as error:
                problem = str(error)
                raise
            finally:
                record = {
                    "args": list(args),
                    "kwargs": kwargs,
                    "attempts": list(client.attempt_history[offset:]),
                    "raw_response": response,
                    "native_error": problem,
                    "pre_submission_paper": self.writes[-1] if self.writes else None,
                    "actual_captured_at": datetime.now(UTC).isoformat(),
                }
                if record["pre_submission_paper"] is None:
                    self.recording_failures.append(
                        "raw submission lacks original pre-submission paper write"
                    )
                try:
                    self.submissions.append(put(self.store, admitted.encoded(record)))
                except (ValueError, TypeError, OSError) as error:
                    self.recording_failures.append(
                        "raw submission evidence: " + str(error)
                    )

        # Measure actual native policy invocation while retaining both target layers.
        def decide(*args, **kwargs):
            self.owned()
            targets, receipt = original_decide(*args, **kwargs)
            self.decisions.append(deepcopy({"targets": targets, "receipt": receipt}))
            return targets, receipt

        self.save, self.submit, self.decide = save, submit, decide
        paper.save_state, native.ReplayBroker._submit = save, submit
        self.policy.decide = decide
        return self

    # Restore exact bindings even when a native refusal or recording failure interrupts.
    def __exit__(self, *error):
        changed = (
            paper.save_state is not self.save
            or native.ReplayBroker._submit is not self.submit
            or self.policy.__dict__.get("decide") is not self.decide
        )
        paper.save_state, native.ReplayBroker._submit = SAVE_STATE, SUBMIT
        self.policy.__dict__.pop("decide", None)
        admitted.require(not changed, "Native observer binding changed")


# Bind one current private account to fixed inputs without admitting caller clocks.
class Nightly:
    # Require the Store's lifetime writer lock and an explicit exclusive private root.
    def __init__(self, store, root, *, pins, expected_head, create=False):
        admitted.require(type(store) is Store, "Exact private Store required")
        codec._identity(pins["identity"], pins["identity_sha256"])
        admitted.require(
            pins["identity"]["source_revision"] == admitted.CURRENT_SOURCE
            and store.identity == pins["identity_sha256"],
            "Exact CURRENT account identity required",
        )
        packet.nanos(datetime.now(UTC).isoformat())
        admitted.require(
            expected_head is None
            or type(expected_head) is str
            and len(expected_head) == 64
            and all(c in "0123456789abcdef" for c in expected_head),
            "External original pre-head required",
        )
        self.store, self.root = store, Path(root)
        self.pin_bytes, self.expected_head = admitted.encoded(pins), expected_head
        admitted.require(
            self.root.parent.resolve() == store.root.resolve()
            and not self.root.is_symlink(),
            "Direct private Store descendant required",
        )
        if create:
            self.root.mkdir(mode=0o700)
            (self.root / "operations").mkdir(mode=0o700)
            sync_directory(self.root)
            sync_directory(store.root)
        admitted.require(
            self.root.is_dir()
            and stat.S_IMODE(self.root.stat().st_mode) == 0o700
            and (self.root / "operations").is_dir()
            and stat.S_IMODE((self.root / "operations").stat().st_mode) == 0o700
            and not (self.root / "operations").is_symlink(),
            "Private original adapter root required",
        )

    # Detach every identity dictionary before native checkpoint validation.
    def pins(self):
        return admitted.decoded(self.pin_bytes)

    # Name standalone operations without pretending they are packet-cycle stages.
    def operation(self, phase, session, pre_head=...):
        admitted.require(
            phase in ("BIRTH", "NIGHTLY_CLOSE"), "Explicit nightly phase required"
        )
        head = self.expected_head if pre_head is ... else pre_head
        return (
            self.root
            / "operations"
            / packet._digest(
                {
                    "identity": self.store.identity,
                    "pre_head": head,
                    "phase": phase,
                    "session": session,
                }
            )
        )

    # Authenticate a result against its original exclusive physical reservation.
    def read_original(self, reference):
        record = admitted.decoded(self.store.read_blob(reference, limit=CAP))
        admitted.require(
            record["schema"] == "standalone-current-nightly/1"
            and type(record["components"]["paper"]) is str
            and record["identity"] == self.store.identity
            and record["packet_pipeline_integrated"] is False
            and record["publication_barrier"] == "CLOSED",
            "Original standalone nightly result required",
        )
        declaration = record["operation"]
        directory = self.operation(
            declaration["phase"], declaration["session"], declaration["pre_head"]
        )
        reservation = physical(directory / "reservation.json")
        original = admitted.decoded(reservation)
        result = admitted.decoded(physical(directory / "result.json"))
        admitted.require(
            result == {"receipt": reference}
            and original == declaration
            and declaration["identity"] == self.store.identity
            and declaration["source_sha256"] == sources()
            and sha256(reservation).hexdigest() == record["reservation_sha256"]
            and record["phase"] == declaration["phase"]
            and record["session"] == declaration["session"]
            and record["context"] == declaration["context_sha256"]
            and record.get("birth") == declaration["birth"],
            "Original nightly reservation/result lineage differs",
        )
        return record

    # Require the exclusive zero-account birth rather than a caller-created CAS claim.
    def read_birth(self, reference):
        record = self.read_original(reference)
        admitted.require(
            record["phase"] == "BIRTH"
            and record["session"] == "2019-02-28"
            and record["initial_cash"] == 100000
            and record["initial_holdings"] == {}
            and record["cost_bps"] == 10
            and record["raw_initial_submissions"] == []
            and record["native_policy_invoked"] is False,
            "Original corrected zero-account birth required",
        )
        return record

    # Admit only an original nightly or the externally pinned final current Cycle head.
    def predecessor(self, reference):
        raw = admitted.decoded(self.store.read_blob(reference, limit=CAP))
        if raw.get("schema") == "standalone-current-nightly/1":
            return self.read_original(reference), "NIGHTLY"
        from backend.market import historical_conditional_cycle as cycle

        admitted.authenticate(cycle.__file__, CYCLE)
        admitted.require(
            self.store.snapshot()["head"] == self.expected_head,
            "Original final Cycle head required",
        )
        entry = cycle._head_entry(self.store, self.expected_head)
        admitted.require(
            entry["stage"] == "OUTCOME_COMMITTED"
            and entry["receipt_sha256"] == reference,
            "Exact committed final Cycle receipt required",
        )
        record = cycle._read_receipt(self.store, reference, self.pins())
        admitted.require(
            record.get("paper_journal_reconciliation")
            == "CURRENT_NATIVE_RECONCILIATION_FINAL_COMPONENTS"
            and record["detail"]["stage"] == "OUTCOME_COMMITTED",
            "Current native reconciled outcome required",
        )
        cycle._final_settlement(self.store, record, self.pins())
        return record, "CYCLE"

    # Recover exact committed references without restoring models or invoking a broker.
    def recover(self, phase, session, *, context_sha256, birth):
        directory = self.operation(phase, session)
        reservation = admitted.decoded(physical(directory / "reservation.json"))
        expected = {
            "identity": self.store.identity,
            "pre_head": self.expected_head,
            "phase": phase,
            "session": session,
            "source_sha256": sources(),
            "context_sha256": context_sha256,
            "birth": birth,
        }
        admitted.require(
            all(reservation.get(k) == v for k, v in expected.items()),
            "Conflicting original nightly reservation",
        )
        try:
            result = admitted.decoded(physical(directory / "result.json"))
        except FileNotFoundError as error:
            raise StorePause(
                "Interrupted nightly operation; never re-execute"
            ) from error
        raw = self.store.read_blob(result["receipt"], limit=CAP)
        admitted.require(
            sha256(raw).hexdigest() == result["receipt"], "Original result bytes differ"
        )
        self.read_original(result["receipt"])
        return result["receipt"]

    # Reserve a single synchronous native lifecycle before touching paper or broker.
    def reserve(self, phase, session, context_sha256, birth, before):
        admitted.require(
            self.store.snapshot()["head"] == self.expected_head,
            "Stale nightly pre-head",
        )
        directory = self.operation(phase, session)
        directory.mkdir(mode=0o700)
        sync_directory(directory.parent)
        value = {
            "identity": self.store.identity,
            "pre_head": self.expected_head,
            "phase": phase,
            "session": session,
            "source_sha256": sources(),
            "context_sha256": context_sha256,
            "birth": birth,
            "before": before,
            "actual_reserved_at": datetime.now(UTC).isoformat(),
        }
        raw = admitted.encoded(value)
        write_once(directory / "reservation.json", raw)
        return directory, sha256(raw).hexdigest()

    # Commit only legacy components until raw Nightly continuation is admitted.
    def complete(self, directory, reservation, value):
        admitted.require(
            type(value["components"]["paper"]) is str,
            "Raw Nightly component continuation is not admitted",
        )
        operation = admitted.decoded(physical(directory / "reservation.json"))
        admitted.require(
            sha256(admitted.encoded(operation)).hexdigest() == reservation,
            "Original reservation bytes differ",
        )
        receipt = put(
            self.store,
            admitted.encoded(
                {
                    **value,
                    "schema": "standalone-current-nightly/1",
                    "identity": self.store.identity,
                    "reservation_sha256": reservation,
                    "operation": operation,
                    "store_head": self.expected_head,
                    "packet_pipeline_integrated": False,
                    "publication_barrier": "CLOSED",
                }
            ),
        )
        write_once(directory / "result.json", admitted.encoded({"receipt": receipt}))
        return receipt

    # Birth exactly100000cash/zero shares and preserve its native empty state first.
    def initialize(self, context):
        admitted.require(
            type(context) is HoldingContext, "Authenticated holding context required"
        )
        context_hash = sha256(context.provenance).hexdigest()
        directory = self.operation("BIRTH", "2019-02-28")
        if directory.exists():
            return None, self.recover(
                "BIRTH", "2019-02-28", context_sha256=context_hash, birth=None
            )
        admitted.require(
            LOCK.acquire(blocking=False), "Concurrent nightly lifecycle refused"
        )
        try:
            value = context.validate()
            admitted.require(
                paper.save_state is SAVE_STATE
                and native.ReplayBroker._submit is SUBMIT,
                "Original native birth bindings required",
            )
            directory, reservation = self.reserve(
                "BIRTH", "2019-02-28", context_hash, None, None
            )
            client = native.ReplayBroker(100000, 10)
            paper.save_state(self.root, paper.PaperState())
            refs = components(self.store, client, self.root, self.pins())
            receipt = self.complete(
                directory,
                reservation,
                {
                    "phase": "BIRTH",
                    "session": "2019-02-28",
                    "first": "2019-03-01",
                    "through": "2026-10-12",
                    "initial_cash": 100000,
                    "initial_holdings": {},
                    "cost_bps": 10,
                    "cohort": value["symbols"],
                    "context": put(self.store, context.provenance),
                    "context_identity": context_identity(value),
                    "components": refs,
                    "raw_initial_submissions": [],
                    "native_policy_invoked": False,
                },
            )
            return client, receipt
        finally:
            LOCK.release()

    # Run the unchanged native close once and retain its literal original receipts.
    def close(self, context, client, session, *, birth, previous):
        admitted.require(
            type(context) is HoldingContext and type(client) is native.ReplayBroker,
            "Exact private context/broker required",
        )
        context_hash = sha256(context.provenance).hexdigest()
        if self.operation("NIGHTLY_CLOSE", session).exists():
            return self.recover(
                "NIGHTLY_CLOSE", session, context_sha256=context_hash, birth=birth
            )
        admitted.require(
            LOCK.acquire(blocking=False), "Concurrent nightly lifecycle refused"
        )
        try:
            context_value = context.validate()
            birth_record = self.read_birth(birth)
            prior, prior_kind = self.predecessor(previous)
            admitted.require(
                birth_record["context_identity"] == context_identity(context_value),
                "Original birth model/input context differs",
            )
            if prior_kind == "NIGHTLY":
                admitted.require(
                    previous == birth or prior["birth"] == birth,
                    "Different original account birth",
                )
            current = components(self.store, client, self.root, self.pins())
            admitted.require(
                current == {name: prior["components"][name] for name in current},
                "Original pre-close components differ",
            )
            report, policy, index = context.select(session)
            at = live_policy_replay.instant(
                context.panel.dates[index],
                calendar.session_close(date.fromisoformat(session)),
            ) + timedelta(minutes=1)
            if prior_kind == "CYCLE":
                admitted.require(
                    session == prior["session"],
                    "Final current-session Cycle outcome required before its close",
                )
            elif prior["phase"] == "BIRTH":
                admitted.require(
                    session == "2019-02-28",
                    "Original prior-close initialization required",
                )
            else:
                admitted.require(
                    date.fromisoformat(session)
                    == intraday_orders.next_session(
                        date.fromisoformat(prior["session"])
                    ),
                    "Sequential original nightly sessions required",
                )
            expected_actions = live_policy_replay.due_actions(context.raw, index, at)
            pre_inception = None
            if prior_kind == "NIGHTLY" and prior["phase"] == "BIRTH":
                pre_inception = pre_inception_actions(
                    client,
                    paper.load_state(self.root),
                    prior_kind=prior_kind,
                    prior=prior,
                    previous=previous,
                    birth=birth,
                    birth_record=birth_record,
                    session=session,
                    due=expected_actions,
                )
            else:
                # Normal sessions still need authenticated earlier event phases.
                admitted.require(
                    not expected_actions,
                    "Economic coordinator evidence required; "
                    "no late action application",
                )
            directory, reservation = self.reserve(
                "NIGHTLY_CLOSE", session, context_hash, birth, current
            )
            began, tick = datetime.now(UTC), time.monotonic_ns()
            client.observe(
                at,
                live_policy_replay.account_marks(
                    context.raw, index, at, context.raw.daily_close[index]
                ),
                False,
            )
            before = deepcopy(client.__dict__)
            old_state = asdict(paper.load_state(self.root))
            old_attempts, old_orders = len(client.attempt_history), set(client._orders)
            output = io.StringIO()
            import contextlib

            with NativeCapture(self.store, self.root, client, policy) as capture:
                try:
                    with contextlib.redirect_stdout(output):
                        entry = market_daily.paper_trade(
                            report,
                            self.root,
                            session,
                            True,
                            client_factory=lambda: client,
                            decision_at=at,
                            holding_policy=policy,
                        )
                    status, reason = "NATIVE_NIGHTLY_RETURNED", None
                except AlpacaTradingError as error:
                    entry, status, reason = (
                        None,
                        "NIGHTLY_BROKER_UNAVAILABLE",
                        str(error),
                    )
                    admitted.require(
                        asdict(paper.load_state(self.root)) == old_state
                        and client.attempt_history[old_attempts:] == ()
                        and not capture.decisions
                        and not capture.writes,
                        "Unavailable close changed state, invoked policy or submitted",
                    )
            decisions = capture.finish()
            attempts = list(client.attempt_history[old_attempts:])
            accepted = [
                deepcopy(client._orders[name])
                for name in client._orders
                if name not in old_orders
            ]
            raw_receipts = {
                "attempts": attempts,
                "accepted": accepted,
                "before_broker_sha256": packet._digest(codec._pack(before)),
                "actual_captured_at": datetime.now(UTC).isoformat(),
            }
            raw_ref = put(self.store, admitted.encoded(raw_receipts))
            after = components(self.store, client, self.root, self.pins())
            context.validate()
            return self.complete(
                directory,
                reservation,
                {
                    "phase": "NIGHTLY_CLOSE",
                    "session": session,
                    "status": status,
                    "reason": reason,
                    "hypothetical_decision_at": at.isoformat(),
                    "actual_compute_started_at": began.isoformat(),
                    "actual_compute_finished_at": datetime.now(UTC).isoformat(),
                    "actual_elapsed_ns": time.monotonic_ns() - tick,
                    "previous": previous,
                    "birth": birth,
                    "pre_inception_actions": pre_inception,
                    "context": put(self.store, context.provenance),
                    "components": after,
                    "raw_submission_receipts": raw_ref,
                    "native_capture": {
                        "physical_writes": capture.writes,
                        "submissions": capture.submissions,
                        "decisions": decisions,
                    },
                    "entry": entry,
                    "native_stdout": output.getvalue(),
                    "holding_policy_calls": len(capture.decisions),
                    "historical_actual_inference": None,
                    "new_base_models_fitted": 0,
                    "independent_ledger": "REQUIRED_SEPARATE_RECEIPT_AUDIT",
                    "auction_phase": "NOT_EXECUTED",
                    "physical_nonfinite": "NO_NORMALIZATION_OR_ADMISSION_RELAXATION",
                },
            )
        finally:
            LOCK.release()


# Keep a corrected submission clock coupled to its original account and context.
@dataclass(frozen=True, slots=True, init=False)
class SubmissionClock:
    raw: bytes
    nightly: Nightly


# Mint only from the exact current birth and canonical market-context capability.
def submission_clock(nightly, birth, context):
    admitted.require(
        type(nightly) is Nightly and type(context) is market.Context,
        "Current account/context capability required",
    )
    codec._identity(nightly.pins()["identity"], nightly.pins()["identity_sha256"])
    value = market.read_context(context)
    original = nightly.read_birth(birth)
    admitted.require(
        original["phase"] == "BIRTH"
        and original["identity"] == nightly.store.identity
        and original["initial_cash"] == 100000
        and original["initial_holdings"] == {}
        and tuple(original["cohort"]) == tuple(value["cohort"]),
        "Original corrected birth/cohort required",
    )
    result = object.__new__(SubmissionClock)
    object.__setattr__(
        result,
        "raw",
        admitted.encoded(
            {
                "identity": nightly.store.identity,
                "birth": birth,
                "context": {"raw": context.raw.decode(), "sha256": context.sha256},
                "source": admitted.CURRENT_SOURCE,
                "execution_timing": intraday_orders.INTRADAY_TIMING,
            }
        ),
    )
    object.__setattr__(result, "nightly", nightly)
    return result


# Validate corrected precise submission clocks without touching legacy audit behavior.
def admit_attempt(clock, attempt, intent):
    admitted.require(
        type(clock) is SubmissionClock, "Authenticated corrected clock required"
    )
    value = admitted.decoded(clock.raw)
    admitted.require(
        type(clock.nightly) is Nightly
        and clock.nightly.store.identity == value["identity"],
        "Original corrected account identity differs",
    )
    codec._identity(
        clock.nightly.pins()["identity"], clock.nightly.pins()["identity_sha256"]
    )
    original = clock.nightly.read_birth(value["birth"])
    context = value["context"]
    data = market.read_context(
        market.Context(context["raw"].encode(), context["sha256"])
    )
    admitted.require(
        tuple(original["cohort"]) == tuple(data["cohort"]),
        "Original corrected account cohort differs",
    )
    admitted.require(
        value["source"] == admitted.CURRENT_SOURCE
        and value["execution_timing"]
        == intent.get("execution_timing")
        == intraday_orders.INTRADAY_TIMING
        and intent.get("execute_on") == data["window"]["completed_at"][:10]
        and intent["symbol"] in data["cohort"]
        and all(
            attempt[name] == intent[name]
            for name in ("client_order_id", "symbol", "side")
        ),
        "Exact corrected native intent/context required",
    )
    admitted.require(
        packet.nanos(attempt["at"])
        == packet.nanos(data["window"]["assumed_submission_at"]),
        "Original corrected submission clock differs",
    )
    return True
