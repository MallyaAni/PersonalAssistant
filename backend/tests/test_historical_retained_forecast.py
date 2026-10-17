"""Synthetic external-proof fixtures; no models, provider or account are called.

These exercise retained-byte admission, not genuine runtime authentication.
The separately retained native acceptance must use the original pinned v2 bytes.
"""

import io
import json
import zipfile
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import historical_retained_forecast as bridge


# Hash exactly the supplied bytes without interpreting or normalizing the input.
def digest(raw):
    return sha256(raw).hexdigest()


# Serialize explicitly synthetic small arrays into the same four-member container.
def archive(values):
    output = io.BytesIO()
    np.savez_compressed(output, **values)
    return output.getvalue()


# Encode raw synthetic rows with the original SIP parquet column/metadata layout.
def parquet(rows, metadata):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({k: [r[k] for r in rows] for k in rows[0]})
    table = table.replace_schema_metadata(
        {k.encode(): v.encode() for k, v in metadata.items()}
    )
    output = io.BytesIO()
    pq.write_table(table, output)
    return output.getvalue()


# Commit changed synthetic fixture bytes and independently declare their new pins.
def seal(f):
    encoded = bridge.original.encoded
    image_sha = digest(encoded(f.image_map))
    f.copied["source_map_sha256"] = image_sha
    f.proof["source_before_after"]["image_source_map_sha256"] = image_sha
    raw = f.raw_source["AAPL"]
    raw.update(sha256=digest(f.parquet), bytes=len(f.parquet))
    f.receipt["raw_files"] = {bridge.RAW_KEY: raw["sha256"]}
    prior_raw, source_raw = encoded(f.prior), encoded(f.raw_source)
    f.receipt.update(
        prior_sha256=digest(prior_raw), raw_source_sha256=digest(source_raw)
    )
    f.proof["prior_provenance_sha256"] = digest(prior_raw)
    receipt_raw, arrays_raw = encoded(f.receipt), archive(f.values)
    f.proof["receipt"] = f.receipt
    f.proof["retained_result"] = {
        "scope": "ONE_AAPL_RETAINED_RESULT",
        "derived-receipt.bin": {
            "sha256": digest(receipt_raw),
            "bytes": len(receipt_raw),
        },
        "derived-arrays.npz": {"sha256": digest(arrays_raw), "bytes": len(arrays_raw)},
    }
    proof_raw = encoded(f.proof)
    f.runtime["file_sha256"] = {
        "out/proof.json": digest(proof_raw),
        "out/derived-receipt.bin": digest(receipt_raw),
        "out/derived-arrays.npz": digest(arrays_raw),
        "out/prior-provenance.json": digest(prior_raw),
    }
    bodies = {
        "proof.json": proof_raw,
        "runtime-proof.json": encoded(f.runtime),
        "derived-receipt.bin": receipt_raw,
        "derived-arrays.npz": arrays_raw,
        "prior-provenance.json": prior_raw,
        "image-provenance-proof.json": encoded(f.copied),
        "image-source-map.json": encoded(f.image_map),
        "raw-bars.json": source_raw,
    }
    for name, body in bodies.items():
        (f.root / name).write_bytes(body)
    f.raw_path.write_bytes(f.parquet)
    f.pins = bridge.Pins(
        *(
            digest(bodies[name])
            for name in (
                "proof.json",
                "runtime-proof.json",
                "derived-receipt.bin",
                "derived-arrays.npz",
                "prior-provenance.json",
                "image-provenance-proof.json",
                "image-source-map.json",
                "raw-bars.json",
            )
        )
    )
    return f


