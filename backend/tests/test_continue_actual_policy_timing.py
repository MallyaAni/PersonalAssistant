"""Continuation guards and real sequential-versus-parallel account parity."""

import copy
import gzip
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from backend.cli import continue_actual_policy_timing as continuation
from backend.cli import market_actual_policy_timing as engine
from backend.tests.test_live_policy_replay import fixture, unavailable
from backend.tests.test_live_probability_timing import Provider
from backend.tests.test_market_actual_policy_timing import dates


# Build the actual fixed grid with a synthetic byte-authenticated completed prefix.
def original_study(root, completed=2):
    root.mkdir()
    (root / "accounts").mkdir()
    grid = engine.account_grid(dates())
    identity = {
        "accounts": grid,
        "policy": engine.POLICY,
        "protocol_sha256": engine.PROTOCOL_SHA,
        "models_fitted": 0,
        "adoption_eligible": False,
        "source": {"manifest_sha256": "a" * 64},
    }
    rows = []
    for spec in grid[:completed]:
        relative = f"accounts/{spec['id']}.json.gz"
        account_hash = engine.archive_account(
            root / relative, {"comparison_account": spec}
        )
        rows.append({**spec, "file": relative, "sha256": account_hash, "scores": {}})
    progress = {"completed": len(rows), "declared": len(grid), "accounts": rows}
    continuation.publish(root / "identity.json", identity)
    continuation.publish(root / "progress.json", progress)
    return identity, progress


# Supply just the isolated original container fields needed by the launch guards.
def container_identity(running=True):
    return {
        "Id": "b" * 64,
        "Image": "sha256:" + "c" * 64,
        "State": {
            "Running": running,
            "Status": "running" if running else "exited",
            "FinishedAt": "2026-10-07T18:00:00Z" if not running else "",
        },
        "Config": {"Cmd": ["python", "-m", continuation.ENGINE], "User": "1000"},
        "HostConfig": {"NetworkMode": "none"},
    }


# Accept both explicit non-root UID forms and reject changed isolation boundaries.
@pytest.mark.parametrize("user", ["1000", "1000:1000", "0", "1000:0"])
def test_inspect_checks_original_uid_and_group(monkeypatch, user):
    item = container_identity()
    item["Config"]["User"] = user
    monkeypatch.setattr(
        continuation.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps([item]).encode(),
    )
    if user in ("1000", "1000:1000"):
        assert continuation.inspect_container("original") == item
    else:
        with pytest.raises(ValueError, match="Original isolated"):
            continuation.inspect_container("original")


# A different entry point or reachable network cannot supply a research continuation.
@pytest.mark.parametrize("defect", ["network", "engine"])
def test_inspect_rejects_other_producer_or_network(monkeypatch, defect):
    item = container_identity()
    if defect == "network":
        item["HostConfig"]["NetworkMode"] = "bridge"
    else:
        item["Config"]["Cmd"][2] = "another.engine"
    monkeypatch.setattr(
        continuation.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps([item]).encode(),
    )
    with pytest.raises(ValueError, match="Original isolated"):
        continuation.inspect_container("original")


# Authenticate saved accounts and retain all pending IDs, without running an account.
def test_prepare_preserves_complete_grid_prefix_bytes_and_original_process(
    tmp_path, monkeypatch
):
    study = tmp_path / "original"
    identity, progress = original_study(study)
    original_bytes = {
        path: path.read_bytes() for path in study.rglob("*") if path.is_file()
    }
    item = container_identity()
    monkeypatch.setattr(continuation, "inspect_container", lambda _: item)
    output = tmp_path / "plan.json"
    plan = continuation.prepare(study, "original", output)
    assert plan["pending"] == identity["accounts"][len(progress["accounts"]) :]
    assert len(plan["pending"]) + len(progress["accounts"]) == 300
    assert plan["workers"] == 2
    assert {row["id"] for row in plan["execution_order"]} == {
        row["id"] for row in plan["pending"]
    }
    assert plan["models_fitted"] == 0
    assert plan["adoption_eligible"] is False
    assert item["State"]["Running"] is True
    assert output.stat().st_mode & 0o777 == 0o600
    assert all(path.read_bytes() == saved for path, saved in original_bytes.items())
    with pytest.raises(FileExistsError):
        continuation.prepare(study, "original", output)


