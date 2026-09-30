"""Compare frozen release readers without touching trading or market state."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading import grounded_release as grounded
from backend.agents.trading import release_tone as tone
from backend.cli.market_grounded_release import write_report
from backend.core.llm import OpenAICompatibleInferenceProvider


class RecordingWriter:
    # Keep public model answers and request fingerprints, never credentials.
    def __init__(self, writer) -> None:
        self.writer = writer
        self.calls: list[dict] = []

    # Forward exactly one call with the reader's original bounds and retain failures.
    def chat(self, messages, max_tokens, response_schema, temperature):
        record = {
            "input_sha256": grounded.text_hash(messages[-1]["content"]),
            "input_chars": len(messages[-1]["content"]),
            "prompt_sha256": grounded.text_hash(messages[0]["content"]),
            "schema_sha256": grounded.text_hash(
                json.dumps(response_schema, sort_keys=True)
            ),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        self.calls.append(record)
        started = time.monotonic()
        try:
            result = self.writer.chat(
                messages, max_tokens, response_schema, temperature
            )
            record.update(
                content=result.get("content"),
                model=result.get("model"),
                usage=result.get("usage"),
                finish_reasons=[
                    choice.get("finish_reason") for choice in result.get("choices", [])
                ],
            )
            return result
        except Exception as exc:
            record["error"] = type(exc).__name__
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - started


# Refuse changed sources, labels or sample size before spending any model calls.
def validate_inputs(corpus: dict, labels: dict) -> dict:
    rows = corpus["rows"]
    annotations = {row["id"]: row for row in labels["rows"]}
    ids = [row["id"] for row in rows]
    if (
        not 1 <= len(rows) <= 12
        or len(set(ids)) != len(ids)
        or len(annotations) != len(labels["rows"])
        or set(ids) != set(annotations)
        or labels.get("frozen_before_inference") is not True
    ):
        raise ValueError("Sample does not match the frozen annotation manifest")
    for row in rows:
        validate_row(row, annotations[row["id"]])
    return annotations


# Check one document's integrity and the eligibility of its frozen expected values.
def validate_row(row: dict, label: dict) -> None:
    if any(
        row.get(key) != label.get(key)
        for key in ("status", "published_at", "source_chars")
    ):
        raise ValueError("Document metadata changed after annotation")
    if "text" in row:
        digest = grounded.text_hash(row["text"])
        if digest != row["source_sha256"] or digest != label["source_sha256"]:
            raise ValueError("Document hash differs from the frozen label")
        if len(row["text"]) != row["source_chars"]:
            raise ValueError("Document length differs from its metadata")
        if any(quote not in row["text"] for quote in label["quotes"]):
            raise ValueError("Annotation quotation is absent from the source")
    if row["status"] != "ready":
        return
    if not row["text"].strip() or len(row["text"]) > grounded.MAX_CHARS:
        raise ValueError("Eligible input exceeds the frozen reader bound")
    published = datetime.fromisoformat(row["published_at"])
    if published.tzinfo is None or published.utcoffset() is None:
        raise ValueError("Publication instant must include a timezone")
    expected = label["expected"]
    if not isinstance(expected, dict) or set(expected) != set(grounded.VALUES):
        raise ValueError("Eligible annotations require every feature")
    for field, value in expected.items():
        if value is not None and value not in grounded.VALUES[field]:
            raise ValueError("Annotation value is outside the reader contract")


# Score known labels without converting ambiguity or extraction failure into success.
def summarize(rows: list[dict]) -> dict:
    ready = [row for row in rows if row["status"] == "ready"]
    fields = {}
    for field in grounded.VALUES:
        scored = [row for row in ready if row["expected"][field] is not None]
        correct = sum(
            row.get("observed", {}).get(field) == row["expected"][field]
            for row in scored
        )
        fields[field] = {"correct": correct, "total": len(scored)}
    return {
        "selected": len(rows),
        "eligible": len(ready),
        "grounded_valid": sum("result" in row for row in ready),
        "incumbent_valid": sum(row.get("incumbent") is not None for row in ready),
        "fields": fields,
        "correct": sum(item["correct"] for item in fields.values()),
        "total": sum(item["total"] for item in fields.values()),
        "ambiguous": sum(
            value is None for row in ready for value in row["expected"].values()
        ),
        "model_calls": sum(
            len(row.get(key, []))
            for row in ready
            for key in ("grounded_calls", "incumbent_calls")
        ),
    }


# Run each frozen reader once per eligible release and checkpoint every completed pair.
def compare(corpus: dict, labels: dict, writer, model: str, save_row=None) -> dict:
    annotations = validate_inputs(corpus, labels)
    rows = []
    for source in corpus["rows"]:
        row = {key: value for key, value in source.items() if key != "text"}
        row["expected"] = annotations[row["id"]]["expected"]
        if row["status"] == "ready":
            captured = RecordingWriter(writer)
            try:
                row["result"] = grounded.extract(
                    captured,
                    source["text"],
                    published_at=datetime.fromisoformat(source["published_at"]),
                    model=model,
                )
                row["observed"] = {
                    field: fact["value"]
                    for field, fact in row["result"]["features"].items()
                }
            except Exception as exc:
                row["grounded_error"] = type(exc).__name__
            row["grounded_calls"] = captured.calls
            incumbent = RecordingWriter(writer)
            answer = tone.ReleaseToneReader(incumbent).score_sync(source["text"])
            row["incumbent"] = asdict(answer) if answer else None
            row["incumbent_calls"] = incumbent.calls
            if answer:
                row["incumbent_demand_direction"] = (
                    "strengthening"
                    if answer.demand > 0.2
                    else "weakening"
                    if answer.demand < -0.2
                    else "neutral"
                )
        rows.append(row)
        if save_row:
            save_row(row)
        print(f"{row['id']}: {row.get('observed', row['status'])}", flush=True)
    return {
        "scope": "real-release reading diagnostic, not trading performance",
        "model": model,
        "grounded_version": grounded.VERSION,
        "incumbent_version": tone.PROMPT_VERSION,
        "completed_at": datetime.now(UTC).isoformat(),
        "summary": summarize(rows),
        "rows": rows,
    }


# Reserve a new artifact directory and run only the explicitly named existing model.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--llm-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    corpus_text = args.corpus.read_text(encoding="utf-8")
    labels_text = args.labels.read_text(encoding="utf-8")
    corpus, labels = json.loads(corpus_text), json.loads(labels_text)
    validate_inputs(corpus, labels)
    args.output_dir.mkdir(parents=False, exist_ok=False)
    provenance = {
        "revision": args.revision,
        "corpus_sha256": grounded.text_hash(corpus_text),
        "labels_sha256": grounded.text_hash(labels_text),
        "started_at": datetime.now(UTC).isoformat(),
    }
    write_report(args.output_dir / "manifest.json", provenance)
    writer = OpenAICompatibleInferenceProvider(
        args.llm_url, args.model, timeout_seconds=120, reasoning_effort=""
    )

    # Use numeric artifact names so source identifiers cannot escape the run directory.
    def save_row(row):
        index = next(
            i for i, item in enumerate(corpus["rows"]) if item["id"] == row["id"]
        )
        write_report(args.output_dir / f"row-{index:02d}.json", row)

    report = compare(corpus, labels, writer, args.model, save_row)
    report.update(provenance)
    write_report(args.output_dir / "report.json", report)
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
