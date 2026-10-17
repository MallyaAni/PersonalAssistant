"""Keep original-only audit admission and bounded loader semantics explicit."""

import json
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import audit_original_live_model_history as cli
from backend.market import live_model_history_audit_inputs as inputs
from backend.market.live_execution_inputs import PassiveMarks
from backend.tests.test_live_execution_inputs import terminal_inputs


# Write externally pinned test metadata without evaluating a model or account.
def write(path, value):
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


# Construct a selected actual-inspect-shaped fixture with only one writable proof bind.
def runtime(tmp_path):
    row = {
        "Id": "a" * 64,
        "Image": cli.IMAGE,
        "Config": {"Hostname": "a" * 12, "User": "1000:1000"},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "NanoCpus": 1_000_000_000,
            "Memory": 2 * 1024**3,
            "MemorySwap": 2 * 1024**3,
            "Privileged": False,
            "Tmpfs": {"/tmp": "rw,size=64m"},
        },
        "Mounts": [
            {"Destination": name, "Source": name, "RW": False, "Type": "bind"}
            for name in (
                "/account",
                "/private",
                str(cli.Path(__file__).resolve().parents[2]),
            )
        ]
        + [{"Destination": "/proof", "Source": "/proof", "RW": True, "Type": "bind"}],
    }
    path = tmp_path / "runtime.json"
    value = {
        "runtime": str(path),
        "runtime_sha256": write(path, [row]),
        "account": "/account",
        "market": "/private",
        "proof_parent": "/proof",
    }
    return value, row


# Check actual resource and source-data isolation rather than trusting a health status.
def test_native_runtime_exact_admission(tmp_path):
    value, _ = runtime(tmp_path)
    result = cli.runtime_admission(value, hostname="a" * 12, uid=1000)
    assert result["image"] == cli.IMAGE
    assert result["uid"] == 1000


# Every weakened container constraint fails before any numerical input can be loaded.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("NetworkMode", "bridge"),
        ("ReadonlyRootfs", False),
        ("NanoCpus", 2_000_000_000),
        ("Memory", 4 * 1024**3),
        ("MemorySwap", 4 * 1024**3),
        ("Privileged", True),
        ("CapAdd", ["SYS_ADMIN"]),
        ("Devices", [{}]),
        ("Tmpfs", {"/app": "rw,size=64m"}),
    ],
)
def test_runtime_resource_corruptions_fail(tmp_path, field, value):
    config, row = runtime(tmp_path)
    row["HostConfig"][field] = value
    config["runtime_sha256"] = write(cli.Path(config["runtime"]), [row])
    with pytest.raises(ValueError, match="AUDIT"):
        cli.runtime_admission(config, hostname="a" * 12, uid=1000)


# An additional writable input or an absent readonly account mount cannot pass.
@pytest.mark.parametrize(
    "route",
    [
        "account-rw",
        "account-absent",
        "extra-rw",
        "wrong-proof",
        "wrong-image",
        "root-user",
        "wrong-host",
    ],
)
def test_runtime_identity_and_mount_corruptions_fail(tmp_path, route):
    value, row = runtime(tmp_path)
    if route == "account-rw":
        row["Mounts"][0]["RW"] = True
    elif route == "account-absent":
        row["Mounts"].pop(0)
    elif route == "extra-rw":
        row["Mounts"].append({"Destination": "/extra", "RW": True, "Type": "bind"})
    elif route == "wrong-proof":
        row["Mounts"][-1]["Destination"] = "/different"
    elif route == "wrong-image":
        row["Image"] = "sha256:" + "b" * 64
    elif route == "root-user":
        row["Config"]["User"] = "0"
    else:
        row["Config"]["Hostname"] = "b" * 12
    value["runtime_sha256"] = write(cli.Path(value["runtime"]), [row])
    with pytest.raises(ValueError, match="AUDIT|PROOF"):
        cli.runtime_admission(value, hostname="a" * 12, uid=1000)


