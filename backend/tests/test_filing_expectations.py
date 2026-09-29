"""The real filing-event extractor and chronological learners, without a broker."""

import copy
import hashlib
import json
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_filing_expectations as cli
from backend.market import filing_expectations as study
from backend.market import fundamental_unit_sources as units

TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"


# Create real source-parsed quarters filed individually, not as one hindsight batch.
def source(extra=(), currency="USD"):
    rows = []
    for year in range(2014, 2022):
        for quarter, (start, end) in enumerate(
            (
                ("01-01", "03-31"),
                ("04-01", "06-30"),
                ("07-01", "09-30"),
                ("10-01", "12-31"),
            )
        ):
            finish = date.fromisoformat(f"{year}-{end}")
            rows.append(
                {
                    "start": f"{year}-{start}",
                    "end": str(finish),
                    "val": 100 + (year - 2014) * 10 + quarter,
                    "filed": str(finish + timedelta(days=30)),
                    "accn": f"{year}-{quarter}",
                    "form": "10-Q",
                }
            )
    rows.extend(extra)
    body = json.dumps(
        {"cik": 1, "facts": {"us-gaap": {TAG: {"units": {currency: rows}}}}}
    ).encode()
    return units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )


# Actual extracted input evidence predates every newly disclosed target.
def test_events_have_prior_inputs_and_exact_growth():
    events, rejected = study.source_events("TEST", source(), date(2022, 3, 1))
    study.validate_events(events)
    assert len(events) == 27
    assert rejected
    row = events[0]
    assert row["period_end"] == "2015-06-30"
    assert row["target"] == pytest.approx(np.log(111 / 101))
    assert row["baseline"] == pytest.approx(np.log(110 / 100))
    assert row["x"][3:7] == [None] * 4
    for event in events:
        assert event["feature_date"] < event["available"]
        for feature in event["feature_evidence"].values():
            for values in feature["inputs"].values():
                for value in values:
                    assert value["available"] <= event["feature_date"]


# Later revisions cannot alter a reconstructed earlier event or create a duplicate.
def test_future_revision_does_not_change_earlier_inputs_or_targets():
    extra = [
        {
            "start": "2015-04-01",
            "end": "2015-06-30",
            "val": 10000,
            "filed": "2023-01-01",
            "accn": "revision",
            "form": "10-Q/A",
        }
    ]
    original, _ = study.source_events("TEST", source(), date(2022, 3, 1))
    changed, _ = study.source_events("TEST", source(extra), date(2023, 2, 1))
    for left, right in zip(original, changed, strict=True):
        left.pop("source_sha256")
        right.pop("source_sha256")
        assert left == right


# Wrong currency never falls through to the unitless financial reader.
def test_non_usd_source_is_not_training_data():
    events, rejected = study.source_events(
        "TEST", source(currency="EUR"), date(2022, 3, 1)
    )
    assert events == []
    assert rejected["target:no_declared_unit"] == 32


# Competing same-date disclosures cannot become an arbitrary training label.
def test_conflicting_current_quarter_is_excluded():
    extra = [
        {
            "start": "2015-04-01",
            "end": "2015-06-30",
            "val": 999,
            "filed": "2015-07-30",
            "accn": "conflict",
            "form": "10-Q",
        }
    ]
    events, rejected = study.source_events("TEST", source(extra), date(2022, 3, 1))
    assert all(row["period_end"] != "2015-06-30" for row in events)
    assert rejected["target:conflicting_latest_vintage"] >= 1


# A first disclosure cannot borrow its growth comparison from a future filing.
def test_missing_prior_disclosure_prevents_a_training_example():
    payload = json.loads(source().body)
    rows = payload["facts"]["us-gaap"][TAG]["units"]["USD"]
    for row in rows:
        if row["end"] == "2014-06-30":
            row["filed"] = "2022-01-01"
    body = json.dumps(payload).encode()
    parsed = units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )
    events, _ = study.source_events("TEST", parsed, date(2022, 3, 1))
    assert all(row["period_end"] != "2015-06-30" for row in events)


# Duplicated rows and contemporaneous features are rejected before fitting.
def test_invalid_event_contract_refused():
    events, _ = study.source_events("TEST", source(), date(2022, 3, 1))
    with pytest.raises(ValueError, match="duplicate"):
        study.validate_events(events + events[:1])
    events[0]["feature_date"] = events[0]["available"]
    with pytest.raises(ValueError, match="precede"):
        study.validate_events(events)


# Validation and scored extremes cannot affect fit-only scaling or imputation.
def test_preprocessing_is_fit_only_and_retains_missing_indicators():
    fit = np.array([[1, np.nan], [2, np.nan], [3, np.nan]])
    params = study.fit_transform(fit)
    before = params.copy()
    transformed = study.transform([[1e10, None]], params)
    np.testing.assert_array_equal(params, before)
    assert np.isfinite(transformed).all()
    assert transformed[0, -1] == 1
    assert transformed[0, 0] < 2


# Generate deterministic synthetic events with enough dates to fit real models.
def synthetic_events():
    events = []
    for year in range(2012, 2027):
        for i in range(60):
            day = date(year, 2, 1) + timedelta(days=i * 4)
            baseline = 0.1 + 0.01 * np.sin(i)
            feature = (i - 30) / 30
            events.append(
                {
                    "ticker": f"T{i}",
                    "cik": i + 1,
                    "period_end": str(day - timedelta(days=30)),
                    "feature_date": str(day - timedelta(days=1)),
                    "available": str(day),
                    "baseline": baseline,
                    "target": baseline + 0.05 * feature,
                    "x": [baseline, feature, 0, 0.2, 0.1, None, 0.1, 120],
                }
            )
    return events


