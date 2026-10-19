"""A metadata-only settlement renewal cannot change trading logic or other sources."""

import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from backend.cli import market_release_admission as admission

PAPER = "backend/agents/trading/desk/paper.py"
MODULE = "fd020b3dba801a47ed7e374e469b12cbaa1390d34de92121cb66148a61a65e7f"
SETTLED = "92e332d28c784b26a0eb11096f807fc2d9cb2e5298a0ff66563bc7a121418bbf"
ORIGINAL = "a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c"
CURRENT = "1a96dd96c254abb4799c6f14cb99938c65fb2907d6777fbc4b1194bfaa851bc4"
ORIGINAL_SAVE = '''# Stream identical JSON bytes before atomically replacing the durable account state.
def save_state(root: Path, state: PaperState) -> Path:
    """Write the PaperState and return its path."""
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(state, handle, indent=2, default=_state_json)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path'''


# Require the real guard to reject corruption in the dependency-free native runner.
@contextmanager
def rejected():
    try:
        yield
    except ValueError:
        return
    raise AssertionError("Corrupted source review was admitted")


# Reconstruct the prior whole source as inert data while pinning both complete files.
def original_paper_source():
    raw = (Path(admission.__file__).resolve().parents[2] / PAPER).read_bytes()
    if admission.digest(raw) != CURRENT:
        raise AssertionError("Exact ownership candidate source required by legacy fixture")
    text = raw.decode()
    functions = [
        node for node in ast.parse(text).body
        if isinstance(node, ast.FunctionDef) and node.name == "save_state"
    ]
    if len(functions) != 1:
        raise AssertionError("One current native writer required by legacy fixture")
    selected = (
        "# Preserve account access while streaming identical JSON before atomic replacement.\n"
        + ast.get_source_segment(text, functions[0])
    )
    if text.count(selected) != 1:
        raise AssertionError("Exact current writer comment and source required")
    original = text.replace(selected, ORIGINAL_SAVE, 1).encode()
    if admission.digest(original) != ORIGINAL:
        raise AssertionError("Reconstructed prior paper source differs")
    return original


# Build the unchanged legacy review around exact original paper bytes, never new code.
def transition():
    raw = original_paper_source()
    new = {PAPER: admission.digest(raw)}
    new.update({f"original/source-{number}": "a" * 64 for number in range(30)})
    old = {
        **new,
        PAPER: "e2eef2f0270497d9a5944212d6581b7ebf503d2675687a172e76690fcc7bc3c3",
    }
    review = {
        "status": "REVIEWED_EXACT_SETTLEMENT_QUANTITY_METADATA",
        "source_changes": {
            PAPER: {"before_sha256": old[PAPER], "after_sha256": new[PAPER]}
        },
        "other_reviewed_sources_unchanged": 30,
        "unchanged_paper_module_ast_sha256": MODULE,
        "original_settled_ast_sha256": SETTLED,
    }
    return old, new, review, raw


# Exercise real source renewal without models or installed selector writes.
class SettlementAdmissionTests(TestCase):
    # Only the exact paper metadata change is admitted under the new review kind.
    def test_exact_metadata_transition_is_admitted(self):
        old, new, review, raw = transition()
        with patch.object(Path, "read_bytes", return_value=raw):
            admission.reviewed_sources(old, new, review)

    # The older settlement-only review cannot approve the new ownership writer.
    def test_prior_settlement_kind_refuses_current_ownership_writer(self):
        old, new, review, _ = transition()
        current = (Path(admission.__file__).resolve().parents[2] / PAPER).read_bytes()
        self.assertEqual(admission.digest(current), CURRENT)
        new[PAPER] = CURRENT
        review["source_changes"][PAPER]["after_sha256"] = CURRENT
        with self.assertRaisesRegex(ValueError, "planning or persistence change"):
            admission.reviewed_sources(old, new, review)

    # Any other guarded module or cohort membership change fails the narrow renewal.
    def test_other_source_changes_and_map_membership_are_rejected(self):
        for change in ("other", "add", "remove", "no_change"):
            with self.subTest(change=change):
                old, new, review, raw = transition()
                if change == "other":
                    new["original/source-0"] = "b" * 64
                elif change == "add":
                    new["extra/source"] = "b" * 64
                elif change == "remove":
                    del new["original/source-0"]
                else:
                    old[PAPER] = new[PAPER]
                with patch.object(Path, "read_bytes", return_value=raw), rejected():
                    admission.reviewed_sources(old, new, review)

    # A valid review label cannot substitute wrong predecessor, candidate or AST pins.
    def test_review_corruptions_are_rejected(self):
        for change in ("before", "after", "count", "module", "settled", "extra"):
            with self.subTest(change=change):
                old, new, review, raw = transition()
                if change in ("before", "after"):
                    review["source_changes"][PAPER][change + "_sha256"] = "f" * 64
                elif change == "count":
                    review["other_reviewed_sources_unchanged"] = 29
                elif change == "extra":
                    review["source_changes"]["other"] = {}
                else:
                    key = (
                        "unchanged_paper_module_ast_sha256"
                        if change == "module"
                        else "original_settled_ast_sha256"
                    )
                    review[key] = "f" * 64
                with patch.object(Path, "read_bytes", return_value=raw), rejected():
                    admission.reviewed_sources(old, new, review)

    # Approval cannot hide changes to planner constants, orders or persistence.
    def test_unrelated_paper_logic_changes_are_rejected(self):
        for change in (
            "constant",
            "planned_field",
            "settled_field",
            "persistence",
            "new_function",
        ):
            with self.subTest(change=change):
                old, new, review, raw = transition()
                text = raw.decode()
                if change == "constant":
                    text += "\nUNREVIEWED_CONSTANT = 1\n"
                elif change == "planned_field":
                    original = "class PaperOrder:"
                    assert original in text
                    text = text.replace(
                        original, original + "\n    unreviewed: int = 0", 1
                    )
                elif change == "settled_field":
                    original = "class Settled:"
                    assert original in text
                    text = text.replace(
                        original, original + "\n    unreviewed: int = 0", 1
                    )
                elif change == "persistence":
                    original = "def save_state(root: Path, state: PaperState) -> Path:"
                    assert original in text
                    text = text.replace(
                        original,
                        original + "\n    raise RuntimeError('changed persistence')",
                        1,
                    )
                else:
                    text += (
                        "\n# Unapproved behavior is deliberately refused."
                        "\ndef unreviewed():\n    return 1\n"
                    )
                changed = text.encode()
                new[PAPER] = admission.digest(changed)
                review["source_changes"][PAPER]["after_sha256"] = new[PAPER]
                with patch.object(Path, "read_bytes", return_value=changed), rejected():
                    admission.reviewed_sources(old, new, deepcopy(review))


if __name__ == "__main__":
    main(verbosity=2)