# A root caller cannot claim the required unprivileged audit UID through its receipt.
def test_actual_uid_is_independently_checked(tmp_path):
    value, _ = runtime(tmp_path)
    with pytest.raises(ValueError, match="RUNTIME"):
        cli.runtime_admission(value, hostname="a" * 12, uid=0)


# Passive alignment preserves every value and missing cell, with no later carry-forward.
def test_passive_marks_keep_inherited_missingness_and_independent_order():
    dates = np.array(["2019-03-01", "2019-03-04"], dtype="datetime64[D]")
    opening = np.array([[10.0, np.nan], [11.0, 20.0]])
    observed = np.repeat(opening[:, None, :], 26, axis=1)
    passive = PassiveMarks(
        dates,
        ("VMW", "KD"),
        opening,
        observed,
        opening + 1,
        {"complete_through": {"VMW": "2019-03-04", "KD": "2019-03-04"}},
    )
    before = opening.copy()
    result = inputs.align_passive(
        np.array(
            ["2019-02-28", "2019-03-01", "2019-03-04", "2019-03-05"],
            dtype="datetime64[D]",
        ),
        passive,
    )
    assert result.tickers == ("VMW", "KD")
    np.testing.assert_array_equal(result.session_open[1:3], opening)
    assert np.isnan(result.session_open[[0, 3]]).all()
    assert np.isnan(result.observation_close[1, :, 1]).all()
    np.testing.assert_array_equal(opening, before)
    assert result.provenance["later_marks"] == "missing_not_invented"


# A passive day absent from the panel cannot be silently shifted to the next session.
def test_passive_calendar_gap_fails():
    passive = PassiveMarks(
        np.array(["2019-03-04"], dtype="datetime64[D]"),
        ("KD",),
        np.ones((1, 1)),
        np.ones((1, 26, 1)),
        np.ones((1, 1)),
        {},
    )
    with pytest.raises(ValueError, match="PASSIVE_CALENDAR"):
        inputs.align_passive(np.array(["2019-03-01"], dtype="datetime64[D]"), passive)


# Original loader extraction stops before a full intraday-grid allocation.
def test_daily_prefix_uses_exact_pinned_source(monkeypatch, tmp_path):
    source = inputs.inspect.getsource(inputs.continuation.inputs)
    assert sha256(source.encode()).hexdigest() == inputs.DAILY_FUNCTION_SHA256
    calls = []

    # A deliberately changed callable must fail admission before execution.
    def different(*args):
        calls.append(args)

    monkeypatch.setattr(inputs.continuation, "inputs", different)
    with pytest.raises(ValueError, match="ORIGINAL_DAILY_LOADER"):
        inputs.daily_prefix(tmp_path, None, None)
    assert not calls


# Byte-authenticated command paths retain exact option identity and do not use defaults.
def test_economic_paths_duplicate_option_fails(monkeypatch):
    command = ["study", "--actions", "/a", "--actions", "/different"]
    monkeypatch.setattr(
        inputs,
        "pinned",
        lambda *args: json.dumps({"commands": {"study": command}}).encode(),
    )
    with pytest.raises(ValueError, match="UNIQUE"):
        inputs.economic_paths()


# Complete-profile admission refuses a running producer even with an authentic hash.
def test_full_profile_requires_completed_original_producer(tmp_path):
    row = {
        "Id": cli.FULL_CONTAINER,
        "Image": "sha256:" + "b" * 64,
        "State": {"Running": True, "ExitCode": 0, "OOMKilled": False},
        "HostConfig": {},
        "Config": {},
    }
    path = tmp_path / "producer.json"
    value = {
        "profile": "original-full-27471",
        "producer_runtime": str(path),
        "producer_runtime_sha256": write(path, [row]),
    }
    with pytest.raises(ValueError, match="SUCCESSFUL_ORIGINAL"):
        cli.producer_admission(value)


