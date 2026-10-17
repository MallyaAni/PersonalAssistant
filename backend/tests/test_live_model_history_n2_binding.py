"""Frozen N2 history retains exact sources across serving metadata renewal."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from backend.market import learned_live_holding
from backend.market import live_model_history_binding as binding
from backend.tests.test_live_model_history_binding import (
    encoded,
    exact_numeric_chain,
    renewed,
    store,
)

PAPER = "backend/agents/trading/desk/paper.py"
N2 = "99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab"


# Read the independently retained actual N2 source manifest, never current selectors.
def sources():
    path = Path("/proof.json")
    if not path.is_file():
        path = (
            Path(binding.__file__).resolve().parents[2]
            / "docs/research"
            / "historical-numeric-merge-source-review-PROPOSED-2026-10-17.json"
        )
    value = json.loads(path.read_bytes())["source_sha256"]
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    assert len(value) == 31
    assert sha256(raw).hexdigest() == N2
    return value


# Permit the unchanged frozen N2 profile without replaying earlier source renewals.
def test_exact_n2_original_profile_retains_all31_sources():
    original = sources()
    before = deepcopy(original)
    binding.reviewed_sources(original, dict(original), [])
    assert original == before


# Exercise the exact actual N2 image source map, not only the external declaration.
@pytest.mark.skipif(
    not Path("/proof.json").is_file(), reason="Explicit retained N2 native fixture only"
)
def test_actual_native_image_sources_equal_retained_n2_manifest():
    assert learned_live_holding.source_identity() == sources()


# Keep ordinary repository tests portable without changing the declared frozen profile.
def test_committed_declaration_matches_retained_native_fixture(monkeypatch):
    original = sources()
    is_file = Path.is_file

    # Exercise the committed declaration when the private native mount is absent.
    def without_native(self):
        return False if str(self) == "/proof.json" else is_file(self)

    monkeypatch.setattr(Path, "is_file", without_native)
    assert sources() == original


# Read only the exact catalogued delivered metadata review, retaining original bytes.
def review():
    path = Path(binding.__file__).resolve().parents[2] / binding.REVIEWS[2]
    raw = path.read_bytes()
    receipt = sha256(raw).hexdigest()
    assert receipt == binding.REVIEW_SHA256[binding.REVIEWS[2]]
    return json.loads(raw), receipt


# Preserve the frozen map while admitting only the deployed paper receipt metadata.
def test_exact_n2_to_delivered_metadata_preserves_original():
    original = sources()
    before = deepcopy(original)
    change, receipt = review()
    latest = {**original, PAPER: change["source_changes"][PAPER]["after_sha256"]}
    binding.reviewed_sources(original, latest, [receipt])
    assert original == before
    assert {name for name in latest if latest[name] != original[name]} == {PAPER}


# Preserve the original30 provenance through both earlier reviews and metadata renewal.
def test_original30_to_metadata_keeps_all_three_exact_review_steps(monkeypatch):
    monkeypatch.setattr(learned_live_holding, "source_identity", sources)
    original, n2, receipts = exact_numeric_chain()
    changes, receipt = review()
    assert n2 == sources()
    latest = {**n2, PAPER: changes["source_changes"][PAPER]["after_sha256"]}
    binding.reviewed_sources(original, latest, [*receipts, receipt])
    with pytest.raises(ValueError, match="(predecessor|renewal)"):
        binding.reviewed_sources(original, latest, [receipt, *receipts])


# A31-file count cannot admit a different source profile even when serving agrees.
@pytest.mark.parametrize("part", ["paper", "model", "missing", "extra"])
def test_other31_source_profiles_are_rejected(part):
    original = sources()
    if part == "missing":
        del original[PAPER]
    elif part == "extra":
        original["backend/market/unreviewed.py"] = "0" * 64
    else:
        original[
            PAPER if part == "paper" else "backend/market/forward_arithmetic.py"
        ] = "0" * 64
    # A30-source same-map legacy path is intentional, so retain31 count here.
    if part == "missing":
        original["backend/market/unreviewed.py"] = "0" * 64
    with pytest.raises(ValueError, match="Unreviewed"):
        binding.reviewed_sources(original, dict(original), [])


# Never accept a changed paper source without the exact recorded renewal receipt.
@pytest.mark.parametrize("receipts", [[], ["0" * 64]])
def test_metadata_change_requires_catalogued_review(receipts):
    original = sources()
    change, _ = review()
    latest = {**original, PAPER: change["source_changes"][PAPER]["after_sha256"]}
    with pytest.raises(ValueError, match="(Unreviewed|catalog)"):
        binding.reviewed_sources(original, latest, receipts)


# Review corruption cannot alter predecessors, source scope or conserved counts.
@pytest.mark.parametrize(
    "part", ["count", "boolean", "path", "before", "same", "extra"]
)
def test_metadata_renewal_rejects_corruption(part):
    candidate = sources()
    value, _ = review()
    if part == "count":
        value["other_reviewed_sources_unchanged"] = 29
    elif part == "boolean":
        value["other_reviewed_sources_unchanged"] = True
    elif part == "path":
        value["source_changes"]["backend/api/v1/market.py"] = value[
            "source_changes"
        ].pop(PAPER)
    elif part == "before":
        value["source_changes"][PAPER]["before_sha256"] = "0" * 64
    elif part == "same":
        value["source_changes"][PAPER]["after_sha256"] = candidate[PAPER]
    else:
        candidate["backend/market/forward_arithmetic.py"] = "0" * 64
    before = deepcopy(candidate)
    with pytest.raises(ValueError, match="(renewal|predecessor)"):
        binding.metadata_renewal(candidate, value)
    assert candidate == before


# Preserve synthetic archived N2 selectors across current metadata renewal.
def test_archived_n2_build_keeps_sources_configs_and_model_receipts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(learned_live_holding, "source_identity", sources)
    value, _, frozen, _ = renewed(tmp_path)
    original = sources()
    release = json.loads((frozen / binding.SNAPSHOTS["release"]).read_bytes())
    release["source_sha256"] = original
    release_sha = store(frozen, "release", encoded(release))
    config = json.loads((frozen / binding.SNAPSHOTS["holding"]).read_bytes())
    config["release_receipt_sha256"] = release_sha
    config_sha = store(frozen, "holding", encoded(config))
    capture = json.loads((frozen / binding.SNAPSHOTS["capture"]).read_bytes())
    capture["source_sha256"] = original
    capture["files"][binding.SNAPSHOTS["release"]] = release_sha
    capture["files"][binding.SNAPSHOTS["holding"]] = config_sha
    capture_sha = store(frozen, "capture", encoded(capture))
    provenance = value["provenance"]
    provenance.update(
        source_sha256=original,
        capture_sha256=capture_sha,
        holding_config_sha256=config_sha,
    )
    original_provenance = deepcopy(provenance)
    archive = {
        name: (frozen / path).read_bytes() for name, path in binding.SNAPSHOTS.items()
    }
    changes, receipt = review()
    latest = {**original, PAPER: changes["source_changes"][PAPER]["after_sha256"]}
    monkeypatch.setattr(learned_live_holding, "source_identity", lambda: latest)
    release["source_sha256"] = latest
    current_release_sha = store(tmp_path, "release", encoded(release))
    store(
        tmp_path,
        "holding",
        encoded({**config, "release_receipt_sha256": current_release_sha}),
    )
    chain = binding.build(tmp_path, frozen, provenance, source_reviews=[receipt])
    assert binding.archived(chain) == archive
    assert provenance == original_provenance
    assert chain["serving_source_sha256"] == latest
    binding.validate(tmp_path, chain, provenance)
    config["cost_bps"] = 11
    config["release_receipt_sha256"] = current_release_sha
    chain["serving_holding_config_sha256"] = store(tmp_path, "holding", encoded(config))
    with pytest.raises(ValueError, match="changed models, economics or release"):
        binding.validate(tmp_path, chain, provenance)
