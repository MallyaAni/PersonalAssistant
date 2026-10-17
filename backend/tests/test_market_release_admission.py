"""A reviewed source renewal cannot silently change numerical trading configuration."""

import ast
import json
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.cli import market_release_admission as admission
from backend.market import learned_live_holding as runtime
from backend.market.grade_led_policy import POLICY


# Encode the precise operator-reviewed bytes used by each candidate fixture.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2).encode()


# Install an old API approval and an explicit renewal to the current exact source.
def renewal(tmp_path, monkeypatch):
    root = tmp_path / "market"
    parent = (root / admission.CONFIG).parent
    parent.mkdir(parents=True)
    source = runtime.source_identity()
    api = "backend/api/v1/market.py"
    old_source = {**source, api: "0" * 64}
    now = datetime.now(UTC)
    evidence = b'{"original_economic_evidence":true}\r\n'
    old_release = {
        "schema": "learned-holding-release/1",
        "approved": True,
        "approved_at": (now - timedelta(days=1)).isoformat(),
        "policy": POLICY,
        "source_sha256": old_source,
        "evidence_sha256": admission.digest(evidence),
    }
    old_config = {
        "policy": POLICY,
        "cost_bps": 10,
        "model_directory": "model",
        "risk_directory": "risk",
        "model_receipt_sha256": "a" * 64,
        "risk_receipt_sha256": "b" * 64,
        "timing_config_sha256": "c" * 64,
        "release_receipt_sha256": admission.digest(encoded(old_release)),
    }
    before = {
        "config.json": encoded(old_config),
        "release.json": encoded(old_release),
        "evidence.json": evidence,
    }
    for name, raw in before.items():
        (parent / name).write_bytes(raw)
    new_release = {
        **old_release,
        "approved_at": now.isoformat(),
        "source_sha256": source,
    }
    new_config = {
        **old_config,
        "release_receipt_sha256": admission.digest(encoded(new_release)),
    }
    bundle = {
        "schema": admission.SCHEMA,
        "target_revision": "d" * 40,
        "review_path": "docs/research/explicit-review.json",
        "review_sha256": "e" * 64,
        "predecessor": {
            name.removesuffix(".json") + "_sha256": admission.digest(raw)
            for name, raw in before.items()
        },
        "config_json": encoded(new_config).decode(),
        "release_json": encoded(new_release).decode(),
        "evidence_json": evidence.decode(),
    }
    review = {
        "status": "REVIEWED_EXACT_SERVING_SOURCE_APPROVAL_CANDIDATE",
        "changed_reviewed_file": api,
        "previous_approved_sha256": old_source[api],
        "reviewed_serving_sha256": source[api],
        "other_reviewed_sources_unchanged": len(source) - 1,
    }
    monkeypatch.setattr(admission, "committed_review", lambda *_: deepcopy(review))
    path = tmp_path / "bundle.json"
    path.write_bytes(encoded(bundle))
    return root, before, bundle, path, review


# Rewrite only fixture bundle bytes after a corruption, keeping its supplied hash exact.
def persist(path, bundle):
    raw = encoded(bundle)
    path.write_bytes(raw)
    return admission.digest(raw)


