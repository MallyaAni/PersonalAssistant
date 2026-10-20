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


# Admit only the reviewed settlement metadata while preserving every other paper node.
def settlement_metadata_review(old, new, review):
    paper_path = "backend/agents/trading/desk/paper.py"
    changes = {
        name for name in old.keys() | new.keys() if old.get(name) != new.get(name)
    }
    if (
        set(old) != set(new)
        or len(old) != 31
        or changes != {paper_path}
        or set(review["source_changes"]) != {paper_path}
        or review["source_changes"][paper_path]
        != {"before_sha256": old[paper_path], "after_sha256": new[paper_path]}
        or type(review["other_reviewed_sources_unchanged"]) is not int
        or review["other_reviewed_sources_unchanged"] != 30
    ):
        raise ValueError("Exact paper-only settlement metadata review required")
    raw = (Path(__file__).resolve().parents[2] / paper_path).read_bytes()
    require_hash(raw, new[paper_path])
    tree = ast.parse(raw)
    changed = {"Settled", "settle", "apply_settlements"}
    added = {"_settlement_quantity", "_settlement_quantity_evidence"}
    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if any(
        sum(node.name == name for node in definitions) != 1 for name in changed | added
    ):
        raise ValueError("Exact settlement metadata definitions required")
    settled = next(node for node in definitions if node.name == "Settled")
    fields = {"submitted_qty", "sender_qty", "quantity_evidence"}
    appended = [
        node
        for node in settled.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id in fields
    ]
    if len(appended) != 3 or {node.target.id for node in appended} != fields:
        raise ValueError("Exact optional settlement quantity fields required")
    settled.body = [node for node in settled.body if node not in appended]
    if (
        digest(ast.dump(settled, include_attributes=False).encode())
        != review["original_settled_ast_sha256"]
    ):
        raise ValueError("Original settlement fields or behavior changed")
    decimal_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module == "decimal"
        and [(name.name, name.asname) for name in node.names]
        == [("Decimal", None), ("InvalidOperation", None)]
    ]
    if len(decimal_imports) != 1:
        raise ValueError("Exact settlement numeric reader import required")
    tree.body = [
        node
        for node in tree.body
        if node not in definitions or node.name not in changed | added
    ]
    tree.body = [node for node in tree.body if node not in decimal_imports]
    if (
        digest(ast.dump(tree, include_attributes=False).encode())
        != review["unchanged_paper_module_ast_sha256"]
    ):
        raise ValueError("Unreviewed paper planning or persistence change")


# Admit only the exact native ownership repair while retaining every other paper node.
def paper_ownership_review(old, new, review):
    path = "backend/agents/trading/desk/paper.py"
    before = "a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c"
    after = "1a96dd96c254abb4799c6f14cb99938c65fb2907d6777fbc4b1194bfaa851bc4"
    changes = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    if (
        set(old) != set(new)
        or len(old) != 31
        or changes != {path}
        or old[path] != before
        or new[path] != after
        or set(review["source_changes"]) != {path}
        or review["source_changes"][path]
        != {"before_sha256": before, "after_sha256": after}
        or type(review["other_reviewed_sources_unchanged"]) is not int
        or review["other_reviewed_sources_unchanged"] != 30
    ):
        raise ValueError("Exact native paper ownership source review required")
    raw = (Path(__file__).resolve().parents[2] / path).read_bytes()
    require_hash(raw, after)
    tree = ast.parse(raw)
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "save_state"
    ]
    if len(functions) != 1 or digest(
        ast.dump(functions[0], include_attributes=False).encode()
    ) != review["reviewed_save_state_ast_sha256"]:
        raise ValueError("Exact reviewed native paper ownership writer required")
    tree.body = [node for node in tree.body if node is not functions[0]]
    if digest(ast.dump(tree, include_attributes=False).encode()) != review[
        "unchanged_paper_module_ast_sha256"
    ]:
        raise ValueError("Unreviewed native paper imports, planning or settlement change")