# Refuse omissions, duplicates, reordered prefixes and inconsistent completion counts.
@pytest.mark.parametrize(
    "defect",
    [
        "grid_omit",
        "grid_duplicate",
        "prefix_order",
        "count",
        "path",
        "changed_spec",
        "policy",
    ],
)
def test_invalid_prefix_cannot_define_a_continuation(tmp_path, defect):
    identity, progress = original_study(tmp_path / "original")
    if defect == "grid_omit":
        identity["accounts"].pop()
    elif defect == "grid_duplicate":
        identity["accounts"][-1] = identity["accounts"][0]
    elif defect == "prefix_order":
        progress["accounts"].reverse()
    elif defect == "count":
        progress["completed"] += 1
    elif defect == "path":
        progress["accounts"][0]["file"] = "../external.json.gz"
    elif defect == "changed_spec":
        progress["accounts"][0]["first"] += 1
    else:
        identity["policy"] = "other-policy"
    with pytest.raises(ValueError, match="Original|original|Inconsistent|Changed"):
        continuation.validate_prefix(identity, progress)


# A matching filename cannot authenticate changed compressed or embedded account bytes.
@pytest.mark.parametrize("defect", ["bytes", "embedded_spec", "symlink"])
def test_account_authentication_rejects_changed_original_artifact(tmp_path, defect):
    root = tmp_path / "original"
    _, progress = original_study(root)
    row = progress["accounts"][0]
    path = root / row["file"]
    if defect == "bytes":
        path.write_bytes(b"changed")
    elif defect == "embedded_spec":
        path.unlink()
        row["sha256"] = engine.archive_account(path, {"comparison_account": {}})
    else:
        target = tmp_path / "external"
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises(ValueError, match="account|Account|Regular"):
        continuation.authenticate_accounts(root, progress["accounts"])


# An active original or stale terminal plan cannot start a second economic producer.
@pytest.mark.parametrize("running", [True, False])
def test_launch_refuses_active_original_and_stale_prefix_before_writes(
    tmp_path, monkeypatch, running
):
    study = tmp_path / "original"
    original_study(study)
    item = container_identity(running)
    monkeypatch.setattr(continuation, "inspect_container", lambda _: item)
    plan = tmp_path / "plan.json"
    continuation.prepare(study, "original", plan)
    if not running:
        (study / "progress.json").write_text("changed prefix")
    output = tmp_path / "continuation"
    with pytest.raises(ValueError, match="Original is active|Stale plan"):
        continuation.launch(plan, output)
    assert not output.exists()


# Duplicate keys and nonfinite values cannot alter a decoded review plan.
@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_ambiguous_plan_json_is_rejected(payload):
    with pytest.raises(ValueError, match="Duplicate|Nonfinite"):
        continuation.decode(payload)


# Compare genuine account results while retaining and checking publication clocks.
def without_publication_clock(account, started, ended):
    result = copy.deepcopy(account)
    entries = result.get("paper_state", {}).get("history", []) + [
        row["entry"]
        for row in result.get("nightlies", [])
        if "written" in row.get("entry", {})
    ]
    for row in entries:
        written = datetime.fromisoformat(row.pop("written"))
        assert started <= written <= ended
    return result


# Archive direct original-engine results without invoking the continuation wrapper.
def original_accounts(panel, raw, cubes, providers, source, specs, output):
    rows = []
    cache = engine.FeatureCache(source["manifest_sha256"])
    for spec in specs:
        root = output / "state" / spec["id"]
        if spec["arm"] in engine.BENCHMARKS:
            result = engine.run_benchmark(
                panel,
                raw,
                root,
                spec["first"],
                spec["last"],
                spec["cost_bps"],
                spec["arm"],
            )
        else:
            method = spec["arm"]
            result = engine.run_account(
                panel,
                raw,
                cubes,
                root,
                spec["first"],
                spec["last"],
                spec["cost_bps"],
                feature_reader=cache,
                reader_builder=engine.build_reader if method != "rule" else None,
                provider=providers[method].provider if method != "rule" else None,
            )
        result["comparison_account"] = spec
        relative = f"accounts/{spec['id']}.json.gz"
        account_hash = engine.archive_account(output / relative, result)
        rows.append(
            {
                **spec,
                "file": relative,
                "sha256": account_hash,
                "scores": {
                    name: engine.account_score(result, lower, upper)
                    for name, lower, upper in engine.WINDOWS
                },
                "fill_records": len(result["fills"]),
                "intents": len(result.get("intents", [])),
                "forecast_decisions": len(result.get("forecast_decisions", [])),
            }
        )
    return rows