# A bounded source profile cannot receive the full producer-runtime acceptance label.
def test_test_profile_limits_are_explicit():
    value = {
        "profile": "complete-private-v10",
        "producer_runtime": None,
        "producer_runtime_sha256": None,
    }
    assert cli.producer_admission(value) == "UNAVAILABLE_PRIVATE_TEST_PROFILE_ONLY"
    value["producer_runtime"] = "/forged"
    with pytest.raises(ValueError, match="TEST_PROFILE"):
        cli.producer_admission(value)


# Independent exchange dates detect omissions even when panel dates also omit them.
def test_calendar_admission_rejects_omitted_exchange_session():
    archives = SimpleNamespace(
        completion={
            "first": "2019-03-01",
            "through": "2019-03-04",
            "sessions": [{"session": "2019-03-01"}],
        }
    )
    with pytest.raises(ValueError, match="COMPLETE_EXCHANGE"):
        cli.calendar_admission(archives, "complete-private-v10")


# The loader makes raw economic arrays readonly without modifying their values or type.
def test_readonly_inputs_reject_mutation():
    fields = {name: None for name in inputs.RawExecutionInputs.__dataclass_fields__}
    fields.update(
        dates=np.array(["2019-03-01"], dtype="datetime64[D]"),
        daily_close=np.array([[10.25]]),
        tickers=("SPY",),
    )
    raw = inputs.RawExecutionInputs(**fields)
    result = inputs.readonly(raw)
    assert result is raw
    with pytest.raises(ValueError, match="read-only"):
        result.daily_close[0, 0] = 10.0


# Runtime validation does not mutate the independently pinned inspect representation.
def test_runtime_receipt_remains_unchanged(tmp_path):
    value, row = runtime(tmp_path)
    before = deepcopy(row)
    cli.runtime_admission(value, hostname="a" * 12, uid=1000)
    assert before == row


# The complete reviewed path retains inherited terminal declarations and event order.
def test_reviewed_economics_retains_terminal_source_order(tmp_path, monkeypatch):
    fixture = terminal_inputs()
    old_panel, passive = fixture["panel"], fixture["passive"]
    panel = SimpleNamespace(
        dates=np.append(old_panel.dates, np.datetime64("2026-09-16")),
        tickers=old_panel.tickers,
    )
    paths = SimpleNamespace(
        **{
            name: tmp_path / name
            for name in (
                "economic_input_proof",
                "actions",
                "action_review",
                "passive_arrays",
                "passive_receipt",
            )
        }
    )
    with paths.passive_arrays.open("wb") as stream:
        np.savez(stream, dates=old_panel.dates)
    original = {
        "basis_as_of": fixture["basis_as_of"],
        "complete_through": fixture["complete_through"],
    }
    compiled = {
        "unresolved": [],
        "scope": {"first_session": "2018-02-01", "last_session": "2026-09-30"},
        "execution_readiness": "pending_declaration_receipts",
        "actions": fixture["actions"],
        "inherited_actions": fixture["inherited_actions"],
    }

    # Substitute only metadata transport; actual economic normalization stays real.
    def metadata(path, expected):
        if path == paths.economic_input_proof:
            return b'{"status":"VERIFIED_INDEPENDENT_REVIEWED_ORIGINAL_INPUTS"}'
        return json.dumps(original).encode() if path == paths.actions else b"{}"

    monkeypatch.setattr(inputs, "pinned", metadata)
    monkeypatch.setattr(inputs, "authenticate_file", lambda *args: None)
    monkeypatch.setattr(inputs, "review_action_export", lambda *args: compiled)
    monkeypatch.setattr(inputs.economics, "load_passive_inputs", lambda *args: passive)
    events = {
        "AAA": [
            {"date": "2026-09-16", "kind": "dividend", "value": 3.0},
            {"date": "2026-09-14", "kind": "dividend", "value": 999.0},
        ],
        "SPY": [],
    }
    factors = np.array([[2.0, 1.0], [1.0, 1.0], [1.0, 1.0]])
    before = deepcopy(compiled)
    actions, aligned, inherited = inputs.reviewed_economics(
        panel, factors, events, paths
    )
    assert list(actions) == list(panel.tickers)
    assert [row["date"] for row in actions["AAA"]] == ["2026-09-15", "2026-09-16"]
    assert actions["AAA"][1]["value"] == 3.0
    assert inherited["CHILD"][0]["value"] == 142.5
    assert inherited["CHILD"][0]["completed_before"] == "2026-09-15T09:30:00-04:00"
    assert np.isnan(aligned.daily_close[1:]).all()
    assert aligned.tickers == ("CHILD",)
    assert "CHILD" not in panel.tickers
    assert compiled == before
    factors[0, 0] += 0.01
    with pytest.raises(ValueError, match="FACTORS_DIFFER"):
        inputs.reviewed_economics(panel, factors, events, paths)


