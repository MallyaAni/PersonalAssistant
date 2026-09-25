"""Synthetic proof of matched accounts, actual folds and retained evidence."""

import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import event_risk, paper, risk, simulate
from backend.cli import market_nested_study as cli
from backend.market import nested_allocation as nested
from backend.market import nested_market_study as study
from backend.market import neural_study_metrics as metrics
from backend.market.allocation_controls import adjusted_open, constant_exposure
from backend.market.nested_ridge import RegressionInputs
from backend.market.research_journal_replay import verify_archive, verify_snapshot
from backend.tests.funded_simulator_fixtures import _report


# Build dated synthetic inputs with a separate QQQ column and genuine forward labels.
def _case():
    from backend.market.nested_market_inputs import binding

    rows = 315
    rng = np.random.default_rng(123)
    prices = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.008, (rows, 5)), axis=0))
    report = _report(prices, tickers=("A", "B", "C", "D", "SPY"))
    original = report.panel
    qqq = 90 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, rows)))
    values = {
        name: np.column_stack((getattr(original, name), qqq))
        for name in ("open", "high", "low", "close", "adj_close", "volume")
    }
    panel = replace(original, tickers=(*original.tickers, "QQQ"), **values)
    weights = np.zeros_like(panel.close)
    equal = np.zeros_like(weights)
    equal[:, :4] = 0.25
    for row in range(rows):
        weights[row, :2] = (0.6, 0.1) if row // 20 % 2 else (0.2, 0.5)
    labels = np.full((rows, 3), np.nan)
    endpoints = np.full(labels.shape, np.datetime64("NaT", "D"))
    for row in range(rows - 6):
        relative = panel.open[row + 6] / panel.open[row + 1]
        labels[row] = np.log(
            [
                1 - weights[row].sum() + weights[row] @ relative,
                relative[-2],
                relative[-1],
            ]
        )
        endpoints[row] = panel.dates[row + 6]
    step = np.arange(rows)
    features = np.column_stack((np.sin(step / 15), np.cos(step / 9)))
    regression = RegressionInputs(
        panel.dates,
        features,
        np.broadcast_to(panel.dates[:, None], features.shape),
        labels,
        endpoints,
        endpoints,
        feature_names=("synthetic_sine", "synthetic_cosine"),
    )
    inputs = SimpleNamespace(
        report=report,
        panel=panel,
        regression=regression,
        stock_weights=weights,
        equal_weights=equal,
        raw_labels=labels,
        label_end_on=endpoints,
        audit={
            "synthetic_only": True,
            "historical_availability_verified": False,
            "book_config": asdict(risk.BOOK_CONFIG),
            "assembly_binding": binding(report),
        },
    )
    protocol = nested.NestedProtocol(
        first_outer=281,
        outer_sessions=10,
        inner_sessions=8,
        inner_blocks=2,
        min_train_rows=20,
        alphas=(1.0,),
        switch_margins=(0.0,),
    )
    return report, inputs, protocol


# Share one real-fit synthetic study and its inputs for exact comparator parity.
@pytest.fixture(scope="module")
def completed():
    report, inputs, protocol = _case()
    return study.run(report, inputs, protocol=protocol), report, inputs, protocol


# Full-sample attribution is derived from all six actual journals, without refits.
def test_full_sample_retains_decision_execution_outcomes(completed):
    evidence, _, _, _ = completed
    for cost in (10, 25):
        table = evidence["summary"]["full_sample"][str(cost)]["decision_outcomes"]
        from backend.market.allocation_attribution import attribution

        expected = attribution(
            {
                name: account["journal"]
                for name, account in evidence["accounts"][str(cost)].items()
            },
            cost_bps=cost,
        )
        assert table == expected
        assert table["reconciliation"]["ok"] is True
        assert table["return_intervals"] == len(table["intervals"])
        assert set(table["accounts"]) == set(study.ACCOUNT_NAMES)
        assert table["adoption_eligible"] is False
        assert table["independent_validation"] is False


