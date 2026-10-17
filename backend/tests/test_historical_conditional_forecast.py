"""Pure admission and clock-domain tests use no actual model or market account."""

import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import historical_conditional_forecast as forecast


# Retain a synthetic external byte identity rather than passing loose model arrays.
def evidence(value):
    raw = forecast.encoded(value)
    return forecast.Evidence(raw, sha256(raw).hexdigest())


# Supply only the relevant preregistered historical clocks to the pure unit path.
def window():
    return forecast.historical_timing_packet.schedule("2019-03-01T14:45:00Z")


# Construct a labelled synthetic fixture through private allocation only.
def prior():
    years, exchange = forecast.calendar.reviewed_sessions()
    dates = np.arange(np.datetime64("2015-01-02"), np.datetime64("2019-03-01"))
    dates = dates[np.is_busday(dates, busdaycal=exchange)]
    assert years
    names = ("AAPL", "SPY", "QQQ", *(f"S{number}" for number in range(93)))
    prices = np.repeat((100 + np.arange(len(dates)) * 0.01)[:, None], 96, axis=1)
    values = {
        "dates": forecast.frozen_array(dates),
        "adj_close": forecast.frozen_array(prices),
        "grades": forecast.frozen_array(np.full(prices.shape, 2, dtype=np.int16)),
        "eligible": forecast.frozen_array(np.ones(prices.shape, dtype=bool)),
        "raw_prior_close": forecast.frozen_array(np.full(96, 100.0)),
    }
    result = object.__new__(forecast.Prior)
    for name, value in {
        **values,
        "tickers": names,
        "provenance": forecast.encoded(
            {
                "session": "2019-03-01",
                "symbols": names,
                "files": {},
                "arrays": {
                    name: forecast._hash(value) for name, value in values.items()
                },
            }
        ),
    }.items():
        object.__setattr__(result, name, value)
    return result


# Supply a fake transport/parser only; native feature extraction remains unmodified.
def raw_prefix(tmp_path, monkeypatch):
    path = tmp_path / "bars_15m_sip/asof=2019-03-01/AAPL.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic parser fixture")
    first = datetime(2019, 3, 1, 9, 30, tzinfo=forecast.calendar.NEW_YORK)
    bars = [
        SimpleNamespace(
            start=first + timedelta(minutes=15 * i),
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=1000.0,
        )
        for i in range(3)
    ]
    monkeypatch.setattr(
        forecast.intraday_sip,
        "read_session_full",
        lambda *args: (
            bars,
            None,
            {
                "complete": "true",
                "ticker": "AAPL",
                "session_date": "2019-03-01",
                "kind": "bars_15m_sip",
                "feed": "sip",
            },
        ),
    )
    return evidence({"AAPL": {"sha256": sha256(path.read_bytes()).hexdigest()}}), path


# Original input bytes cannot be mutated, ambiguously parsed, or renamed.
@pytest.mark.parametrize(
    "raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}']
)
def test_strict_external_evidence(raw):
    with pytest.raises(ValueError, match="Duplicate|Nonfinite"):
        forecast.Evidence(raw, sha256(raw).hexdigest())


# A changed external digest fails before metadata can be interpreted.
def test_evidence_requires_immutable_external_identity():
    with pytest.raises(ValueError, match="digest"):
        forecast.Evidence(b"{}", "0" * 64)
    with pytest.raises(ValueError, match="immutable"):
        forecast.Evidence(bytearray(b"{}"), sha256(b"{}").hexdigest())
    item = evidence({"source": "synthetic"})
    with pytest.raises(FrozenInstanceError):
        item.raw = b"{}"


