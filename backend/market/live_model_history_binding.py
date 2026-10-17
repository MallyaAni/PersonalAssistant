"""Authenticate frozen retrospective inputs separately from their serving release."""

import ast
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from backend.market import learned_live_holding
from backend.market.grade_led_policy import POLICY

SCHEMA = "live-model-history-serving-binding/1"
REVIEWS = (
    "docs/research/trading-source-approval-review-2026-10-17.json",
    "docs/research/trading-numeric-source-review-2026-10-17.json",
    "docs/research/settlement-metadata-source-review-2026-10-17.json",
)
REVIEW_SHA256 = {
    REVIEWS[0]: "8b628c76066f62ee724a36d3d07219848786d49d51bb243d73e3e056d7c72bd4",
    REVIEWS[1]: "2f048a8040532bfdaa49b1101e552457454b526b510b4ee9f2422f3a67a3e5f7",
    REVIEWS[2]: "875976f63a530bc14898f3d3121e6177421f82e2275f7a8dabc5cf2b94266ac6",
}
# Exact source_identity map from independently retained installed N2ad44/e0.
N2_SOURCE_SHA256 = "99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab"
SNAPSHOTS = {
    "capture": "capture.json",
    "holding": "desk/learned-holding/config.json",
    "release": "desk/learned-holding/release.json",
    "evidence": "desk/learned-holding/evidence.json",
    "timing": "desk/learned-timing/config.json",
}


# Compare a content identity without accepting non-digest values or coerced types.
def require_hash(raw, expected):
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(char not in "0123456789abcdef" for char in expected)
        or sha256(raw).hexdigest() != expected
    ):
        raise ValueError("Historical serving binding bytes differ")


# Decode only the original archived bytes, retaining their exact encoded identities.
def archived(binding):
    if binding.get("schema") != SCHEMA or set(binding["archive"]) != set(SNAPSHOTS):
        raise ValueError("Complete historical serving binding archive required")
    return {name: raw.encode("utf-8") for name, raw in binding["archive"].items()}


# Verify unchanged holding functions for an explicitly reviewed guard-list extension.
def guard_extension(candidate, review):
    paths = {
        "backend/api/v1/market.py",
        "backend/market/learned_live_holding.py",
        "backend/market/live_model_decision.py",
    }
    if set(review["source_changes"]) != paths:
        raise ValueError("Exact reviewed source guard extension paths required")
    for name, change in review["source_changes"].items():
        if set(change) != {"before_sha256", "after_sha256"}:
            raise ValueError("Exact reviewed source guard extension schema required")
        if candidate.get(name) != change["before_sha256"]:
            raise ValueError("Historical source guard extension predecessor differs")
        if (name not in candidate) != (name == "backend/market/live_model_decision.py"):
            raise ValueError(
                "Only the reviewed read-only projection may extend sources"
            )
        candidate[name] = change["after_sha256"]
    tree = ast.parse(Path(learned_live_holding.__file__).read_bytes())
    functions = {
        node.name: sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "source_identity"
    }
    if functions != review["original_holding_function_ast_sha256"]:
        raise ValueError("Source guard renewal changed a holding function")


# Load immutable committed reviews without trusting filename identity alone.
def review_catalog():
    catalog = {}
    for path in REVIEWS:
        raw = (Path(__file__).resolve().parents[2] / path).read_bytes()
        require_hash(raw, REVIEW_SHA256[path])
        catalog[sha256(raw).hexdigest()] = json.loads(raw)
    return catalog


# Distinguish the original30-source chain from the exact later frozen N2 profile.
def original_profile(original):
    raw = json.dumps(original, sort_keys=True, separators=(",", ":")).encode()
    return len(original) == 30 or (
        len(original) == 31 and sha256(raw).hexdigest() == N2_SOURCE_SHA256
    )


# Reject coerced, incomplete or noncanonical source identities on either profile.
def source_digests(source):
    for value in source.values():
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError("Exact historical trading source digests required")


# Require an exact chain of installed review receipts, never a source wildcard.
def reviewed_sources(original, serving, reviews):
    catalog = review_catalog()
    candidate = dict(original)
    if not isinstance(reviews, list) or len(set(reviews)) != len(reviews):
        raise ValueError("Unique reviewed historical serving source chain required")
    for receipt in reviews:
        if receipt not in catalog:
            raise ValueError("Historical source review is not in the installed catalog")
        review = catalog[receipt]
        if review["status"] == "REVIEWED_EXACT_SERVING_SOURCE_GUARD_EXTENSION":
            guard_extension(candidate, review)
            continue
        if review["status"] == "REVIEWED_EXACT_SETTLEMENT_QUANTITY_METADATA":
            metadata_renewal(candidate, review)
            continue
        name = review["changed_reviewed_file"]
        if (
            review["status"] != "REVIEWED_EXACT_SERVING_SOURCE_APPROVAL_CANDIDATE"
            or name != "backend/api/v1/market.py"
            or isinstance(review["other_reviewed_sources_unchanged"], bool)
            or not isinstance(review["other_reviewed_sources_unchanged"], int)
            or review["other_reviewed_sources_unchanged"] != len(candidate) - 1
            or candidate.get(name) != review["previous_approved_sha256"]
            or review["reviewed_serving_sha256"] == candidate.get(name)
        ):
            raise ValueError("Unreviewed historical-to-serving trading source change")
        candidate[name] = review["reviewed_serving_sha256"]
    if not original_profile(original) or candidate != serving:
        raise ValueError("Unreviewed historical-to-serving trading source change")
    source_digests(original)
    source_digests(serving)