# All six accounts have a real independently reconstructed ledger at both costs.
def test_complete_study_uses_matched_verified_accounts(completed):
    evidence, report, inputs, protocol = completed
    expected_dates = inputs.panel.dates[protocol.first_outer :]
    assert report.panel.tickers == ("A", "B", "C", "D", "SPY")
    assert evidence["accounting_verified"] is True
    assert evidence["benchmark_study_complete"] is True
    assert evidence["adoption_eligible"] is False
    assert evidence["independent_validation"] is False
    assert evidence["historical_availability_verified"] is False
    assert set(evidence["accounts"]) == {"10", "25"}
    for group in evidence["accounts"].values():
        assert set(group) == set(study.ACCOUNT_NAMES)
        for account in group.values():
            proof = verify_snapshot(account["journal"])
            assert proof["ok"], proof["errors"]
            assert proof == account["verification"]
            np.testing.assert_array_equal(account["curve"].dates, expected_dates)
            np.testing.assert_array_equal(
                account["curve"].equity, [mark["nav"] for mark in proof["marks"]]
            )
            assert account["curve"].traded_notional == proof["total_traded"]
            assert proof["marks"][0]["cash"] == 1
            assert not any(proof["marks"][0]["positions"])
    assert (
        evidence["protocol_document_sha256"]
        == hashlib.sha256(study.PROTOCOL_PATH.read_bytes()).hexdigest()
    )


# The incumbent comparison is exactly the unchanged public live-policy invocation.
@pytest.mark.parametrize("cost", [10, 25])
def test_incumbent_matches_direct_unchanged_run(completed, cost):
    evidence, report, _, protocol = completed
    direct = simulate.run(
        report,
        since=report.panel.dates[protocol.first_outer].astype(object),
        config=risk.BOOK_CONFIG,
        rebalance=paper.REBALANCE_EVERY,
        cost_bps=cost,
        use_exits=False,
        event_lifecycle=True,
        event_exposure=event_risk.live_path(report.panel),
        **simulate.LIVE_POLICY,
    )
    account = evidence["accounts"][str(cost)]["incumbent"]
    np.testing.assert_allclose(
        account["curve"].equity, direct.equity, rtol=1e-12, atol=1e-12
    )
    assert account["curve"].traded_notional == pytest.approx(direct.traded)
    assert account["verification"]["marks"][0]["session_index"] == protocol.first_outer
    # This would fail if price row zero were confused with the first account mark.
    for offset, mark in enumerate(account["verification"]["marks"]):
        values = (
            np.asarray(mark["positions"])
            * report.panel.adj_close[mark["session_index"]]
        )
        assert account["curve"].largest_position_fraction[offset] == pytest.approx(
            values.max() / mark["nav"]
        )


# Index controls are funded daily accounts, not normalized source prices or adapters.
@pytest.mark.parametrize("cost", [10, 25])
@pytest.mark.parametrize("symbol", ["SPY", "QQQ"])
def test_index_controls_match_the_canonical_account(completed, cost, symbol):
    evidence, _, inputs, protocol = completed
    column = inputs.panel.tickers.index(symbol)
    cut = slice(protocol.first_outer, None)
    panel = inputs.panel
    closes = panel.adj_close[cut, column]
    opens = adjusted_open(panel.open, panel.close, panel.adj_close)[cut, column]
    expected = constant_exposure(closes, opens, 1.0, cost)
    account = evidence["accounts"][str(cost)][symbol]
    np.testing.assert_allclose(
        account["curve"].equity, expected, rtol=1e-12, atol=1e-12
    )
    assert not np.array_equal(account["curve"].equity, closes / closes[0])
    assert (
        len(
            [
                event
                for event in account["journal"]["events"]
                if event["type"] == "decision"
            ]
        )
        == len(closes) - 1
    )


# Off-cadence account starts seed the effective basket without moving global refreshes.
def test_equal_weight_keeps_absolute_cadence(completed):
    evidence, _, inputs, protocol = completed
    events = evidence["accounts"]["10"]["equal_weight"]["journal"]["events"]
    decisions = [event for event in events if event["type"] == "decision"]
    updates = [
        event["session"]
        for event in decisions
        if event["metadata"]["instruction"]["stock_weights"] is not None
    ]
    assert updates == [
        str(inputs.panel.dates[t])
        for t in range(protocol.first_outer, len(inputs.panel.dates) - 1)
        if t == protocol.first_outer or t % 20 == 0
    ]


