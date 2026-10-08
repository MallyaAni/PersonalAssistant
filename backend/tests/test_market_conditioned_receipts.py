"""Saved calibration proof refuses changed dates, coefficients and uncertainty."""

import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from backend.cli import verify_joint_funded as verifier
from backend.cli.verify_joint_funded import MarketCalibrationVerifier
from backend.market import (
    joint_funded_accounts,
    probabilistic_execution,
    probabilistic_execution_saved,
)
from backend.market import market_conditioned_calibration as model
from backend.market.calendar import NEW_YORK, session_close
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.joint_funded_accounts import candidate_grid
from backend.market.joint_funded_policy import (
    MarketConditionedTimedFundedPolicy,
    RetainedMarketConditionedFundedPolicy,
)
from backend.market.live_execution_inputs import prepare
from backend.market.live_policy_replay import run_account
from backend.market.live_probability_timing import build_reader
from backend.tests import test_joint_probability_timing as journey
from backend.tests.test_joint_probability_timing import timing as timing
from backend.tests.test_live_policy_replay import fixture
from backend.tests.test_market_conditioned_calibration import evidence
from backend.tests.test_market_conditioned_holding import example as example
from backend.tests.test_market_conditioned_holding import reader as reader
from backend.tests.test_verify_actual_policy_timing import direct_data
from backend.tests.test_verify_joint_funded import save


# Align a genuine synthetic timing bank and four-stock raw execution fixture.
@pytest.fixture(scope="module")
def screen_inputs(reader):
    old, _, cubes = fixture(tuple(map(str, reader.dates)))
    columns = [0, 0, 1, 2]
    panel = replace(
        old,
        tickers=tuple(reader.symbols),
        **{
            name: getattr(old, name)[:, columns].copy()
            for name in ("open", "high", "low", "close", "adj_close", "volume")
        },
    )
    cubes["BBB"] = replace(cubes["AAA"], ticker="BBB")
    raw = prepare(
        panel,
        np.tile([3, 0, 0, 3], (len(reader.dates), 1)).astype(np.int16),
        np.tile([True, False, False, False], (len(reader.dates), 1)),
        cubes,
        dict.fromkeys(panel.tickers, ()),
        basis_as_of=str(reader.dates[-1]),
        complete_through=str(reader.dates[-1]),
        provenance={"origin": "synthetic_screen_driver"},
    )
    means = np.full((len(reader.dates), 23, 4), -0.02)
    means[:, 0] = 0.02
    args = {
        "dates": reader.dates,
        "symbols": tuple(reader.symbols),
        "means": means,
        "second_moments": means**2 + 0.01,
        "labels": means.copy(),
        "valid": np.ones_like(means, dtype=bool),
        "outcome_end_dates": reader.dates,
        "data_as_of": datetime.combine(
            reader.dates[-1].astype(object),
            session_close(reader.dates[-1].astype(object)),
            NEW_YORK,
        ),
        "horizon": probabilistic_execution.HORIZON,
    }
    calibrated = probabilistic_execution.calibrate(**args)
    timing = probabilistic_execution_saved.load_saved(
        **args,
        manifest=calibrated.manifest,
        saved_probability=calibrated.probability_positive,
        saved_quantiles=calibrated.quantiles,
    )
    return panel, raw, cubes, timing


# The fixed screen rejects missing timing before creating any account artifacts.
def test_market_screen_requires_original_timing_before_effects(
    reader, screen_inputs, tmp_path
):
    panel, raw, cubes, _ = screen_inputs
    output = tmp_path / "screen"
    with pytest.raises(ValueError, match="aligned saved distributions"):
        joint_funded_accounts.evaluate(
            panel,
            raw,
            cubes,
            reader,
            output,
            {"manifest_sha256": "a" * 64, "source_revision": "b" * 40},
            policy=verifier.MARKET_TIMED_POLICY,
        )
    assert not output.exists()


