"""Continue the same frozen account grid with bounded, isolated workers.

Preparation is read-only apart from a new plan. Launch never stops the original
producer: it refuses a running container, a stale plan or an existing output.
The original engine stays mounted separately and unchanged. Completed accounts
are copied byte-for-byte; only unfinished accounts are executed. Independent
economic verification is still required after aggregation.
"""

import argparse
import gzip
import hashlib
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

ENGINE = "backend.cli.market_actual_policy_timing"
POLICY = "actual-policy-timing/1-research"
PROTOCOL_SHA = "8bb0b528f56dd4f43e72823e4efa8eee71631e90b6d84831c881247a70cbabcc"
SPEC_KEYS = ("arm", "cost_bps", "start", "first", "last", "first_session", "id")
_CONTEXT = None


# Reject ambiguous evidence rather than select a usable subset of accounts.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Authenticate regular files without accepting redirected source or account bytes.
def digest(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Regular evidence required")
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


# Refuse duplicate keys that can give two readers different account identities.
def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate evidence key")
        result[key] = value
    return result


# Reject nonfinite JSON evidence instead of silently accepting a malformed score.
def invalid_constant(value):
    raise ValueError(f"Nonfinite evidence: {value}")


# Decode evidence using strict object and numeric semantics.
def decode(payload):
    return json.loads(
        payload, object_pairs_hook=unique_object, parse_constant=invalid_constant
    )


# Write one private immutable artifact without overwriting a prior attempt.
def publish(path, value):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


# Validate the original complete specification and its completed prefix.
def validate_prefix(identity, progress):
    grid = identity["accounts"]
    expected = [
        (arm, cost, start)
        for cost in (0, 10, 25)
        for start in range(20)
        for arm in ("rule", "boosting", "ridge", "SPY", "QQQ")
    ]
    require(
        identity["policy"] == POLICY
        and identity["protocol_sha256"] == PROTOCOL_SHA
        and identity["models_fitted"] == 0
        and identity["adoption_eligible"] is False
        and len(grid) == len(expected),
        "Original complete frozen identity required",
    )
    for spec, (arm, cost, start) in zip(grid, expected, strict=True):
        require(
            set(spec) == set(SPEC_KEYS)
            and (spec["arm"], spec["cost_bps"], spec["start"]) == (arm, cost, start)
            and spec["id"] == f"{arm}-{cost}-{start}"
            and type(spec["first"]) is type(spec["last"]) is int
            and spec["first"] < spec["last"],
            "Changed or incomplete original account grid",
        )
    rows = progress["accounts"]
    require(
        type(progress["completed"]) is int
        and progress["completed"] == len(rows)
        and progress["declared"] == len(grid)
        and len(rows) <= len(grid),
        "Inconsistent original completed count",
    )
    for spec, row in zip(grid, rows, strict=False):
        require(
            {key: row[key] for key in SPEC_KEYS} == spec
            and row["file"] == f"accounts/{spec['id']}.json.gz",
            "Original accounts must be an unmodified completed prefix",
        )
    return grid, rows


# Check completed compressed bytes and their embedded specification, without scoring.
def authenticate_accounts(study, rows):
    for row in rows:
        path = Path(study) / row["file"]
        require(digest(path) == row["sha256"], "Completed account hash changed")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            saved = decode(handle.read())
        require(
            saved["comparison_account"] == {key: row[key] for key in SPEC_KEYS},
            "Completed account specification differs",
        )
        require(digest(path) == row["sha256"], "Account changed while inspected")


# Read current Docker state through an argument list, never shell interpolation.
def inspect_container(name):
    raw = subprocess.check_output(["docker", "inspect", name], timeout=30)
    items = decode(raw)
    require(len(items) == 1, "One original container required")
    item = items[0]
    require(
        item["Config"]["Cmd"][:3] == ["python", "-m", ENGINE]
        and item["HostConfig"]["NetworkMode"] == "none"
        and item["Config"]["User"] in ("1000", "1000:1000"),
        "Original isolated producer required",
    )
    return item


# Complete each start across all costs first, without consulting any account outcome.
def scheduling_order(specs):
    arms = ("rule", "boosting", "ridge", "SPY", "QQQ")
    return sorted(
        specs,
        key=lambda spec: (spec["start"], spec["cost_bps"], arms.index(spec["arm"])),
    )


# Snapshot a complete prefix for review without stopping or changing its producer.
def prepare(study, container, output):
    original = inspect_container(container)
    identity_path, progress_path = (
        Path(study) / "identity.json",
        Path(study) / "progress.json",
    )
    identity_bytes, progress_bytes = (
        identity_path.read_bytes(),
        progress_path.read_bytes(),
    )
    identity, progress = decode(identity_bytes), decode(progress_bytes)
    grid, rows = validate_prefix(identity, progress)
    authenticate_accounts(study, rows)
    require(identity_path.read_bytes() == identity_bytes, "Original identity changed")
    plan = {
        "version": 1,
        "original_container": original["Id"],
        "original_image": original["Image"],
        "original_study": str(Path(study).resolve()),
        "identity_sha256": hashlib.sha256(identity_bytes).hexdigest(),
        "progress_sha256": hashlib.sha256(progress_bytes).hexdigest(),
        "original_source": identity["source"],
        "identity": identity,
        "progress": progress,
        "pending": grid[len(rows) :],
        "execution_order": scheduling_order(grid[len(rows) :]),
        "workers": 2,
        "scheduler_sha256": digest(__file__),
        "models_fitted": 0,
        "adoption_eligible": False,
    }
    publish(output, plan)
    return plan


# Retain only the original declared engine arguments, with no new economic options.
def engine_arguments(command, output):
    require(command[:3] == ["python", "-m", ENGINE], "Original engine command required")
    parser = argparse.ArgumentParser(add_help=False)
    for name in (
        "snapshot",
        "provenance",
        "cubes",
        "actions",
        "input-receipt",
        "prepared",
        "moments",
        "fit-proof",
        "diagnostic",
        "probability-proof",
        "source-manifest",
        "output",
        "action-review",
        "passive-arrays",
        "passive-receipt",
        "economic-input-proof",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--reviewed-economics", action="store_true", required=True)
    args = parser.parse_args(command[3:])
    args.output = Path(output)
    return args


# Install a private cache in each child while leaving inherited inputs untouched.
def initialize_worker(context):
    global _CONTEXT
    os.umask(0o077)
    engine, panel, raw, cubes, providers, source, output = context
    _CONTEXT = (
        engine,
        panel,
        raw,
        cubes,
        providers,
        engine.FeatureCache(source["manifest_sha256"]),
        Path(output),
    )


# Execute exactly one original account using the unmodified planner and sender.
def execute_account(spec, context):
    engine, panel, raw, cubes, providers, cache, output = context
    root = output / "state" / spec["id"]
    arguments = (panel, raw, root, spec["first"], spec["last"], spec["cost_bps"])
    if spec["arm"] in engine.BENCHMARKS:
        result = engine.run_benchmark(*arguments, spec["arm"])
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
    path = output / "accounts" / (spec["id"] + ".json.gz")
    account_hash = engine.archive_account(path, result)
    row = {
        **spec,
        "file": str(path.relative_to(output)),
        "sha256": account_hash,
        "scores": {
            name: engine.account_score(result, lower, upper)
            for name, lower, upper in engine.WINDOWS
        },
        "fill_records": len(result["fills"]),
        "intents": len(result.get("intents", [])),
        "forecast_decisions": len(result.get("forecast_decisions", [])),
    }
    publish(output / "receipts" / (spec["id"] + ".json"), row)
    return row


# Dispatch a child account against its own copied process context and cache.
def worker_account(spec):
    require(_CONTEXT is not None, "Worker initialization required")
    return execute_account(spec, _CONTEXT)


# Keep at most two accounts active and stop assigning new work after any failure.
def bounded_accounts(pool, specs):
    remaining = iter(specs)
    active = {}
    for _ in range(2):
        spec = next(remaining, None)
        if spec is not None:
            active[pool.submit(worker_account, spec)] = spec
    while active:
        done, _ = wait(active, return_when=FIRST_COMPLETED)
        completed = []
        # Check the whole completed batch before submitting any additional account.
        for future in done:
            spec = active.pop(future)
            row = future.result()
            require(row["id"] == spec["id"], "Wrong worker account returned")
            completed.append(row)
        for row in completed:
            yield row
        for _ in completed:
            spec = next(remaining, None)
            if spec is not None:
                active[pool.submit(worker_account, spec)] = spec


# Restore original inputs once and distribute only unfinished accounts on Linux.
def execute(plan_path, command_path, terminal_path, output):
    require(sys.platform == "linux", "Frozen Linux image required")
    plan, terminal = (
        decode(Path(plan_path).read_bytes()),
        decode(Path(terminal_path).read_bytes()),
    )
    require(
        terminal["Id"] == plan["original_container"]
        and terminal["Image"] == plan["original_image"]
        and terminal["State"]["Running"] is False
        and terminal["State"]["Status"] == "exited"
        and terminal["State"]["FinishedAt"] not in ("", "0001-01-01T00:00:00Z")
        and plan["scheduler_sha256"] == digest(__file__)
        and plan["workers"] == 2,
        "Terminal original producer and exact reviewed scheduler required",
    )
    original = Path("/original-output/actual-study")
    require(
        digest(original / "identity.json") == plan["identity_sha256"]
        and digest(original / "progress.json") == plan["progress_sha256"],
        "Plan is stale; prepare again after original producer is terminal",
    )
    grid, rows = validate_prefix(plan["identity"], plan["progress"])
    require(plan["pending"] == grid[len(rows) :], "No omitted or repeated accounts")
    require(
        plan["execution_order"] == scheduling_order(plan["pending"]),
        "Scheduling order must depend only on declared account metadata",
    )
    authenticate_accounts(original, rows)
    from backend.cli import market_actual_policy_timing as engine

    args = engine_arguments(decode(Path(command_path).read_bytes()), output)
    source = engine.source_identity(args)
    require(source == plan["original_source"], "Original engine source changed")
    require(
        engine.runtime_identity()["image_id"] == plan["original_image"],
        "Original pinned runtime image required",
    )
    panel, raw, cubes, providers, files = engine.load_inputs(args)
    require(
        engine.account_grid(panel.dates) == grid
        and files == plan["identity"]["original_files"],
        "Original model, data and complete grid required",
    )
    engine.check_original_files(files)
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    for name in ("accounts", "receipts"):
        (output / name).mkdir(mode=0o700)
    identity = {
        **plan["identity"],
        "runtime": engine.runtime_identity(),
        "continuation": {
            "plan_sha256": digest(plan_path),
            "scheduler_sha256": digest(__file__),
            "original_container": terminal["Id"],
            "terminal_receipt_sha256": digest(terminal_path),
            "reused_accounts": len(rows),
            "workers": 2,
            "partial_original_state_resumed": False,
        },
    }
    publish(output / "identity.json", identity)
    for row in rows:
        shutil.copyfile(original / row["file"], output / row["file"])
        os.chmod(output / row["file"], 0o600)
        require(
            digest(output / row["file"]) == row["sha256"], "Copy changed saved bytes"
        )
    indexed = {row["id"]: row for row in rows}
    context = (engine, panel, raw, cubes, providers, source, str(output))
    # Fork shares immutable loaded arrays; each child owns its cache and account files.
    try:
        with ProcessPoolExecutor(
            max_workers=2,
            mp_context=multiprocessing.get_context("fork"),
            initializer=initialize_worker,
            initargs=(context,),
        ) as pool:
            for row in bounded_accounts(pool, plan["execution_order"]):
                require(row["id"] not in indexed, "Repeated completed account")
                indexed[row["id"]] = row
                publish(
                    output / "receipts" / f"completed-{len(indexed):03d}.json",
                    {
                        "completed": len(indexed),
                        "account": row["id"],
                        "sha256": row["sha256"],
                    },
                )
                print(
                    json.dumps({"completed": len(indexed), "account": row["id"]}),
                    flush=True,
                )
    except BaseException as error:
        publish(
            output / "failure.json",
            {
                "status": "failed_preserve_all_files_no_automatic_retry",
                "error_type": type(error).__name__,
                "completed": len(indexed),
                "adoption_eligible": False,
            },
        )
        raise
    final_rows = [indexed[spec["id"]] for spec in grid]
    authenticate_accounts(output, final_rows)
    engine.check_original_files(files)
    require(
        engine.source_identity(args) == source,
        "Frozen source changed during continuation",
    )
    publish(
        output / "report.json",
        {
            "status": "complete_pending_independent_verification",
            "policy": POLICY,
            "identity_sha256": digest(output / "identity.json"),
            "accounts": final_rows,
            "summary": engine.comparison_summary(final_rows),
            "adoption_eligible": False,
        },
    )


# Start a continuation only after a fresh terminal check, never stopping the original.
def launch(plan_path, output):
    plan = decode(Path(plan_path).read_bytes())
    original = inspect_container(plan["original_container"])
    require(
        original["State"]["Running"] is False
        and original["State"]["Status"] == "exited"
        and original["Image"] == plan["original_image"]
        and digest(__file__) == plan["scheduler_sha256"],
        "Original is active or reviewed launch identity differs; do not duplicate it",
    )
    study = Path(plan["original_study"])
    require(
        digest(study / "identity.json") == plan["identity_sha256"]
        and digest(study / "progress.json") == plan["progress_sha256"],
        "Stale plan; preserve current completed prefix and prepare again",
    )
    output = Path(output).resolve()
    output.mkdir(mode=0o700, exist_ok=False)
    publish(
        output / "terminal.json",
        {
            "Id": original["Id"],
            "Image": original["Image"],
            "State": original["State"],
        },
    )
    publish(output / "command.json", original["Config"]["Cmd"])
    shutil.copyfile(plan_path, output / "plan.json")
    command = [
        "docker",
        "run",
        "--name",
        "actual-continuation-" + digest(output / "plan.json")[:12],
        "--network",
        "none",
        "--read-only",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--memory-swap",
        "4g",
        "--user",
        original["Config"]["User"],
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--workdir",
        "/app",
        "--env",
        "PYTHONPATH=/app",
        "--env",
        "SECRET_KEY=unused-isolated-research-continuation",
        "--env",
        "ANIOS_RESEARCH_IMAGE_ID=" + original["Image"],
    ]
    destinations = set()
    for mount in original["Mounts"]:
        require(mount["Type"] == "bind", "Original bind-only inputs required")
        target = mount["Destination"]
        require(
            not mount["RW"] or target == "/output", "Unexpected writable original input"
        )
        if target == "/output":
            target = "/original-output"
        require(target not in destinations, "Duplicate original mount")
        destinations.add(target)
        command += ["--mount", f"type=bind,src={mount['Source']},dst={target},readonly"]
    require(
        {"/app", "/manifest.json", "/original-output"} <= destinations,
        "Original mounts incomplete",
    )
    for item in original["Config"]["Env"]:
        if item.split("=", 1)[0] in (
            "ANIOS_TEST_MODE",
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
        ):
            command += ["--env", item]
    command += [
        "--mount",
        f"type=bind,src={Path(__file__).resolve()},dst=/scheduler.py,readonly",
        "--mount",
        f"type=bind,src={output},dst=/continuation",
        original["Image"],
        "python",
        "/scheduler.py",
        "execute",
        "--plan",
        "/continuation/plan.json",
        "--output",
        "/continuation/study",
        "--command",
        "/continuation/command.json",
        "--terminal",
        "/continuation/terminal.json",
    ]
    with (output / "launch.log").open("xb") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)


# Expose separate plan, guarded launch and isolated execution paths.
def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "launch", "execute"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--container")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--command", type=Path)
    parser.add_argument("--terminal", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        require(
            args.study is not None and args.container is not None,
            "Original study and container required",
        )
        prepare(args.study, args.container, args.output)
    elif args.mode == "launch":
        require(args.plan is not None, "Reviewed plan required")
        launch(args.plan, args.output)
    else:
        require(
            all(item is not None for item in (args.plan, args.command, args.terminal)),
            "Isolated evidence paths required",
        )
        execute(args.plan, args.command, args.terminal, args.output)


if __name__ == "__main__":
    main()