# Byte-backed arrays cannot regain write permission or observe later caller mutations.
def test_arrays_have_immutable_bytes_bases():
    original = np.array([[1.0, np.nan]], dtype=np.float32)
    frozen = forecast.frozen_array(original)
    original[0, 0] = 999.0
    assert frozen[0, 0] == 1.0
    assert np.isnan(frozen[0, 1])
    with pytest.raises(ValueError, match="WRITEABLE"):
        frozen.flags.writeable = True
    with pytest.raises(ValueError, match="non-object"):
        forecast.frozen_array(np.array([object()], dtype=object))


# Public constructors cannot turn caller-provided expected hashes into admitted arrays.
@pytest.mark.parametrize(
    "kind", [forecast.Prior, forecast.AdmittedTiming, forecast.ConditionalForecast]
)
def test_only_loader_can_construct_admitted_handles(kind):
    with pytest.raises(TypeError):
        kind(provenance=b"{}")


# Every changed historical availability assumption fails instead of becoming a sweep.
@pytest.mark.parametrize(
    "name",
    [
        "assumed_bar_available_at",
        "assumed_forecast_available_at",
        "assumed_decision_at",
        "assumed_submission_at",
        "assumed_arrival_at",
        "quote_end",
    ],
)
def test_fixed_availability_is_not_a_tunable_parameter(name):
    value = window()
    value[name] = (
        datetime.fromisoformat(value[name]) + timedelta(milliseconds=1)
    ).isoformat()
    with pytest.raises(ValueError, match="availability"):
        forecast.conditional_window(value)


# Naive or nonboundary times cannot silently change the feature observation window.
@pytest.mark.parametrize(
    "value",
    [
        "2019-03-01T14:45:00",
        "2019-03-01T14:45:00.000001+00:00",
        "2019-03-01T14:46:00+00:00",
    ],
)
def test_exact_aware_window_boundary_required(value):
    changed = window()
    changed["completed_at"] = value
    with pytest.raises(ValueError, match="boundary|timestamp"):
        forecast.conditional_window(changed)


# Extra schedule claims cannot masquerade as preregistered assumptions.
def test_full_schedule_disallows_extra_fields():
    changed = {**window(), "extra_clock": "2019-03-01T14:45:32Z"}
    with pytest.raises(ValueError, match="schedule"):
        forecast.conditional_window(changed)


# An admitted model file's changed bytes fail before native configuration admission.
def test_admitted_file_mutation_is_rechecked(tmp_path, monkeypatch):
    path = tmp_path / "models.npz"
    path.write_bytes(b"declared synthetic model")
    model = object.__new__(forecast.AdmittedTiming)
    object.__setattr__(
        model,
        "files",
        forecast.encoded({str(path): sha256(path.read_bytes()).hexdigest()}),
    )
    calls = []
    monkeypatch.setattr(
        forecast.learned_live_holding,
        "read_configuration",
        lambda *args: calls.append(args),
    )
    path.write_bytes(b"changed synthetic model")
    with pytest.raises(ValueError, match="bytes differ"):
        model.validate()
    assert calls == []


# Causal context revalidation rejects changed source bytes, arrays and cohort order.
@pytest.mark.parametrize("kind", ["source", "array", "cohort"])
def test_prior_revalidates_independent_identity(tmp_path, kind):
    context = prior()
    if kind == "source":
        path = tmp_path / "prior.parquet"
        path.write_bytes(b"prior source")
        metadata = forecast.decoded(context.provenance)
        metadata["files"] = {str(path): sha256(path.read_bytes()).hexdigest()}
        object.__setattr__(context, "provenance", forecast.encoded(metadata))
        path.write_bytes(b"changed prior source")
    elif kind == "array":
        object.__setattr__(
            context,
            "adj_close",
            forecast.frozen_array(np.zeros_like(context.adj_close)),
        )
    else:
        object.__setattr__(context, "tickers", tuple(reversed(context.tickers)))
    with pytest.raises(ValueError, match="bytes differ|array changed|cohort changed"):
        context.validate()