# Run the real screen driver through persisted learned intents, fills and saved scores.
def test_market_screen_carries_original_timing_to_real_account(
    reader, screen_inputs, tmp_path, monkeypatch
):
    panel, raw, cubes, timing = screen_inputs
    first, last = len(reader.dates) - 2, len(reader.dates) - 1
    spec = {
        "id": "market-10-0",
        "arm": verifier.MARKET_TIMED_POLICY,
        "cost_bps": 10,
        "start": 0,
        "first": first,
        "last": last,
        "first_session": str(reader.dates[first]),
    }

    # Limit this synthetic component period without changing the registered grid.
    def component_grid(dates, *, policy):
        assert np.array_equal(dates, reader.dates)
        assert policy == verifier.MARKET_TIMED_POLICY
        return [spec]

    # Isolate event dependencies while keeping the actual planner and sender active.
    def cached_features(key):
        return journey.features

    monkeypatch.setattr(joint_funded_accounts, "candidate_grid", component_grid)
    monkeypatch.setattr(joint_funded_accounts, "FeatureCache", cached_features)
    output = tmp_path / "screen"
    result = joint_funded_accounts.evaluate(
        panel,
        raw,
        cubes,
        reader,
        output,
        {"manifest_sha256": "a" * 64, "source_revision": "b" * 40},
        policy=verifier.MARKET_TIMED_POLICY,
        timing=timing,
    )
    assert result["declared"] == len(result["accounts"]) == 1
    account = verifier.ledger.read_account(output, result["accounts"][0])
    assert account["policy"] == verifier.MARKET_TIMED_POLICY
    assert account["forecast_decisions"]
    assert account["broker"]["holdings"].get("AAA", 0) > 0
    assert account["broker"]["cash"] < account["initial_cash"]
    assert any(row["filled_qty"] > 0 for row in account["fills"])
    assert all(
        row["timing_policy"] == "live-probability-timing/1-research"
        for row in account["intents"]
        if row["execution_timing"] == "dip_or_close"
    )


# Build a real numeric fitted receipt with an explicit synthetic historical bank.
def case(*, constant=False, default=False):
    dates, endpoints, forecast, outcome, context, support = evidence()
    endpoints[-2:] = np.datetime64("NaT", "D")
    if constant:
        forecast[:], context[:] = 0.003, [0.01, -0.1, 0.02, 0.5]
    if default:
        outcome[111] = -1
    fit = model.fit_market_log(
        dates,
        endpoints,
        forecast,
        outcome,
        context,
        support,
        fit_date=np.datetime64("2020-08-03"),
    )
    day = int(np.flatnonzero(dates == np.datetime64("2020-08-10"))[0])
    features = np.zeros((len(dates), 2, 13))
    features[:, 0, 4] = 0.02
    features[:, 1, [1, 5, 4, 12]] = context
    bank = {
        "dates": dates,
        "endpoints": endpoints,
        "symbols": ("AAA", "SPY"),
        "forecasts": np.c_[forecast, np.zeros(len(dates))],
        "labels": np.c_[outcome, np.zeros(len(dates))],
        "support": np.c_[support, np.zeros(len(dates), dtype=bool)],
        "features": features,
    }
    root = Path(__file__).resolve().parents[2]
    files = (
        "backend/market/market_conditioned_holding.py",
        "backend/market/market_conditioned_calibration.py",
        model.PROTOCOL,
    )
    source = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
    }
    mean, multiplier = fit.predict(forecast[day], context[day])
    sample = {
        "policy": "market-conditioned-joint-holding/1-research",
        "status": "available",
        "decision_date": str(dates[day]),
        "fit_date": fit.fit_date,
        "label_end_before": fit.cutoff,
        "symbols": ["AAA"],
        "joint_dates": len(fit.selected),
        "decision_indices": fit.selected.tolist(),
        "current_context": context[day].tolist(),
        "current_context_sha256": _hash(context[day]),
        "calibration_identity": {
            "policy": "market-conditioned-joint-holding/1-research",
            "source_sha256": source[files[0]],
            "numerical_source_sha256": source[files[1]],
            "protocol_sha256": source[model.PROTOCOL],
            "context": list(model.CONTEXT),
            "context_sha256": _hash(context),
            "features_sha256": _hash(features),
            "confidence_guarantee": False,
            "adoption_eligible": False,
            "calibration_residuals": "in_sample_on_genuine_OOS_base_forecasts",
        },
        "calibration": [{"symbol": "AAA", **fit.receipt()}],
        "predictions": [
            {"conditional_log_mean": mean, "residual_multiplier": multiplier}
        ],
    }
    return bank, source, sample