# Writable proof aliases must not expose a readonly original host directory to writes.
def test_runtime_proof_cannot_alias_original_host_path(tmp_path):
    value, row = runtime(tmp_path)
    row["Mounts"][-1]["Source"] = "/account/new-proof"
    value["runtime_sha256"] = write(cli.Path(value["runtime"]), [row])
    with pytest.raises(ValueError, match="OVERLAPS"):
        cli.runtime_admission(value, hostname="a" * 12, uid=1000)


# The actual final state must match pinned completion content and retain its bytes.
def test_all_archives_and_physical_state_are_rechecked(tmp_path):
    folder = tmp_path / "state/paper"
    folder.mkdir(parents=True)
    (tmp_path / "sessions").mkdir()
    path = tmp_path / "sessions/2019-03-01.json.gz"
    path.write_bytes(b"original saved compressed bytes")
    state = folder / "state.json"
    expected = asdict(cli.paper.PaperState())
    state.write_text(json.dumps(expected))
    archives = SimpleNamespace(
        root=tmp_path,
        completion={
            "sessions": [
                {
                    "session": "2019-03-01",
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
            ]
        },
        ending_state=cli.digest(expected),
    )
    before = cli.preserved_archives(archives)
    assert len(before) == 2
    state.write_text(json.dumps({**expected, "pending": [1]}))
    with pytest.raises(ValueError, match="PHYSICAL_STATE_DIFFERS"):
        cli.preserved_archives(archives)
    state.write_text(json.dumps(expected))
    path.write_bytes(b"changed saved compressed bytes")
    with pytest.raises(ValueError, match="bytes differ"):
        cli.preserved_archives(archives)


# Only physical state uses source-pinned nonfinite-to-null export semantics.
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_physical_missing_literals_match_original_export(literal):
    value = asdict(cli.paper.PaperState())
    value["allocation_state"] = {"missing": None}
    raw = json.dumps(value).replace('"missing": null', '"missing": ' + literal).encode()
    assert cli.physical_state(raw) == value
    with pytest.raises(ValueError, match="Nonfinite"):
        cli.strict_json(raw)


# Duplicate members, numeric overflow, and incomplete physical schemas still fail.
@pytest.mark.parametrize("route", ["duplicate", "overflow", "schema"])
def test_physical_missing_decoder_does_not_weaken_other_admission(route):
    value = asdict(cli.paper.PaperState())
    value["allocation_state"] = {"x": 1.0}
    raw = json.dumps(value).encode()
    if route == "duplicate":
        raw = raw[:-1] + b',"pending":[]}'
    elif route == "overflow":
        raw = raw.replace(b'"x": 1.0', b'"x": 1e999')
    else:
        raw = b"{}"
    with pytest.raises(ValueError, match="DUPLICATE|NONFINITE|SCHEMA"):
        cli.physical_state(raw)


# Build a synthetic full producer solely to test exact immutable runtime rejection.
def producer(tmp_path):
    mounts = [
        ("/app", "/original-source", "ro"),
        ("/private", "/original-inputs", "ro"),
        ("/output", str(cli.Path(cli.FULL_ACCOUNT).parent), "rw"),
    ]
    command = ["docker", "run"]
    for target, host, mode in mounts:
        command += ["-v", host + ":" + target + ":" + mode]
    command += [
        cli.PRODUCER_IMAGE,
        "python",
        "-m",
        "backend.cli.market_live_model_history",
        "--output",
        "/output/account",
    ]
    execution = tmp_path / "execution.json"
    runtime_path = tmp_path / "producer.json"
    row = {
        "Id": cli.FULL_CONTAINER,
        "Image": cli.PRODUCER_IMAGE,
        "State": {"Running": False, "ExitCode": 0, "OOMKilled": False},
        "Config": {"User": "1000:1000"},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "NanoCpus": 1_000_000_000,
            "Memory": 4 * 1024**3,
            "Privileged": False,
        },
        "Mounts": [
            {"Source": host, "Destination": target, "RW": mode == "rw", "Type": "bind"}
            for target, host, mode in mounts
        ],
    }
    value = {
        "profile": "original-full-27471",
        "producer_runtime": str(runtime_path),
        "producer_runtime_sha256": write(runtime_path, [row]),
        "execution": str(execution),
        "execution_sha256": write(
            execution, {"real_orders": False, "command": command}
        ),
    }
    return value, row