# Loader paths detect changed bytes, oversized metadata, symlinks and missing files.
@pytest.mark.parametrize("route", ["changed", "symlink", "missing", "large"])
def test_local_source_admission_is_bounded(tmp_path, monkeypatch, route):
    path = tmp_path / "source.json"
    path.write_bytes(b"{}")
    expected = sha256(b"{}").hexdigest()
    if route == "changed":
        path.write_bytes(b"[]")
    elif route == "symlink":
        original = tmp_path / "original.json"
        path.rename(original)
        path.symlink_to(original)
    elif route == "missing":
        path.unlink()
    else:
        monkeypatch.setattr(forecast, "META_CAP", 1)
    with pytest.raises((ValueError, FileNotFoundError)):
        forecast.metadata(path, expected)


# Exact current continuation pins cannot be replaced by old or fabricated approvals.
def test_current_approval_cannot_accept_an_unreviewed_continuation(tmp_path):
    item = evidence({"not": "current reviewed continuation"})
    with pytest.raises(ValueError, match="current metadata continuation"):
        forecast.admit(tmp_path, tmp_path, tmp_path, item, item)


# A direct request for an old or future session fails before any file allocation.
@pytest.mark.parametrize("session", ["2019-02-28", "2026-10-13", "2019-3-1"])
def test_prior_loader_has_fixed_account_bounds(tmp_path, session):
    with pytest.raises(ValueError, match="outside contract|Invalid isoformat"):
        forecast.load_prior(tmp_path, tmp_path, session)


# Extraction consumes exactly completed bars; a later forming bar never supplies values.
def test_prefix_extraction_drops_future_bars(tmp_path, monkeypatch):
    source, _ = raw_prefix(tmp_path, monkeypatch)
    result, files = forecast.prefixes(prior(), tmp_path, source, ("AAPL",), window())
    assert len(result["AAPL"]["open"]) == 1
    assert result["AAPL"]["starts"] == ["2019-03-01T09:30:00-05:00"]
    assert result["AAPL"]["published_at"] == window()["assumed_bar_available_at"]
    assert len(files) == 1
    with pytest.raises(ValueError, match="read-only"):
        result["AAPL"]["open"][0] = 12.0


# Later-session incompleteness cannot erase an already completed earlier prefix.
def test_prefix_does_not_consume_later_session_completeness(tmp_path, monkeypatch):
    source, _ = raw_prefix(tmp_path, monkeypatch)
    original = forecast.intraday_sip.read_session_full

    # Change only the future full-session flag while preserving the first raw bar.
    def incomplete(*args):
        rows, auction, metadata = original(*args)
        return rows[:1], auction, {**metadata, "complete": "false"}

    monkeypatch.setattr(forecast.intraday_sip, "read_session_full", incomplete)
    result, _ = forecast.prefixes(prior(), tmp_path, source, ("AAPL",), window())
    assert "AAPL" in result
    assert len(result["AAPL"]["close"]) == 1


# Due-symbol missingness must be explicitly pinned, not inferred from absent requests.
def test_due_symbol_source_must_be_declared(tmp_path, monkeypatch):
    source, _ = raw_prefix(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="source missing"):
        forecast.prefixes(prior(), tmp_path, source, ("S0",), window())
    with pytest.raises(ValueError, match="unique"):
        forecast.prefixes(prior(), tmp_path, source, ("AAPL", "AAPL"), window())


# Declared absent prefixes stay absent and cannot use a later source file fallback.
def test_explicit_missing_prefix_is_preserved(tmp_path):
    source = evidence({"AAPL": {"sha256": None, "status": "missing"}})
    result, files = forecast.prefixes(prior(), tmp_path, source, ("AAPL",), window())
    assert result == {}
    assert list(files.values()) == [None]
    path = next(iter(files))
    Path(path).parent.mkdir(parents=True)
    Path(path).write_bytes(b"later observation")
    with pytest.raises(ValueError, match="missing raw source"):
        forecast.prefixes(prior(), tmp_path, source, ("AAPL",), window())


