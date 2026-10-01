"""Re-score masked releases with the desk's own tone reader (arm B), and ask
the leak question (the registered check before any score is read).

    python -m backend.cli.market_tone_rescore leak --sample work/leak_sample.jsonl \\
        --answers work/leak_answers.jsonl
    python -m backend.cli.market_tone_rescore score --masked work/masked \\
        --out work/tone_masked --concurrency 4

`docs/research/tone-validity-plan-2026-09-30.md`, arm B: the same model and
prompt (`release_tone/3`, `ReleaseToneReader`) read the masked text
(`market_tone_validity mask`) instead of the release. `score` writes one
partial file per name, `<out>/<ticker>.jsonl`, in the tone pipeline's own
partial format (`language.append_partial`), which `market_tone_validity
evaluate --tone-masked <out>` reads; a run interrupted mid-way resumes from
what it wrote. `leak` sends each sampled masked release with the leak
question and writes `{accession, answer}` lines for `market_tone_validity
leak-score`.

The reader is the nightly's (`market_tone.clients`): the deployment's own
model server, so a score here is the same reading the desk would make of
the masked text. Nothing here writes to the market store.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from backend.agents.trading.release_tone import PROMPT_VERSION, ReleaseTone
from backend.market import language

# The leak question's answer budget and its schema.
LEAK_MAX_TOKENS = 120
LEAK_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string"},
        "quarter": {"type": "string"},
        "year": {"type": "string"},
    },
    "required": ["company", "quarter", "year"],
}


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("score", help="re-score masked releases (arm B)")
    s.add_argument("--masked", required=True, type=Path, help="<out>/masked of the mask step")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--concurrency", type=int, default=4)
    s.add_argument("--llm-url", default="")
    s.add_argument("--llm-model", default="")
    s.add_argument("--limit", type=int, default=None, help="score at most this many (smoke)")
    k = sub.add_parser("leak", help="ask the leak question on the sample")
    k.add_argument("--sample", required=True, type=Path)
    k.add_argument("--answers", required=True, type=Path)
    k.add_argument("--concurrency", type=int, default=4)
    k.add_argument("--llm-url", default="")
    k.add_argument("--llm-model", default="")
    return parser


# The masked rows of one name's JSONL, in file order.
def read_masked(path: Path) -> list[dict[str, Any]]:
    """Return the rows of a masked JSONL file."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


# A ToneRecord from the reader's ReleaseTone for a masked row.
def to_record(row: dict[str, Any], tone: ReleaseTone, model: str) -> language.ToneRecord:
    """Return the ToneRecord of a scored masked release."""
    return language.ToneRecord(
        accession=str(row["accession"]),
        reaction_date=date.fromisoformat(row["reaction_date"]),
        guidance=tone.guidance,
        demand=tone.demand,
        pricing=tone.pricing,
        capex=tone.capex,
        supply_constrained=tone.supply_constrained,
        summary=tone.summary,
        model=model,
        prompt_version=PROMPT_VERSION,
        truncated=tone.truncated,
        quarter_end=date.fromisoformat(tone.quarter_end) if tone.quarter_end else None,
        revenue_usd_m=tone.revenue_usd_m,
        eps_usd=tone.eps_usd,
        net_income_usd_m=tone.net_income_usd_m,
        gross_margin_pct=tone.gross_margin_pct,
    )


# Score every masked release of every name under `masked` that `out` does
# not hold yet, `concurrency` at a time with one reader each; each score is
# appended to the name's partial file as it arrives. `readers` are objects
# with `score_sync(text)`; `model` names them. Returns (scored, failed).
def score_masked(
    masked: Path,
    out: Path,
    readers: Sequence[Any],
    model: str,
    log: Callable[[str], None] = print,
    limit: int | None = None,
) -> tuple[int, int]:
    """Return (scored, failed) over the run."""
    out.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    scored = failed = 0
    budget = limit
    for path in sorted(masked.glob("*.jsonl")):
        ticker = path.stem
        partial = out / f"{ticker}.jsonl"
        done = set(language.read_partial(partial)) if partial.exists() else set()
        todo = [r for r in read_masked(path) if str(r["accession"]) not in done]
        if budget is not None:
            todo = todo[: max(budget, 0)]
            budget -= len(todo)
        if not todo:
            continue

        # One release through one reader.
        def work(item: tuple[int, dict[str, Any]]) -> tuple[dict[str, Any], ReleaseTone | None]:
            index, row = item
            try:
                return row, readers[index % len(readers)].score_sync(str(row["text"]))
            except Exception as exc:  # noqa: BLE001 - one failure must not end the run
                log(f"{ticker:6} {row['accession']} failed: {exc}")
                return row, None

        with ThreadPoolExecutor(max_workers=len(readers)) as pool:
            for row, tone in pool.map(work, enumerate(todo)):
                if tone is None:
                    failed += 1
                    continue
                language.append_partial(partial, to_record(row, tone, model))
                scored += 1
        log(
            f"{ticker:6} {len(todo):3d} scored, {len(done):3d} kept "
            f"({time.monotonic() - began:.0f}s; failed so far {failed})"
        )
        if budget is not None and budget <= 0:
            break
    return scored, failed


# Ask the leak question of every sampled release not yet answered, writing
# `{accession, answer}` lines; `writers` are chat providers (`chat`).
def ask_leak(
    sample: Path, answers: Path, writers: Sequence[Any], log: Callable[[str], None] = print
) -> int:
    """Return the number of answers written."""
    rows = read_masked(sample)
    done: set[str] = set()
    if answers.exists():
        done = {str(json.loads(l)["accession"]) for l in answers.read_text().splitlines() if l.strip()}
    todo = [r for r in rows if str(r["accession"]) not in done]

    # One question through one writer.
    def work(item: tuple[int, dict[str, Any]]) -> tuple[str, Any]:
        index, row = item
        try:
            result = writers[index % len(writers)].chat(
                [{"role": "user", "content": str(row["prompt"])}],
                LEAK_MAX_TOKENS,
                LEAK_SCHEMA,
                0.0,
            )
            return str(row["accession"]), result.get("content", "")
        except Exception as exc:  # noqa: BLE001 - keep asking
            log(f"{row['accession']} failed: {exc}")
            return str(row["accession"]), None

    written = 0
    with ThreadPoolExecutor(max_workers=len(writers)) as pool, answers.open("a", encoding="utf-8") as fh:
        for accession, answer in pool.map(work, enumerate(todo)):
            if answer is None:
                continue
            fh.write(json.dumps({"accession": accession, "answer": answer}) + "\n")
            fh.flush()
            written += 1
    log(f"{written} answers written ({len(done)} kept)")
    return written


# Run the command.
def main(argv: list[str] | None = None) -> int:
    """Run the command line."""
    args = build_parser().parse_args(argv)
    from backend.cli.market_tone import clients

    readers, model = clients(args.llm_url, args.llm_model, args.concurrency)
    if args.command == "score":
        scored, failed = score_masked(args.masked, args.out, readers, model, limit=args.limit)
        print(f"scored {scored}, failed {failed}, model {model}, prompt {PROMPT_VERSION}")
        return 0 if failed == 0 else 1
    written = ask_leak(args.sample, args.answers, [r.writer for r in readers])
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