# Admit reviewed order persistence and fill projection while pinning all other logic.
def reconciliation_review(old, new, review):
    path = "backend/cli/market_daily.py"
    projection = "backend/market/live_model_decision.py"
    allowed = {path, projection}
    changes = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    if (
        set(old) != set(new)
        or len(old) != 31
        or changes != allowed
        or set(review["source_changes"]) != allowed
        or any(review["source_changes"][name]
               != {"before_sha256": old[name], "after_sha256": new[name]}
               for name in allowed)
        or type(review["other_reviewed_sources_unchanged"]) is not int
        or review["other_reviewed_sources_unchanged"] != 29
    ):
        raise ValueError("Exact reconciliation and fill-projection source review required")
    raw = (Path(__file__).resolve().parents[2] / path).read_bytes()
    require_hash(raw, new[path])
    tree = ast.parse(raw)
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_reconcile"
    ]
    if len(functions) != 1 or digest(
        ast.dump(functions[0], include_attributes=False).encode()
    ) != review["reviewed_reconcile_ast_sha256"]:
        raise ValueError("Exact reviewed reconciliation body required")
    tree.body = [node for node in tree.body if node is not functions[0]]
    if digest(ast.dump(tree, include_attributes=False).encode()) != review[
        "unchanged_daily_module_ast_sha256"
    ]:
        raise ValueError("Unreviewed daily planning, submission or persistence change")
    raw = (Path(__file__).resolve().parents[2] / projection).read_bytes()
    require_hash(raw, new[projection])
    tree = ast.parse(raw)
    selected = {"recorded_fills", "_recorded_fill_entry"}
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in selected]
    if (
        len(functions) != 2
        or {node.name for node in functions} != selected
        or {node.name: digest(ast.dump(node, include_attributes=False).encode())
            for node in functions} != review["reviewed_fill_functions_ast_sha256"]
    ):
        raise ValueError("Exact recorded-fill projection functions required")
    tree.body = [node for node in tree.body if node not in functions]
    if digest(ast.dump(tree, include_attributes=False).encode()) != review[
        "unchanged_decision_module_ast_sha256"
    ]:
        raise ValueError("Unreviewed numeric decision or terminal conclusion change")


# Admit the independent publisher hook only when the entire original strategy module reconstructs exactly.
def independent_publication_review(old, new, review):
    added = {f"backend/market/{name}.py" for name in (
        "strategy_model_allocation", "strategy_publication", "strategy_entry_context", "strategy_entries"
    )}
    _publication_review(old, new, review, added)


# Admit the separate observed model-book closure without weakening the earlier four-component review.
def observed_reference_review(old, new, review):
    added = {f"backend/market/{name}.py" for name in (
        "strategy_model_allocation", "strategy_publication", "strategy_entry_context", "strategy_entries",
        "strategy_reference_transition", "strategy_reference_entries", "strategy_reference_book",
        "strategy_model_history", "strategy_history_installation", "strategy_history_publication"
    )}
    _publication_review(old, new, review, added)


# Reconstruct the entire admitted original holding module after removing only the declared guard additions and publisher hook.
def _publication_review(old, new, review, added):
    from backend.market import learned_live_holding as runtime

    holding = "backend/market/learned_live_holding.py"
    changes = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    if (
        len(old) != 31 or len(new) != 31 + len(added) or set(new) - set(old) != added or set(old) - set(new)
        or changes != added | {holding} or set(review["source_changes"]) != changes
        or old[holding] != "25fee57bd3dc57c2b945e204aa3b83e39434cf4f84f8a165a4b9e41f9f6183e1"
        or type(review["other_reviewed_sources_unchanged"]) is not int
        or review["other_reviewed_sources_unchanged"] != 30
        or new != runtime.source_identity()
        or review["original_holding_module_ast_sha256"]
        != "458218fde5e6136cdd44fdf19bf03d4d382a1dc0e3327a6c7b707d315f86c880"
        or any(review["source_changes"][name] != {"before_sha256": old.get(name), "after_sha256": new[name]} for name in changes)
    ):
        raise ValueError("Exact independent publication source review required")
    code = Path(__file__).resolve().parents[2]
    for name in added:
        require_hash((code / name).read_bytes(), new[name])
    raw = Path(runtime.__file__).read_bytes()
    require_hash(raw, new[holding])
    tree = ast.parse(raw)
    source = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "source_identity")
    prepare = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "prepare")
    paths = next(node.value for node in source.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "paths" for target in node.targets))
    expected_paths = {ast.dump(ast.parse("root / " + repr(name), mode="eval").body, include_attributes=False) for name in added}
    removed = [node for node in paths.elts if ast.dump(node, include_attributes=False) in expected_paths]
    if len(removed) != len(added) or {ast.dump(node, include_attributes=False) for node in removed} != expected_paths:
        raise ValueError("Exact independent publication guard additions required")
    paths.elts = [node for node in paths.elts if node not in removed]
    expected_tail = ast.parse('''selected = factory(reader, config["cost_bps"], root, raw, admission, completed)
if config["policy"] == grade_led_policy.POLICY:
    from backend.market import strategy_publication
    strategy_publication.publish_prepared(selected, report, clock=clock)
return selected
''').body
    if [ast.dump(node, include_attributes=False) for node in prepare.body[-3:]] != [ast.dump(node, include_attributes=False) for node in expected_tail]:
        raise ValueError("Exact pre-account publication callback required")
    prepare.body[-3:] = [ast.Return(value=prepare.body[-3].value)]
    if digest(ast.dump(tree, include_attributes=False).encode()) != review["original_holding_module_ast_sha256"]:
        raise ValueError("Independent publication changed original holding economics or guards")