# Verification calls no estimator, numeric fitter or current prediction mechanism.
@pytest.mark.parametrize(
    ("constant", "default"), [(False, False), (True, False), (False, True)]
)
def test_saved_numeric_receipt_without_refitting(monkeypatch, constant, default):
    bank, source, sample = case(constant=constant, default=default)

    # A saved proof must not regenerate the candidate whose result it checks.
    def forbidden(*args, **kwargs):
        pytest.fail("Saved verification attempted fitting or prediction")

    monkeypatch.setattr(model, "fit_market_log", forbidden)
    monkeypatch.setattr(model.MarketLogFit, "predict", forbidden)
    MarketCalibrationVerifier(bank, source).check(sample)


# Shape-valid fabricated claims cannot pass as authenticated calibration evidence.
@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("calibration", 0, "coefficients", 0), 0.1, "stationarity"),
        (("predictions", 0, "residual_multiplier"), 100, "mean and leverage"),
        (("predictions", 0, "conditional_log_mean"), 0.1, "mean and leverage"),
        (("calibration", 0, "center", 0), 0.1, "training centers"),
        (("calibration", 0, "singular_values", 0), 100, "singular values"),
        (("calibration", 0, "directions", 0, 0), 0.1, "orthonormal"),
        (("calibration", 0, "row_hashes", "outcomes"), "0" * 64, "value differs"),
        (("calibration_identity", "source_sha256"), "0" * 64, "value differs"),
        (("calibration", 0, "confidence_guarantee"), True, "limitations"),
        (("calibration", 0, "rank"), 5, "numbers required"),
        (("current_context", 0), 0.1, "arithmetic differs"),
        (("calibration", 0, "coefficients", 0), False, "numbers required"),
    ],
)
def test_saved_receipt_mutations_refused(path, value, error):
    bank, source, sample = case()
    target = sample
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=error):
        MarketCalibrationVerifier(bank, source).check(sample)


# Neither omitted training dates nor future training dates certify a saved model.
@pytest.mark.parametrize("future", [False, True])
def test_changed_original_training_dates_refused(future):
    bank, source, sample = case()
    rows = sample["calibration"][0]["selected_indices"]
    if future:
        rows[-1] += 10
    else:
        rows.pop(0)
    with pytest.raises(ValueError, match="Original market singleton dates"):
        MarketCalibrationVerifier(bank, source).check(sample)


# Empty or repeated stocks cannot conceal a missing independent model check.
@pytest.mark.parametrize("empty", [False, True])
def test_original_stock_list_required(empty):
    bank, source, sample = case()
    for field in ("symbols", "calibration", "predictions"):
        sample[field] = [] if empty else sample[field] * 2
    with pytest.raises(ValueError, match="Unique nonempty"):
        MarketCalibrationVerifier(bank, source).check(sample)


# Detaching arrays and source metadata prevents a caller from changing a saved proof.
def test_bank_detachment_and_original_endpoint_contract():
    bank, source, sample = case()
    verifier = MarketCalibrationVerifier(bank, source)
    bank["features"][:] = np.nan
    source.clear()
    verifier.check(sample)
    wrong, source, _ = case()
    wrong["endpoints"][100] -= np.timedelta64(1, "D")
    with pytest.raises(ValueError, match=r"D\+2"):
        MarketCalibrationVerifier(wrong, source)


# NumPy symbol arrays retain their order and compare exactly with physical JSON names.
def test_market_bank_numpy_symbols_match_physical_names():
    bank, source, sample = case()
    names = bank["symbols"]
    bank["symbols"] = np.asarray(names)
    checked = MarketCalibrationVerifier(bank, source)
    verifier.ledger.same(checked.symbols, names)
    assert all(type(name) is str for name in checked.symbols)
    checked.check(sample)
    with pytest.raises(ValueError, match="value differs"):
        verifier.ledger.same(checked.symbols, names[::-1])


