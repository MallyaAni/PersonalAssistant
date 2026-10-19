"""Ownership-only source approval cannot admit another writer or economic change."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.cli import market_release_admission as admission

PAPER = "backend/agents/trading/desk/paper.py"
BEFORE = "a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c"
AFTER = "1a96dd96c254abb4799c6f14cb99938c65fb2907d6777fbc4b1194bfaa851bc4"
SAVE = "bce627aba5775d7f413d2ff20463def10e8177718f933e4d5e233d950b7222f7"
REMAINDER = "20e7baa802964b5bdc58aec243e8e92f0bab6cd79b9b4d2e5872f960c2a2ac68"


# Encode only explicit synthetic approval selectors with stable original bytes.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2).encode()


# Bind the new review to exact real writer bytes and thirty unchanged synthetic pins.
def transition():
    raw = (Path(admission.__file__).resolve().parents[2] / PAPER).read_bytes()
    assert admission.digest(raw) == AFTER
    new = {PAPER: AFTER}
    new.update({f"original/source-{number}": "a" * 64 for number in range(30)})
    old = {**new, PAPER: BEFORE}
    review = {
        "status": "REVIEWED_NATIVE_PAPER_OWNERSHIP_PRESERVATION",
        "source_changes": {PAPER: {"before_sha256": BEFORE, "after_sha256": AFTER}},
        "other_reviewed_sources_unchanged": 30,
        "reviewed_save_state_ast_sha256": SAVE,
        "unchanged_paper_module_ast_sha256": REMAINDER,
    }
    return old, new, review, raw


# Exercise bundle validation on private selectors without models, account or Git access.
def bundle_fixture(tmp_path, monkeypatch):
    old, new, review, _ = transition()
    now = datetime.now(UTC)
    evidence = b'{"synthetic_original_economic_evidence":true}\r\n'
    old_release = {
        "schema": "learned-holding-release/1",
        "approved": True,
        "approved_at": (now - timedelta(days=1)).isoformat(),
        "policy": "synthetic unchanged policy",
        "source_sha256": old,
        "evidence_sha256": admission.digest(evidence),
    }
    old_config = {
        "policy": "synthetic unchanged policy",
        "cost_bps": 10,
        "model_directory": "synthetic-model",
        "risk_directory": "synthetic-risk",
        "model_receipt_sha256": "b" * 64,
        "risk_receipt_sha256": "c" * 64,
        "timing_config_sha256": "d" * 64,
        "release_receipt_sha256": admission.digest(encoded(old_release)),
    }
    before = {
        "config.json": encoded(old_config),
        "release.json": encoded(old_release),
        "evidence.json": evidence,
    }
    root = tmp_path / "market"
    parent = (root / admission.CONFIG).parent
    parent.mkdir(parents=True)
    for name, raw in before.items():
        (parent / name).write_bytes(raw)
    release = {**old_release, "approved_at": now.isoformat(), "source_sha256": new}
    config = {**old_config, "release_receipt_sha256": admission.digest(encoded(release))}
    bundle = {
        "schema": admission.SCHEMA,
        "target_revision": "e" * 40,
        "review_path": "docs/research/synthetic-ownership-review.json",
        "review_sha256": "f" * 64,
        "predecessor": {
            name.removesuffix(".json") + "_sha256": admission.digest(raw)
            for name, raw in before.items()
        },
        "config_json": encoded(config).decode(),
        "release_json": encoded(release).decode(),
        "evidence_json": evidence.decode(),
    }

    # Substitute only the committed-review transport with its explicit synthetic record.
    def reviewed_record(*args):
        return deepcopy(review)

    # Inspect private selectors instead of importing runtime models or account code.
    def synthetic_check(candidate_root):
        selectors = admission.installed(candidate_root)
        assert json.loads(selectors["release.json"])["source_sha256"] == new
        assert selectors["evidence.json"] == evidence
        return {"status": "ADMITTED_SYNTHETIC_SELECTOR_CHECK"}

    monkeypatch.setattr(admission, "committed_review", reviewed_record)
    monkeypatch.setattr(admission, "check", synthetic_check)
    path = tmp_path / "bundle.json"
    return root, before, bundle, path, review


# Admit only the exact ownership writer under its separately named review kind.
def test_exact_native_ownership_source_review_is_admitted():
    old, new, review, _ = transition()
    admission.reviewed_sources(old, new, review)


# Reject changes to source membership, original pins, review count or exact AST claims.
@pytest.mark.parametrize(
    "corruption",
    ["other", "add", "remove", "no_change", "before", "after", "count",
     "bool_count", "extra", "save", "remainder", "status", "old_kind"],
)
def test_ownership_review_refuses_unknown_or_unreviewed_scope(corruption):
    old, new, review, _ = transition()
    if corruption == "other":
        new["original/source-0"] = "0" * 64
    elif corruption == "add":
        new["unknown/source.py"] = "0" * 64
    elif corruption == "remove":
        del new["original/source-0"]
    elif corruption == "no_change":
        old[PAPER] = AFTER
    elif corruption in {"before", "after"}:
        value = "0" * 64
        (old if corruption == "before" else new)[PAPER] = value
        review["source_changes"][PAPER][corruption + "_sha256"] = value
    elif corruption in {"count", "bool_count"}:
        review["other_reviewed_sources_unchanged"] = 29 if corruption == "count" else True
    elif corruption == "extra":
        review["source_changes"]["unknown/source.py"] = {}
    elif corruption in {"save", "remainder"}:
        key = "reviewed_save_state_ast_sha256" if corruption == "save" else "unchanged_paper_module_ast_sha256"
        review[key] = "0" * 64
    else:
        review["status"] = (
            "REVIEWED_EXACT_ORDER_RECONCILIATION_AND_FILL_PROJECTION"
            if corruption == "old_kind" else "UNKNOWN_REVIEW"
        )
    with pytest.raises(ValueError):
        admission.reviewed_sources(old, new, review)


# Updated whole-file claims cannot hide writer, import, planner or other-function edits.
@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("mode = 0o600", "mode = 0o644"),
        ("json.dump(state, handle, indent=2, default=_state_json)",
         "json.dump(state, handle, indent=None, default=_state_json)"),
        ("os.fsync(handle.fileno())", "handle.flush()"),
        ("temporary.replace(path)", "temporary.unlink(missing_ok=True)"),
        ("def load_state(root: Path) -> PaperState:",
         "def load_state(root: Path) -> PaperState:\n    raise RuntimeError('unreviewed')"),
        ("import tempfile", "import tempfile\nimport socket"),
        ("REBALANCE_EVERY = 20", "REBALANCE_EVERY = 21"),
    ],
)
def test_ownership_review_refuses_changed_native_behavior(before, after):
    old, new, review, raw = transition()
    text = raw.decode()
    assert text.count(before) == 1
    changed = text.replace(before, after, 1).encode()
    new[PAPER] = admission.digest(changed)
    review["source_changes"][PAPER]["after_sha256"] = new[PAPER]
    with patch.object(Path, "read_bytes", return_value=changed), pytest.raises(ValueError):
        admission.reviewed_sources(old, new, review)


# Exact bundle preflight leaves all original installed selectors byte-identical.
def test_ownership_bundle_preflight_keeps_original_selectors(tmp_path, monkeypatch):
    root, before, bundle, path, _ = bundle_fixture(tmp_path, monkeypatch)
    raw = encoded(bundle)
    path.write_bytes(raw)
    result = admission.preflight(root, path, admission.digest(raw), bundle["target_revision"])
    assert result["status"] == "REVIEWED_BUNDLE_ADMITTED"
    assert admission.installed(root) == before


# Ownership approval must retain the existing model, risk, timing, cost and evidence gates.
@pytest.mark.parametrize(
    ("part", "key", "value"),
    [
        ("config", "cost_bps", 11),
        ("config", "policy", "changed"),
        ("config", "model_directory", "changed"),
        ("config", "risk_directory", "changed"),
        ("config", "model_receipt_sha256", "0" * 64),
        ("config", "risk_receipt_sha256", "0" * 64),
        ("config", "timing_config_sha256", "0" * 64),
        ("release", "approved", False),
        ("release", "policy", "changed"),
        ("evidence", None, "changed"),
    ],
)
def test_ownership_bundle_rejects_economic_changes(tmp_path, monkeypatch, part, key, value):
    root, before, bundle, path, _ = bundle_fixture(tmp_path, monkeypatch)
    if part == "evidence":
        bundle["evidence_json"] += value
    else:
        item = json.loads(bundle[part + "_json"])
        item[key] = value
        bundle[part + "_json"] = encoded(item).decode()
        if part == "release":
            config = json.loads(bundle["config_json"])
            config["release_receipt_sha256"] = admission.digest(encoded(item))
            bundle["config_json"] = encoded(config).decode()
    raw = encoded(bundle)
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="models, costs, policy or evidence"):
        admission.preflight(root, path, admission.digest(raw), bundle["target_revision"])
    assert admission.installed(root) == before