# Keep carried capital and cumulative local trading at each actual fold boundary.
def test_fold_tables_use_real_fits_and_reconcile_trading(completed):
    evidence, _, inputs, protocol = completed
    rows = evidence["summary"]["actual_outer_folds"]
    assert len(rows) == len(evidence["nested"]["outer_folds"]) == 4
    for cost in (10, 25):
        for name, account in evidence["accounts"][str(cost)].items():
            reconstructed = 0
            for row, fit in zip(rows, evidence["nested"]["outer_folds"], strict=True):
                assert row["model_hash"] == fit["model_hash"]
                start, stop = (
                    fit["start"] - protocol.first_outer,
                    fit["stop"] - protocol.first_outer,
                )
                table = row["cost_levels"][str(cost)]["performance"]
                assert table["first_session"] == str(inputs.panel.dates[fit["start"]])
                assert table["last_session"] == str(inputs.panel.dates[fit["stop"]])
                mark = account["verification"]["marks"]
                local = mark[stop]["traded"] - mark[start]["traded"]
                assert table["rows"][name][
                    "traded_notional_per_starting_nav"
                ] == pytest.approx(local / mark[start]["nav"])
                reconstructed += local
            assert reconstructed == pytest.approx(
                account["verification"]["total_traded"]
            )


# Regime tables consume source SPY with its warm-up, and rolling windows stay explicit.
def test_scorecards_use_price_evidence_and_keep_unknown_intervals(completed):
    evidence, _, inputs, _ = completed
    spy = inputs.panel.adj_close[:, inputs.panel.tickers.index("SPY")]
    for cost in (10, 25):
        curves = {
            name: account["curve"]
            for name, account in evidence["accounts"][str(cost)].items()
        }
        expected = metrics.regime_scorecard(
            curves,
            cost_bps=cost,
            evidence=metrics.RegimeEvidence(inputs.panel.dates, spy),
        )
        table = evidence["summary"]["full_sample"][str(cost)]
        assert table["regimes"] == expected
        assert expected["regime_intervals_reconcile"]
        assert "unknown_or_unavailable" in expected["regimes"]
        assert table["performance"]["rolling_windows_overlap"]


# Retain raw and masked outcomes beside full fit, prediction and policy evidence.
def test_retains_raw_labels_fits_configuration_and_source_fingerprints(completed):
    evidence, _, inputs, _ = completed
    np.testing.assert_array_equal(
        evidence["additional_inputs"]["raw_labels"], inputs.raw_labels
    )
    np.testing.assert_array_equal(
        evidence["additional_inputs"]["label_end_on"], inputs.label_end_on
    )
    np.testing.assert_array_equal(
        evidence["nested"]["source_inputs"]["arrays"]["labels"],
        inputs.regression.labels,
    )
    assert evidence["configuration"]["live_policy"] == simulate.LIVE_POLICY
    assert evidence["configuration"]["event_guidance_change"] == "2026-06-18"
    assert evidence["configuration"]["sizing"]["name_cap"] == 0.15
    assert evidence["nested"]["inner_runs"]
    assert evidence["nested"]["outer_folds"][0]["fit"]["targets"]


# The archive retains every ledger and can replay each through the real standalone CLI.
def test_archive_readback_and_real_journal_cli(completed, tmp_path):
    evidence = completed[0]
    destination = tmp_path / "synthetic-study"
    manifest_path = study.archive(evidence, destination)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["evidence_sha256"] == evidence["evidence_sha256"]
    files = {
        str(path.relative_to(destination))
        for path in destination.rglob("*")
        if path.is_file() and path != manifest_path
    }
    assert files == set(manifest["files"])
    for name, entry in manifest["files"].items():
        data = (destination / name).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    journals = list((destination / "journals").iterdir())
    assert len(journals) == manifest["journal_count"] == 20
    for journal in journals:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "backend.cli.market_verify_journal",
                "--archive",
                str(journal),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout) == verify_archive(journal)
    with np.load(destination / "arrays.npz", allow_pickle=False) as arrays:
        assert arrays.files
        assert any(
            np.array_equal(arrays[key], completed[2].raw_labels, equal_nan=True)
            for key in arrays.files
            if arrays[key].shape == completed[2].raw_labels.shape
        )
    assert json.loads((destination / "summary.json").read_text()) == evidence["summary"]
    with pytest.raises(ValueError, match="must be new"):
        study.archive(evidence, destination)