# A malformed numeric symbol cannot become a valid name through string conversion.
def test_market_bank_nonstring_symbols_refused():
    bank, source, _ = case()
    bank["symbols"] = (123, "SPY")
    with pytest.raises(ValueError, match="market calibration symbols"):
        MarketCalibrationVerifier(bank, source)


# An unidentified changed current predictor is rejected instead of certifying precision.
def test_current_query_outside_fitted_span_refused():
    bank, source, sample = case(constant=True)
    day = int(
        np.flatnonzero(bank["dates"] == np.datetime64(sample["decision_date"]))[0]
    )
    bank["forecasts"][day, 0] = 0.1
    with pytest.raises(ValueError, match="identified market query"):
        MarketCalibrationVerifier(bank, source).check(sample)


# Persist a genuine private replay using the selected shared holding planner.
def saved_market_account(reader, timing, tmp_path_factory, policy_type):
    panel, raw, cubes = fixture(tuple(map(str, reader.dates)))
    policy = policy_type(reader, 10)
    first, last = len(reader.dates) - 2, len(reader.dates) - 1
    account = run_account(
        panel,
        raw,
        cubes,
        tmp_path_factory.mktemp("market-account") / "account",
        first,
        last,
        10,
        holding_policy=policy,
        feature_reader=journey.features,
        reader_builder=build_reader,
        provider=timing.provider,
    )
    root = Path(__file__).resolve().parents[2]
    files = (
        "backend/market/joint_funded_policy.py",
        "backend/market/live_probability_timing.py",
        "backend/market/market_conditioned_holding.py",
        "backend/market/market_conditioned_calibration.py",
        "docs/research/market-conditioned-holding-plan-2026-10-05.md",
        policy.protocol,
    )
    source = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
    }
    data = {**direct_data(raw, cubes), "grades": raw.grades, "eligible": raw.eligible}
    bank = {
        name: getattr(reader, name)
        for name in (
            "dates",
            "endpoints",
            "forecasts",
            "labels",
            "features",
            "support",
            "symbols",
        )
    }
    return account, data, source, bank


# Preserve the original policy's actual saved acceptance accounts.
@pytest.fixture(scope="module")
def market_account(reader, timing, tmp_path_factory):
    return saved_market_account(
        reader, timing, tmp_path_factory, MarketConditionedTimedFundedPolicy
    )


# Exercise the same shared retained planner through the actual replay and sender.
@pytest.fixture(scope="module")
def retained_account(reader, timing, tmp_path_factory):
    return saved_market_account(
        reader, timing, tmp_path_factory, RetainedMarketConditionedFundedPolicy
    )


# Independent verification must accept the genuine V6 ledger without producer work.
def test_retained_actual_account_saved_proof(retained_account, monkeypatch):
    account, data, source, bank = retained_account

    # Reconstructing trades or refitting cannot substitute for archived evidence.
    def forbidden(*args, **kwargs):
        pytest.fail("Saved verification called the producer")

    monkeypatch.setattr(RetainedMarketConditionedFundedPolicy, "decide", forbidden)
    monkeypatch.setattr(model, "fit_market_log", forbidden)
    monkeypatch.setattr(model.MarketLogFit, "predict", forbidden)
    counts = verifier.candidate_receipts(
        account, data, source, policy=account["policy"],
        market_calibration=MarketCalibrationVerifier(bank, source),
    )
    assert counts["ordinary_receipts"] == 3
    assert account["policy"] == verifier.RETAINED_POLICY


