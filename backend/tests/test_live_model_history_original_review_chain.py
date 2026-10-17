"""Original audit admission stays frozen as serving review catalogs grow."""

import json
from pathlib import Path

import pytest

from backend.market import live_model_history_binding as binding
from backend.market import live_model_history_stream_audit as audit


# Keep the original two source transitions independent of the delivered metadata review.
def test_original_audit_selects_only_exact_frozen_n2_reviews():
    root = Path(binding.__file__).resolve().parents[2]
    n2 = json.loads(
        (
            root
            / "docs/research"
            / "historical-numeric-merge-source-review-PROPOSED-2026-10-17.json"
        ).read_bytes()
    )["source_sha256"]
    assert binding.original_profile(n2)
    first, numeric = [
        json.loads((root / path).read_bytes()) for path in audit.ORIGINAL_SOURCE_REVIEWS
    ]
    original = dict(n2)
    for name, change in numeric["source_changes"].items():
        if change["before_sha256"] is None:
            del original[name]
        else:
            original[name] = change["before_sha256"]
    original[first["changed_reviewed_file"]] = first["previous_approved_sha256"]
    selected = [binding.REVIEW_SHA256[path] for path in audit.ORIGINAL_SOURCE_REVIEWS]
    assert len(selected) == 2
    binding.reviewed_sources(original, n2, selected)
    assert len(binding.REVIEWS) == 3
    with pytest.raises(ValueError, match="Unreviewed"):
        binding.reviewed_sources(
            original, n2, [binding.REVIEW_SHA256[path] for path in binding.REVIEWS]
        )