# Corrupt journal data cannot become a scored or published account.
def test_corrupt_journal_fails_closed_before_archive(completed, tmp_path):
    evidence = copy.deepcopy(completed[0])
    evidence["accounts"]["10"]["SPY"]["journal"]["prices"]["close"][1][0] *= 2
    with pytest.raises(ValueError, match="evidence changed"):
        study.archive(evidence, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


# Safety checks run before fits, and do not silently trim an inconsistent report grid.
@pytest.mark.parametrize(
    "defect", ["calendar", "price", "label", "equal_cadence", "report"]
)
def test_bad_bound_inputs_fail_before_fits(monkeypatch, defect):
    report, inputs, protocol = _case()
    if defect == "calendar":
        inputs.panel = replace(
            inputs.panel, dates=inputs.panel.dates + np.timedelta64(1, "D")
        )
    elif defect == "price":
        inputs.panel.open[4, 0] *= 2
    elif defect == "label":
        inputs.raw_labels = inputs.raw_labels[:, :2]
    elif defect == "equal_cadence":
        inputs.equal_weights[5, :2] = (0.1, 0.4)
    else:
        inputs.report = copy.copy(report)

    # Any fitting call would invalidate this early-boundary test.
    def forbidden(*args, **kwargs):
        pytest.fail("invalid inputs reached model fitting")

    monkeypatch.setattr(study.nested, "run", forbidden)
    with pytest.raises(ValueError, match="calendar|open|labels|cadence|report"):
        study.run(report, inputs, protocol=protocol)


# Existing, symlinked and parent-traversing output locations are never overwritten.
@pytest.mark.parametrize("kind", ["existing", "symlink", "traversal", "missing_parent"])
def test_archive_destination_refusals(tmp_path, kind):
    target = tmp_path / "output"
    if kind == "existing":
        target.mkdir()
    elif kind == "symlink":
        target.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "traversal":
        target = tmp_path / ".." / "output"
    else:
        target = tmp_path / "absent" / "output"
    with pytest.raises(ValueError, match="output"):
        study.check_destination(target)


# The public CLI offers no alternate market protocol and rejects overwrite before load.
def test_cli_rejects_existing_output_before_loading(tmp_path):
    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "--report",
                "missing",
                "--store-root",
                "missing",
                "--manifest",
                "missing",
                "--output",
                str(tmp_path),
            ]
        )
    assert caught.value.code == 2


# The public CLI wires the pinned loader, fixed study and exclusive archive together.
def test_cli_uses_fixed_protocol(monkeypatch, tmp_path, capsys):
    report, inputs, _ = _case()
    calls = []

    # Expose the loader contract without labelling synthetic inputs as pinned data.
    def load(*args):
        calls.append(("load", args))
        return inputs

    # This structural test checks CLI wiring; real fits and ledgers are tested above.
    def run(actual_report, actual_inputs):
        assert actual_report is report
        assert actual_inputs is inputs
        calls.append(("run",))
        return {"synthetic": True}

    # Check the destination; the archive's behavioral test runs the real writer.
    def archive(evidence, path):
        assert evidence == {"synthetic": True}
        calls.append(("archive", path))
        return path / "manifest.json"

    monkeypatch.setitem(
        sys.modules, "backend.market.nested_market_inputs", SimpleNamespace(load=load)
    )
    monkeypatch.setattr(study, "run", run)
    monkeypatch.setattr(study, "archive", archive)
    assert (
        cli.main(
            [
                "--report",
                "report",
                "--store-root",
                "store",
                "--manifest",
                "manifest",
                "--output",
                str(tmp_path / "fresh"),
            ]
        )
        == 0
    )
    assert [row[0] for row in calls] == ["load", "run", "archive"]
    assert "adoption eligible: false" in capsys.readouterr().out


