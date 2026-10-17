"""A metadata-only settlement renewal cannot change trading logic or other sources."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from backend.cli import market_release_admission as admission

PAPER = "backend/agents/trading/desk/paper.py"
MODULE = "fd020b3dba801a47ed7e374e469b12cbaa1390d34de92121cb66148a61a65e7f"
SETTLED = "92e332d28c784b26a0eb11096f807fc2d9cb2e5298a0ff66563bc7a121418bbf"


# Require the real guard to reject corruption in the dependency-free native runner.
@contextmanager
def rejected():
    try:
        yield
    except ValueError:
        return
    raise AssertionError("Corrupted source review was admitted")


# Build an exact synthetic source-map transition around the reviewed candidate bytes.
def transition():
    raw = (Path(admission.__file__).resolve().parents[2] / PAPER).read_bytes()
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
        old, new, review, _ = transition()
        admission.reviewed_sources(old, new, review)

    # Any other guarded module or cohort membership change fails the narrow renewal.
    def test_other_source_changes_and_map_membership_are_rejected(self):
        for change in ("other", "add", "remove", "no_change"):
            with self.subTest(change=change):
                old, new, review, _ = transition()
                if change == "other":
                    new["original/source-0"] = "b" * 64
                elif change == "add":
                    new["extra/source"] = "b" * 64
                elif change == "remove":
                    del new["original/source-0"]
                else:
                    old[PAPER] = new[PAPER]
                with rejected():
                    admission.reviewed_sources(old, new, review)

    # A valid review label cannot substitute wrong predecessor, candidate or AST pins.
    def test_review_corruptions_are_rejected(self):
        for change in ("before", "after", "count", "module", "settled", "extra"):
            with self.subTest(change=change):
                old, new, review, _ = transition()
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
                with rejected():
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
