"""Independent saved-account arithmetic and tamper rejection, without model work."""

import ast
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import verify_actual_policy_timing as verifier
from backend.market import calendar
from backend.tests.test_live_policy_replay import fixture


# Authenticated bytes with a known false entitlement must not earn a proof certificate.
def test_known_bad_action_export_cannot_be_certified(monkeypatch):
    monkeypatch.setattr(verifier, "ACTIONS_SHA", verifier.REJECTED_ACTIONS_SHA)
    with pytest.raises(ValueError, match="Known incorrect stock-distribution"):
        verifier.load_original_data(None, {})


# Give saved-only checks direct original arrays from a real synthetic account fixture.
def direct_data(raw, cubes):
    return {
        "dates": raw.dates,
        "names": raw.tickers,
        "close": raw.daily_close.copy(),
        "actions": {
            name: [dict(row) for row in rows] for name, rows in raw.actions.items()
        },
        "cubes": {
            name: {
                field: getattr(cube, field).copy()
                for field in ("dates", "open", "close", "auction_open")
            }
            for name, cube in cubes.items()
        },
    }


# Declare an explicitly synthetic bounded account without changing the production grid.
def spec(arm="rule"):
    return {
        "arm": arm,
        "cost_bps": 10,
        "start": 0,
        "first": 1,
        "last": 2,
        "first_session": "2026-09-02",
        "id": f"{arm}-10-0",
    }


# Produce actual synthetic receipts only in the test's setup, before saved-only checks.
def actual_account(tmp_path, arm="rule", *, missing_fill=False):
    from backend.market.live_policy_replay import run_account, run_benchmark
    from backend.market.live_probability_timing import build_reader

    panel, raw, cubes = fixture(missing_fill=missing_fill)
    declaration = spec(arm)
    if arm in verifier.BENCHMARKS:
        account = run_benchmark(panel, raw, tmp_path / "source", 1, 2, 10, arm)
    else:
        options = {}
        if arm != "rule":
            options = {"reader_builder": build_reader, "provider": unavailable_forecast}
        account = run_account(
            panel, raw, cubes, tmp_path / "source", 1, 2, 10, **options
        )
    account["comparison_account"] = declaration
    return account, declaration, direct_data(raw, cubes)


# Keep synthetic candidate distributions unavailable without consulting a predictor.
def unavailable_forecast(day, clock, stock):
    return None


