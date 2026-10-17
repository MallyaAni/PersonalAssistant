"""Check or install an explicit reviewed approval without changing trading economics."""

import argparse
import ast
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

CONFIG = "desk/learned-holding/config.json"
NAMES = ("config.json", "release.json", "evidence.json")
SCHEMA = "learned-holding-approval-bundle/1"


# Bind every supplied identity to exact original encoded bytes.
def digest(raw):
    return sha256(raw).hexdigest()


# Reject a changed reviewed artifact before decoding or activating it.
def require_hash(raw, expected):
    if not isinstance(expected, str) or len(expected) != 64 or digest(raw) != expected:
        raise ValueError("Exact trading approval artifact digest required")


# Read the three existing selectors without creating or modifying the installation.
def installed(root):
    parent = (Path(root) / CONFIG).parent
    return {name: (parent / name).read_bytes() for name in NAMES}


# Recognize partial installs and dangling selectors instead of skipping damage.
def configured(root):
    parent = (Path(root) / CONFIG).parent
    return any(os.path.lexists(parent / name) for name in NAMES)


# Admit the current source using the existing guard, without broker or model inference.
def check(root):
    root = Path(root)
    if not configured(root):
        return {"status": "NOT_CONFIGURED"}
    from backend.market import learned_live_holding as runtime

    raw = installed(root)
    selected, _ = runtime.read_configuration(root, datetime.now(UTC))
    if raw != installed(root) or selected != raw["config.json"]:
        raise ValueError("Trading approval changed during admission check")
    return {
        "status": "ADMITTED",
        "source_sha256": runtime.source_identity(),
        "config_sha256": digest(raw["config.json"]),
        "release_sha256": digest(raw["release.json"]),
        "evidence_sha256": digest(raw["evidence.json"]),
    }


# Require committed review bytes from the exact candidate revision, not a local note.
def committed_review(bundle, revision):
    code = Path(__file__).resolve().parents[2]
    if (
        subprocess.check_output(
            ["git", "-C", str(code), "rev-parse", "HEAD"], text=True
        ).strip()
        != revision
    ):
        raise ValueError("Trading approval candidate revision differs")
    relative = Path(bundle["review_path"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:2] != ("docs", "research")
    ):
        raise ValueError("Committed relative trading approval review required")
    path = (code / relative).resolve()
    if not path.is_relative_to(code):
        raise ValueError("Trading approval review escaped candidate source")
    raw = path.read_bytes()
    require_hash(raw, bundle["review_sha256"])
    committed = subprocess.check_output(
        ["git", "-C", str(code), "show", revision + ":" + relative.as_posix()]
    )
    if raw != committed:
        raise ValueError("Trading approval review is not the committed candidate")
    return json.loads(raw)


# Require exact reviewed API changes and a function-preserving source guard extension.
def reviewed_sources(old, new, review):
    changes = {
        name for name in old.keys() | new.keys() if old.get(name) != new.get(name)
    }
    api = "backend/api/v1/market.py"
    if review["status"] == "REVIEWED_EXACT_SERVING_SOURCE_APPROVAL_CANDIDATE":
        if (
            changes != {api}
            or review["changed_reviewed_file"] != api
            or review["previous_approved_sha256"] != old.get(api)
            or review["reviewed_serving_sha256"] != new.get(api)
            or review["other_reviewed_sources_unchanged"] != len(old) - 1
        ):
            raise ValueError("Unreviewed trading API source change")
        return
    if review["status"] != "REVIEWED_EXACT_SERVING_SOURCE_GUARD_EXTENSION":
        raise ValueError("Exact reviewed trading source extension required")
    allowed = {
        "backend/api/v1/market.py",
        "backend/market/learned_live_holding.py",
        "backend/market/live_model_decision.py",
    }
    if (
        changes != allowed
        or set(review["source_changes"]) != allowed
        or set(new) - set(old) != {"backend/market/live_model_decision.py"}
        or set(old) - set(new)
    ):
        raise ValueError("Unreviewed trading source change")
    for name, row in review["source_changes"].items():
        if row != {"before_sha256": old.get(name), "after_sha256": new.get(name)}:
            raise ValueError("Trading review source predecessor or candidate differs")
    from backend.market import learned_live_holding as runtime

    tree = ast.parse(Path(runtime.__file__).read_bytes())
    functions = {
        node.name: digest(ast.dump(node, include_attributes=False).encode())
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "source_identity"
    }
    if functions != review["original_holding_function_ast_sha256"]:
        raise ValueError("Trading approval changed an existing holding function")


