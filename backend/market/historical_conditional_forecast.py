"""Frozen current timing on archived prefixes, with explicit conditional clocks.

No provider, broker, model fitting, publication or live inference receipt exists
here. External byte pins are an admission requirement, not issuer authentication.
"""

import json
import math
import os
import stat
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import sklearn

from backend.market import (
    calendar,
    forward_entry_features,
    historical_timing_packet,
    intraday_sip,
    learned_live_holding,
)
from backend.market import forward_execution as inference
from backend.market import forward_probability_timing as forward
from backend.market import probabilistic_execution as probability
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.panel import build_panel
from backend.market.store import MarketStore

CURRENT_SOURCE = "3b72cd4e0bc15acd24432d501918c721685a5333"
CURRENT_IMAGE = (
    "sha256:f6127ef3d56d9d5d858ee82fea0dbde95886d286288570aa6b590a6ab53d3272"
)
CONTINUATION = "ee27ebad9f9d6d90276ad7fb1b69a37bfa4e9f0c189fdc9d1bb4b08c46c64296"
DELIVERY = "30b3e789890b33f5a107132b0c8c09e5394dc45a774a98f87c9f5ce7934834cc"
SOURCE_MAP = "bfbcb6ece4ea500726e00abbb06fc2c84d63d386bb307958016915357aaef5b3"
PACKET_SOURCE = "54763a69c3a0f7f7a6c8fa90fc7ff278ade0eec93e9b4872afa9c8a5f055377d"
CURRENT_CONFIG = "f96a29777403f5f08623709b70f36b15300500065202acbd215cd43f3c99a588"
CURRENT_RELEASE = "1c1c6e9bcc7e9fa8d095f6ce5e6bf973c99ed19531e88c38a9aba5ed8410cd3e"
ECONOMIC_EVIDENCE = "4d6af1bb755243bdce9a5c74477ae43cf91a72cbe7fa9e2985d13bfd5d3cacb9"
OLD_CONFIG = "1a14980a66a1cb5994f0bb82667dd46fce40ec7eb0705728d93e36b18faf5901"
CAPTURE = "1b8247f7fd042a1bfc7aaa7803df7e94cbc7943bd119fd2a8f4940b17d1c7e9c"
OVERLAY = "5d0640d321ba97ab7d1e37b3e1c680c21af68fc355a905842ace50d808db988c"
CLOSE = "97a3a9893da942211ccc584ea664b377d4826e1710ee0b36e3b0d0838862601c"
CLOSE_ARRAYS = "3598ab539d37c48c58bfe823d607377243731aa1db3d650a92cb7f1a9a525d79"
TIMING_FILES = {
    "config.json": "d03339a3ad4b590ef8ed4205375d39d634df12a6fb49e290ab5b0f3642ea679a",
    "model/publication.json": (
        "7759572d79f1bc4e0cb288c04f9d14d318c8d51f15d447efd7a6bf47864d60a8"
    ),
    "model/models.npz": (
        "14a47423e82608361c0810b399a17bb817b119c4783f7995728b18323f5d5c41"
    ),
    "residual/residuals.json": (
        "348b81ca6018a73701aaa8e76970facf514ebba6b6a0e68e204b1f28eb4aca9b"
    ),
    "residual/residuals.npz": (
        "4616b41cc6e39b2e8c763417def0baaa1bdd01800e5535a412594671d1d3f94e"
    ),
}
CONTEXT_SOURCES = {
    "backend/market/panel.py": (
        "dee6b591080f18ba0b35c1241d96cb0e906957b3007f25be941957d2ee7252a2"
    ),
    "backend/market/store.py": (
        "a299516ab68710d56355e036770d3c9695ed332641e9fa6ee4d64c9f6ede9aff"
    ),
    "backend/market/yahoo.py": (
        "311323b71355858a1ea1fca9d7b03861df71f35466a789d90a872bbbdc93e82d"
    ),
}
META_CAP = 16 * 1024**2
ARRAY_CAP = 64 * 1024**2


# Refuse incomplete or contradictory provenance without optimization-sensitive asserts.
def require(condition, reason):
    if not condition:
        raise ValueError(reason)


# Encode finite outer metadata independently of mutable caller dictionaries.
def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


# Reject duplicate fields rather than selecting the last source claim.
def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate conditional JSON member")
        result[key] = value
    return result


# Reject nonfinite constants in every external receipt.
def constant(value):
    raise ValueError("Nonfinite conditional JSON constant")