# An absent installed configuration is an explicit read-only no-op.
def test_absent_configuration_and_stale_source_are_not_silent_approval(
    tmp_path, monkeypatch
):
    assert admission.check(tmp_path) == {"status": "NOT_CONFIGURED"}
    root, before, _, _, _ = renewal(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Exact reviewed"):
        admission.preflight(root)
    assert admission.installed(root) == before


# Only the reviewed selectors change; exact old snapshots and rollback remain available.
def test_reviewed_approval_preflight_activate_and_unrestarted_rollback(
    tmp_path, monkeypatch
):
    root, before, bundle, path, _ = renewal(tmp_path, monkeypatch)
    expected = persist(path, bundle)
    revision = bundle["target_revision"]
    assert (
        admission.preflight(root, path, expected, revision)["status"]
        == "REVIEWED_BUNDLE_ADMITTED"
    )
    assert admission.installed(root) == before
    result = admission.activate(root, path, expected, revision, tmp_path / "archives")
    assert result["status"] == "ADMITTED"
    archive = Path(result["archive"])
    assert {name: (archive / name).read_bytes() for name in admission.NAMES} == before
    assert (archive / "evidence.json").read_bytes() == admission.installed(root)[
        "evidence.json"
    ]
    assert admission.check(root)["status"] == "ADMITTED"
    assert admission.rollback(root, archive)["status"] == "RESTORED_ORIGINAL_APPROVAL"
    assert admission.installed(root) == before


# No model, risk, cost, timing or evidence edit can hide behind a valid bundle hash.
@pytest.mark.parametrize(
    ("part", "key", "value"),
    [
        ("config", "cost_bps", 11),
        ("config", "policy", "other"),
        ("config", "model_receipt_sha256", "f" * 64),
        ("config", "risk_receipt_sha256", "f" * 64),
        ("config", "timing_config_sha256", "f" * 64),
        ("evidence", None, "edited"),
        ("predecessor", "config_sha256", "f" * 64),
        ("release", "approved", False),
        ("release", "source_sha256", {}),
        ("release", "approved_at", "2999-01-01T00:00:00+00:00"),
    ],
)
def test_corrupt_or_unreviewed_bundle_fails_without_live_changes(
    tmp_path, monkeypatch, part, key, value
):
    root, before, bundle, path, _ = renewal(tmp_path, monkeypatch)
    if part in ("config", "release"):
        item = json.loads(bundle[part + "_json"])
        item[key] = value
        bundle[part + "_json"] = encoded(item).decode()
        if part == "release":
            config = json.loads(bundle["config_json"])
            config["release_receipt_sha256"] = admission.digest(encoded(item))
            bundle["config_json"] = encoded(config).decode()
    elif part == "evidence":
        bundle["evidence_json"] += value
    else:
        bundle[part][key] = value
    with pytest.raises((ValueError, KeyError)):
        admission.preflight(
            root, path, persist(path, bundle), bundle["target_revision"]
        )
    assert admission.installed(root) == before


# Missing digest, wrong bytes and a different target cannot activate an approval.
def test_bundle_requires_paired_digest_and_exact_target(tmp_path, monkeypatch):
    root, before, bundle, path, _ = renewal(tmp_path, monkeypatch)
    for supplied, expected, target in (
        (path, None, bundle["target_revision"]),
        (None, "a" * 64, bundle["target_revision"]),
        (path, "0" * 64, bundle["target_revision"]),
        (path, admission.digest(path.read_bytes()), "f" * 40),
    ):
        with pytest.raises(
            ValueError, match="(supplied together|digest|bundle required)"
        ):
            admission.preflight(root, supplied, expected, target)
    assert admission.installed(root) == before


# A failed second atomic selector write restores both exact original files.
def test_failed_activation_restores_old_selectors_and_keeps_archive(
    tmp_path, monkeypatch
):
    root, before, bundle, path, _ = renewal(tmp_path, monkeypatch)
    replace = admission.replace_file

    # Fail only the candidate config write so the original selector can be restored.
    def fail_new_config(destination, raw):
        if destination.name == "config.json" and raw != before["config.json"]:
            raise OSError("injected candidate write failure")
        replace(destination, raw)

    monkeypatch.setattr(admission, "replace_file", fail_new_config)
    with pytest.raises(OSError, match="injected"):
        admission.activate(
            root,
            path,
            persist(path, bundle),
            bundle["target_revision"],
            tmp_path / "archives",
        )
    assert admission.installed(root) == before
    assert len(list((tmp_path / "archives").glob("*/receipt.json"))) == 1


# The guard-list extension cannot alter any original holding function body.
def test_reviewed_guard_extension_exact_sources_and_function_ast(tmp_path):
    source = runtime.source_identity()
    old = {
        **source,
        "backend/api/v1/market.py": "0" * 64,
        "backend/market/learned_live_holding.py": "1" * 64,
    }
    new = {**source, "backend/market/live_model_decision.py": "2" * 64}
    tree = ast.parse(Path(runtime.__file__).read_bytes())
    functions = {
        node.name: admission.digest(ast.dump(node, include_attributes=False).encode())
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "source_identity"
    }
    review = {
        "status": "REVIEWED_EXACT_SERVING_SOURCE_GUARD_EXTENSION",
        "source_changes": {
            name: {"before_sha256": old.get(name), "after_sha256": new.get(name)}
            for name in old.keys() | new.keys()
            if old.get(name) != new.get(name)
        },
        "original_holding_function_ast_sha256": functions,
    }
    admission.reviewed_sources(old, new, review)
    review["original_holding_function_ast_sha256"]["_release"] = "e" * 64
    with pytest.raises(ValueError, match="holding function"):
        admission.reviewed_sources(old, new, review)


# A hash-pinned review must actually belong to the candidate Git tree.
def test_review_must_be_committed_in_exact_candidate(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    (repo / "backend/cli").mkdir(parents=True)
    path = repo / "docs/research/review.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"reviewed":true}')
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "review",
        ],
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    monkeypatch.setattr(
        admission, "__file__", str(repo / "backend/cli/market_release_admission.py")
    )
    bundle = {
        "review_path": "docs/research/review.json",
        "review_sha256": admission.digest(path.read_bytes()),
    }
    assert admission.committed_review(bundle, revision) == {"reviewed": True}
    path.write_bytes(b'{"reviewed":false}')
    bundle["review_sha256"] = admission.digest(path.read_bytes())
    with pytest.raises(ValueError, match="committed candidate"):
        admission.committed_review(bundle, revision)


# Admission rejects selectors changed while the source guard is reading them.
def test_admission_rejects_concurrent_selector_change(tmp_path, monkeypatch):
    root, _, bundle, path, _ = renewal(tmp_path, monkeypatch)
    admission.activate(
        root,
        path,
        persist(path, bundle),
        bundle["target_revision"],
        tmp_path / "archives",
    )
    read = runtime.read_configuration

    # Reproduce another writer replacing the selected config after the guard read.
    def racing_read(selected_root, now):
        result = read(selected_root, now)
        config = selected_root / admission.CONFIG
        config.write_bytes(config.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(runtime, "read_configuration", racing_read)
    with pytest.raises(ValueError, match="changed during admission"):
        admission.check(root)


# Rollback refuses to overwrite a newer selector or restore corrupted archived bytes.
@pytest.mark.parametrize("corrupt_archive", [False, True])
def test_rollback_rejects_changed_current_or_archived_selectors(
    tmp_path, monkeypatch, corrupt_archive
):
    root, _, bundle, path, _ = renewal(tmp_path, monkeypatch)
    result = admission.activate(
        root,
        path,
        persist(path, bundle),
        bundle["target_revision"],
        tmp_path / "archives",
    )
    archive = Path(result["archive"])
    destination = (
        archive / "config.json" if corrupt_archive else root / admission.CONFIG
    )
    destination.write_bytes(destination.read_bytes() + b"\n")
    before_rejection = admission.installed(root)
    with pytest.raises(ValueError, match="artifact digest"):
        admission.rollback(root, archive)
    assert admission.installed(root) == before_rejection
