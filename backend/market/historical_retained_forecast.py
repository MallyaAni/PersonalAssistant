"""Unused, externally pinned ONE_AAPL retained forecast and raw-anchor bridge.

This reads a prior computation, never restores or calls a model. External pins
must come from an independently reviewed proof, not from the files being read.
The returned outer binding is conditional evidence, not a live inference receipt,
issuer assertion, available account, submitted order or fill. No Cycle is wired.
"""

import io
import json
import math
import os
import stat
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.market import forward_probability_timing as forward
from backend.market import (
    historical_conditional_forecast as original,
)
from backend.market import (
    historical_conditional_market as market,
)
from backend.market import (
    historical_timing_packet as packet,
)
from backend.market import (
    intraday_sip,
    learned_live_holding,
)
from backend.market import (
    probabilistic_execution as probability,
)
from backend.market.daily_arithmetic_bridge import _hash

CAP = 512 * 1024
RAW_CAP = 1024 * 1024
HELPER = "68536cfef1d27e5a612cd4ddbd1b5e87f725e1c0f6e06bf5bc20cd051d0ea29c"
IMAGE_MAP = "1d126a0b335452e541d48b1d3befc4525323b819135f4b65ee5de07f61b2bfb5"
RAW_KEY = "/raw/bars_15m_sip/asof=2019-03-01/AAPL.parquet"
COMPARISONS = frozenset(
    [
        "all21_features_exact",
        "benchmarks_unavailable",
        "cohort_order_exact",
        "full_frame_and_valid_exact",
        "mean_scale_exact",
        "native_current_typed_identity_exact",
        "native_horizon_exact",
        "native_reader_identity_exact",
        "no_live_inference_receipt",
        "only_AAPL_valid",
        "prior_calendar_exact",
        "publication_closed",
        "raw_prior_close_exact",
        "residual_rows_exact",
    ]
)
MEMBERS = ("features", "valid", "AAPL_residuals", "AAPL_weights")
PACKAGES = {
    "numpy": (
        "2.5.3",
        "09295a80660f17925ae23765ce8cbd7ff7ceae968d5f2f89349f1cb74c0b9e11",
    ),
    "sklearn": (
        "1.9.1",
        "66a78bb27706626c4cc8ef424a5479f6301204baacd85986e8002c16b751fef1",
    ),
}


# Name the independently supplied original-byte identities before reading any file.
@dataclass(frozen=True, slots=True)
class Pins:
    proof: str
    runtime: str
    receipt: str
    arrays: str
    prior: str
    source_copy: str
    source_map: str
    raw_source: str

    # Refuse missing or malformed external commitments rather than deriving them.
    def __post_init__(self):
        for name in self.__slots__:
            value = getattr(self, name)
            original.require(
                type(value) is str
                and len(value) == 64
                and all(c in "0123456789abcdef" for c in value),
                "Explicit external SHA256 pins required",
            )


GENUINE = Pins(
    "56414456269865f2a72c7d05703e10d605358e3b1a3406c27a5abfe0b33a2bd0",
    "74a0a879ed1bed9d08de87590c7b362b4a2fb9096ad1bd0625537c8935552d2d",
    "285f438b241649e1060de7943e9e9eeb3193d49bc1fe1027e44441e68b855f7e",
    "ab5c072e256fc31a76583d885fe458c0247d4158d9d02a317d1ba4114fbabc95",
    "19f0465fde2550f9fdee650e7341f4b3d5436d9cab40c1ff7a25f9ec70cf880a",
    "671e236f75ee6e420ae09c2f54029119b1c096c0703a0a55fb90298853ae3c2f",
    IMAGE_MAP,
    "65402bdc171cdb26c12626d024d1160aa20b56f5cb5158580de14c179336c5c2",
)