# A carried migration must preserve the real incumbent prefix and existing shares.
def test_retained_transition_carries_incumbent_holdings(
    reader, timing, tmp_path, monkeypatch, retained_account
):
    panel, raw, cubes = fixture(tuple(map(str, reader.dates)))
    first, last = len(reader.dates) - 3, len(reader.dates) - 1
    cutoff = str(reader.dates[first])
    incumbent = run_account(
        panel, raw, cubes, tmp_path / "incumbent", first, last, 10,
        feature_reader=journey.features,
    )
    chosen = RetainedMarketConditionedFundedPolicy(reader, 10)
    carried = run_account(
        panel, raw, cubes, tmp_path / "carried", first, last, 10,
        holding_policy=chosen, holding_start=cutoff,
        feature_reader=journey.features, reader_builder=build_reader,
        provider=timing.provider,
    )
    assert carried["sessions"][0] == incumbent["sessions"][0]
    assert carried["sessions"][1]["holdings"] == incumbent["sessions"][1]["holdings"]
    assert carried["sessions"][1]["holdings"]["AAA"] > 0
    assert carried["sessions"][1]["cash"] == incumbent["sessions"][1]["cash"]
    assert carried["nightlies"][0] == incumbent["nightlies"][0]
    assert carried["nightlies"][1]["entry"]["policy"] == chosen.version
    assert carried["holding_start"] == cutoff
    _, data, source, bank = retained_account
    counts = verifier.candidate_receipts(
        carried, data, source, policy=chosen.version, holding_start=cutoff,
        market_calibration=MarketCalibrationVerifier(bank, source),
    )
    assert counts["ordinary_receipts"] == 3
    changed = deepcopy(carried)
    changed["nightlies"][0]["persisted_policy"] = chosen.version
    with pytest.raises(ValueError, match="Carried incumbent"):
        verifier.candidate_receipts(
            changed, data, source, policy=chosen.version, holding_start=cutoff,
            market_calibration=MarketCalibrationVerifier(bank, source),
        )


# An archive cannot move its transition forward to evade modeled-receipt validation.
def test_unadmitted_transition_is_refused(retained_account):
    original, data, source, bank = retained_account
    account = deepcopy(original)
    account["holding_start"] = "2099-01-01"
    with pytest.raises(ValueError, match="Declared holding start"):
        verifier.candidate_receipts(
            account, data, source, policy=account["policy"],
            market_calibration=MarketCalibrationVerifier(bank, source),
        )


# The new saved account path must consume the authenticated bank without replaying it.
def test_market_account_saved_receipts(market_account, monkeypatch):
    account, data, source, bank = market_account

    # Saved checks cannot manufacture a replacement account or fit a new model.
    def forbidden(*args, **kwargs):
        pytest.fail("Saved account validation attempted producer work")

    monkeypatch.setattr(model, "fit_market_log", forbidden)
    monkeypatch.setattr(model.MarketLogFit, "predict", forbidden)
    monkeypatch.setattr("backend.market.live_policy_replay.run_account", forbidden)
    counts = verifier.candidate_receipts(
        account,
        data,
        source,
        policy=account["policy"],
        market_calibration=MarketCalibrationVerifier(bank, source),
    )
    assert counts["ordinary_receipts"] == 3
    checked = deepcopy(account)
    spec = {
        "arm": checked["policy"],
        "cost_bps": 10,
        "start": 0,
        "first": len(data["dates"]) - 2,
        "last": len(data["dates"]) - 1,
        "first_session": checked["first"],
        "id": "market-component-10",
    }
    checked["comparison_account"] = spec
    ledger_counts = verifier.ledger.reconcile_account(
        checked, spec, data, account_policy=checked["policy"]
    )
    assert ledger_counts["sessions"] == 2


# Missing original bank admission cannot be replaced by trusted saved fit metadata.
def test_market_account_requires_original_bank(market_account):
    account, data, source, _ = market_account
    with pytest.raises(ValueError, match="Original authenticated market"):
        verifier.candidate_receipts(account, data, source, policy=account["policy"])


