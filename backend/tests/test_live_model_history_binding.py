"""Approval renewal must not relabel history or admit changed numerical models."""

import ast
import json
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from backend.cli.market_publish_live_history import publish
from backend.market import learned_live_holding
from backend.market import live_model_history_binding as binding
from backend.market import live_model_history_projection as projection
from backend.market.live_model_history_reader import read
from backend.tests.test_live_model_history_reader import publication


# Encode deterministic bytes so the test can authenticate every original snapshot.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2).encode()


# Store a new test artifact without touching its already captured counterpart.
def store(root, name, raw):
    path = root / binding.SNAPSHOTS[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


# Reproduce the original source/config and its approval-only current renewal.
def renewed(root):
    value, old_path = publication(root)
    frozen = root / "frozen"
    review_raw = (
        Path(binding.__file__).resolve().parents[2] / binding.REVIEWS[0]
    ).read_bytes()
    review = json.loads(review_raw)
    original_sources = learned_live_holding.source_identity()
    original_sources[review["changed_reviewed_file"]] = review[
        "previous_approved_sha256"
    ]
    evidence_sha = store(frozen, "evidence", b'{"original_economics":true}\r\n')
    timing = {
        "model_receipt_sha256": "c" * 64,
        "residual_receipt_sha256": "d" * 64,
        "cost_bps": 10,
    }
    timing_sha = store(frozen, "timing", encoded(timing))
    release = {
        "schema": "learned-holding-release/1",
        "approved": True,
        "approved_at": "2026-10-13T17:48:48+00:00",
        "policy": value["policy"],
        "source_sha256": original_sources,
        "evidence_sha256": evidence_sha,
    }
    release_sha = store(frozen, "release", encoded(release))
    config = {
        "policy": value["policy"],
        "cost_bps": 10,
        "model_directory": "model",
        "risk_directory": "risk",
        "model_receipt_sha256": "a" * 64,
        "risk_receipt_sha256": "b" * 64,
        "timing_config_sha256": timing_sha,
        "release_receipt_sha256": release_sha,
    }
    config_sha = store(frozen, "holding", encoded(config))
    capture = {
        "source_sha256": original_sources,
        "files": {
            binding.SNAPSHOTS[name]: sha256(
                (frozen / binding.SNAPSHOTS[name]).read_bytes()
            ).hexdigest()
            for name in ("holding", "timing", "release", "evidence")
        },
    }
    capture_sha = store(frozen, "capture", encoded(capture))
    current_release = {
        **release,
        "approved_at": "2026-10-17T07:34:50+00:00",
        "source_sha256": learned_live_holding.source_identity(),
    }
    current_release_sha = store(root, "release", encoded(current_release))
    store(
        root,
        "holding",
        encoded({**config, "release_receipt_sha256": current_release_sha}),
    )
    for name in ("timing", "evidence"):
        store(root, name, (frozen / binding.SNAPSHOTS[name]).read_bytes())
    value["provenance"].update(
        source_sha256=original_sources,
        holding_config_sha256=config_sha,
        timing_config_sha256=timing_sha,
        capture_sha256=capture_sha,
        model_receipt_sha256=config["model_receipt_sha256"],
        risk_receipt_sha256=config["risk_receipt_sha256"],
        timing_model_receipt_sha256=timing["model_receipt_sha256"],
        timing_residual_receipt_sha256=timing["residual_receipt_sha256"],
    )
    return value, old_path, frozen, [sha256(review_raw).hexdigest()]


# Persist the exact independent proof identity used by the publication boundary.
def proof(root, value):
    path = root / "proof.json"
    path.write_bytes(encoded({"account_sha256": value["provenance"]["account_sha256"]}))
    return path, sha256(path.read_bytes()).hexdigest()


# Preserve all original provenance and amounts across all94 immutable readbacks.
def test_renewed_approval_publishes94_without_relabelling_or_writing_archive(
    tmp_path, monkeypatch
):
    value, old_path, frozen, reviews = renewed(tmp_path)
    original = deepcopy(value["provenance"])
    archived = {
        str(path): path.read_bytes() for path in frozen.rglob("*") if path.is_file()
    }
    old_payload = old_path.read_bytes()
    stocks = {
        f"TEST{index}": {**deepcopy(value), "ticker": f"TEST{index}"}
        for index in range(94)
    }
    monkeypatch.setattr(projection, "project", lambda *_: deepcopy(stocks))
    path, expected = proof(tmp_path, value)
    with pytest.raises(ValueError, match="installed live model configuration"):
        publish(tmp_path / "unused-account", path, expected, tmp_path)
    result = publish(
        tmp_path / "unused-account",
        path,
        expected,
        tmp_path,
        frozen_market=frozen,
        source_reviews=reviews,
    )
    assert result["stocks"] == 94 and result["account_replayed"] is False
    for name in stocks:
        current = read(tmp_path, name)
        assert current["decisions"] == value["decisions"]
        assert {key: current["provenance"][key] for key in original} == original
    assert {
        str(path): path.read_bytes() for path in frozen.rglob("*") if path.is_file()
    } == archived
    assert old_path.read_bytes() == old_payload


# Even a self-consistently rehashed new config cannot change models, costs or risk.
@pytest.mark.parametrize(
    "key,new_value",
    [
        ("cost_bps", 11),
        ("model_receipt_sha256", "e" * 64),
        ("risk_receipt_sha256", "e" * 64),
        ("timing_config_sha256", "e" * 64),
    ],
)
def test_binding_refuses_numerical_configuration_change(tmp_path, key, new_value):
    value, _, frozen, reviews = renewed(tmp_path)
    chain = binding.build(tmp_path, frozen, value["provenance"], source_reviews=reviews)
    config_path = tmp_path / binding.SNAPSHOTS["holding"]
    config = json.loads(config_path.read_bytes())
    config[key] = new_value
    chain["serving_holding_config_sha256"] = store(tmp_path, "holding", encoded(config))
    with pytest.raises(ValueError, match="changed models, economics or release"):
        binding.validate(tmp_path, chain, value["provenance"])


# Changed numerical source cannot hide behind a freshly consistent release receipt.
def test_binding_refuses_unreviewed_numerical_source(tmp_path, monkeypatch):
    value, _, frozen, reviews = renewed(tmp_path)
    chain = binding.build(tmp_path, frozen, value["provenance"], source_reviews=reviews)
    changed = learned_live_holding.source_identity()
    changed["backend/market/forward_arithmetic.py"] = "e" * 64
    monkeypatch.setattr(learned_live_holding, "source_identity", lambda: changed)
    release = json.loads((tmp_path / binding.SNAPSHOTS["release"]).read_bytes())
    release["source_sha256"] = changed
    chain["serving_release_sha256"] = store(tmp_path, "release", encoded(release))
    config = json.loads((tmp_path / binding.SNAPSHOTS["holding"]).read_bytes())
    config["release_receipt_sha256"] = chain["serving_release_sha256"]
    chain["serving_holding_config_sha256"] = store(tmp_path, "holding", encoded(config))
    chain["serving_source_sha256"] = changed
    with pytest.raises(ValueError, match="Unreviewed"):
        binding.validate(tmp_path, chain, value["provenance"])


# Neither a forged review nor missing or changed original archive is an admission.
@pytest.mark.parametrize(
    "part", ["holding", "release", "evidence", "timing", "capture", "review"]
)
def test_binding_rejects_archive_and_review_corruption(tmp_path, part):
    value, _, frozen, reviews = renewed(tmp_path)
    chain = binding.build(tmp_path, frozen, value["provenance"], source_reviews=reviews)
    if part == "review":
        chain["source_reviews_sha256"] = ["e" * 64]
    else:
        chain["archive"][part] += " "
    with pytest.raises(ValueError):
        binding.validate(tmp_path, chain, value["provenance"])


# Reject physical model-array drift before any new manifest can become visible.
def test_binding_rechecks_original_model_bytes(tmp_path):
    value, _, frozen, reviews = renewed(tmp_path)
    model = "desk/learned-holding/model/model.npz"
    for root in (frozen, tmp_path):
        path = root / model
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original model arrays")
    capture = json.loads((frozen / "capture.json").read_bytes())
    capture["files"][model] = sha256((frozen / model).read_bytes()).hexdigest()
    value["provenance"]["capture_sha256"] = store(frozen, "capture", encoded(capture))
    chain = binding.build(tmp_path, frozen, value["provenance"], source_reviews=reviews)
    (tmp_path / model).write_bytes(b"changed model arrays")
    with pytest.raises(ValueError, match="bytes differ"):
        binding.verify_artifacts(tmp_path, chain)


# A trusted guard extension preserves every original holding function except its list.
def test_guard_extension_checks_exact_paths_predecessors_and_function_bodies(
    tmp_path, monkeypatch
):
    sources = learned_live_holding.source_identity()
    tree = ast.parse(Path(learned_live_holding.__file__).read_bytes())
    functions = {
        node.name: sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "source_identity"
    }
    review = {
        "source_changes": {
            name: {"before_sha256": sources.get(name), "after_sha256": "e" * 64}
            for name in (
                "backend/api/v1/market.py",
                "backend/market/learned_live_holding.py",
                "backend/market/live_model_decision.py",
            )
        },
        "original_holding_function_ast_sha256": functions,
    }
    result = dict(sources)
    binding.guard_extension(result, review)
    assert len(result) == 31
    altered = deepcopy(review)
    altered["source_changes"]["backend/market/learned_live_holding.py"][
        "before_sha256"
    ] = "0" * 64
    with pytest.raises(ValueError, match="predecessor"):
        binding.guard_extension(dict(sources), altered)
    altered = deepcopy(review)
    altered["source_changes"]["backend/market/forward_arithmetic.py"] = {
        "before_sha256": sources["backend/market/forward_arithmetic.py"],
        "after_sha256": "f" * 64,
    }
    with pytest.raises(ValueError, match="paths"):
        binding.guard_extension(dict(sources), altered)
    altered = deepcopy(review)
    altered["source_changes"]["backend/api/v1/market.py"]["extra_approval"] = True
    with pytest.raises(ValueError, match="schema"):
        binding.guard_extension(dict(sources), altered)
    path = tmp_path / "holding.py"
    path.write_text(
        Path(learned_live_holding.__file__)
        .read_text()
        .replace(
            "def _release(root, config, now):",
            "def _release(root, config, now):\n    raise ValueError('changed')",
        )
    )
    monkeypatch.setattr(learned_live_holding, "__file__", str(path))
    with pytest.raises(ValueError, match="changed a holding function"):
        binding.guard_extension(dict(sources), review)


# A complete ticker cohort from a short probe still cannot become the full publication.
def test_publisher_refuses_bounded_calendar_before_any_manifest_write(
    tmp_path, monkeypatch
):
    value, _, frozen, reviews = renewed(tmp_path)
    value["through"] = "2019-03-04"
    stock_views = {
        f"TEST{index}": {**deepcopy(value), "ticker": f"TEST{index}"}
        for index in range(94)
    }
    monkeypatch.setattr(projection, "project", lambda *_: stock_views)
    path, expected = proof(tmp_path, value)
    before = {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    with pytest.raises(ValueError, match="bounded stage refused"):
        publish(
            tmp_path / "unused-account",
            path,
            expected,
            tmp_path,
            frozen_market=frozen,
            source_reviews=reviews,
        )
    assert {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before


# A later reviewed API/guard extension must follow the archived earlier review exactly.
def test_review_chain_admits_exact31_source_extension_only_in_order(
    tmp_path, monkeypatch
):
    value, _, _, reviews = renewed(tmp_path)
    current = learned_live_holding.source_identity()
    tree = ast.parse(Path(learned_live_holding.__file__).read_bytes())
    functions = {
        node.name: sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "source_identity"
    }
    paths = (
        "backend/api/v1/market.py",
        "backend/market/learned_live_holding.py",
        "backend/market/live_model_decision.py",
    )
    changes = {
        name: {"before_sha256": current.get(name), "after_sha256": str(index + 1) * 64}
        for index, name in enumerate(paths)
    }
    review = {
        "status": "REVIEWED_EXACT_SERVING_SOURCE_GUARD_EXTENSION",
        "source_changes": changes,
        "original_holding_function_ast_sha256": functions,
    }
    path = tmp_path / "guard-review.json"
    path.write_bytes(encoded(review))
    receipt = sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(binding, "REVIEWS", (*binding.REVIEWS, str(path)))
    monkeypatch.setattr(
        binding, "REVIEW_SHA256", {**binding.REVIEW_SHA256, str(path): receipt}
    )
    serving = {
        **current,
        **{name: change["after_sha256"] for name, change in changes.items()},
    }
    binding.reviewed_sources(
        value["provenance"]["source_sha256"], serving, [*reviews, receipt]
    )
    with pytest.raises(ValueError, match="predecessor"):
        binding.reviewed_sources(
            value["provenance"]["source_sha256"], serving, [receipt, *reviews]
        )
    with pytest.raises(ValueError, match="Unreviewed"):
        binding.reviewed_sources(value["provenance"]["source_sha256"], serving, reviews)


# Reconstruct both real reviewed transitions without importing the urgent API candidate.
def exact_numeric_chain():
    root = Path(binding.__file__).resolve().parents[2]
    rows = [json.loads((root / name).read_bytes()) for name in binding.REVIEWS]
    original = learned_live_holding.source_identity()
    original[rows[0]["changed_reviewed_file"]] = rows[0]["previous_approved_sha256"]
    serving = dict(original)
    serving[rows[0]["changed_reviewed_file"]] = rows[0]["reviewed_serving_sha256"]
    for name, change in rows[1]["source_changes"].items():
        assert serving.get(name) == change["before_sha256"]
        serving[name] = change["after_sha256"]
    receipts = [binding.REVIEW_SHA256[name] for name in binding.REVIEWS]
    return original, serving, receipts


# Trust one explicit test-only receipt without adding any future production approval.
def fixture_api_review(tmp_path, monkeypatch, serving, **changes):
    api = "backend/api/v1/market.py"
    review = {
        "status": "REVIEWED_EXACT_SERVING_SOURCE_APPROVAL_CANDIDATE",
        "changed_reviewed_file": api,
        "previous_approved_sha256": serving[api],
        "reviewed_serving_sha256": "e" * 64,
        "other_reviewed_sources_unchanged": len(serving) - 1,
        "scope": "Controlled test receipt only; not a production approval",
        **changes,
    }
    path = tmp_path / "fixture-third-api-review.json"
    path.write_bytes(encoded(review))
    receipt = sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(binding, "REVIEWS", (*binding.REVIEWS, str(path)))
    monkeypatch.setattr(
        binding, "REVIEW_SHA256", {**binding.REVIEW_SHA256, str(path): receipt}
    )
    return receipt


# Exact committed reviews admit30 original sources to the new31-source binding.
def test_committed_numeric_review_admits_original30_to_exact31():
    original, serving, receipts = exact_numeric_chain()
    assert len(original) == 30
    assert len(serving) == 31
    assert receipts[1] == (
        "2f048a8040532bfdaa49b1101e552457454b526b510b4ee9f2422f3a67a3e5f7"
    )
    binding.reviewed_sources(original, serving, receipts)


# A laterAPI-only31-source review preserves30 other hashes and all original provenance.
def test_later_exact_api31_review_requires30_unchanged_sources(tmp_path, monkeypatch):
    original, serving, receipts = exact_numeric_chain()
    frozen_original = deepcopy(original)
    receipt = fixture_api_review(tmp_path, monkeypatch, serving)
    latest = {**serving, "backend/api/v1/market.py": "e" * 64}
    binding.reviewed_sources(original, latest, [*receipts, receipt])
    assert original == frozen_original
    assert {name for name in serving if serving[name] != latest[name]} == {
        "backend/api/v1/market.py"
    }


# The longer chain preserves frozen provenance and cannot permit changed economics.
def test_full31_binding_keeps_original_archive_and_rejects_changed_cost(
    tmp_path, monkeypatch
):
    value, _, frozen, _ = renewed(tmp_path)
    original = deepcopy(value["provenance"])
    archive = {
        name: (frozen / path).read_bytes() for name, path in binding.SNAPSHOTS.items()
    }
    _, serving, receipts = exact_numeric_chain()
    receipt = fixture_api_review(tmp_path, monkeypatch, serving)
    latest = {**serving, "backend/api/v1/market.py": "e" * 64}
    monkeypatch.setattr(learned_live_holding, "source_identity", lambda: latest)
    release = json.loads((tmp_path / binding.SNAPSHOTS["release"]).read_bytes())
    release.update(source_sha256=latest, approved_at=datetime.now(UTC).isoformat())
    release_sha = store(tmp_path, "release", encoded(release))
    config = json.loads((tmp_path / binding.SNAPSHOTS["holding"]).read_bytes())
    config["release_receipt_sha256"] = release_sha
    store(tmp_path, "holding", encoded(config))
    chain = binding.build(
        tmp_path, frozen, value["provenance"], source_reviews=[*receipts, receipt]
    )
    assert value["provenance"] == original
    assert len(original["source_sha256"]) == 30
    assert len(chain["serving_source_sha256"]) == 31
    assert binding.archived(chain) == archive
    config["cost_bps"] = 11
    chain["serving_holding_config_sha256"] = store(tmp_path, "holding", encoded(config))
    with pytest.raises(ValueError, match="changed models, economics or release"):
        binding.validate(tmp_path, chain, value["provenance"])


# Every31-sourceAPI renewal still rejects stale predecessors, counts and extra changes.
@pytest.mark.parametrize(
    "corruption",
    [
        "old_count",
        "float_count",
        "boolean_count",
        "old_api",
        "same_api",
        "wrong_path",
        "model",
        "projection",
        "extra",
        "missing",
    ],
)
def test_later_api31_review_rejects_unreviewed_source_changes(
    tmp_path, monkeypatch, corruption
):
    original, serving, receipts = exact_numeric_chain()
    changes = {}
    if corruption == "old_count":
        changes["other_reviewed_sources_unchanged"] = 29
    elif corruption == "float_count":
        changes["other_reviewed_sources_unchanged"] = 30.0
    elif corruption == "boolean_count":
        changes["other_reviewed_sources_unchanged"] = True
    elif corruption == "old_api":
        changes["previous_approved_sha256"] = original["backend/api/v1/market.py"]
    elif corruption == "same_api":
        changes["reviewed_serving_sha256"] = serving["backend/api/v1/market.py"]
    elif corruption == "wrong_path":
        changes["changed_reviewed_file"] = "backend/market/forward_arithmetic.py"
    receipt = fixture_api_review(tmp_path, monkeypatch, serving, **changes)
    latest = {**serving, "backend/api/v1/market.py": "e" * 64}
    if corruption == "model":
        latest["backend/market/forward_arithmetic.py"] = "f" * 64
    elif corruption == "projection":
        latest["backend/market/live_model_decision.py"] = "f" * 64
    elif corruption == "extra":
        latest["backend/market/unreviewed.py"] = "f" * 64
    elif corruption == "missing":
        del latest["backend/market/forward_arithmetic.py"]
    with pytest.raises(ValueError, match="Unreviewed"):
        binding.reviewed_sources(original, latest, [*receipts, receipt])


# A chain cannot omit, reorder, repeat or substitute one of its exact review receipts.
@pytest.mark.parametrize(
    "corruption",
    ["reordered", "duplicate", "missing_first", "missing_guard", "unknown"],
)
def test_real_numeric_chain_rejects_incomplete_or_forged_receipt_sequences(
    tmp_path, monkeypatch, corruption
):
    original, serving, receipts = exact_numeric_chain()
    receipt = fixture_api_review(tmp_path, monkeypatch, serving)
    latest = {**serving, "backend/api/v1/market.py": "e" * 64}
    if corruption == "reordered":
        chain = [receipts[1], receipts[0], receipt]
    elif corruption == "duplicate":
        chain = [*receipts, receipts[1], receipt]
    elif corruption == "missing_first":
        chain = [receipts[1], receipt]
    elif corruption == "missing_guard":
        chain = [receipts[0], receipt]
    else:
        chain = [*receipts, "0" * 64]
    with pytest.raises(ValueError, match="(predecessor|Unique|Unreviewed|catalog)"):
        binding.reviewed_sources(original, latest, chain)


# Editing a cataloged review cannot create another trusted hash from the same filename.
def test_review_catalog_pins_actual_committed_numeric_review_bytes(
    tmp_path, monkeypatch
):
    original, serving, receipts = exact_numeric_chain()
    source = Path(binding.__file__).resolve().parents[2] / binding.REVIEWS[1]
    path = tmp_path / "changed-numeric-review.json"
    path.write_bytes(source.read_bytes() + b"\n")
    monkeypatch.setattr(binding, "REVIEWS", (binding.REVIEWS[0], str(path)))
    monkeypatch.setattr(
        binding,
        "REVIEW_SHA256",
        {binding.REVIEWS[0]: receipts[0], str(path): receipts[1]},
    )
    with pytest.raises(ValueError, match="bytes differ"):
        binding.reviewed_sources(original, serving, receipts)