# Read at most cap+1 bytes from one stable regular descriptor without symlink paths.
def _read(path, expected, cap=CAP):
    path = Path(path).absolute()
    original.identity(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        original.require(stat.S_ISREG(before.st_mode), "Regular retained file required")
        original.require(before.st_size <= cap, "Retained resource cap: PAUSE")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(cap + 1)
        after = os.fstat(fd)
        current = path.stat(follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        original.require(
            len(raw) <= cap
            and all(
                getattr(before, k) == getattr(after, k) == getattr(current, k)
                for k in fields
            )
            and len(raw) == before.st_size,
            "Retained source changed or exceeded cap: PAUSE",
        )
        original.identity(path)
    finally:
        os.close(fd)
    original.require(
        sha256(raw).hexdigest() == expected, "External retained bytes differ"
    )
    return raw


# Keep JSON parsing bounded, finite and duplicate-free for every original receipt.
def _json(raw):
    original.require(type(raw) is bytes and len(raw) <= CAP, "Retained JSON cap: PAUSE")
    value = original.decoded(raw)
    original.require(type(value) is dict, "Retained JSON object required")
    return value


# Parse actual clocks without silently inventing a timezone or using the host clock.
def _clock(value):
    original.require(type(value) is str, "Explicit aware retained clock required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    original.require(
        result.tzinfo is not None and result.utcoffset() is not None,
        "Aware retained clock required",
    )
    return result.astimezone(UTC)


# Check the independently pinned physical runtime and readonly source-overlay proof.
def _runtime(runtime, proof, copied, image_map, pins):
    state, limits = runtime["state"], runtime["runtime"]
    original.require(
        runtime["image"] == original.CURRENT_IMAGE
        and runtime["user"] == "1000:1000"
        and len(runtime["container_id"]) == 64
        and state["ExitCode"] == 0
        and state["OOMKilled"] is False
        and state["Status"] == "exited"
        and state["Running"] is False
        and limits["NetworkMode"] == "none"
        and limits["ReadonlyRootfs"] is True
        and limits["NanoCpus"] == 1_000_000_000
        and limits["Memory"] == limits["MemorySwap"] == 2_147_483_648
        and limits["Tmpfs"] == {"/tmp": "rw,size=64m"},
        "Exact independently pinned current runtime required",
    )
    mounts = runtime["mounts"]
    destinations = [m["Destination"] for m in mounts]
    original.require(
        len(destinations) == len(set(destinations))
        and {"/app/backend", "/app/docs", "/image-source-map.json", RAW_KEY, "/out"}
        <= set(destinations)
        and all(m["RW"] is (m["Destination"] == "/out") for m in mounts),
        "Original readonly forecast mounts differ",
    )
    mount_map = {m["Destination"]: m["Source"] for m in mounts}
    source = proof["source_before_after"]
    original.require(
        source["helper_sha256"] == HELPER
        and source["image_source_files"] == len(image_map) == 1655
        and source["image_source_map_sha256"] == pins.source_map
        and source["private_permissions_only"] is True
        and source["whole_backend_readonly_overlay"] is True
        and copied["status"] == "VERIFIED_READABLE_COPY_FROM_UNMOUNTED_IMMUTABLE_IMAGE"
        and copied["source_map_sha256"] == pins.source_map
        and copied["recorded_before_after_bytes_equal"] is True
        and copied["native_stdout_equals_copied_map"] is True
        and copied["live_or_image_permission_changes"] is False
        and copied["current_physical_map_comparisons"][
            str(Path(mount_map["/app/backend"]).parent)
        ]
        == 1655,
        "Independent source-copy/overlay binding differs",
    )
    for kind in ("extraction_container", "unmounted_image_hash_container"):
        value = copied[kind]
        original.require(
            value["image"] == original.CURRENT_IMAGE and value["mounts"] == [],
            "Unmounted immutable source proof required",
        )
    original.require(
        copied["extraction_container"]["state"]["Status"] == "created"
        and copied["extraction_container"]["state"]["StartedAt"].startswith("0001-")
        and copied["unmounted_image_hash_container"]["network"] == "none"
        and copied["unmounted_image_hash_container"]["readonly_root"] is True
        and copied["unmounted_image_hash_container"]["state"]["ExitCode"] == 0,
        "Actual source extraction proof differs",
    )
    expected = {
        "out/proof.json": pins.proof,
        "out/derived-receipt.bin": pins.receipt,
        "out/derived-arrays.npz": pins.arrays,
        "out/prior-provenance.json": pins.prior,
    }
    original.require(
        all(runtime["file_sha256"].get(k) == v for k, v in expected.items()),
        "Runtime retained-file references differ",
    )
    for name, (version, digest) in PACKAGES.items():
        value = proof["native_packages"][name]
        original.require(
            value
            == {
                "version": version,
                "path": f"/usr/local/lib/python3.12/site-packages/{name}/__init__.py",
                "sha256": digest,
            },
            "Native package provenance differs",
        )


# Reject ZIP expansion and unsafe NPY headers before allocating retained arrays.
def _arrays(raw):
    original.require(type(raw) is bytes and len(raw) <= CAP, "Retained NPZ cap: PAUSE")
    output = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        original.require(
            {i.filename for i in infos} == {n + ".npy" for n in MEMBERS}
            and len(infos) == len(MEMBERS)
            and sum(i.file_size for i in infos) <= CAP
            and all(i.file_size <= CAP and not i.flag_bits & 1 for i in infos),
            "Exact bounded retained NPZ members required: PAUSE",
        )
        shapes = {"features": (96, 21), "valid": (96,)}
        for name in MEMBERS:
            with archive.open(name + ".npy") as stream:
                version = np.lib.format.read_magic(stream)
                original.require(
                    version in ((1, 0), (2, 0)), "Safe retained NPY version required"
                )
                read_header = {
                    (1, 0): np.lib.format.read_array_header_1_0,
                    (2, 0): np.lib.format.read_array_header_2_0,
                }[version]
                shape, fortran, dtype = read_header(stream, max_header_size=4096)
                expected = np.dtype(
                    bool
                    if name == "valid"
                    else np.float32
                    if name == "features"
                    else np.float64
                )
                original.require(
                    dtype == expected
                    and not fortran
                    and (
                        shape == shapes[name]
                        if name in shapes
                        else len(shape) == 1 and 0 < shape[0] <= 32768
                    )
                    and math.prod(shape) * dtype.itemsize
                    == archive.getinfo(name + ".npy").file_size - stream.tell(),
                    "Exact retained array type/shape/size required",
                )
            with archive.open(name + ".npy") as stream:
                value = np.lib.format.read_array(
                    stream, allow_pickle=False, max_header_size=4096
                )
            output[name] = original.frozen_array(value)
    return output


# Keep immutable samples and admission metadata without a public constructor.
@dataclass(frozen=True, slots=True, init=False)
class RetainedForecast:
    receipt: bytes
    binding: bytes
    features: np.ndarray
    valid: np.ndarray
    _values: tuple

    # Only the byte-authenticating loader may allocate an admitted retained handle.
    def __new__(cls):
        raise TypeError("Use read_retained with independent original-byte pins")

    # Return a detached native dictionary while retaining exact missing distributions.
    def distributions(self):
        return {
            n: None if v is None else probability.Distribution(*v)
            for n, v in self._values
        }


# Validate one admitted context against the retained full frame and native arithmetic.
def _result(receipt, proof, values, context, requested):
    ctx = market.read_context(context)
    original.require(
        ctx["phase"] == "MODEL_TIMED_MARKET_ONLY"
        and ctx["window"] == receipt["hypothetical_window"]
        and ctx["window"] == packet.schedule("2019-03-01T14:45:00Z")
        and ctx["cohort"] == receipt["symbols"]
        and requested == ("AAPL",)
        and receipt["requested_symbols"] == list(requested),
        "Exact ONE_AAPL context/cohort/requested set required",
    )
    symbols = tuple(ctx["cohort"])
    original.require(
        receipt["feature_names"]
        == list(original.forward_entry_features.original.FEATURE_NAMES),
        "Original feature order differs",
    )
    features, valid = values["features"], values["valid"]
    residuals, weights = probability._sample(
        values["AAPL_residuals"], values["AAPL_weights"]
    )
    index = symbols.index("AAPL")
    original.require(
        valid.tolist() == [i == index for i in range(96)]
        and np.isfinite(features[valid]).all()
        and _hash(features) == receipt["features_sha256"]
        and _hash(valid) == receipt["valid_sha256"]
        and len(residuals) == proof["residual_rows"]
        and features[index].tolist() == proof["feature_row"],
        "Original full frame/valid/sample binding differs",
    )
    identities = receipt["native_distributions"]
    original.require(
        set(identities) == set(symbols)
        and all(identities[n] is None for n in symbols if n != "AAPL"),
        "Original unavailable names must remain unavailable",
    )
    item = identities["AAPL"]
    original.require(
        type(item["mean"]) in (int, float)
        and type(item["scale"]) in (int, float)
        and item["mean"] == proof["distribution_mean"]
        and item["scale"] == proof["distribution_scale"],
        "Original retained mean/scale differs",
    )
    dist = probability.Distribution(
        item["mean"], item["scale"], residuals, weights, item["horizon"]
    )
    distributions = {n: dist if n == "AAPL" else None for n in symbols}
    original.require(
        forward._forecast_identity(distributions) == identities,
        "Native typed forecast identity differs",
    )
    observation = receipt["native_observation"]
    original.require(
        observation["clock"] == 0
        and observation["timing_supported"] is True
        and _clock(observation["completed_at"]) == _clock(ctx["window"]["completed_at"])
        and _clock(observation["observed_at"])
        == _clock(ctx["window"]["assumed_decision_at"])
        and observation["daily_as_of"] == receipt["hypothetical_daily_available_at"]
        and set(observation["identity"]["prefixes"]) == {"AAPL"},
        "Original conditional observation differs",
    )
    return tuple(
        (
            n,
            None
            if n != "AAPL"
            else (dist.mean, dist.scale, residuals, weights, dist.horizon),
        )
        for n in symbols
    )


# Authenticate one retained computation without invoking artifact restore or inference.
def read_retained(root, context, *, requested=("AAPL",), pins=GENUINE):
    original.require(type(pins) is Pins, "Independent retained Pins required")
    root = Path(root)
    filenames = {
        "proof": "proof.json",
        "runtime": "runtime-proof.json",
        "receipt": "derived-receipt.bin",
        "arrays": "derived-arrays.npz",
        "prior": "prior-provenance.json",
        "source_copy": "image-provenance-proof.json",
        "source_map": "image-source-map.json",
        "raw_source": "raw-bars.json",
    }
    bodies = {n: _read(root / p, getattr(pins, n)) for n, p in filenames.items()}
    data = {n: _json(b) for n, b in bodies.items() if n != "arrays"}
    receipt, proof = data["receipt"], data["proof"]
    _runtime(data["runtime"], proof, data["source_copy"], data["source_map"], pins)
    original.require(
        proof["status"]
        == "VERIFIED_ONE_CURRENT_SOURCE_CONDITIONAL_FORECAST_NEW_HELPER_ONLY"
        and set(proof["comparisons"]) == COMPARISONS
        and all(v is True for v in proof["comparisons"].values())
        and proof["account_replay"] is False
        and proof["base_fits"] == proof["provider_calls"] == 0
        and proof["original_full_run_timing"] == "FAILED_UNCHANGED"
        and proof["all_history_acceptance"] == "UNVERIFIED"
        and proof["publication_barrier"] == "CLOSED"
        and proof["receipt"] == receipt
        and proof["generic_cycle_binding"]
        == "UNVERIFIED_SEPARATE_INTEGRATION_REQUIRED",
        "Exact bounded retained proof required",
    )
    original.require(
        receipt["schema"] == "conditional-current-model-forecast/1"
        and receipt["helper_sha256"] == HELPER
        and receipt["current_source"] == original.CURRENT_SOURCE
        and receipt["current_config_sha256"] == original.CURRENT_CONFIG
        and receipt["current_release_sha256"] == original.CURRENT_RELEASE
        and receipt["economic_evidence_sha256"] == original.ECONOMIC_EVIDENCE
        and receipt["source31_map_sha256"] == original.SOURCE_MAP
        and receipt["expected_native_image"] == original.CURRENT_IMAGE
        and receipt["continuation_sha256"] == original.CONTINUATION
        and receipt["availability_is_assumed"] is True
        and receipt["actual_live_inference_receipt"] is False
        and receipt["historical_actual_receive_publication_inference"] is None
        and receipt["base_models_fitted"] == 0
        and receipt["publication_barrier"] == "CLOSED"
        and receipt["generic_cycle_binding"]
        == "UNVERIFIED_SEPARATE_INTEGRATION_REQUIRED"
        and receipt["origin"]
        == "ARCHIVED_RAW_INPUT_WITH_DECLARED_HISTORICAL_AVAILABILITY"
        and receipt["prior_sha256"] == proof["prior_provenance_sha256"] == pins.prior
        and receipt["raw_source_sha256"] == pins.raw_source,
        "Current conditional source/profile/provenance differs",
    )
    for name, raw in (
        ("derived-receipt.bin", bodies["receipt"]),
        ("derived-arrays.npz", bodies["arrays"]),
    ):
        item = proof["retained_result"][name]
        original.require(
            item == {"sha256": sha256(raw).hexdigest(), "bytes": len(raw)},
            "Retained archive descriptor differs",
        )
    original.require(
        proof["retained_result"]["scope"] == "ONE_AAPL_RETAINED_RESULT",
        "Retained scope differs",
    )
    current = learned_live_holding.source_identity()
    original.require(
        len(current) == 31
        and sha256(
            json.dumps(current, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == original.SOURCE_MAP
        and all(data["source_map"].get(k) == v for k, v in current.items())
        and receipt["native_sources"] == forward._inference_sources()
        and receipt["model_sources"] == original.inference._sources()
        and receipt["model_receipt_sha256"]
        == original.TIMING_FILES["model/publication.json"]
        and receipt["residual_receipt_sha256"]
        == original.TIMING_FILES["residual/residuals.json"]
        and receipt["actual_residual_publication"]["residual_artifact"]["sha256"]
        == original.TIMING_FILES["residual/residuals.npz"],
        "Actual shared source/current31 differs",
    )
    original.authenticate(Path(original.__file__), HELPER)
    start, admitted, end = (
        _clock(receipt[n])
        for n in (
            "actual_compute_started_at",
            "actual_model_admission_at",
            "actual_compute_finished_at",
        )
    )
    original.require(
        _clock(data["runtime"]["state"]["StartedAt"])
        <= start
        <= admitted
        <= end
        <= _clock(data["runtime"]["state"]["FinishedAt"])
        and receipt["actual_elapsed_ns"] > 0
        and start > _clock(receipt["hypothetical_window"]["quote_end"])
        and all(
            _clock(receipt[n]["published_at"]) <= admitted
            for n in ("actual_model_publication", "actual_residual_publication")
        ),
        "Actual publication/computation clocks differ",
    )
    values = _arrays(bodies["arrays"])
    rows = _result(receipt, proof, values, context, requested)
    prior = data["prior"]
    observed_identity = receipt["native_observation"]["identity"]
    original.require(
        prior["schema"] == "conditional-full-prior/1"
        and prior["session"] == "2019-03-01"
        and prior["symbols"] == receipt["symbols"]
        and prior["historical_as_published"] is False
        and all(
            prior["arrays"][k] == observed_identity[v]
            for k, v in (
                ("dates", "prior_dates"),
                ("adj_close", "prior_prices"),
                ("grades", "prior_grades"),
                ("eligible", "prior_eligible"),
            )
        )
        and all(
            data["source_map"].get(k) == v
            for k, v in observed_identity["sources"].items()
        ),
        "Original prior context differs",
    )
    binding = original.encoded(
        {
            "schema": "retained-conditional-forecast-binding/1",
            "origin": "ONE_AAPL_RETAINED_RESULT",
            "files": {n: getattr(pins, n) for n in filenames},
            "context_sha256": context.sha256,
            "actual_live_inference_receipt": False,
            "publication_barrier": "CLOSED",
            "generic_cycle_binding": "UNVERIFIED_SEPARATE_INTEGRATION_REQUIRED",
            "reader_samples": {
                "residuals": sha256(
                    rows[receipt["symbols"].index("AAPL")][1][2].tobytes()
                ).hexdigest(),
                "weights": sha256(
                    rows[receipt["symbols"].index("AAPL")][1][3].tobytes()
                ).hexdigest(),
            },
        }
    )
    result = object.__new__(RetainedForecast)
    for name, value in (
        ("receipt", bodies["receipt"]),
        ("binding", binding),
        ("features", values["features"]),
        ("valid", values["valid"]),
        ("_values", rows),
    ):
        object.__setattr__(result, name, value)
    return result


# Preserve source-aware anchor evidence separately from the legacy four-field rows.
@dataclass(frozen=True, slots=True, init=False)
class AnchorBinding:
    raw: bytes
    legacy: market.Anchors

    # Only same-parquet extraction may produce a source-aware anchor binding.
    def __new__(cls):
        raise TypeError("Use bind_raw_anchors with original raw source files")


# Bind the unique consumed opening to the same original parquet and completed prefix.
def bind_raw_anchors(retained, context, raw_path, raw_source_path):
    original.require(
        type(retained) is RetainedForecast, "Admitted retained forecast required"
    )
    binding, receipt = _json(retained.binding), _json(retained.receipt)
    ctx = market.read_context(context)
    original.require(
        context.sha256 == binding["context_sha256"], "Original anchor context differs"
    )
    source = _json(_read(raw_source_path, binding["files"]["raw_source"]))["AAPL"]
    original.require(
        set(receipt["raw_files"]) == {RAW_KEY}
        and receipt["raw_files"][RAW_KEY] == source["sha256"],
        "Same forecast raw parquet required",
    )
    raw = _read(raw_path, source["sha256"], RAW_CAP)
    original.require(len(raw) == source["bytes"], "Raw source byte count differs")
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(io.BytesIO(raw))
    original.require(
        parquet.metadata.num_rows <= 128
        and sum(
            parquet.metadata.row_group(i).total_byte_size
            for i in range(parquet.metadata.num_row_groups)
        )
        <= RAW_CAP,
        "Raw parquet expansion cap: PAUSE",
    )
    table = parquet.read(
        columns=["start", "open", "high", "low", "close", "volume"], use_threads=False
    )
    meta = {k.decode(): v.decode() for k, v in (table.schema.metadata or {}).items()}
    original.require(
        meta == source["metadata"]
        and all(
            meta.get(k) == v
            for k, v in {
                "ticker": "AAPL",
                "session_date": "2019-03-01",
                "kind": intraday_sip.KIND,
                "feed": "sip",
                "adjustment": "raw",
                "timeframe": "15Min",
            }.items()
        ),
        "Original raw SIP identity differs",
    )
    columns = table.to_pydict()
    completed = _clock(ctx["window"]["completed_at"])
    starts = [_clock(v) for v in columns["start"]]
    required = [completed - timedelta(minutes=15)]
    original.require(
        [t for t in starts if required[0] <= t <= completed] == required + [completed],
        "Unique exact raw prefix/opening rows required",
    )
    rows = [starts.index(t) for t in required]
    original.require(
        all(starts[i] < completed for i in rows), "Only completed prefix rows required"
    )
    identity = receipt["native_observation"]["identity"]["prefixes"]["AAPL"]
    typed = {
        name: _hash(np.array([columns[name][i] for i in rows], dtype=np.float64))
        for name in ("open", "high", "low", "close", "volume")
    }
    typed["starts"] = _hash(
        np.array([t.replace(tzinfo=None) for t in required], dtype="datetime64[ns]")
    )
    original.require(
        all(identity.get(k) == v for k, v in typed.items())
        and _clock(identity["published_at"])
        == _clock(ctx["window"]["assumed_bar_available_at"]),
        "Original implicit685 completed-prefix extraction differs",
    )
    index = starts.index(completed)
    price = columns["open"][index]
    original.require(
        type(price) in (float, int) and math.isfinite(price) and price > 0,
        "Positive consumed raw opening required",
    )
    row = original.encoded(
        {
            "symbol": "AAPL",
            "at": ctx["window"]["completed_at"],
            "open": price,
            "basis": "raw_current_shares",
        }
    )
    ref = sha256(row).hexdigest()
    legacy_raw = original.encoded(
        {
            "schema": "conditional-raw-anchors/1",
            "origin": "PINNED_RAW_ROWS_NOT_PROVIDER_PROOF",
            "completed_at": ctx["window"]["completed_at"],
            "references": {"AAPL": ref},
        }
    )
    legacy = market.anchors(legacy_raw, sha256(legacy_raw).hexdigest(), {ref: row})
    outer = original.encoded(
        {
            "schema": "source-aware-retained-anchor-binding/1",
            "forecast_binding_sha256": sha256(retained.binding).hexdigest(),
            "raw_parquet_sha256": source["sha256"],
            "raw_source_sha256": binding["files"]["raw_source"],
            "legacy_anchor_sha256": legacy.sha256,
            "original_raw_row_index": index,
            "prefix_rule": (
                "685_NATIVE_FIRST_COMPLETED_REGULAR_PREFIX_NOT_RETAINED_PER_ROW_HASH"
            ),
            "rechecked_prefix_hashes": typed,
            "consumed_open_not_fill": True,
            "actual_historical_publication": None,
            "provider_or_issuer_identity": "NOT_PROVED",
        }
    )
    result = object.__new__(AnchorBinding)
    object.__setattr__(result, "raw", outer)
    object.__setattr__(result, "legacy", legacy)
    return result