# Write a compressed receipt with deterministic bytes for checksum and tamper cases.
def saved_archive(study, account, declaration):
    path = study / "accounts" / (declaration["id"] + ".json.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(account, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(gzip.compress(payload, mtime=0))
    return {
        **declaration,
        "file": str(path.relative_to(study)),
        "sha256": verifier.digest(path),
    }


# Prove the verifier has no import or invocation of the economic producer machinery.
def test_verifier_has_no_producer_or_simulator_dependency():
    source = Path(verifier.__file__).read_text()
    tree = ast.parse(source)
    forbidden = {
        "market_actual_policy_timing",
        "live_policy_replay",
        "replay_broker",
        "probabilistic_execution_saved",
        "market_probabilistic_funded_timing",
        "learned_entry_models",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not forbidden.intersection((node.module or "").split("."))
            assert not forbidden.intersection(alias.name for alias in node.names)
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert name not in {
                "run_account",
                "run_benchmark",
                "calibrate",
                "load_saved",
                "fit",
            }


# Verify five actual synthetic archives after disabling producer entry points.
def test_saved_archive_workflow_never_calls_producer(tmp_path, monkeypatch):
    from backend.cli import market_actual_policy_timing as producer
    from backend.market import live_policy_replay, replay_broker

    grid, rows = [], []
    study = tmp_path / "saved"
    data = None
    for arm in (*verifier.ARMS, *verifier.BENCHMARKS):
        account, declaration, data = actual_account(tmp_path / arm, arm)
        grid.append(declaration)
        row = saved_archive(study, account, declaration)
        row.update(
            scores={
                name: producer.account_score(account, lower, upper)
                for name, lower, upper in verifier.WINDOWS
            },
            fill_records=len(account["fills"]),
            intents=len(account.get("intents", [])),
            forecast_decisions=len(account.get("forecast_decisions", [])),
        )
        rows.append(row)
    report = {
        "status": "complete_pending_independent_verification",
        "policy": verifier.POLICY,
        "adoption_eligible": False,
        "accounts": rows,
    }

    # Fail if saved-only acceptance reaches a generator or broker constructor.
    def forbidden(*args, **kwargs):
        raise AssertionError("producer/simulator invoked by verifier")

    for name in (
        "run_account",
        "run_benchmark",
        "account_score",
        "comparison_summary",
        "load_inputs",
    ):
        monkeypatch.setattr(producer, name, forbidden)
    monkeypatch.setattr(live_policy_replay, "run_account", forbidden)
    monkeypatch.setattr(live_policy_replay, "run_benchmark", forbidden)
    monkeypatch.setattr(replay_broker.ReplayBroker, "__init__", forbidden)
    result = verifier.verify_saved(study, report, {"accounts": grid}, data, grid=grid)
    assert result["accounts"] == 5
    assert result["policy_accounts"] == 3
    assert result["benchmark_accounts"] == 2
    assert result["counts"]["fills"] == 5
    assert result["summary"] is None  # Explicitly bounded synthetic acceptance.


# Reject altered receipt bytes even when they remain a valid gzip/JSON document.
def test_compressed_receipt_hash_tamper_rejected(tmp_path):
    account, declaration, _ = actual_account(tmp_path)
    row = saved_archive(tmp_path / "saved", account, declaration)
    account["sessions"][-1]["nav"] += 1
    path = tmp_path / "saved" / row["file"]
    path.write_bytes(gzip.compress(json.dumps(account).encode()))
    with pytest.raises(ValueError, match="hash differs"):
        verifier.read_account(tmp_path / "saved", row)


# Refuse traversal and alternative account filenames before reading any evidence.
@pytest.mark.parametrize(
    "filename", ["../secret.json.gz", "/tmp/account.json.gz", "accounts/other.json.gz"]
)
def test_account_paths_are_bound_to_original_identifier(tmp_path, filename):
    with pytest.raises(ValueError, match="path"):
        verifier.read_account(
            tmp_path, {**spec(), "file": filename, "sha256": "a" * 64}
        )


# Reject ledger or raw-price changes even with a newly valid archive hash.
@pytest.mark.parametrize(
    "change",
    [
        "cash",
        "nav",
        "shares",
        "basis",
        "fee",
        "fill_price",
        "requested_qty",
        "filled_qty",
        "accepted",
        "capital",
        "cost",
        "final_clock",
        "dates",
        "initial",
        "adoption",
    ],
)
def test_saved_account_arithmetic_tamper_rejected(tmp_path, change):
    account, declaration, data = actual_account(tmp_path)
    mutations = {
        "cash": (("sessions", -1, "cash"), 75226.25),
        "nav": (("sessions", -1, "nav"), 100226.25),
        "shares": (("sessions", -1, "holdings", "AAA"), 251),
        "basis": (("broker", "average_prices", "AAA"), 100),
        "fee": (("fills", 0, "fee"), 25.75),
        "fill_price": (("fills", 0, "price"), 100),
        "requested_qty": (("fills", 0, "requested_qty"), 251),
        "filled_qty": (("fills", 0, "filled_qty"), 249.5),
        "accepted": (("attempts", 0, "accepted"), False),
        "capital": (("initial_cash",), 100001),
        "cost": (("cost_bps",), 0),
        "final_clock": (("broker", "observed_at"), "2026-09-03T19:59:00+00:00"),
        "dates": (("sessions", 1, "session"), "2026-09-04"),
        "initial": (("sessions", 1, "initial"), True),
        "adoption": (("adoption_eligible",), True),
    }
    path, value = mutations[change]
    container = account
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value
    with pytest.raises(ValueError, match="differs|required|missing|invalid|bounds"):
        verifier.reconcile_account(account, declaration, data)


# Retain explicit unfilled whole-share quantities in the missing-fill metrics.
def test_missing_execution_quantity_is_preserved(tmp_path):
    account, declaration, data = actual_account(tmp_path, missing_fill=True)
    verifier.reconcile_account(account, declaration, data)
    score = verifier.independent_score(account, "2026-09-02", "2026-09-04")
    assert score["missed_fill_quantity"] == 500
    assert score["total_gain"] == 0
    assert score["unexecuted_original_intents"] == 2
    assert score["remaining_original_qty_by_symbol"] == {"AAA": 500}


# Reconcile split-created entitlements and unpaid dividends through saved ETF receipts.
def test_dated_split_dividend_arithmetic_and_payment_tamper(tmp_path):
    from dataclasses import replace

    from backend.market.live_policy_replay import run_benchmark

    panel, raw, cubes = fixture()
    close = raw.daily_close.copy()
    close[2, 1] = 50.0
    actions = dict(raw.actions)
    actions["SPY"] = (
        {"date": "2026-09-03", "kind": "split", "value": 2.0},
        {"date": "2026-09-03", "kind": "dividend", "value": 0.5},
    )
    raw = replace(raw, daily_close=close, actions=actions)
    account = run_benchmark(panel, raw, tmp_path / "source", 1, 2, 10, "SPY")
    declaration = spec("SPY")
    account["comparison_account"] = declaration
    data = direct_data(raw, cubes)
    verifier.reconcile_account(account, declaration, data)
    assert account["broker"]["holdings"] == {"SPY": 1998.0}
    assert account["broker"]["dividends"][-1]["amount"] == 999.0
    account["broker"]["dividends"][-1]["paid"] = True
    with pytest.raises(ValueError, match="dividend"):
        verifier.reconcile_account(account, declaration, data)


# Prove the source conversion uses only dated later splits and original amount units.
def test_raw_source_dividend_conversion_preserves_original_amount():
    days = np.array(["2020-01-02", "2020-01-03"], dtype="datetime64[D]")
    exported = {
        "basis_as_of": "2020-01-03",
        "complete_through": "2020-01-03",
        "actions": {
            "AAA": [
                {"date": "2020-01-02", "kind": "dividend", "value": 0.25},
                {"date": "2020-01-03", "kind": "split", "value": 4.0},
            ]
        },
    }
    normalized, factors = verifier.normalize_actions(
        ("AAA",), days, exported, "split_adjusted_archive_share_dollars"
    )
    assert normalized["AAA"][0] == {
        "date": "2020-01-02",
        "kind": "dividend",
        "value": 1.0,
        "source_value": 0.25,
    }
    assert factors[:, 0].tolist() == [4.0, 1.0]
    raw, _ = verifier.normalize_actions(
        ("AAA",), days, exported, "raw_ex_date_share_dollars"
    )
    assert raw["AAA"][0]["value"] == 0.25
    with pytest.raises(ValueError, match="basis"):
        verifier.normalize_actions(("AAA",), days, exported, None)


# Refuse fabricated marked wealth where a carried raw closing mark is missing.
def test_missing_held_mark_is_null_and_cannot_be_dropped(tmp_path):
    account, declaration, data = actual_account(tmp_path, "SPY")
    data["close"][2, 1] = np.nan
    final = account["sessions"][-1]
    final.update(
        nav=None, price_nav=None, status="missing_held_close", missing_symbols=["SPY"]
    )
    final.pop("dividend_receivable")
    result = verifier.reconcile_account(account, declaration, data)
    assert result["missing_held_marks"] == 1
    assert (
        verifier.independent_score(account, "2026-09-02", "2026-09-04")["total_gain"]
        is None
    )
    final["nav"] = account["sessions"][-2]["nav"]
    with pytest.raises(ValueError, match="Missing held NAV"):
        verifier.reconcile_account(account, declaration, data)


# Preserve a missing benchmark entry as an unavailable comparison.
def test_unavailable_benchmark_entry_cannot_be_substituted(tmp_path):
    from dataclasses import replace

    from backend.market.live_policy_replay import run_benchmark

    panel, raw, cubes = fixture()
    opening = raw.session_open.copy()
    opening[1, 1] = np.nan
    account = run_benchmark(
        panel, replace(raw, session_open=opening), tmp_path / "source", 1, 2, 10, "SPY"
    )
    declaration = spec("SPY")
    account["comparison_account"] = declaration
    data = direct_data(raw, cubes)
    data["cubes"]["SPY"]["open"][1, 0] = np.nan
    verifier.reconcile_account(account, declaration, data)
    assert (
        verifier.independent_score(account, "2026-09-02", "2026-09-04")[
            "benchmark_reference_available"
        ]
        is False
    )
    account["entry"]["status"] = "filled_opening_proxy"
    with pytest.raises(ValueError, match="entry"):
        verifier.reconcile_account(account, declaration, data)


# Supply explicit hand-valued records for independent era and completeness calculations.
def valued_account(nav=(100.0, 110.0, 105.0)):
    return {
        "sessions": [
            {
                "session": day,
                "initial": index == 0,
                "nav": value,
                "price_nav": value,
                "cash": 10.0 if value else 0.0,
                "dividend_receivable": 0.0,
            }
            for index, (day, value) in enumerate(
                zip(("2020-12-31", "2021-01-04", "2021-01-05"), nav, strict=True)
            )
        ],
        "fills": [
            {
                "at": "2021-01-04T14:30:00+00:00",
                "client_order_id": "buy",
                "requested_qty": 1,
                "filled_qty": 1,
                "price": 20.0,
                "fee": 0.02,
            }
        ],
        "attempts": [],
        "intents": [],
    }


# Retain the funded baseline, adjacent returns and positive-loss drawdown.
def test_fixed_era_metrics_follow_hand_calculation():
    score = verifier.independent_score(valued_account(), "2021-01-01", "2026-10-01")
    assert score["total_gain"] == pytest.approx(0.05)
    assert score["cagr"] == pytest.approx(1.05**126 - 1)
    assert score["drawdown_positive_loss"] == pytest.approx(1 - 105 / 110)
    returns = [0.1, 105 / 110 - 1]
    deviation = math.sqrt(sum((value - sum(returns) / 2) ** 2 for value in returns) / 2)
    assert score["sharpe"] == pytest.approx(
        sum(returns) / 2 * math.sqrt(252) / deviation
    )
    assert score["realized_turnover"] == 0.2
    assert score["realized_notional"] == 20.0
    assert score["fees"] == 0.02


# Keep endpoint gain, interior-gap risk limits and bankruptcy distinct.
@pytest.mark.parametrize(
    ("nav", "status", "gain"),
    [
        ((100, None, 105), "missing_wealth_observations", 0.05),
        ((100, 110, None), "missing_wealth_observations", None),
        ((100, 110, 0), "zero_wealth", -1.0),
    ],
)
def test_missing_and_zero_nav_are_distinct(nav, status, gain):
    score = verifier.independent_score(valued_account(nav), "2021-01-01", "2026-10-01")
    assert score["status"] == status
    assert (
        score["total_gain"] == pytest.approx(gain)
        if gain is not None
        else score["total_gain"] is None
    )
    assert score["sharpe"] is None
    assert score["cagr"] == (-1.0 if gain == -1 else None)


# Count refused retries as attempts while preserving their one original unmet intent.
def test_refusal_retry_metrics_preserve_quantity_basis():
    account = valued_account()
    account["fills"] = []
    refused = {
        "at": "2021-01-04T14:45:00+00:00",
        "client_order_id": "blocked",
        "qty": 8,
        "accepted": False,
    }
    account["attempts"] = [refused, {**refused, "at": "2021-01-04T15:00:00+00:00"}]
    account["intents"] = [
        {
            "client_order_id": "blocked",
            "qty": 8,
            "symbol": "AAA",
            "session": "2020-12-31",
        }
    ]
    score = verifier.independent_score(account, "2021-01-01", "2026-10-01")
    assert score["refused_attempt_quantity"] == 16
    assert score["refused_unique_intents"] == 1
    assert score["refused_attempts"] == 2
    assert score["unexecuted_original_intents"] == 1
    assert score["remaining_original_qty_by_symbol"] == {"AAA": 8}


# Retain all fixed starts, unavailable benchmark excess and common paired risk counts.
def test_grid_and_independent_pairs_retain_every_start():
    _, sessions = calendar.reviewed_sessions()
    days = np.arange(np.datetime64("2018-01-31"), np.datetime64("2026-10-01"))
    dates = days[np.is_busday(days, busdaycal=sessions)]
    grid = verifier.fixed_grid(dates)
    assert len(grid) == 300
    assert sum(row["arm"] in verifier.ARMS for row in grid) == 180
    rows = []
    for row in grid:
        gain = {"rule": 0.1, "boosting": 0.12, "ridge": 0.09, "SPY": 0.11, "QQQ": 0.13}[
            row["arm"]
        ]
        score = {
            "status": "complete",
            "total_gain": gain,
            "benchmark_reference_available": row["arm"] in verifier.BENCHMARKS,
        }
        if row["arm"] == "boosting" and row["start"] == 3:
            score["status"] = "missing_wealth_observations"
        if row["arm"] == "QQQ" and row["start"] == 7:
            score["benchmark_reference_available"] = False
        rows.append(
            {**row, "scores": {name: dict(score) for name, _, _ in verifier.WINDOWS}}
        )
    summary = verifier.independent_summary(rows)
    assert len(summary) == 24
    assert summary[0]["endpoint_pairs"] == 20
    assert summary[0]["complete_risk_pairs"] == 19
    assert summary[0]["count_better"] == 20
    assert summary[0]["median_gain_difference"] == pytest.approx(0.02)
    assert summary[0]["pairs"][7]["benchmark_excess"]["QQQ"] is None


# Reject missing fixed-grid accounts before decoding anything from a reduced report.
def test_missing_account_declaration_rejected(tmp_path):
    _, sessions = calendar.reviewed_sessions()
    days = np.arange(np.datetime64("2018-01-31"), np.datetime64("2026-10-01"))
    data = {"dates": days[np.is_busday(days, busdaycal=sessions)]}
    grid = verifier.fixed_grid(data["dates"])
    report = {
        "status": "complete_pending_independent_verification",
        "policy": verifier.POLICY,
        "adoption_eligible": False,
        "accounts": [],
    }
    with pytest.raises(ValueError, match="accounts missing"):
        verifier.verify_saved(tmp_path, report, {"accounts": grid}, data)


# Reject false nulls, booleans, nonfinite JSON and duplicate evidence fields.
@pytest.mark.parametrize(
    "payload", [b'{"cash": NaN}', b'{"cash": Infinity}', b'{"cash": 1, "cash": 2}']
)
def test_ambiguous_json_is_rejected(payload):
    with pytest.raises(ValueError, match="Nonfinite|Duplicate"):
        verifier.decode(payload)


# Detect changed original bytes and originally missing evidence.
def test_original_input_hashes_and_absence_are_checked(tmp_path):
    present, absent = tmp_path / "original", tmp_path / "missing"
    present.write_bytes(b"original")
    files = {str(present): hashlib.sha256(b"original").hexdigest(), str(absent): None}
    verifier.check_originals(files)
    absent.write_bytes(b"new")
    with pytest.raises(ValueError, match="absent input appeared"):
        verifier.check_originals(files)
    absent.unlink()
    present.write_bytes(b"changed")
    with pytest.raises(ValueError, match="input changed"):
        verifier.check_originals(files)


# Require every equality check to preserve null/boolean meaning and nested schemas.
@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (0, None),
        (1, True),
        (True, 1),
        ({"a": 1}, {"a": 1, "b": 0}),
        (float("nan"), 0.0),
    ],
)
def test_nested_evidence_comparison_rejects_false_equivalence(actual, expected):
    with pytest.raises(ValueError, match="differ|required"):
        verifier.same(actual, expected)