# Real ridge and LightGBM fits respect cutoffs and future-label invariance.
def test_real_walk_forward_does_not_learn_from_future_targets():
    events = synthetic_events()
    predictions, receipts = study.walk_forward(events)
    assert np.isfinite(predictions["lightgbm"]).sum() == 480
    for receipt in receipts:
        assert receipt["fit_latest_available"] < f"{receipt['year']}-01-01"
        assert receipt["inner_latest_available"] < receipt["validation_first_feature"]
        assert 1 <= receipt["best_iteration"] <= 500
    changed = copy.deepcopy(events)
    for row in changed:
        if row["feature_date"] >= "2025-01-01":
            row["target"] += 100
    revised, _ = study.walk_forward(changed)
    earlier = np.array([row["feature_date"] < "2025-01-01" for row in events])
    for name in predictions:
        np.testing.assert_array_equal(
            predictions[name][earlier], revised[name][earlier]
        )
    summary = study.summarize(events, predictions)
    assert summary["ridge"]["mse"] < summary["ridge"]["baseline_mse"]
    assert summary["ridge"]["verdict"] == "DO_NOT_ADVANCE"  # 480, below the 500 floor.


# The Jan-1 event is forecast by the previous year's model, never by a later fit.
def test_year_boundary_uses_actual_feature_date():
    row = synthetic_events()[0]
    row.update(feature_date="2019-12-31", available="2020-01-01")
    assert study.split([row], 2019)["test"][0]
    assert not study.split([row], 2020)["test"][0]
    assert not study.split([row], 2020)["fit"][0]


# Every benchmark uses the same strictly later open and the same twenty-session end.
def test_returns_exclude_information_date_and_preserve_missing():
    dates = np.arange("2020-01-01", "2020-02-10", dtype="datetime64[D]")
    prices = np.column_stack(
        (np.arange(100, 140), np.arange(200, 240), np.arange(300, 340))
    ).astype(float)
    panel = SimpleNamespace(
        dates=dates,
        tickers=("TEST", "SPY", "QQQ"),
        open=prices,
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    events = [
        {"ticker": "TEST", "available": "2020-01-02"},
        {"ticker": "TEST", "available": "2020-02-01"},
    ]
    rows = study.event_returns(events, panel)
    assert rows[0]["entry"] == "2020-01-03"
    assert rows[0]["exit"] == "2020-01-23"
    assert rows[0]["stock"] == pytest.approx(np.log(122 / 102))
    assert rows[0]["QQQ"] == pytest.approx(np.log(322 / 302))
    assert rows[1]["status"] == "immature"
    panel.open[22, 0] = np.nan
    assert study.event_returns(events, panel)[0]["stock"] is None


# Research writes refuse replacement and event loads verify the exact declared bytes.
def test_exclusive_json_and_hash_validation(tmp_path):
    events = synthetic_events()
    path = tmp_path / "events.json"
    dataset = {
        "schema": "filing-expectations-events/1",
        "features": list(study.FEATURES),
        "events": events,
    }
    digest = cli.write_json(path, dataset)
    assert cli.load_events(path, digest) == dataset
    with pytest.raises(FileExistsError):
        cli.write_json(path, dataset)
    with pytest.raises(ValueError, match="hash"):
        cli.load_events(path, "0" * 64)


# Export, fit and strict persisted report are exercised through the actual CLI helpers.
def test_export_evaluate_readback_with_real_archive(tmp_path):
    from datetime import UTC, datetime

    from backend.market import fundamental_source_store as store_sources
    from backend.market.store import MarketStore

    root = tmp_path / "sources"
    store_sources.save(
        MarketStore(root),
        "TEST",
        date(2022, 3, 1),
        source(),
        captured_at=datetime(2022, 3, 1, 12, tzinfo=UTC),
    )
    events_file = tmp_path / "events.json"
    cli.export(SimpleNamespace(sources=root, asof=date(2022, 3, 1), out=events_file))
    digest = hashlib.sha256(events_file.read_bytes()).hexdigest()
    output = tmp_path / "results"
    cli.evaluate(
        SimpleNamespace(events=events_file, sha256=digest, out=output, market=None)
    )
    report = json.loads((output / "summary.json").read_bytes())
    assert report["eligible_events"] == 27
    assert report["models"]["lightgbm"]["verdict"] == "INSUFFICIENT_DATA"
    assert report["live_promotion_authorized"] is False
    assert report["events_sha256"] == digest
    with pytest.raises(FileExistsError):
        cli.evaluate(
            SimpleNamespace(events=events_file, sha256=digest, out=output, market=None)
        )


# The error interval is deterministic and preserves date-clustered observations.
def test_block_bootstrap_is_reproducible():
    days = np.arange("2015-01-01", "2020-01-01", dtype="datetime64[D]")[::20]
    result = study.benefit_interval(days, np.ones(len(days)))
    assert result == [1.0, 1.0]
    assert study.benefit_interval(days[:2], np.ones(2)) == [None, None]