# Rehashed account metadata cannot hide changed funding, permissions or routing.
@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("observed_cash",), 1, "observed funding"),
        (("grades", "AAA"), 0, "original grade permissions"),
        (("targets", "AAA"), -0.1, "Invalid target"),
        (("timing_source_sha256",), "0" * 64, "value differs"),
        (("timing_policy",), "legacy", "value differs"),
        (("entry_qualification", "selection_uses_future_outcomes"), True, "limitation"),
    ],
)
def test_market_account_metadata_tampering(market_account, path, value, error):
    original, data, source, bank = market_account
    account = deepcopy(original)
    target = account["nightlies"][0]["entry"]["joint_funded"]["receipt"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    if path[0] == "targets":
        account["nightlies"][0]["entry"]["joint_funded"]["targets"][path[1]] = value
    with pytest.raises(ValueError, match=error):
        verifier.candidate_receipts(
            account,
            data,
            source,
            policy=account["policy"],
            market_calibration=MarketCalibrationVerifier(bank, source),
        )


# Freeze three market-model accounts without altering any previously registered grid.
def test_market_screen_uses_same_first_start_and_costs():
    dates = np.arange("2018-01-01", "2026-10-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)]
    old = candidate_grid(dates)
    market = candidate_grid(dates, policy=verifier.MARKET_TIMED_POLICY)
    assert market == verifier.candidate_grid(dates, policy=verifier.MARKET_TIMED_POLICY)
    assert [row["id"] for row in market] == [
        "market-0-0",
        "market-10-0",
        "market-25-0",
    ]
    assert len(old) == 60
    assert len(candidate_grid(dates, policy=verifier.MATURITY_POLICY)) == 60
    assert len(candidate_grid(dates, policy=verifier.CALIBRATED_POLICY)) == 3
    assert {row["id"] for row in market}.isdisjoint(row["id"] for row in old)
    first = [row for row in old if row["start"] == 0]
    for registered, control in zip(market, first, strict=True):
        assert {k: v for k, v in registered.items() if k not in ("id", "arm")} == {
            k: v for k, v in control.items() if k not in ("id", "arm")
        }
        assert registered["first_session"] == "2018-02-01"
        assert dates[registered["last"]] == np.datetime64("2026-09-30")


# Authenticate a saved physical account and its scored index without producer calls.
def test_market_saved_score_index_requires_original_bank(
    market_account,
    tmp_path,
    monkeypatch,
):
    original, data, source, bank = market_account
    account = deepcopy(original)
    spec = {
        "arm": verifier.MARKET_TIMED_POLICY,
        "cost_bps": 10,
        "start": 0,
        "first": len(data["dates"]) - 2,
        "last": len(data["dates"]) - 1,
        "first_session": account["first"],
        "id": "market-10-0",
    }
    account["comparison_account"] = spec
    row = save(tmp_path, account, spec)

    # The independent account fold cannot create a new fit, forecast or trade.
    def forbidden(*args, **kwargs):
        pytest.fail("Saved account verification invoked a producer")

    monkeypatch.setattr(model, "fit_market_log", forbidden)
    monkeypatch.setattr(model.MarketLogFit, "predict", forbidden)
    monkeypatch.setattr("backend.market.live_policy_replay.run_account", forbidden)
    checked = verifier.verify_rows(
        tmp_path,
        [row],
        data,
        candidate=True,
        source=source,
        policy=verifier.MARKET_TIMED_POLICY,
        market_calibration=MarketCalibrationVerifier(bank, source),
    )
    assert checked[0]["ordinary_receipts"] == 3
    assert checked[0]["counts"]["sessions"] == 2
    assert checked[0]["scores"] == row["scores"]
    with pytest.raises(ValueError, match="Original authenticated market"):
        verifier.verify_rows(
            tmp_path,
            [row],
            data,
            candidate=True,
            source=source,
            policy=verifier.MARKET_TIMED_POLICY,
        )
    wrong = deepcopy(row)
    wrong["scores"]["full"]["total_gain"] = 100.0
    with pytest.raises(ValueError, match="independent account scores"):
        verifier.verify_rows(
            tmp_path,
            [wrong],
            data,
            candidate=True,
            source=source,
            policy=verifier.MARKET_TIMED_POLICY,
            market_calibration=MarketCalibrationVerifier(bank, source),
        )