# Exercise all 22 real features through real fits, six ledgers, archival and CLI replay.
def test_real_assembly_to_study_archive_and_cli(tmp_path):
    from backend.market.nested_market_inputs import FEATURE_NAMES, assemble

    report, supplied, protocol = _case()
    before = {
        name: getattr(report.panel, name).copy()
        for name in ("open", "high", "low", "close", "adj_close", "volume")
    }
    inputs = assemble(report, supplied.panel)
    assert inputs.regression.features.shape == (315, 22)
    assert inputs.regression.feature_names == FEATURE_NAMES
    assert np.isnan(inputs.regression.labels[:200]).all()
    assert np.isfinite(inputs.raw_labels[:200]).any()
    evidence = study.run(report, inputs, protocol=protocol)
    for name, values in before.items():
        np.testing.assert_array_equal(getattr(report.panel, name), values)
    destination = tmp_path / "real-assembly-synthetic-study"
    study.archive(evidence, destination)
    archive = json.loads((destination / "manifest.json").read_text())
    assert archive["journal_count"] == 20
    assert (
        destination / "protocol.md"
    ).read_bytes() == study.PROTOCOL_PATH.read_bytes()
    assert "code/backend/market/nested_market_inputs.py" in archive["files"]
    for name in ("fomc_decisions.csv", "nyse_holidays.json"):
        source = study.ROOT / "backend/market/data" / name
        archived = destination / "code/backend/market/data" / name
        assert archived.read_bytes() == source.read_bytes()
        assert (
            evidence["source_hashes"][str(source.relative_to(study.ROOT))]
            == hashlib.sha256(source.read_bytes()).hexdigest()
        )
    for folder in (destination / "journals").iterdir():
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "backend.cli.market_verify_journal",
                "--archive",
                str(folder),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout)["accounting_verified"] is True


# Later source-price changes cannot rewrite prior real fits, choices or account marks.
def test_actual_pipeline_future_prefix_noninterference():
    from backend.market.nested_market_inputs import assemble

    report, supplied, protocol = _case()
    first = study.run(report, assemble(report, supplied.panel), protocol=protocol)
    changed_report, changed, _ = _case()
    # The legacy fixture aliases its OHLC arrays; own each field before changing it.
    for owner in (changed_report, changed):
        arrays = {}
        for name in ("open", "high", "low", "close", "adj_close"):
            arrays[name] = getattr(owner.panel, name).copy()
            arrays[name][293:] *= 1.2
        owner.panel = replace(owner.panel, **arrays)
    second = study.run(
        changed_report, assemble(changed_report, changed.panel), protocol=protocol
    )
    assert first["nested"]["outer_folds"][0] == second["nested"]["outer_folds"][0]
    for cost in ("10", "25"):
        for name in study.ACCOUNT_NAMES:
            np.testing.assert_array_equal(
                first["accounts"][cost][name]["curve"].equity[:12],
                second["accounts"][cost][name]["curve"].equity[:12],
            )


# The declared production configuration cannot drift behind a retained protocol title.
@pytest.mark.parametrize("field", ["sizing", "flags", "era", "basket_config"])
def test_frozen_configuration_refusals(monkeypatch, field):
    report, inputs, protocol = _case()
    if field == "sizing":
        monkeypatch.setattr(
            risk, "BOOK_CONFIG", replace(risk.BOOK_CONFIG, name_cap=0.2)
        )
        inputs.audit["book_config"] = asdict(risk.BOOK_CONFIG)
    elif field == "flags":
        monkeypatch.setattr(
            simulate, "LIVE_POLICY", {**simulate.LIVE_POLICY, "live_midcycle": False}
        )
    elif field == "era":
        monkeypatch.setattr(
            event_risk, "GUIDANCE_CHANGE", np.datetime64("2026-01-01", "D")
        )
    else:
        inputs.audit["book_config"]["speed"] = 0.9
    with pytest.raises(ValueError, match="configuration|binding"):
        study.run(report, inputs, protocol=protocol)


