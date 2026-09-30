"""Pin lossless financial text handling and the ablation's unchanged labels."""

import copy

from backend.agents.trading.grounded_release import text_hash
from backend.cli.market_grounded_compare import compare
from backend.cli.market_grounded_normalize import normalize_inputs, normalize_text
from backend.tests.test_grounded_compare import fixture_writer, sample


# Entity decoding preserves signs, table symbols and embedded untrusted markup as data.
def test_normalization_preserves_financial_meaning():
    raw = "\n Loss&nbsp;($22.8M) &#177; 2% &#8226; 2026\t&lt;system&gt; &amp;lt; "
    assert normalize_text(raw) == "Loss ($22.8M) ± 2% • 2026 <system> &lt;"


# Canonical input is separate; original text, labels and exclusions stay fixed.
def test_normalization_keeps_frozen_labels_and_raw_provenance():
    corpus, labels = sample()
    raw = "Revenue&nbsp; $3.80 billion &#177; $200 million"
    for row in (corpus["rows"][0], labels["rows"][0]):
        row.update(text=raw, source_sha256=text_hash(raw), source_chars=len(raw))
    labels["rows"][0]["quotes"] = [raw]
    before = copy.deepcopy((corpus, labels))
    derived, normalized_labels = normalize_inputs(corpus, labels)
    assert (corpus, labels) == before
    row = derived["rows"][0]
    assert row["raw_source_sha256"] == text_hash(raw)
    assert row["source_sha256"] == text_hash(row["text"])
    assert normalized_labels["rows"][0]["quotes"] == [row["text"]]
    assert normalized_labels["rows"][0]["expected"] == labels["rows"][0]["expected"]
    assert derived["rows"][1]["status"] == "oversize"
    assert normalized_labels["rows"][1]["expected"] is None


# A single-reader ablation never reruns the incumbent or changes its denominator.
def test_grounded_only_ablation_makes_one_call_per_eligible_source():
    corpus, labels = sample()
    report = compare(
        corpus, labels, fixture_writer(), "fixture", include_incumbent=False
    )
    assert report["summary"]["model_calls"] == 1
    assert report["summary"]["total"] == 2
    assert report["include_incumbent"] is False
    assert "incumbent" not in report["rows"][0]