# Run original rule, both CDF paths and ETF controls in two isolated worker processes.
@pytest.mark.parametrize(
    "case", ["normal", "missing_fill", "early_close", "missing_forecast"]
)
def test_parallel_accounts_match_complete_real_sequential_journeys(
    tmp_path, monkeypatch, case
):
    from backend.market import alpaca_trading

    # Fail if any actual planner or child process constructs an environment broker.
    def forbidden():
        raise AssertionError("Synthetic continuation attempted an external broker")

    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    supplied_dates = (
        ("2026-11-25", "2026-11-27", "2026-11-30")
        if case == "early_close"
        else ("2026-09-01", "2026-09-02", "2026-09-03")
    )
    panel, raw, cubes = fixture(supplied_dates, missing_fill=case == "missing_fill")
    providers = {
        arm: SimpleNamespace(
            provider=unavailable if case == "missing_forecast" else Provider(0).provider
        )
        for arm in ("boosting", "ridge")
    }
    specs = [
        {
            "arm": arm,
            "cost_bps": 10,
            "start": 0,
            "first": 1,
            "last": 2,
            "first_session": str(panel.dates[1]),
            "id": f"{arm}-10-0",
        }
        for arm in (*engine.ARMS, *engine.BENCHMARKS)
    ]
    source = {"manifest_sha256": "a" * 64}
    outputs = [tmp_path / name for name in ("sequential", "parallel")]
    for output in outputs:
        output.mkdir()
        (output / "accounts").mkdir()
        (output / "receipts").mkdir()
    # The original writer records publication times to whole seconds.
    started = datetime.now(UTC).replace(microsecond=0)
    expected_rows = original_accounts(
        panel, raw, cubes, providers, source, specs, outputs[0]
    )
    context = (engine, panel, raw, cubes, providers, source, str(outputs[1]))
    with ProcessPoolExecutor(
        max_workers=2,
        mp_context=multiprocessing.get_context("fork"),
        initializer=continuation.initialize_worker,
        initargs=(context,),
    ) as pool:
        actual_rows = {
            row["id"]: row for row in continuation.bounded_accounts(pool, specs)
        }
    ended = datetime.now(UTC)
    assert set(actual_rows) == {spec["id"] for spec in specs}
    for row in expected_rows:
        actual = actual_rows[row["id"]]
        assert {key: value for key, value in row.items() if key != "sha256"} == {
            key: value for key, value in actual.items() if key != "sha256"
        }
        saved = []
        for output, record in zip(outputs, (row, actual), strict=True):
            path = output / record["file"]
            assert continuation.digest(path) == record["sha256"]
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                saved.append(continuation.decode(handle.read()))
        assert without_publication_clock(
            saved[0], started, ended
        ) == without_publication_clock(saved[1], started, ended)
        if row["arm"] == "rule" and case == "normal":
            assert saved[1]["fills"][0]["filled_qty"] == 250
            assert saved[1]["fills"][0]["price"] == 99
            assert saved[1]["broker"]["holdings"] == {"AAA": 250}
        if row["arm"] in ("boosting", "ridge") and case == "normal":
            assert saved[1]["forecast_decisions"]
        if row["arm"] in ("boosting", "ridge") and case == "missing_forecast":
            assert all(
                item["state"] == "unavailable"
                for item in saved[1]["forecast_decisions"]
            )
            assert saved[1]["fills"][0]["price"] == 101
        if row["arm"] == "rule" and case == "missing_fill":
            assert saved[1]["fills"][0]["filled_qty"] == 0
            assert saved[1]["fills"][0]["reason"] == "missing_execution_price"


# A failed child prevents dispatching the rest of the grid and cannot hide the failure.
def test_failure_stops_new_dispatch_without_replaying_completed_accounts(monkeypatch):
    submitted = []

    # Return an immediate failed future without creating any economic account.
    def submit(function, spec):
        from concurrent.futures import Future

        submitted.append(spec["id"])
        future = Future()
        future.set_exception(ValueError("first failing boundary"))
        return future

    pool = SimpleNamespace(submit=submit)
    specs = [{"id": str(index)} for index in range(8)]
    with pytest.raises(ValueError, match="first failing boundary"):
        list(continuation.bounded_accounts(pool, specs))
    assert submitted == ["0", "1"]
