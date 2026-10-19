"""A reviewed reconciliation repair cannot silently approve other trading changes."""

import ast
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.cli import market_release_admission as admission

DAILY = "backend/cli/market_daily.py"
VIEW = "backend/market/live_model_decision.py"
UNCHANGED = "abff05260e84aba546764b8fb030053f22f8eccbe7d309278a52d455f299622e"
UNCHANGED_VIEW = "3e894a1f3b802cffb2fd897cc9c7240f6fd1a00b8cade100fb6a1b019f389889"


# Build a synthetic approval transition around the actual candidate CLI source.
def transition():
    raw = (Path(admission.__file__).resolve().parents[2] / DAILY).read_bytes()
    reconcile = next(
        node for node in ast.parse(raw).body
        if isinstance(node, ast.FunctionDef) and node.name == "_reconcile"
    )
    view_raw = (Path(admission.__file__).resolve().parents[2] / VIEW).read_bytes()
    new = {DAILY: admission.digest(raw), VIEW: admission.digest(view_raw)}
    new.update({f"original/source-{number}": "a" * 64 for number in range(29)})
    old = {**new, DAILY: "b" * 64, VIEW: "d" * 64}
    review = {
        "status": "REVIEWED_EXACT_ORDER_RECONCILIATION_AND_FILL_PROJECTION",
        "source_changes": {name: {"before_sha256": old[name], "after_sha256": new[name]} for name in (DAILY, VIEW)},
        "other_reviewed_sources_unchanged": 29,
        "unchanged_daily_module_ast_sha256": UNCHANGED,
        "unchanged_decision_module_ast_sha256": UNCHANGED_VIEW,
        "reviewed_fill_functions_ast_sha256": {
            node.name: admission.digest(ast.dump(node, include_attributes=False).encode())
            for node in ast.parse(view_raw).body if isinstance(node, ast.FunctionDef)
            and node.name in {"recorded_fills", "_recorded_fill_entry"}
        },
        "reviewed_reconcile_ast_sha256": admission.digest(
            ast.dump(reconcile, include_attributes=False).encode()
        ),
    }
    return old, new, review, raw


# Admit the exact reviewed repair without requiring an installed account or models.
def test_exact_reconciliation_review_is_admitted():
    old, new, review, _ = transition()
    admission.reviewed_sources(old, new, review)


# Reject changed source membership, predecessor pins and review scope.
@pytest.mark.parametrize("corruption", ["other", "add", "remove", "before", "after", "count", "bool_count", "extra", "body", "module"])
def test_reconciliation_review_refuses_unreviewed_scope(corruption):
    old, new, review, _ = transition()
    if corruption == "other":
        new["original/source-0"] = "c" * 64
    elif corruption == "add":
        new["extra"] = "c" * 64
    elif corruption == "remove":
        del new["original/source-0"]
    elif corruption in ("before", "after"):
        review["source_changes"][DAILY][corruption + "_sha256"] = "f" * 64
    elif corruption in ("count", "bool_count"):
        review["other_reviewed_sources_unchanged"] = 28 if corruption == "count" else True
    elif corruption == "extra":
        review["source_changes"]["extra"] = {}
    else:
        key = "reviewed_reconcile_ast_sha256" if corruption == "body" else "unchanged_daily_module_ast_sha256"
        review[key] = "f" * 64
    with pytest.raises(ValueError):
        admission.reviewed_sources(old, new, review)


# Reject unrelated CLI edits even when their whole-file hashes are updated.
@pytest.mark.parametrize("addition", ["UNREVIEWED = True", "def _send_due():\n    raise RuntimeError('unreviewed')"])
def test_reconciliation_approval_cannot_hide_other_cli_behavior(addition):
    old, new, review, raw = transition()
    changed = raw + ("\n" + addition + "\n").encode()
    new[DAILY] = admission.digest(changed)
    review["source_changes"][DAILY]["after_sha256"] = new[DAILY]
    with patch.object(Path, "read_bytes", return_value=changed), pytest.raises(ValueError):
        admission.reviewed_sources(old, new, deepcopy(review))


# A changed reconciliation cannot reuse the prior committed function approval.
def test_reconciliation_body_requires_new_exact_review():
    old, new, review, raw = transition()
    text = raw.decode()
    original = '"""Return (state after settlement, what settled)."""'
    assert text.count(original) == 1
    changed = text.replace(original, original + "\n    raise RuntimeError('unreviewed')", 1).encode()
    new[DAILY] = admission.digest(changed)
    review["source_changes"][DAILY]["after_sha256"] = new[DAILY]
    with patch.object(Path, "read_bytes", return_value=changed), pytest.raises(ValueError):
        admission.reviewed_sources(old, new, review)


# Partial-fill display approval cannot alter the separate terminal-only conclusion path.
def test_fill_projection_approval_preserves_terminal_decision_logic():
    old, new, review, _ = transition()
    original_read = Path.read_bytes
    view_path = Path(admission.__file__).resolve().parents[2] / VIEW
    raw = view_path.read_bytes()
    text = raw.decode()
    needle = 'if entry.get("terminal") is not True:'
    assert text.count(needle) == 1
    changed = text.replace(needle, 'if False:', 1).encode()
    new[VIEW] = admission.digest(changed)
    review["source_changes"][VIEW]["after_sha256"] = new[VIEW]

    # Substitute only the deliberate source mutation while reading the actual CLI.
    def read_candidate(path):
        return changed if path == view_path else original_read(path)

    with patch.object(Path, "read_bytes", read_candidate), pytest.raises(ValueError):
        admission.reviewed_sources(old, new, review)