# Declare a tiny synthetic bundle while requiring actual unchanged current sources.
@pytest.fixture
def bundle(tmp_path):
    current = bridge.learned_live_holding.source_identity()
    if (
        digest(json.dumps(current, sort_keys=True, separators=(",", ":")).encode())
        != bridge.original.SOURCE_MAP
    ):
        pytest.skip(
            "Positive fixture needs current3b72 sources; skip is not verification"
        )
    symbols = (
        "AAPL",
        "SPY",
        "QQQ",
        *("X" + chr(65 + i // 26) + chr(65 + i % 26) for i in range(93)),
    )
    window = bridge.packet.schedule("2019-03-01T14:45:00Z")
    context = bridge.market.context(
        window["completed_at"],
        symbols,
        cohort_sha256=bridge.packet._digest(list(symbols)),
    )
    values = {
        "features": np.full((96, 21), np.nan, dtype=np.float32),
        "valid": np.array([True] + [False] * 95),
        "AAPL_residuals": np.array([-1, 0, 1, 2], dtype=np.float64),
        "AAPL_weights": np.array([1e-200, 1, 2, 3], dtype=np.float64),
    }
    values["features"][0] = np.arange(21, dtype=np.float32)
    rows = [
        {
            "start": "2019-03-01T14:30:00+00:00",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000.0,
        },
        {
            "start": "2019-03-01T14:45:00+00:00",
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 102.0,
            "volume": 500.0,
        },
    ]
    metadata = {
        "ticker": "AAPL",
        "session_date": "2019-03-01",
        "kind": "bars_15m_sip",
        "feed": "sip",
        "adjustment": "raw",
        "timeframe": "15Min",
    }
    prefix = {
        k: bridge._hash(np.array([rows[0][k]], dtype=np.float64))
        for k in ("open", "high", "low", "close", "volume")
    }
    prefix.update(
        starts=bridge._hash(np.array(["2019-03-01T14:30:00"], dtype="datetime64[ns]")),
        published_at="2019-03-01T09:45:30-05:00",
        prior_close="a" * 64,
    )
    distribution = bridge.probability.Distribution(
        0.01, 0.02, values["AAPL_residuals"], values["AAPL_weights"]
    )
    native_sources = bridge.forward._inference_sources()
    image_map = {**bridge.original.inference._sources(), **native_sources, **current}
    while len(image_map) < 1655:
        image_map[f"backend/synthetic_fixture/{len(image_map)}.py"] = "a" * 64
    prior_arrays = {k: "a" * 64 for k in ("dates", "adj_close", "grades", "eligible")}
    receipt = {
        "schema": "conditional-current-model-forecast/1",
        "helper_sha256": bridge.HELPER,
        "origin": "ARCHIVED_RAW_INPUT_WITH_DECLARED_HISTORICAL_AVAILABILITY",
        "current_source": bridge.original.CURRENT_SOURCE,
        "expected_native_image": bridge.original.CURRENT_IMAGE,
        "source31_map_sha256": bridge.original.SOURCE_MAP,
        "current_config_sha256": bridge.original.CURRENT_CONFIG,
        "current_release_sha256": bridge.original.CURRENT_RELEASE,
        "economic_evidence_sha256": bridge.original.ECONOMIC_EVIDENCE,
        "continuation_sha256": bridge.original.CONTINUATION,
        "availability_is_assumed": True,
        "actual_live_inference_receipt": False,
        "historical_actual_receive_publication_inference": None,
        "base_models_fitted": 0,
        "publication_barrier": "CLOSED",
        "generic_cycle_binding": "UNVERIFIED_SEPARATE_INTEGRATION_REQUIRED",
        "symbols": list(symbols),
        "requested_symbols": ["AAPL"],
        "feature_names": list(
            bridge.original.forward_entry_features.original.FEATURE_NAMES
        ),
        "features_sha256": bridge._hash(values["features"]),
        "valid_sha256": bridge._hash(values["valid"]),
        "native_distributions": bridge.forward._forecast_identity(
            {n: distribution if n == "AAPL" else None for n in symbols}
        ),
        "native_sources": native_sources,
        "model_sources": bridge.original.inference._sources(),
        "hypothetical_window": window,
        "hypothetical_daily_available_at": "2019-02-28T16:01:00-05:00",
        "native_observation": {
            "clock": 0,
            "timing_supported": True,
            "completed_at": "2019-03-01T09:45:00-05:00",
            "observed_at": "2019-03-01T09:45:31.100000-05:00",
            "daily_as_of": "2019-02-28T16:01:00-05:00",
            "identity": {
                "prefixes": {"AAPL": prefix},
                "sources": native_sources,
                **{
                    v: prior_arrays[k]
                    for k, v in (
                        ("dates", "prior_dates"),
                        ("adj_close", "prior_prices"),
                        ("grades", "prior_grades"),
                        ("eligible", "prior_eligible"),
                    )
                },
            },
        },
        "model_receipt_sha256": bridge.original.TIMING_FILES["model/publication.json"],
        "residual_receipt_sha256": bridge.original.TIMING_FILES[
            "residual/residuals.json"
        ],
        "actual_model_publication": {"published_at": "2026-10-05T16:00:00Z"},
        "actual_residual_publication": {
            "published_at": "2026-10-06T16:00:00Z",
            "residual_artifact": {
                "sha256": bridge.original.TIMING_FILES["residual/residuals.npz"]
            },
        },
        "actual_compute_started_at": "2026-10-17T16:00:01Z",
        "actual_model_admission_at": "2026-10-17T16:00:01.1Z",
        "actual_compute_finished_at": "2026-10-17T16:00:01.2Z",
        "actual_elapsed_ns": 200000000,
    }
    proof = {
        "status": "VERIFIED_ONE_CURRENT_SOURCE_CONDITIONAL_FORECAST_NEW_HELPER_ONLY",
        "comparisons": dict.fromkeys(bridge.COMPARISONS, True),
        "account_replay": False,
        "base_fits": 0,
        "provider_calls": 0,
        "all_history_acceptance": "UNVERIFIED",
        "original_full_run_timing": "FAILED_UNCHANGED",
        "publication_barrier": "CLOSED",
        "generic_cycle_binding": "UNVERIFIED_SEPARATE_INTEGRATION_REQUIRED",
        "residual_rows": 4,
        "feature_row": values["features"][0].tolist(),
        "distribution_mean": 0.01,
        "distribution_scale": 0.02,
        "source_before_after": {
            "helper_sha256": bridge.HELPER,
            "image_source_files": 1655,
            "private_permissions_only": True,
            "whole_backend_readonly_overlay": True,
        },
        "native_packages": {
            n: {
                "version": v,
                "sha256": h,
                "path": f"/usr/local/lib/python3.12/site-packages/{n}/__init__.py",
            }
            for n, (v, h) in bridge.PACKAGES.items()
        },
    }
    runtime = {
        "image": bridge.original.CURRENT_IMAGE,
        "user": "1000:1000",
        "container_id": "a" * 64,
        "state": {
            "Status": "exited",
            "ExitCode": 0,
            "OOMKilled": False,
            "Running": False,
            "StartedAt": "2026-10-17T16:00:00Z",
            "FinishedAt": "2026-10-17T16:00:02Z",
        },
        "runtime": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "NanoCpus": 1000000000,
            "Memory": 2147483648,
            "MemorySwap": 2147483648,
            "Tmpfs": {"/tmp": "rw,size=64m"},
        },
        "mounts": [
            {
                "Destination": p,
                "Source": "/source/backend"
                if p == "/app/backend"
                else "/source/" + p.rsplit("/", 1)[-1],
                "RW": p == "/out",
            }
            for p in (
                "/app/backend",
                "/app/docs",
                "/image-source-map.json",
                bridge.RAW_KEY,
                "/out",
            )
        ],
    }
    copied = {
        "status": "VERIFIED_READABLE_COPY_FROM_UNMOUNTED_IMMUTABLE_IMAGE",
        "recorded_before_after_bytes_equal": True,
        "native_stdout_equals_copied_map": True,
        "live_or_image_permission_changes": False,
        "current_physical_map_comparisons": {"/source": 1655},
        "extraction_container": {
            "image": bridge.original.CURRENT_IMAGE,
            "mounts": [],
            "state": {"Status": "created", "StartedAt": "0001-01-01T00:00:00Z"},
        },
        "unmounted_image_hash_container": {
            "image": bridge.original.CURRENT_IMAGE,
            "mounts": [],
            "network": "none",
            "readonly_root": True,
            "state": {"ExitCode": 0},
        },
    }
    return seal(
        SimpleNamespace(
            root=tmp_path,
            raw_path=tmp_path / "AAPL.parquet",
            context=context,
            receipt=receipt,
            values=values,
            proof=proof,
            runtime=runtime,
            copied=copied,
            image_map=image_map,
            prior={
                "schema": "conditional-full-prior/1",
                "session": "2019-03-01",
                "symbols": list(symbols),
                "historical_as_published": False,
                "arrays": prior_arrays,
            },
            raw_source={"AAPL": {"metadata": metadata}},
            rows=rows,
            metadata=metadata,
            parquet=parquet(rows, metadata),
        )
    )


# Admit the explicit synthetic fixture without treating its declarations as live proof.
def load(f, **kwargs):
    return bridge.read_retained(f.root, f.context, pins=f.pins, **kwargs)


# Preserve missing names, small positive weights, arrays and conditional clocks.
def test_retained_arithmetic_and_detachment(bundle, monkeypatch):
    # Any model call would invalidate the retained-only acceptance path.
    def forbidden(*args, **kwargs):
        raise AssertionError("Retained bridge must not call inference")

    monkeypatch.setattr(bridge.original, "infer", forbidden)
    monkeypatch.setattr(bridge.original.inference, "current_distributions", forbidden)
    monkeypatch.setattr(bridge.forward, "load_residual_month", forbidden)
    value = load(bundle)
    a, b = value.distributions(), value.distributions()
    assert a is not b
    assert a["AAPL"] is not b["AAPL"]
    assert a["SPY"] is a["QQQ"] is a["XAA"] is None
    assert a["AAPL"].weights[0] == 1e-200
    assert (
        bridge.forward._forecast_identity(a) == bundle.receipt["native_distributions"]
    )
    for array in (value.features, value.valid, a["AAPL"].weights, a["AAPL"].residuals):
        with pytest.raises(ValueError, match="WRITEABLE|writeable"):
            array.setflags(write=True)
    a["AAPL"] = None
    assert value.distributions()["AAPL"] is not None
    assert json.loads(value.receipt)["actual_live_inference_receipt"] is False


# External bytes are checked before interpreting even a syntactically valid replacement.
def test_original_external_pins_cannot_be_replaced(bundle):
    (bundle.root / "derived-receipt.bin").write_bytes(b"{}")
    with pytest.raises(ValueError, match="External retained bytes"):
        load(bundle)


# Every changed accepted-result field fails even under newly declared fixture byte pins.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_source", "a" * 40),
        ("current_config_sha256", "a" * 64),
        ("source31_map_sha256", "a" * 64),
        ("helper_sha256", "a" * 64),
        ("actual_live_inference_receipt", True),
        ("availability_is_assumed", False),
        ("publication_barrier", "OPEN"),
        ("requested_symbols", ["AAPL", "STX"]),
        ("actual_compute_finished_at", "2099-01-01T00:00:00Z"),
        ("actual_compute_started_at", "2019-03-01T14:45:31Z"),
        ("actual_model_admission_at", "2026-10-17T16:00:03Z"),
    ],
)
def test_receipt_corruption(bundle, field, value):
    bundle.receipt[field] = value
    seal(bundle)
    with pytest.raises(ValueError, match="differ|required"):
        load(bundle)