# Validate reviewed renewal bytes while preserving all original model/economic fields.
def candidate(root, bundle_path, bundle_sha, revision):
    raw_bundle = Path(bundle_path).read_bytes()
    require_hash(raw_bundle, bundle_sha)
    bundle = json.loads(raw_bundle)
    if (
        set(bundle)
        != {
            "schema",
            "target_revision",
            "review_path",
            "review_sha256",
            "predecessor",
            "config_json",
            "release_json",
            "evidence_json",
        }
        or bundle["schema"] != SCHEMA
        or bundle["target_revision"] != revision
    ):
        raise ValueError("Exact reviewed trading approval bundle required")
    before = installed(root)
    if set(bundle["predecessor"]) != {
        "config_sha256",
        "release_sha256",
        "evidence_sha256",
    }:
        raise ValueError("Complete original trading approval identities required")
    for name in NAMES:
        require_hash(
            before[name], bundle["predecessor"][name.removesuffix(".json") + "_sha256"]
        )
    after = {
        name: bundle[name.removesuffix(".json") + "_json"].encode("utf-8")
        for name in NAMES
    }
    old_config, new_config = (
        json.loads(before["config.json"]),
        json.loads(after["config.json"]),
    )
    old_release, new_release = (
        json.loads(before["release.json"]),
        json.loads(after["release.json"]),
    )
    require_hash(before["release.json"], old_config["release_receipt_sha256"])
    require_hash(before["evidence.json"], old_release["evidence_sha256"])
    require_hash(after["release.json"], new_config["release_receipt_sha256"])
    if datetime.fromisoformat(new_release["approved_at"]) < datetime.fromisoformat(
        old_release["approved_at"]
    ):
        raise ValueError("Trading source approval cannot predate its predecessor")
    if (
        after["evidence.json"] != before["evidence.json"]
        or {
            key: value
            for key, value in old_config.items()
            if key != "release_receipt_sha256"
        }
        != {
            key: value
            for key, value in new_config.items()
            if key != "release_receipt_sha256"
        }
        or {
            key: value
            for key, value in old_release.items()
            if key not in ("source_sha256", "approved_at")
        }
        != {
            key: value
            for key, value in new_release.items()
            if key not in ("source_sha256", "approved_at")
        }
    ):
        raise ValueError(
            "Trading approval cannot change models, costs, policy or evidence"
        )
    review = committed_review(bundle, revision)
    reviewed_sources(old_release["source_sha256"], new_release["source_sha256"], review)
    with tempfile.TemporaryDirectory(prefix="trading-approval-check-") as temporary:
        parent = (Path(temporary) / CONFIG).parent
        parent.mkdir(parents=True)
        for name, raw in after.items():
            (parent / name).write_bytes(raw)
        admitted = check(temporary)
    return before, after, admitted


# Check candidate admission before the deploy checkout or any approval selector moves.
def preflight(root, bundle_path=None, bundle_sha=None, revision=None):
    if not configured(root):
        if bundle_path or bundle_sha:
            raise ValueError("Cannot renew an absent trading configuration")
        return {"status": "NOT_CONFIGURED"}
    if bool(bundle_path) != bool(bundle_sha):
        raise ValueError(
            "Trading approval bundle and exact digest must be supplied together"
        )
    if not bundle_path:
        return check(root)
    _, _, admitted = candidate(root, bundle_path, bundle_sha, revision)
    return {
        **admitted,
        "status": "REVIEWED_BUNDLE_ADMITTED",
        "bundle_sha256": bundle_sha,
    }