# Exercise real native features while replacing only numerical artifact I/O/inference.
@pytest.fixture
def synthetic_inference(tmp_path, monkeypatch):
    model = object.__new__(forecast.AdmittedTiming)
    object.__setattr__(model, "artifact_root", tmp_path)
    object.__setattr__(model, "continuation", evidence({"fixture": "continuation"}))
    object.__setattr__(model, "delivery", evidence({"fixture": "delivery"}))
    calls = []
    monkeypatch.setattr(
        forecast.AdmittedTiming, "validate", lambda self: calls.append("admission")
    )
    residual = SimpleNamespace(
        receipt={"identity": {"published_at": "2026-10-04T00:00:00+00:00"}}
    )
    monkeypatch.setattr(
        forecast.forward, "load_residual_month", lambda *args, **kwargs: residual
    )
    monkeypatch.setattr(
        forecast.forward,
        "_validate_residual_month",
        lambda *args: calls.append("residual-final"),
    )
    monkeypatch.setattr(
        forecast,
        "metadata",
        lambda *args: evidence(
            {"identity": {"published_at": "2026-10-04T00:00:00+00:00"}}
        ),
    )

    # Record actual admission time without allowing a public historical-clock override.
    def distributions(*args, **kwargs):
        calls.append(kwargs)
        result = dict.fromkeys(kwargs["symbols"])
        if kwargs["timing_supported"] and kwargs["valid"][0]:
            result["AAPL"] = forecast.probability.Distribution(
                0.0001, 0.01, np.array([-0.1, 0.1]), np.array([0.5, 0.5])
            )
        return result

    monkeypatch.setattr(forecast.inference, "current_distributions", distributions)
    source, _ = raw_prefix(tmp_path, monkeypatch)
    return model, prior(), source, calls


# Native feature values and model admission keep historical and actual clocks separate.
def test_real_features_and_outer_receipt_clock_domains(tmp_path, synthetic_inference):
    model, context, source, calls = synthetic_inference
    begin = datetime.now(UTC)
    result = forecast.infer(model, context, tmp_path, source, ("AAPL",), window())
    end = datetime.now(UTC)
    receipt = forecast.decoded(result.receipt)
    observed = next(value for value in calls if isinstance(value, dict))["observed_at"]
    assert begin <= observed <= end
    assert observed.year != 2019
    assert receipt["native_observation"]["observed_at"].startswith("2019-03-01")
    assert result.features.shape == (96, 21)
    assert result.valid.sum() == 1
    assert receipt["historical_actual_receive_publication_inference"] is None
    assert receipt["actual_live_inference_receipt"] is False
    assert "inference" not in receipt
    assert receipt["generic_cycle_binding"].startswith("UNVERIFIED")
    assert calls.count("admission") == 2
    assert calls.count("residual-final") == 1
    detached = result.distributions()
    assert detached["SPY"] is None
    assert detached["QQQ"] is None
    with pytest.raises(ValueError, match="WRITEABLE"):
        detached["AAPL"].residuals.flags.writeable = True
    detached["AAPL"] = None
    assert result.distributions()["AAPL"] is not None


# Empty explicit prefixes retain native unavailable forecasts.
def test_missing_native_features_remain_unavailable(tmp_path, synthetic_inference):
    model, context, _, _ = synthetic_inference
    source = evidence({"S0": {"sha256": None, "status": "missing"}})
    result = forecast.infer(model, context, tmp_path, source, ("S0",), window())
    assert not result.valid.any()
    assert all(value is None for value in result.distributions().values())


# No public method accepts a caller's replacement for the actual computation clock.
def test_no_public_actual_clock_override():
    assert "clock" not in inspect.signature(forecast.infer).parameters
    assert "actual_clock" not in inspect.signature(forecast.infer).parameters
    assert "clock" not in inspect.signature(forecast.admit).parameters