# A pinned runtime cannot self-assert writable sources, another image, or failed checks.
@pytest.mark.parametrize(
    "kind", ["image", "rw", "comparison", "copy", "package", "prior", "source"]
)
def test_runtime_source_and_prior_corruption(bundle, kind):
    if kind == "image":
        bundle.runtime["image"] = "sha256:" + "a" * 64
    elif kind == "rw":
        bundle.runtime["mounts"][0]["RW"] = True
    elif kind == "comparison":
        bundle.proof["comparisons"]["mean_scale_exact"] = False
    elif kind == "copy":
        bundle.copied["recorded_before_after_bytes_equal"] = False
    elif kind == "package":
        bundle.proof["native_packages"]["numpy"]["sha256"] = "a" * 64
    elif kind == "prior":
        bundle.prior["arrays"]["dates"] = "b" * 64
    else:
        bundle.image_map["backend/market/probabilistic_execution.py"] = "b" * 64
    seal(bundle)
    with pytest.raises(ValueError, match="differ|required"):
        load(bundle)


# Sample and frame corruption cannot be repaired through dtype casts or weight tuning.
@pytest.mark.parametrize(
    "kind",
    [
        "dtype",
        "shape",
        "negative",
        "zero",
        "nan",
        "overflow",
        "features",
        "valid",
        "horizon",
        "mean",
        "scale",
        "sample",
    ],
)
def test_array_and_forecast_corruption(bundle, kind):
    if kind == "dtype":
        bundle.values["AAPL_residuals"] = bundle.values["AAPL_residuals"].astype(
            np.float32
        )
    elif kind == "shape":
        bundle.values["features"] = np.zeros((95, 21), dtype=np.float32)
    elif kind in ("negative", "zero", "nan", "overflow"):
        bundle.values["AAPL_weights"][:] = {
            "negative": -1,
            "zero": 0,
            "nan": np.nan,
            "overflow": 1e308,
        }[kind]
    elif kind == "features":
        bundle.values["features"][0, 0] += 1
    elif kind == "valid":
        bundle.values["valid"][1] = True
    elif kind in ("horizon", "mean", "scale"):
        bundle.receipt["native_distributions"]["AAPL"][kind] = {
            "horizon": "later",
            "mean": 9,
            "scale": 0,
        }[kind]
    else:
        bundle.values["AAPL_residuals"][0] += 1
    seal(bundle)
    with pytest.raises(ValueError, match="differ|required"):
        load(bundle)