# A producer cannot supply a different mark calendar or monetary result for scoring.
@pytest.mark.parametrize("field", ["dates", "nav", "traded"])
def test_verified_account_refuses_mismatched_producer(completed, field):
    account = completed[0]["accounts"]["10"]["SPY"]
    dates = account["curve"].dates.copy()
    nav = account["curve"].equity.copy()
    traded = account["curve"].traded_notional
    if field == "dates":
        dates[0] -= np.timedelta64(1, "D")
    elif field == "nav":
        nav[1] += 0.001
    else:
        traded += 0.001
    with pytest.raises(ValueError, match="calendar|NAV|notional"):
        study._verified_account(account["journal"], dates, nav, traded)


# Changed decisions or assembly code are rejected before the first fitted model.
@pytest.mark.parametrize(
    "field", ["grades", "scores", "states", "sides", "themes", "source"]
)
def test_report_and_assembly_source_drift_rejected_before_fit(
    monkeypatch, tmp_path, field
):
    from backend.market import nested_market_inputs as assembly

    report, inputs, protocol = _case()
    if field == "grades":
        report.graded.grades[20, 0] = 0
    elif field == "scores":
        report.scores[20, 0] += 1
    elif field == "states":
        report.regime.states[20] = replace(report.regime.states[20], exposure=0.75)
    elif field == "sides":
        report.sides["A"] = "software"
    elif field == "themes":
        report.panel.themes["A"] = ("changed",)
    else:
        monkeypatch.setattr(assembly, "ROOT", tmp_path)

    # Any fit here would consume inputs built from a different state or source.
    def forbidden(*args, **kwargs):
        pytest.fail("changed report/source reached fitting")

    monkeypatch.setattr(study.nested, "run", forbidden)
    with pytest.raises(ValueError, match="Assembly binding changed"):
        study.run(report, inputs, protocol=protocol)


# A report changed during account execution cannot escape the ending binding check.
def test_report_mutation_during_run_is_rejected(monkeypatch):
    report, inputs, protocol = _case()
    real_run = study.nested.run

    # Return genuine fitted results, then simulate a concurrent report mutation.
    def changed(*args, **kwargs):
        result = real_run(*args, **kwargs)
        report.scores[300, 0] += 1
        return result

    monkeypatch.setattr(study.nested, "run", changed)
    with pytest.raises(ValueError, match="Assembly binding changed"):
        study.run(report, inputs, protocol=protocol)


# The archive refuses altered conclusions or inputs even when journals stay valid.
@pytest.mark.parametrize(
    "field", ["summary", "curve", "verification", "raw_labels", "fit", "predictions"]
)
def test_complete_evidence_digest_rejects_post_run_mutations(
    completed, tmp_path, field
):
    evidence = copy.deepcopy(completed[0])
    if field == "summary":
        evidence["summary"]["full_sample"]["10"]["performance"]["rows"]["candidate"][
            "total_return"
        ] += 1
    elif field == "curve":
        evidence["accounts"]["10"]["candidate"]["curve"].equity[1] += 1
    elif field == "verification":
        evidence["accounts"]["10"]["candidate"]["verification"]["total_traded"] += 1
    elif field == "raw_labels":
        evidence["additional_inputs"]["raw_labels"][0, 0] += 1
    elif field == "fit":
        evidence["nested"]["outer_folds"][0]["fit"]["sha256"] = "changed"
    else:
        evidence["nested"]["outer_folds"][0]["predictions"][0][0] += 1
    target = tmp_path / "refused"
    with pytest.raises(ValueError, match="evidence changed"):
        study.archive(evidence, target)
    assert not target.exists()


# A legitimate deep copy retains the same complete receipt and archives successfully.
def test_complete_evidence_digest_accepts_deepcopy(completed, tmp_path):
    copied = copy.deepcopy(completed[0])
    assert study._evidence_digest(copied) == completed[0]["evidence_sha256"]
    path = study.archive(copied, tmp_path / "deep-copied")
    assert json.loads(path.read_text())["journal_count"] == 20