# A genuine completed producer identity binds all receipt mounts and its sole output.
def test_original_producer_exact_identity(tmp_path):
    value, _ = producer(tmp_path)
    assert cli.producer_admission(value)["image"] == cli.PRODUCER_IMAGE


# Wrong image, UID, resources, network, and output aliases fail before model loading.
@pytest.mark.parametrize(
    "route", ["image", "uid", "memory", "cpu", "network", "writable", "mount", "output"]
)
def test_original_producer_runtime_corruptions_fail(tmp_path, route):
    value, row = producer(tmp_path)
    if route == "image":
        row["Image"] = cli.IMAGE
    elif route == "uid":
        row["Config"]["User"] = "0"
    elif route == "memory":
        row["HostConfig"]["Memory"] *= 2
    elif route == "cpu":
        row["HostConfig"]["NanoCpus"] *= 2
    elif route == "network":
        row["HostConfig"]["NetworkMode"] = "bridge"
    elif route == "writable":
        row["Mounts"][0]["RW"] = True
    elif route == "mount":
        row["Mounts"][0]["Source"] = "/different"
    else:
        row["Mounts"][-1]["Source"] = "/different"
        execution = json.loads(cli.Path(value["execution"]).read_bytes())
        execution["command"][7] = "/different:/output:rw"
        value["execution_sha256"] = write(cli.Path(value["execution"]), execution)
    value["producer_runtime_sha256"] = write(cli.Path(value["producer_runtime"]), [row])
    with pytest.raises(ValueError, match="PRODUCER|ORIGINAL_OUTPUT"):
        cli.producer_admission(value)


# Bind every real audit implementation while keeping the Git corpus fixture synthetic.
def source_fixture(tmp_path):
    root = cli.Path(cli.__file__).resolve().parents[2]
    names = (
        "backend/cli/audit_original_live_model_history.py",
        "backend/cli/verify_actual_policy_timing.py",
        "backend/cli/verify_live_model_history.py",
        "backend/market/live_model_history_audit_inputs.py",
        "backend/market/live_model_history_stream_audit.py",
        "backend/market/live_model_history_pending_audit.py",
        "backend/market/live_model_history_observation_context.py",
        "backend/market/live_model_history_nightly_model.py",
        "backend/market/live_model_history_nightly_audit.py",
        "backend/market/live_model_history_receipts.py",
        "backend/market/live_model_history_input_auth.py",
        "backend/market/live_model_history_binding.py",
        "backend/market/live_policy_replay.py",
        "backend/agents/trading/desk/paper.py",
    )
    actual = {name: sha256((root / name).read_bytes()).hexdigest() for name in names}
    original = {f"original-{number}": "b" * 64 for number in range(2431)}
    path = tmp_path / "git-map.json"
    record = {"revision": cli.FULL_REVISION, "files": original}
    value = {
        "profile": "original-full-27471",
        "audit_source_sha256": actual,
        "git_map": str(path),
        "git_map_sha256": write(path, record),
    }
    return value, SimpleNamespace(sources=original), record