# Context order, native historical clocks and requested due names are exact bindings.
@pytest.mark.parametrize("kind", ["cohort", "window", "observed", "requested"])
def test_context_and_clock_corruption(bundle, kind):
    if kind == "cohort":
        bundle.receipt["symbols"][0:2] = reversed(bundle.receipt["symbols"][0:2])
    elif kind == "window":
        bundle.receipt["hypothetical_window"]["assumed_submission_at"] = (
            "2019-03-01T14:45:31.3Z"
        )
    elif kind == "observed":
        bundle.receipt["native_observation"]["observed_at"] = "2019-03-01T14:45:31.2Z"
    seal(bundle)
    with pytest.raises(ValueError, match="differ|required"):
        load(bundle, requested=("STX",) if kind == "requested" else ("AAPL",))


# The source-aware outer receipt leaves the legacy anchor row API exactly unchanged.
def test_raw_anchor_binding(bundle):
    result = bridge.bind_raw_anchors(
        load(bundle), bundle.context, bundle.raw_path, bundle.root / "raw-bars.json"
    )
    data = json.loads(result.raw)
    row = json.loads(result.legacy.sources[0][1])
    assert set(row) == {"symbol", "at", "open", "basis"}
    assert row["open"] == 101
    assert data["consumed_open_not_fill"] is True
    assert data["raw_parquet_sha256"] == digest(bundle.parquet)
    assert data["original_raw_row_index"] == 1
    assert data["actual_historical_publication"] is None


