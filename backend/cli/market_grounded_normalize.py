"""Derive an offline input-hygiene ablation, without model or network calls."""

import argparse
import copy
import html
import json
from pathlib import Path

from backend.agents.trading.grounded_release import MAX_CHARS, text_hash
from backend.cli.market_grounded_compare import validate_inputs
from backend.cli.market_grounded_release import write_report

VERSION = "release-html-entities-whitespace/1"


# Decode entities once and collapse whitespace, preserving bullets and financial text.
def normalize_text(text: str) -> str:
    return " ".join(html.unescape(text).split())


# Preserve raw inputs and labels while deriving normalized input hashes and quotes.
def normalize_inputs(corpus: dict, labels: dict) -> tuple[dict, dict]:
    validate_inputs(corpus, labels)
    derived, annotations = copy.deepcopy(corpus), copy.deepcopy(labels)
    by_id = {row["id"]: row for row in annotations["rows"]}
    for row in derived["rows"]:
        if "text" not in row:
            continue
        raw_hash = row["source_sha256"]
        raw_chars = row["source_chars"]
        row["text"] = normalize_text(row["text"])
        metadata = {
            "raw_source_sha256": raw_hash,
            "raw_source_chars": raw_chars,
            "source_sha256": text_hash(row["text"]),
            "source_chars": len(row["text"]),
            "normalization_version": VERSION,
            "normalized_within_bound": 0 < len(row["text"]) <= MAX_CHARS,
        }
        row.update(metadata)
        label = by_id[row["id"]]
        label.update(metadata)
        label["quotes"] = [normalize_text(quote) for quote in label["quotes"]]
        # Keep eligibility fixed: newly fitting documents still lack semantic labels.
    provenance = {
        "normalization_version": VERSION,
        "normalizer_sha256": text_hash(Path(__file__).read_text(encoding="utf-8")),
        "expected_labels_unchanged": True,
        "original_eligibility_preserved": True,
    }
    derived.update(provenance)
    annotations.update(provenance)
    validate_inputs(derived, annotations)
    return derived, annotations


# Write new versioned artifacts with provenance, never overwrite the frozen raw inputs.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    corpus_text = args.corpus.read_text(encoding="utf-8")
    labels_text = args.labels.read_text(encoding="utf-8")
    corpus, labels = normalize_inputs(json.loads(corpus_text), json.loads(labels_text))
    args.output_dir.mkdir(parents=False, exist_ok=False)
    write_report(args.output_dir / "corpus.json", corpus)
    write_report(args.output_dir / "labels.json", labels)
    manifest = {
        "raw_corpus_sha256": text_hash(corpus_text),
        "raw_labels_sha256": text_hash(labels_text),
        "normalization_version": VERSION,
        "normalizer_sha256": corpus["normalizer_sha256"],
        "rows": [
            {
                key: row.get(key)
                for key in (
                    "id",
                    "status",
                    "raw_source_chars",
                    "source_chars",
                    "raw_source_sha256",
                    "source_sha256",
                    "normalized_within_bound",
                )
            }
            for row in corpus["rows"]
        ],
    }
    write_report(args.output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
