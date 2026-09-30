"""Prove the comparison's denominators, frozen inputs and one-call boundaries."""

import copy
import json
from types import SimpleNamespace

import pytest

from backend.agents.trading import grounded_release as grounded
from backend.cli.market_grounded_compare import compare, validate_inputs


# Build a minimal registered corpus with one ambiguous field and one excluded release.
def sample():
    text = "A source without forward guidance or financing commentary."
    row = {
        "id": "sample",
        "status": "ready",
        "text": text,
        "source_sha256": grounded.text_hash(text),
        "source_chars": len(text),
        "published_at": "2022-01-01T20:00:00+00:00",
    }
    label = {
        **row,
        "quotes": [],
        "expected": {
            "guidance": "not_stated",
            "demand": None,
            "financing_risk": "not_stated",
        },
    }
    excluded = {"id": "oversize", "status": "oversize", "expected": None}
    return {"rows": [row, excluded]}, {
        "frozen_before_inference": True,
        "rows": [label, excluded.copy()],
    }


# Answer according to each reader's schema so tests exercise both actual reader paths.
def fixture_writer(invent_quote=False):
    # Keep model metadata and a raw answer just as the existing transport returns them.
    def chat(messages, max_tokens, schema, temperature):
        if schema["title"] == "GroundedRelease":
            payload = {
                field: {"value": "not_stated", "quote": None}
                for field in grounded.VALUES
            }
            if invent_quote:
                payload["guidance"] = {"value": "raised", "quote": "Not in the source."}
        else:
            payload = {
                "guidance": 0,
                "demand": 0,
                "pricing": 0,
                "capex": 0,
                "supply_constrained": 0,
                "summary": "No stated comparison.",
            }
        return {
            "content": json.dumps(payload),
            "model": "fixture",
            "choices": [{"finish_reason": "stop"}],
        }

    return SimpleNamespace(chat=chat)


# Excluded and ambiguous rows stay visible without becoming correct neutral predictions.
def test_comparison_preserves_denominators_and_reader_limits():
    corpus, labels = sample()
    saved = []
    report = compare(corpus, labels, fixture_writer(), "fixture", saved.append)
    summary = report["summary"]
    assert (summary["selected"], summary["eligible"], summary["ambiguous"]) == (2, 1, 1)
    assert (summary["correct"], summary["total"], summary["model_calls"]) == (2, 2, 2)
    assert len(saved) == 2
    row = report["rows"][0]
    assert row["grounded_calls"][0]["max_tokens"] == 1200
    assert row["incumbent_calls"][0]["max_tokens"] == 300
    assert row["incumbent_demand_direction"] == "neutral"
    assert row["result"]["usable_after"] > row["published_at"]


# A bad citation remains a failed extraction with its raw answer, never a dropped row.
def test_invalid_evidence_retains_raw_payload_and_counts_as_missed():
    corpus, labels = sample()
    report = compare(corpus, labels, fixture_writer(invent_quote=True), "fixture")
    assert report["summary"]["correct"] == 0
    assert report["summary"]["total"] == 2
    row = report["rows"][0]
    assert row["grounded_error"] == "ValueError"
    assert "Not in the source" in row["grounded_calls"][0]["content"]
    assert row["incumbent"] is not None


# Changed sources, duplicate cases and naive timestamps fail before inference.
@pytest.mark.parametrize(
    "change", ["text", "hash", "duplicate", "time", "unfrozen", "quote"]
)
def test_changed_manifest_fails_closed(change):
    corpus, labels = sample()
    if change == "text":
        corpus["rows"][0]["text"] += " modified"
    elif change == "hash":
        labels["rows"][0]["source_sha256"] = "wrong"
    elif change == "duplicate":
        corpus["rows"].append(copy.deepcopy(corpus["rows"][0]))
    elif change == "time":
        corpus["rows"][0]["published_at"] = "2022-01-01T20:00:00"
    elif change == "quote":
        labels["rows"][0]["quotes"] = ["invented quotation"]
    else:
        labels["frozen_before_inference"] = False
    with pytest.raises(ValueError, match="Document|Sample|Annotation|Publication"):
        validate_inputs(corpus, labels)


# Transport failures consume one call per reader and remain in the denominator.
def test_transport_failure_is_not_retried_or_scored_as_absence():
    corpus, labels = sample()
    calls = []

    # Record one attempted request then reproduce an unavailable runtime.
    def fail(*args):
        calls.append(args)
        raise TimeoutError("Do not persist a provider's sensitive error body")

    report = compare(corpus, labels, SimpleNamespace(chat=fail), "fixture")
    assert len(calls) == 2
    assert report["summary"]["correct"] == 0
    assert report["summary"]["incumbent_valid"] == 0
    assert "sensitive" not in json.dumps(report)