# Apply only the reviewed future-receipt metadata change to the exact N2 predecessor.
def metadata_renewal(candidate, review):
    name = "backend/agents/trading/desk/paper.py"
    if (
        set(review["source_changes"]) != {name}
        or type(review["other_reviewed_sources_unchanged"]) is not int
        or review["other_reviewed_sources_unchanged"] != 30
        or len(candidate) != 31
    ):
        raise ValueError("Exact31-source settlement metadata renewal required")
    change = review["source_changes"][name]
    if (
        set(change) != {"before_sha256", "after_sha256"}
        or candidate.get(name) != change["before_sha256"]
        or change["before_sha256"] == change["after_sha256"]
        or sha256(
            json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != N2_SOURCE_SHA256
    ):
        raise ValueError("Exact N2 settlement metadata predecessor required")
    candidate[name] = change["after_sha256"]


# Admit approval renewal while retaining original numerical and economic fields.
def validate(root, binding, provenance):
    root = Path(root)
    old_raw = archived(binding)
    old = {name: json.loads(raw) for name, raw in old_raw.items()}
    for name, key in (
        ("capture", "capture_sha256"),
        ("holding", "holding_config_sha256"),
        ("timing", "timing_config_sha256"),
    ):
        require_hash(old_raw[name], provenance[key])
    for name in ("holding", "release", "evidence", "timing"):
        require_hash(old_raw[name], old["capture"]["files"][SNAPSHOTS[name]])
    if old["capture"]["source_sha256"] != provenance["source_sha256"]:
        raise ValueError("Historical capture source identity differs")
    require_hash(old_raw["release"], old["holding"]["release_receipt_sha256"])
    require_hash(old_raw["evidence"], old["release"]["evidence_sha256"])
    now = datetime.now(UTC)
    current_raw, current = learned_live_holding.read_configuration(root, now)
    require_hash(current_raw, binding["serving_holding_config_sha256"])
    release_raw = (root / SNAPSHOTS["release"]).read_bytes()
    require_hash(release_raw, binding["serving_release_sha256"])
    release = json.loads(release_raw)
    require_hash(
        (root / SNAPSHOTS["evidence"]).read_bytes(), old["release"]["evidence_sha256"]
    )
    require_hash(
        (root / SNAPSHOTS["timing"]).read_bytes(), provenance["timing_config_sha256"]
    )
    if (
        {
            key: value
            for key, value in current.items()
            if key != "release_receipt_sha256"
        }
        != {
            key: value
            for key, value in old["holding"].items()
            if key != "release_receipt_sha256"
        }
        or old["holding"]["policy"] != POLICY
        or old["holding"]["cost_bps"] != 10
        or old["release"]["source_sha256"] != provenance["source_sha256"]
        or old["release"]["approved"] is not True
        or datetime.fromisoformat(old["release"]["approved_at"]) > now
        or {
            key: value
            for key, value in release.items()
            if key not in ("source_sha256", "approved_at")
        }
        != {
            key: value
            for key, value in old["release"].items()
            if key not in ("source_sha256", "approved_at")
        }
        or binding["account_sha256"] != provenance["account_sha256"]
        or binding["serving_source_sha256"] != learned_live_holding.source_identity()
        or release["source_sha256"] != binding["serving_source_sha256"]
    ):
        raise ValueError(
            "Historical serving binding changed models, economics or release"
        )
    for config, key, target in (
        (old["holding"], "model_receipt_sha256", "model_receipt_sha256"),
        (old["holding"], "risk_receipt_sha256", "risk_receipt_sha256"),
        (old["timing"], "model_receipt_sha256", "timing_model_receipt_sha256"),
        (old["timing"], "residual_receipt_sha256", "timing_residual_receipt_sha256"),
    ):
        if config[key] != provenance[target]:
            raise ValueError("Historical serving binding model receipt differs")
    reviewed_sources(
        provenance["source_sha256"],
        release["source_sha256"],
        binding["source_reviews_sha256"],
    )


# Recheck installed model arrays and receipts against the frozen capture.
def verify_artifacts(root, binding):
    capture = json.loads(archived(binding)["capture"])
    for path, expected in capture["files"].items():
        if path.startswith("desk/learned-") and path not in (
            SNAPSHOTS["holding"],
            SNAPSHOTS["release"],
        ):
            if path not in SNAPSHOTS.values() and (
                Path(path).is_absolute() or ".." in Path(path).parts
            ):
                raise ValueError("Relative historical model artifact path required")
            require_hash((Path(root) / path).read_bytes(), expected)


# Build a separate immutable binding without editing the original account or capture.
def build(root, frozen_market, provenance, *, source_reviews):
    root, frozen_market = Path(root), Path(frozen_market)
    value = {
        "schema": SCHEMA,
        "account_sha256": provenance["account_sha256"],
        "archive": {
            name: (frozen_market / path).read_bytes().decode("utf-8")
            for name, path in SNAPSHOTS.items()
        },
        "serving_holding_config_sha256": sha256(
            (root / SNAPSHOTS["holding"]).read_bytes()
        ).hexdigest(),
        "serving_release_sha256": sha256(
            (root / SNAPSHOTS["release"]).read_bytes()
        ).hexdigest(),
        "serving_source_sha256": learned_live_holding.source_identity(),
        "source_reviews_sha256": list(source_reviews),
    }
    validate(root, value, provenance)
    verify_artifacts(root, value)
    return value