# Require an exact reviewed transition without broadening the production source guard.
def reviewed_sources(old, new, review):
    if review["status"] == "REVIEWED_EXACT_OBSERVED_REFERENCE_PUBLICATION":
        observed_reference_review(old, new, review)
        return
    if review["status"] == "REVIEWED_EXACT_INDEPENDENT_STRATEGY_PUBLICATION":
        independent_publication_review(old, new, review)
        return
    if review["status"] == "REVIEWED_NATIVE_PAPER_OWNERSHIP_PRESERVATION":
        paper_ownership_review(old, new, review)
        return
    if review["status"] == "REVIEWED_EXACT_ORDER_RECONCILIATION_AND_FILL_PROJECTION":
        reconciliation_review(old, new, review)
        return
    if review["status"] == "REVIEWED_EXACT_SETTLEMENT_QUANTITY_METADATA":
        settlement_metadata_review(old, new, review)
        return
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


# Read an optional committed initial model snapshot without inference, clock extension or account access.
def initial_publication(review, revision, config_raw, now):
    metadata = review.get("initial_publication")
    if metadata is None:
        return None
    from backend.market import strategy_publication as publication

    if (review["status"] not in ("REVIEWED_EXACT_INDEPENDENT_STRATEGY_PUBLICATION", "REVIEWED_EXACT_OBSERVED_REFERENCE_PUBLICATION")
            or not isinstance(metadata, dict) or set(metadata) != {"path", "sha256", "bytes"}
            or type(metadata["bytes"]) is not int or not 0 < metadata["bytes"] <= publication.MAX_BYTES):
        raise ValueError("Exact reviewed initial publication required")
    relative = Path(metadata["path"])
    code = Path(__file__).resolve().parents[2]
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != ("docs", "research"):
        raise ValueError("Committed initial publication path required")
    path = (code / relative).resolve()
    if not path.is_relative_to(code) or path.stat().st_size != metadata["bytes"]:
        raise ValueError("Finite reviewed initial publication required")
    raw = path.read_bytes()
    require_hash(raw, metadata["sha256"])
    committed = subprocess.check_output(["git", "-C", str(code), "show", revision + ":" + relative.as_posix()])
    if raw != committed:
        raise ValueError("Initial publication is not the committed original")
    value = publication.validate(json.loads(raw), now, expected_sources=publication._sources(),
        config_sha256=digest(config_raw))
    config = json.loads(config_raw)
    if (value["identity"]["economic_parameters"]["cost_bps"] != config["cost_bps"]
            or any(value["identity"][name] != config[key] for name, key in (
                ("holding_model_receipt_sha256", "model_receipt_sha256"),
                ("risk_receipt_sha256", "risk_receipt_sha256"),
                ("timing_config_sha256", "timing_config_sha256")))):
        raise ValueError("Initial publication changed original model configuration")
    return value


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
    initial_publication(review, revision, after["config.json"], datetime.now(UTC))
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


# Archive original selectors and install only reviewed approval and optional initial model bytes.
def activate(root, bundle_path, bundle_sha, revision, archive_dir):
    from backend.agents.trading.desk import paper

    root = Path(root)
    with paper.transaction(root):
        before, after, _ = candidate(root, bundle_path, bundle_sha, revision)
        raw_bundle = Path(bundle_path).read_bytes()
        require_hash(raw_bundle, bundle_sha)
        review = committed_review(json.loads(raw_bundle), revision)
        initial = initial_publication(review, revision, after["config.json"], datetime.now(UTC))
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
        if initial is not None:
            receipt["initial_publication"] = {**review["initial_publication"], "snapshot_id": initial["snapshot_id"]}
        with (archive / "receipt.json").open("x") as stream:
            json.dump(receipt, stream, sort_keys=True)
        (archive / "receipt.json").chmod(0o600)
        try:
            for name in ("release.json", "config.json"):
                replace_file((root / CONFIG).with_name(name), after[name])
            admitted = check(root)
            if initial is not None:
                from backend.market import strategy_publication as publication

                publication.publish(root, initial, datetime.now(UTC))
        except Exception:
            for name in ("release.json", "config.json"):
                replace_file((root / CONFIG).with_name(name), before[name])
            raise
    result = {**admitted, "archive": str(archive.resolve()), "bundle_sha256": bundle_sha}
    if initial is not None:
        result["initial_snapshot_id"] = initial["snapshot_id"]
    return result


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