# Wrong, duplicate, missing or prefix-corrupt original rows never become an anchor.
@pytest.mark.parametrize(
    "kind", ["unbound", "duplicate", "missing", "misaligned", "prefix", "metadata"]
)
def test_raw_anchor_corruption(bundle, kind):
    value = load(bundle)
    if kind == "unbound":
        bundle.raw_path.write_bytes(b"different")
    else:
        if kind == "duplicate":
            bundle.rows.append(dict(bundle.rows[1]))
        elif kind == "missing":
            bundle.rows.pop()
        elif kind == "misaligned":
            bundle.rows[0]["start"] = "2019-03-01T14:30:01Z"
        elif kind == "prefix":
            bundle.rows[0]["close"] = 100
        else:
            bundle.metadata["adjustment"] = "all"
        bundle.parquet = parquet(bundle.rows, bundle.metadata)
        seal(bundle)
        value = load(bundle)
    with pytest.raises(ValueError, match="differ|required"):
        bridge.bind_raw_anchors(
            value, bundle.context, bundle.raw_path, bundle.root / "raw-bars.json"
        )


# JSON ambiguity and oversized files are rejected before semantic or ZIP expansion.
def test_duplicate_json_and_bounded_read(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        bridge._json(b'{"a":1,"a":2}')
    path = tmp_path / "source"
    path.write_bytes(b"a" * 9)
    with pytest.raises(ValueError, match="PAUSE"):
        bridge._read(path, digest(path.read_bytes()), cap=8)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="Regular conditional source"):
        bridge._read(link, digest(path.read_bytes()))


# ZIP names and declared expansion are checked before any NPY object can be loaded.
@pytest.mark.parametrize("kind", ["extra", "duplicate", "object", "expanded", "header"])
def test_npz_admission_before_allocation(kind):
    arrays = {
        "features": np.zeros((96, 21), dtype=np.float32),
        "valid": np.zeros(96, dtype=bool),
        "AAPL_residuals": np.ones(4),
        "AAPL_weights": np.ones(4),
    }
    if kind == "extra":
        arrays["extra"] = np.ones(1)
    elif kind == "object":
        arrays["AAPL_residuals"] = np.array([{}], dtype=object)
    elif kind == "expanded":
        arrays["features"] = np.zeros(bridge.CAP, dtype=np.float64)
    raw = archive(arrays)
    if kind in ("duplicate", "header"):
        output = io.BytesIO(raw)
        with zipfile.ZipFile(output, "a") as z:
            z.writestr(
                "valid.npy" if kind == "duplicate" else "../valid.npy", b"not an NPY"
            )
        raw = output.getvalue()
    with pytest.raises(ValueError, match="required"):
        bridge._arrays(raw)


# A caller cannot allocate an admitted result or source-aware anchor directly.
@pytest.mark.parametrize("kind", [bridge.RetainedForecast, bridge.AnchorBinding])
def test_admitted_handles_have_no_public_constructor(kind):
    with pytest.raises(TypeError):
        kind()


# Default genuine pins are distinct from every synthetic fixture declaration.
def test_genuine_pins_are_not_self_derived(bundle):
    with pytest.raises(ValueError, match="External retained bytes"):
        bridge.read_retained(bundle.root, bundle.context)
    with pytest.raises(ValueError, match="pins required"):
        replace(bridge.GENUINE, runtime="not-a-digest")