# Supply a complete synthetic producer manifest distinct from verifier source.
@pytest.fixture(scope="module")
def source_identity_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp("independent_source_identity")
    names = (
        verifier.PROTOCOL,
        "backend/cli/market_actual_policy_timing.py",
        "backend/market/live_policy_replay.py",
        "backend/market/replay_broker.py",
        "backend/cli/market_daily.py",
        "backend/market/live_execution_inputs.py",
        "backend/market/live_policy_report.py",
        "backend/market/live_policy_features.py",
        "backend/market/live_probability_timing.py",
    )
    files = {}
    for name in (
        *names,
        *(f"synthetic/{index}.txt" for index in range(2300 - len(names))),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic source identity fixture")
        files[name] = verifier.digest(path)
    # The protocol itself uses the actual frozen bytes even in this synthetic tree.
    path = root / verifier.PROTOCOL
    path.write_bytes(
        (Path(verifier.__file__).resolve().parents[2] / verifier.PROTOCOL).read_bytes()
    )
    files[verifier.PROTOCOL] = verifier.digest(path)
    revision = "a" * 40
    manifest_path = root / "source-manifest.json"
    manifest_path.write_text(json.dumps({"git_commit": revision, "files": files}))
    identity = {
        "source": {
            "git_commit": revision,
            "files": len(files),
            "manifest_sha256": verifier.digest(manifest_path),
        },
        "policy": verifier.POLICY,
        "protocol_sha256": verifier.PROTOCOL_SHA,
        "models_fitted": 0,
        "adoption_eligible": False,
        "availability": (
            "current_vintage_grades_universe_and_history_not_exact_live_reconstruction"
        ),
        "sizing": "unchanged_actual_graded_equal_weight_5",
        "holding_exits": "unchanged_grade_reset_FOMC_paths",
        "dividends": "unspendable_receivables_unknown_payment_dates_no_reinvestment",
        "fills": (
            "conditional_original_raw_SIP_proxy_not_proven_broker_or_midpoint_fills"
        ),
        "runtime": {
            "image_id": "pinned-synthetic-image",
            "python": "synthetic",
            "numpy": "synthetic",
            "platform": "synthetic",
            "container_hostname": "synthetic",
            "thread_limits": {"OMP_NUM_THREADS": "1"},
        },
        "restored_models": {
            name: {
                "status": "VERIFIED_SAVED_DISTRIBUTIONS",
                "no_refit_or_recalibration": True,
            }
            for name in ("boosting", "ridge")
        },
    }
    return root, manifest_path, revision, identity


# Authenticate producer bytes through the explicit producer source mount.
def test_producer_and_verifier_source_are_separate(source_identity_fixture):
    root, manifest, revision, identity = source_identity_fixture
    verifier.check_identity(
        identity, manifest, revision, "pinned-synthetic-image", root
    )
    with pytest.raises(ValueError, match="differs|required"):
        verifier.check_identity(
            identity,
            manifest,
            revision,
            "pinned-synthetic-image",
            root / "unrelated-verifier-source",
        )


# Reject relabelled provenance, adoption, image or model receipts.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("availability", "historically verified"),
        ("models_fitted", 1),
        ("adoption_eligible", True),
        ("policy", "another policy"),
        ("protocol_sha256", "b" * 64),
        ("dividends", "reinvested"),
        ("fills", "actual broker fills"),
    ],
)
def test_identity_limitation_tamper_rejected(source_identity_fixture, field, value):
    root, manifest, revision, original = source_identity_fixture
    identity = copy.deepcopy(original)
    identity[field] = value
    with pytest.raises(ValueError, match="differs|required|missing"):
        verifier.check_identity(
            identity, manifest, revision, "pinned-synthetic-image", root
        )