# Reject overflowing numeric metadata before it can become a source identity.
def finite(value):
    result = float(value)
    require(math.isfinite(result), "Nonfinite conditional JSON number")
    return result


# Parse only finite duplicate-free immutable source metadata.
def decoded(raw):
    require(
        type(raw) is bytes and len(raw) <= META_CAP,
        "Bounded immutable metadata required",
    )
    return json.loads(
        raw, object_pairs_hook=unique, parse_constant=constant, parse_float=finite
    )


# Admit externally supplied byte identity without treating a digest as an issuer claim.
@dataclass(frozen=True, slots=True)
class Evidence:
    raw: bytes
    sha256: str

    # Retain exact original bytes and a separately supplied expected digest.
    def __post_init__(self):
        require(
            type(self.raw) is bytes and len(self.raw) <= META_CAP,
            "Bounded immutable source bytes required",
        )
        require(
            type(self.sha256) is str
            and len(self.sha256) == 64
            and sha256(self.raw).hexdigest() == self.sha256,
            "External source digest differs",
        )
        decoded(self.raw)


# Identify a stable regular input without following any symlinked path component.
def identity(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        require(not component.is_symlink(), "Regular conditional source paths required")
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), "Regular conditional source file required")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


# Stream fixed-size chunks and detect replacement or edits during authentication.
def authenticate(path, expected):
    before = identity(path)
    result = sha256()
    with Path(path).open("rb") as stream:
        require(
            identity(path) == before and os.fstat(stream.fileno()).st_ino == before[1],
            "Source replaced before read",
        )
        while block := stream.read(1024**2):
            result.update(block)
        after = os.fstat(stream.fileno())
    require(
        identity(path) == before
        and (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        == before,
        "Conditional source changed during read",
    )
    require(result.hexdigest() == expected, "Conditional source bytes differ")
    return expected


# Allocate only bounded metadata after its independent original hash has matched.
def metadata(path, expected):
    authenticate(path, expected)
    require(identity(path)[2] <= META_CAP, "Conditional metadata cap exceeded")
    with Path(path).open("rb") as stream:
        raw = stream.read(META_CAP + 1)
    require(
        len(raw) <= META_CAP and sha256(raw).hexdigest() == expected,
        "Conditional metadata changed",
    )
    return Evidence(raw, expected)


# Copy typed arrays into immutable byte-backed views with no writable base object.
def frozen_array(value):
    array = np.asarray(value)
    require(
        not array.dtype.hasobject and array.nbytes <= ARRAY_CAP,
        "Bounded non-object conditional array required",
    )
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


# Carry complete causal prior rows with immutable source and array identities.
@dataclass(frozen=True, slots=True, init=False)
class Prior:
    dates: np.ndarray
    tickers: tuple
    adj_close: np.ndarray
    grades: np.ndarray
    eligible: np.ndarray
    raw_prior_close: np.ndarray
    provenance: bytes

    # Reauthenticate every source and all detached arrays before another observation.
    def validate(self):
        value = decoded(self.provenance)
        for name, expected in value["files"].items():
            authenticate(name, expected)
        for name, expected in value["arrays"].items():
            require(
                _hash(getattr(self, name)) == expected, "Admitted prior array changed"
            )
        require(
            tuple(value["symbols"]) == self.tickers, "Admitted prior cohort changed"
        )
        return value


# Restore the verified full-context6176 extraction at any explicitly reviewed session.
def load_prior(market, observation, session):
    market, observation = Path(market), Path(observation)
    day = date.fromisoformat(session)
    require(
        day.isoformat() == session and date(2019, 3, 1) <= day <= date(2026, 10, 12),
        "Corrected account session outside contract",
    )
    root = Path(__file__).resolve().parents[2]
    for name, expected in CONTEXT_SOURCES.items():
        authenticate(root / name, expected)
    capture = decoded(metadata(market / "capture.json", CAPTURE).raw)
    overlay = decoded(metadata(market / "grade-overlay-proof.json", OVERLAY).raw)
    close = decoded(metadata(observation / "close.json", CLOSE).raw)
    files = {
        str(market / "capture.json"): CAPTURE,
        str(market / "grade-overlay-proof.json"): OVERLAY,
        str(observation / "close.json"): CLOSE,
        str(observation / "close.npz"): CLOSE_ARRAYS,
    }
    files.update(
        {str(root / name): expected for name, expected in CONTEXT_SOURCES.items()}
    )
    files.update(
        {
            str(market / name): expected
            for name, expected in capture["files"].items()
            if name.startswith(("bars/", "actions/"))
        }
    )
    for name, expected in files.items():
        authenticate(name, expected)
    require(
        close["arrays_sha256"] == CLOSE_ARRAYS
        and forward._digest(close["identity"])
        == close["identity_sha256"]
        == overlay["original_observation_identity_sha256"],
        "Original context metadata identity differs",
    )
    with np.load(observation / "close.npz", allow_pickle=False) as archive:
        dates, symbols, original_grades = (
            archive["dates"],
            tuple(archive["symbols"].tolist()),
            archive["history_grades"],
        )
    for name, value in (
        ("dates", dates),
        ("symbols", np.array(symbols)),
        ("history_grades", original_grades),
    ):
        require(
            value.nbytes <= ARRAY_CAP
            and _hash(value) == close["identity"]["array_sha256"][name],
            "Original context array differs",
        )
    require(
        len(symbols) == 96
        and len(set(symbols)) == 96
        and symbols == tuple(capture["symbols"])
        and _hash(original_grades) == overlay["original_grade_array_sha256"],
        "Exact full96 chart/benchmark cohort required",
    )
    require(str(dates[0]) == "2015-01-02", "Full original EMA/breadth prefix required")
    store = MarketStore(market)
    through = date.fromisoformat(capture["through"])
    panel = build_panel(
        store, symbols, "SPY", {}, asof=through, start=dates[0].astype(object)
    )
    require(
        panel.tickers == symbols and np.array_equal(panel.dates, dates),
        "Complete original context calendar differs",
    )
    grades = np.full(panel.close.shape, -1, dtype=np.int16)
    labels = {"A+": 3, "A": 2, "B": 1, "C": 0}
    for stock, symbol in enumerate(symbols):
        if symbol in ("SPY", "QQQ"):
            grades[:, stock] = original_grades[:, stock]
            continue
        path = market / "history" / (symbol + ".json")
        expected = overlay["histories"][symbol]
        history = decoded(metadata(path, expected).raw)
        files[str(path)] = expected
        require(
            history["asof"] >= capture["through"],
            "Completed chart grade archive required",
        )
        for row in history["rows"]:
            index = int(np.searchsorted(dates, np.datetime64(row["date"])))
            if index < len(dates) and dates[index] == np.datetime64(row["date"]):
                grades[index, stock] = labels.get(row.get("grade"), -1)
    end = int(np.searchsorted(dates, np.datetime64(session)))
    require(
        0 < end < len(dates) and str(dates[end]) == session,
        "Exact prior session boundary required",
    )
    raw_prior = np.full(len(symbols), np.nan)
    for stock, symbol in enumerate(symbols):
        history = store.read(symbol, through)
        factor = math.prod(
            action.value
            for action in history.actions
            if action.kind == "split"
            and action.action_date > dates[end - 1].astype(object)
        )
        raw_prior[stock] = panel.close[end - 1, stock] * factor
    values = {
        "dates": frozen_array(dates[:end]),
        "adj_close": frozen_array(panel.adj_close[:end]),
        "grades": frozen_array(grades[:end]),
        "eligible": frozen_array(grades[:end] >= 0),
        "raw_prior_close": frozen_array(raw_prior),
    }
    provenance = encoded(
        {
            "schema": "conditional-full-prior/1",
            "session": session,
            "symbols": list(symbols),
            "files": files,
            "arrays": {name: _hash(value) for name, value in values.items()},
            "historical_as_published": False,
            "basis": "retrospective_final_archive_saved_recalculated_chart_grades",
        }
    )
    result = object.__new__(Prior)
    for name, value in {"tickers": symbols, "provenance": provenance, **values}.items():
        object.__setattr__(result, name, value)
    result.validate()
    return result


# Hold exact current approval and immutable model/artifact identities.
@dataclass(frozen=True, slots=True, init=False)
class AdmittedTiming:
    root: Path
    artifact_root: Path
    archive: Path
    continuation: Evidence
    delivery: Evidence
    files: bytes

    # Reject changed native source, selectors, model arrays or predecessor snapshots.
    def validate(self):
        for path, expected in decoded(self.files).items():
            authenticate(path, expected)
        expected = decoded(self.delivery.raw)["admission"]["source_sha256"]
        require(
            learned_live_holding.source_identity() == expected,
            "Current3b72 guarded sources differ",
        )
        require(
            np.__version__ == "2.5.3" and sklearn.__version__ == "1.9.1",
            "Exact current native numerical packages required",
        )
        actual = datetime.now(UTC)
        raw, holding = learned_live_holding.read_configuration(self.root, actual)
        require(
            sha256(raw).hexdigest() == CURRENT_CONFIG,
            "Current approval configuration differs",
        )
        return holding


# Admit only the explicit later metadata continuation, preserving all older selectors.
def admit(approval_root, artifact_root, archive_root, continuation, delivery):
    require(
        type(continuation) is Evidence and continuation.sha256 == CONTINUATION,
        "Reviewed current metadata continuation required",
    )
    require(
        type(delivery) is Evidence and delivery.sha256 == DELIVERY,
        "Independent current delivery receipt required",
    )
    current, native = decoded(continuation.raw), decoded(delivery.raw)
    identity = current["current_delivered_identity"]
    require(
        identity["source"] == CURRENT_SOURCE
        and identity["image"] == CURRENT_IMAGE
        and identity["source31_map_sha256"] == SOURCE_MAP
        and sha256(
            json.dumps(
                native["admission"]["source_sha256"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        == SOURCE_MAP,
        "Exact current31 identity required",
    )
    require(
        current["original_contract"]["sha256"]
        == "033934aa845739fa818930cd890409100d7df37d57e4cde5bc07e801d2eca1e9"
        and current["new_generic_get_authorization"] is False,
        "Unchanged corrected contract required",
    )
    approval, artifacts, archive = map(
        Path, (approval_root, artifact_root, archive_root)
    )
    holding_root = approval / "desk/learned-holding"
    files = {
        str(holding_root / name): expected
        for name, expected in (
            ("config.json", CURRENT_CONFIG),
            ("release.json", CURRENT_RELEASE),
            ("evidence.json", ECONOMIC_EVIDENCE),
        )
    }
    for name, expected in native["approval_archive"]["prior_sha256"].items():
        files[str(archive / name)] = expected
    files[str(archive / "receipt.json")] = identity[
        "original_selector_archive_receipt_sha256"
    ]
    files.update(
        {
            str(artifacts / "desk/learned-timing" / name): expected
            for name, expected in TIMING_FILES.items()
        }
    )
    files[str(artifacts / "desk/learned-holding/config.json")] = OLD_CONFIG
    capture_path = artifacts / "capture.json"
    capture = decoded(metadata(capture_path, CAPTURE).raw)
    files[str(capture_path)] = CAPTURE
    files.update(
        {
            str(artifacts / name): expected
            for name, expected in capture["files"].items()
            if name.startswith(("desk/learned-holding/", "desk/learned-timing/"))
        }
    )
    for path, expected in files.items():
        authenticate(path, expected)
    original = decoded(
        metadata(artifacts / "desk/learned-holding/config.json", OLD_CONFIG).raw
    )
    current_config = decoded(metadata(holding_root / "config.json", CURRENT_CONFIG).raw)
    predecessor = decoded(
        metadata(
            archive / "config.json",
            native["approval_archive"]["prior_sha256"]["config.json"],
        ).raw
    )
    require(
        {k: v for k, v in original.items() if k != "release_receipt_sha256"}
        == {k: v for k, v in current_config.items() if k != "release_receipt_sha256"}
        == {k: v for k, v in predecessor.items() if k != "release_receipt_sha256"},
        "Model or economic configuration changed across source approvals",
    )
    timing = decoded(
        metadata(
            artifacts / "desk/learned-timing/config.json", TIMING_FILES["config.json"]
        ).raw
    )
    require(
        timing["cost_bps"] == current_config["cost_bps"] == 10
        and current_config["timing_config_sha256"] == TIMING_FILES["config.json"]
        and timing["model_receipt_sha256"] == TIMING_FILES["model/publication.json"]
        and timing["residual_receipt_sha256"] == TIMING_FILES["residual/residuals.json"]
        and timing["model_directory"] == "model"
        and timing["residual_directory"] == "residual",
        "Exact original timing artifacts and10bp required",
    )
    result = object.__new__(AdmittedTiming)
    for name, value in {
        "root": approval,
        "artifact_root": artifacts,
        "archive": archive,
        "continuation": continuation,
        "delivery": delivery,
        "files": encoded(files),
    }.items():
        object.__setattr__(result, name, value)
    result.validate()
    return result


# Extract only completed native raw bars from independently pinned local source files.
def prefixes(prior, raw_root, source, requested, window):
    require(
        type(prior) is Prior and type(source) is Evidence,
        "Authenticated prior and raw source bytes required",
    )
    require(
        type(requested) is tuple
        and len(requested) == len(set(requested))
        and set(requested) <= set(prior.tickers),
        "Explicit unique due-symbol coverage required",
    )
    declaration = decoded(source.raw)
    completed = datetime.fromisoformat(window["completed_at"])
    session = completed.astimezone(calendar.NEW_YORK).date()
    require(
        decoded(prior.provenance)["session"] == session.isoformat(),
        "Prefix/prior session differs",
    )
    opening = datetime.combine(session, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    count = int((completed - opening).total_seconds() // 900)
    require(
        1 <= count <= 25 and completed == opening + timedelta(minutes=15 * count),
        "Exact completed prefix boundary required",
    )
    result, files = {}, {}
    for symbol in requested:
        require(symbol in declaration, "Explicit due-symbol raw source missing")
        record = declaration[symbol]
        path = (
            Path(raw_root)
            / "bars_15m_sip"
            / ("asof=" + session.isoformat())
            / (symbol + ".parquet")
        )
        expected = record["sha256"]
        if expected is None:
            require(
                not path.exists() and record.get("status") == "missing",
                "Declared missing raw source changed",
            )
            files[str(path)] = None
            continue
        authenticate(path, expected)
        require(identity(path)[2] <= 1024**2, "Single-session raw source cap exceeded")
        files[str(path)] = expected
        found = intraday_sip.read_session_full(MarketStore(raw_root), symbol, session)
        if found is None:
            continue
        require(
            found[2].get("ticker") == symbol
            and found[2].get("session_date") == session.isoformat()
            and found[2].get("kind") == intraday_sip.KIND
            and found[2].get("feed") == "sip",
            "Original raw SIP prefix identity differs",
        )
        # Later missing slots cannot decide whether this completed prefix exists.
        rows = found[0][:count]
        result[symbol] = {
            "starts": [row.start.isoformat() for row in rows],
            "published_at": window["assumed_bar_available_at"],
            "prior_close": float(prior.raw_prior_close[prior.tickers.index(symbol)]),
            **{
                name: frozen_array(
                    np.array([getattr(row, name) for row in rows], dtype=np.float64)
                )
                for name in ("open", "high", "low", "close", "volume")
            },
        }
    return result, files


# Return detached native distributions without exposing mutable receipt expectations.
@dataclass(frozen=True, slots=True, init=False)
class ConditionalForecast:
    features: np.ndarray
    valid: np.ndarray
    receipt: bytes
    _distributions: tuple

    # Build a new native dictionary whose residual arrays have immutable bytes bases.
    def distributions(self):
        return {
            symbol: None if values is None else probability.Distribution(*values)
            for symbol, values in self._distributions
        }


# Require the preregistered availability schedule without changing its declared values.
def conditional_window(value):
    authenticate(Path(historical_timing_packet.__file__), PACKET_SOURCE)
    window = decoded(encoded(value))
    require(
        window == historical_timing_packet.schedule(window["completed_at"]),
        "Fixed conditional availability schedule differs",
    )
    return window


# Compute native features and distributions under separate actual and assumed clocks.
def infer(admitted, prior, raw_root, raw_source, requested, window):
    require(
        type(admitted) is AdmittedTiming and type(prior) is Prior,
        "Exact admitted conditional timing inputs required",
    )
    actual_start, monotonic_start = datetime.now(UTC), time.monotonic_ns()
    admitted.validate()
    prior_metadata = prior.validate()
    window = conditional_window(window)
    decision = datetime.fromisoformat(window["assumed_decision_at"])
    require(
        window["completed_at"][:10] == prior_metadata["session"],
        "Conditional observation session differs",
    )
    raw_prefixes, raw_files = prefixes(prior, raw_root, raw_source, requested, window)
    prior_panel = SimpleNamespace(
        dates=prior.dates, tickers=prior.tickers, adj_close=prior.adj_close
    )
    previous = prior.dates[-1].astype(object)
    daily_as_of = datetime.combine(
        previous, calendar.session_close(previous), calendar.NEW_YORK
    ) + timedelta(minutes=1)
    frame = forward_entry_features.observe(
        prior_panel,
        prior.grades,
        prior.eligible,
        raw_prefixes,
        observed_at=decision,
        daily_as_of=daily_as_of,
    )
    require(
        frame["features"].shape == (96, 21)
        and frame["features"].dtype == np.float32
        and frame["valid"].shape == (96,),
        "Exact96x21 native feature frame required",
    )
    timing = admitted.artifact_root / "desk/learned-timing"
    model_clock = datetime.now(UTC)
    residual = forward.load_residual_month(
        timing / "residual",
        receipt_sha256=TIMING_FILES["residual/residuals.json"],
        observed_at=model_clock,
    )
    distribution = inference.current_distributions(
        timing / "model",
        TIMING_FILES["model/publication.json"],
        residual,
        symbols=prior.tickers,
        values=frame["features"],
        valid=frame["valid"],
        observed_at=model_clock,
        timing_supported=frame["timing_supported"],
    )
    actual_end, monotonic_end = datetime.now(UTC), time.monotonic_ns()
    require(
        actual_start <= model_clock <= actual_end and monotonic_end >= monotonic_start,
        "Actual computation clocks moved backwards",
    )
    forward._validate_residual_month(residual, actual_end)
    admitted.validate()
    prior.validate()
    for path, expected in raw_files.items():
        require(
            not Path(path).exists(), "Originally missing raw prefix appeared"
        ) if expected is None else authenticate(path, expected)
    values = tuple(
        (
            symbol,
            None
            if item is None
            else (
                item.mean,
                item.scale,
                frozen_array(item.residuals),
                frozen_array(item.weights),
            ),
        )
        for symbol, item in distribution.items()
    )
    result = {
        "schema": "conditional-current-model-forecast/1",
        "origin": "ARCHIVED_RAW_INPUT_WITH_DECLARED_HISTORICAL_AVAILABILITY",
        "current_source": CURRENT_SOURCE,
        "expected_native_image": CURRENT_IMAGE,
        "source31_map_sha256": SOURCE_MAP,
        "continuation_sha256": admitted.continuation.sha256,
        "current_config_sha256": CURRENT_CONFIG,
        "current_release_sha256": CURRENT_RELEASE,
        "economic_evidence_sha256": ECONOMIC_EVIDENCE,
        "helper_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "actual_compute_started_at": actual_start.isoformat(),
        "actual_model_admission_at": model_clock.isoformat(),
        "actual_compute_finished_at": actual_end.isoformat(),
        "actual_elapsed_ns": monotonic_end - monotonic_start,
        "hypothetical_window": window,
        "hypothetical_daily_available_at": daily_as_of.isoformat(),
        "historical_actual_receive_publication_inference": None,
        "prior_sha256": sha256(prior.provenance).hexdigest(),
        "raw_source_sha256": raw_source.sha256,
        "raw_files": raw_files,
        "requested_symbols": list(requested),
        "symbols": list(frame["symbols"]),
        "feature_names": list(frame["feature_names"]),
        "features_sha256": _hash(frame["features"]),
        "valid_sha256": _hash(frame["valid"]),
        "native_observation": {
            name: frame[name]
            for name in (
                "identity",
                "clock",
                "completed_at",
                "observed_at",
                "daily_as_of",
                "timing_supported",
            )
        },
        "model_receipt_sha256": TIMING_FILES["model/publication.json"],
        "residual_receipt_sha256": TIMING_FILES["residual/residuals.json"],
        "actual_model_publication": decoded(
            metadata(
                timing / "model/publication.json",
                TIMING_FILES["model/publication.json"],
            ).raw
        )["identity"],
        "actual_residual_publication": residual.receipt["identity"],
        "native_distributions": forward._forecast_identity(distribution),
        "native_sources": forward._inference_sources(),
        "model_sources": inference._sources(),
        "availability_is_assumed": True,
        "actual_live_inference_receipt": False,
        "generic_cycle_binding": "UNVERIFIED_SEPARATE_INTEGRATION_REQUIRED",
        "publication_barrier": "CLOSED",
        "base_models_fitted": 0,
    }
    output = object.__new__(ConditionalForecast)
    for name, value in {
        "features": frozen_array(frame["features"]),
        "valid": frozen_array(frame["valid"]),
        "receipt": encoded(result),
        "_distributions": values,
    }.items():
        object.__setattr__(output, name, value)
    return output