# The full profile requires the exact external complete Git map, not a revision string.
def test_exact_full_source_map_admission(tmp_path):
    value, archives, _ = source_fixture(tmp_path)
    result = cli.source_admission(value, archives)
    assert result["files"] == 2431
    assert result["revision"] == cli.FULL_REVISION


# Every executed verifier dependency needs its own independently supplied source pin.
@pytest.mark.parametrize(
    "name",
    [
        "backend/cli/verify_actual_policy_timing.py",
        "backend/cli/verify_live_model_history.py",
    ],
)
def test_executed_verifier_dependency_pin_is_required(tmp_path, name):
    value, archives, _ = source_fixture(tmp_path)
    value["audit_source_sha256"].pop(name)
    with pytest.raises(ValueError, match="ALL_AUDIT_COMPONENT_SOURCE_PINS_REQUIRED"):
        cli.source_admission(value, archives)


# A different valid source digest cannot substitute for an executed verifier's bytes.
@pytest.mark.parametrize(
    "name",
    [
        "backend/cli/verify_actual_policy_timing.py",
        "backend/cli/verify_live_model_history.py",
    ],
)
def test_executed_verifier_dependency_pin_cannot_be_substituted(tmp_path, name):
    value, archives, _ = source_fixture(tmp_path)
    value["audit_source_sha256"][name] = value["audit_source_sha256"][
        "backend/cli/audit_original_live_model_history.py"
    ]
    with pytest.raises(ValueError, match="Pinned stream input bytes differ"):
        cli.source_admission(value, archives)


# Later changes to a private faithful source copy fail without altering native files.
@pytest.mark.parametrize(
    "name",
    [
        "backend/cli/verify_actual_policy_timing.py",
        "backend/cli/verify_live_model_history.py",
    ],
)
def test_executed_verifier_dependency_rejects_stale_actual_bytes(
    tmp_path, monkeypatch, name
):
    value, archives, _ = source_fixture(tmp_path)
    original_root = cli.Path(cli.__file__).resolve().parents[2]
    private = tmp_path / "source-copy"
    for relative in value["audit_source_sha256"]:
        copied = private / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes((original_root / relative).read_bytes())
    monkeypatch.setattr(
        cli,
        "__file__",
        str(private / "backend/cli/audit_original_live_model_history.py"),
    )
    assert cli.source_admission(value, archives)["files"] == 2431
    changed = private / name
    changed.write_bytes(changed.read_bytes() + b"\n# Private stale-source fixture.\n")
    with pytest.raises(ValueError, match="Pinned stream input bytes differ"):
        cli.source_admission(value, archives)


# A missing blob, changed digest, wrong revision or extra schema member cannot pass.
@pytest.mark.parametrize(
    "route", ["missing", "changed", "revision", "schema", "stale-pin"]
)
def test_full_git_source_corruptions_fail(tmp_path, route):
    value, archives, record = source_fixture(tmp_path)
    record = deepcopy(record)
    if route == "missing":
        record["files"].pop("original-0")
    elif route == "changed":
        record["files"]["original-0"] = "c" * 64
    elif route == "revision":
        record["revision"] = "0" * 40
    elif route == "schema":
        record["approved"] = True
    else:
        record["revision"] = "0" * 40
    result = write(cli.Path(value["git_map"]), record)
    if route != "stale-pin":
        value["git_map_sha256"] = result
    with pytest.raises(ValueError, match="BLOB_PROFILE|bytes differ"):
        cli.source_admission(value, archives)


# The bounded-only path cannot inherit a fabricated full Git authenticity assertion.
def test_private_source_profile_does_not_claim_full_git(tmp_path):
    value, archives, _ = source_fixture(tmp_path)
    value["profile"] = "complete-private-v10"
    with pytest.raises(ValueError, match="NOT_FULL_GIT"):
        cli.source_admission(value, archives)
    value["git_map"] = value["git_map_sha256"] = None
    assert cli.source_admission(value, archives) == "UNVERIFIED_TEST_PROFILE_ONLY"