# Require an exact pinned producer image rather than merely copying its runtime string.
def test_wrong_pinned_producer_image_rejected(source_identity_fixture):
    root, manifest, revision, identity = source_identity_fixture
    with pytest.raises(ValueError, match="image differs"):
        verifier.check_identity(identity, manifest, revision, "another-image", root)


# Verify a fresh proof from actual synthetic archives and original hash checks.
def test_independent_proof_workflow_and_fresh_output(tmp_path, monkeypatch):
    from backend.cli import market_actual_policy_timing as producer

    account, declaration, data = actual_account(tmp_path / "producer")
    study = tmp_path / "study"
    row = saved_archive(study, account, declaration)
    row.update(
        scores={
            name: producer.account_score(account, lower, upper)
            for name, lower, upper in verifier.WINDOWS
        },
        fill_records=len(account["fills"]),
        intents=len(account["intents"]),
        forecast_decisions=0,
    )
    original = tmp_path / "original"
    original.write_bytes(b"original synthetic input")
    identity = {
        "accounts": [declaration],
        "original_files": {str(original): verifier.digest(original)},
        "source": {"git_commit": "a" * 40},
        "runtime": {"image_id": "synthetic-image"},
    }
    (study / "identity.json").write_text(json.dumps(identity))
    report = {
        "status": "complete_pending_independent_verification",
        "policy": verifier.POLICY,
        "adoption_eligible": False,
        "identity_sha256": verifier.digest(study / "identity.json"),
        "accounts": [row],
    }
    (study / "report.json").write_text(json.dumps(report))
    # Synthetic adapters bypass only external dataset/source identity, never accounting.
    monkeypatch.setattr(verifier, "check_identity", lambda *args: None)
    monkeypatch.setattr(verifier, "load_original_data", lambda *args: data)
    saved_checker = verifier.verify_saved
    monkeypatch.setattr(
        verifier, "verify_saved", lambda *args: saved_checker(*args, grid=[declaration])
    )
    args = SimpleNamespace(
        study=study,
        output=tmp_path / "proof",
        producer_source=tmp_path / "source",
        source_manifest=tmp_path / "manifest",
        source_revision="a" * 40,
        producer_image="synthetic-image",
        verifier_revision="b" * 40,
        verifier_image="separate-verifier-image",
    )
    proof = verifier.verify(args)
    assert proof["verified"]["accounts"] == 1
    assert proof["models_called"] == proof["accounts_resimulated"] == 0
    assert proof["verifier_source_revision"] == "b" * 40
    assert proof["producer_source"]["git_commit"] == "a" * 40
    assert proof["adoption_eligible"] is False
    assert (
        "all_name_corporate_action_declaration_history_and_payment_completeness"
        in proof["unverified"]
    )
    assert (args.output / "proof.json").is_file()
    with pytest.raises(ValueError, match="Fresh"):
        verifier.verify(args)