# Replace only one approval file atomically, never a model, evidence or account file.
def replace_file(path, raw):
    temporary = path.with_name(path.name + ".approval-" + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# Archive the original selectors exclusively before applying already reviewed bytes.
def activate(root, bundle_path, bundle_sha, revision, archive_dir):
    from backend.agents.trading.desk import paper

    root = Path(root)
    with paper.transaction(root):
        before, after, _ = candidate(root, bundle_path, bundle_sha, revision)
        archive = Path(archive_dir) / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex
        )
        archive.mkdir(mode=0o700, parents=True, exist_ok=False)
        for name, raw in before.items():
            with (archive / name).open("xb") as stream:
                stream.write(raw)
            (archive / name).chmod(0o600)
        receipt = {
            "schema": SCHEMA,
            "root": str(root.resolve()),
            "revision": revision,
            "bundle_sha256": bundle_sha,
            "archive": str(archive.resolve()),
            "before": {name: digest(raw) for name, raw in before.items()},
            "after": {name: digest(raw) for name, raw in after.items()},
        }
        with (archive / "receipt.json").open("x") as stream:
            json.dump(receipt, stream, sort_keys=True)
        (archive / "receipt.json").chmod(0o600)
        try:
            for name in ("release.json", "config.json"):
                replace_file((root / CONFIG).with_name(name), after[name])
            admitted = check(root)
        except Exception:
            for name in ("release.json", "config.json"):
                replace_file((root / CONFIG).with_name(name), before[name])
            raise
    return {**admitted, "archive": str(archive.resolve()), "bundle_sha256": bundle_sha}


# Restore exact prior approval bytes when an unrestarted deployment rolls back its code.
def rollback(root, archive):
    from backend.agents.trading.desk import paper

    root, archive = Path(root), Path(archive)
    receipt = json.loads((archive / "receipt.json").read_bytes())
    if receipt["root"] != str(root.resolve()) or receipt["schema"] != SCHEMA:
        raise ValueError("Original trading approval rollback root differs")
    with paper.transaction(root):
        current = installed(root)
        prior = {name: (archive / name).read_bytes() for name in NAMES}
        for name in NAMES:
            require_hash(current[name], receipt["after"][name])
            require_hash(prior[name], receipt["before"][name])
        for name in ("release.json", "config.json"):
            replace_file((root / CONFIG).with_name(name), prior[name])
    return {"status": "RESTORED_ORIGINAL_APPROVAL"}


# Prove exact original selectors after an activation whose outcome was not returned.
def verify_original(root, bundle_path, bundle_sha):
    from backend.agents.trading.desk import paper

    raw = Path(bundle_path).read_bytes()
    require_hash(raw, bundle_sha)
    bundle = json.loads(raw)
    if bundle["schema"] != SCHEMA or set(bundle["predecessor"]) != {
        "config_sha256",
        "release_sha256",
        "evidence_sha256",
    }:
        raise ValueError("Original approval predecessor identities required")
    with paper.transaction(Path(root)):
        for name, current in installed(root).items():
            require_hash(
                current, bundle["predecessor"][name.removesuffix(".json") + "_sha256"]
            )
    return {"status": "ORIGINAL_APPROVAL_BYTES_VERIFIED"}


# Require explicit commands and bundle digests; no command generates an approval.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("check", "preflight", "activate", "rollback", "verify-original"),
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--bundle")
    parser.add_argument("--bundle-sha256")
    parser.add_argument("--revision")
    parser.add_argument("--archive-dir")
    parser.add_argument("--archive")
    args = parser.parse_args()
    if args.command == "check":
        result = check(args.root)
    elif args.command == "preflight":
        result = preflight(args.root, args.bundle, args.bundle_sha256, args.revision)
    elif args.command == "activate":
        if not all((args.bundle, args.bundle_sha256, args.revision, args.archive_dir)):
            parser.error(
                "Activation requires exact bundle, revision and archive directory"
            )
        result = activate(
            args.root, args.bundle, args.bundle_sha256, args.revision, args.archive_dir
        )
    elif args.command == "rollback":
        if not args.archive:
            parser.error("Rollback requires the original exclusive archive")
        result = rollback(args.root, args.archive)
    else:
        if not all((args.bundle, args.bundle_sha256)):
            parser.error("Original verification requires the exact bundle and digest")
        result = verify_original(args.root, args.bundle, args.bundle_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
