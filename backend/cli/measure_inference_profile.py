"""Measure one serving configuration, so configurations can be compared.

    python -m backend.cli.measure_inference_profile \
        --base-url http://animallya-spark1.local:8899 --model qwen3.8-27b \
        --label "bf16 mtp3" --append docs/MODEL_EVALUATION.md

Throughput here is not one number. It is decode rate multiplied by how many
tokens the model chooses to spend, and the second factor moved seven times
further than the first when thinking was switched on. A table of one metric
would have hidden that, so every run records the whole set and says which
serving flags produced it.

Requests are issued strictly one at a time and never concurrently. Two parallel
requests with MTP speculative decoding produced `cudaErrorIllegalAddress` and
killed the engine on this GB10 build, losing a collection run that was midway
through. A benchmark that crashes what it measures is worse than no benchmark.

What each row means:

- **ttft** - how long before anything appears. With thinking on this is not
  what the user waits, because thinking is streamed as `reasoning` and the
  reply path only renders `content`.
- **decode** - tokens per second once generating, measured over a long
  completion. A short one is dominated by ttft and reads far too low: the same
  model measured 8.25 over 64 tokens and 22.1 over 800.
- **answer tokens** - what the model actually spends on a fixed question. The
  lever with the widest range, and entirely a configuration choice.
- **wall clock** - answer tokens over decode rate. What a person experiences.
- **prefill** - tokens per second ingesting context, measured at two sizes
  because it falls as context grows. This is what decides how much evidence a
  turn can afford, which is otherwise guesswork.
"""

import argparse
import json
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

# A question with a definite answer that invites a few hundred words, so the
# spend is the model's choice rather than an artefact of asking for length.
_QUESTION = "Why do bridges use arches? Explain the structural reason."
# Long enough to generate past the point where ttft dominates the rate.
_LONG = "Explain how a suspension bridge carries load, in detail."


def _chat(
    base_url: str, model: str, body: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = httpx.post(
        f"{base_url}/v1/chat/completions",
        json={"model": model, **body},
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), elapsed


# Time to the first character the user would actually see.
def _time_to_first_content(
    base_url: str, model: str, body: dict[str, Any], timeout: float
) -> tuple[float | None, float | None]:
    started = time.perf_counter()
    first_any: float | None = None
    first_content: float | None = None
    with httpx.stream(
        "POST",
        f"{base_url}/v1/chat/completions",
        json={"model": model, "stream": True, **body},
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data: ") or line.endswith("[DONE]"):
                continue
            try:
                delta = json.loads(line[6:])["choices"][0].get("delta", {})
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if first_any is None and (delta.get("reasoning") or delta.get("content")):
                first_any = time.perf_counter() - started
            if first_content is None and delta.get("content"):
                first_content = time.perf_counter() - started
                break
    return first_any, first_content


def _thinking(enabled: bool) -> dict[str, Any]:
    # Thinking is on by default; turning it off is a template argument rather
    # than a sampling parameter, so it cannot be expressed as reasoning_effort.
    return {} if enabled else {"chat_template_kwargs": {"enable_thinking": False}}


def _answer_profile(
    base_url: str, model: str, thinking: bool, max_tokens: int, timeout: float
) -> dict[str, Any]:
    body = {
        "messages": [{"role": "user", "content": _QUESTION}],
        "max_tokens": max_tokens,
        **_thinking(thinking),
    }
    payload, seconds = _chat(base_url, model, body, timeout)
    choice = payload["choices"][0]
    usage = payload.get("usage") or {}
    content = choice["message"].get("content") or ""
    spent = usage.get("completion_tokens") or 0
    return {
        "thinking": thinking,
        "answer_tokens": spent,
        "answer_characters": len(content),
        "wall_clock_seconds": round(seconds, 1),
        "finish_reason": choice.get("finish_reason"),
        # An empty reply that finished on length is the failure mode that makes
        # a small cap catastrophic rather than merely limiting on this model.
        "empty_reply": not content.strip(),
    }


def _decode_rate(
    base_url: str, model: str, max_tokens: int, timeout: float
) -> dict[str, Any]:
    body = {
        "messages": [{"role": "user", "content": _LONG}],
        "max_tokens": max_tokens,
        **_thinking(False),
    }
    payload, seconds = _chat(base_url, model, body, timeout)
    spent = (payload.get("usage") or {}).get("completion_tokens") or 0
    return {
        "decode_tokens_per_second": round(spent / seconds, 2) if seconds else 0.0,
        "measured_over_tokens": spent,
    }


def _prefill_rate(
    base_url: str, model: str, approx_tokens: int, timeout: float
) -> dict[str, Any]:
    # Roughly four characters a token; the reported prompt_tokens is what the
    # rate is computed from, so the estimate only needs to land in the region.
    filler = (
        "An overview covering background, development and commentary from "
        "observers, stating no figure, date or specific finding. "
    ) * max(1, approx_tokens // 22)
    body = {
        "messages": [
            {"role": "user", "content": filler + "\n\nIn one sentence: what is this?"}
        ],
        "max_tokens": 40,
        **_thinking(False),
    }
    payload, seconds = _chat(base_url, model, body, timeout)
    usage = payload.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens") or 0
    return {
        "prompt_tokens": prompt_tokens,
        "prefill_tokens_per_second": round(prompt_tokens / seconds, 1)
        if seconds
        else 0.0,
    }


# Speculative-decoding acceptance, read from the server rather than inferred.
#
# Throughput alone cannot separate a drafter that is working from one that is
# being ignored, which is why this is read instead of guessed at.
def _acceptance(base_url: str) -> float | None:
    try:
        response = httpx.get(f"{base_url}/metrics", timeout=20)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    accepted = drafted = None
    for line in response.text.splitlines():
        if line.startswith("#"):
            continue
        if "spec_decode_num_accepted_tokens" in line:
            accepted = float(line.rsplit(" ", 1)[-1])
        elif "spec_decode_num_draft_tokens" in line:
            drafted = float(line.rsplit(" ", 1)[-1])
    if not accepted or not drafted:
        return None
    return round(1 + accepted / drafted, 2)


def profile(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {
        "label": args.label,
        "model": args.model,
        "measured_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
    }
    print(f"[{args.label}] decode rate...", flush=True)
    result.update(
        _decode_rate(args.base_url, args.model, args.decode_tokens, args.timeout)
    )

    print(f"[{args.label}] time to first token...", flush=True)
    first_any, first_content = _time_to_first_content(
        args.base_url,
        args.model,
        {
            "messages": [{"role": "user", "content": _QUESTION}],
            "max_tokens": args.max_tokens,
        },
        args.timeout,
    )
    result["ttft_any_seconds"] = round(first_any, 2) if first_any else None
    # The number that matters on a thinking model: the wait before the user
    # sees a word of the answer, not before the engine emits its first token.
    result["ttft_content_seconds"] = round(first_content, 2) if first_content else None

    for thinking in (True, False):
        print(f"[{args.label}] answer, thinking={thinking}...", flush=True)
        key = "thinking_on" if thinking else "thinking_off"
        result[key] = _answer_profile(
            args.base_url, args.model, thinking, args.max_tokens, args.timeout
        )

    for size in args.prefill_sizes:
        print(f"[{args.label}] prefill at ~{size}...", flush=True)
        result[f"prefill_{size}"] = _prefill_rate(
            args.base_url, args.model, size, args.timeout
        )

    result["mtp_acceptance_length"] = _acceptance(args.base_url)
    return result


# One row per configuration, so configurations sit side by side in the doc.
def _as_row(result: dict[str, Any]) -> str:
    on, off = result["thinking_on"], result["thinking_off"]
    prefills = [v for k, v in result.items() if k.startswith("prefill_")]
    rates = " / ".join(str(p["prefill_tokens_per_second"]) for p in prefills)
    return (
        f"| {result['label']} "
        f"| {result['decode_tokens_per_second']} "
        f"| {result.get('mtp_acceptance_length') or '-'} "
        f"| {result.get('ttft_content_seconds') or '-'} "
        f"| {on['answer_tokens']} / {off['answer_tokens']} "
        f"| {on['wall_clock_seconds']} / {off['wall_clock_seconds']} "
        f"| {rates} "
        f"| {'EMPTY' if on['empty_reply'] else 'ok'} |"
    )


_HEADER = (
    "| config | decode tok/s | MTP accept | ttft to content | "
    "answer tokens on/off | wall clock on/off | prefill tok/s | thinking reply |\n"
    "|---|---|---|---|---|---|---|---|"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--label", required=True, help="the serving flags in short")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--decode-tokens", type=int, default=600)
    parser.add_argument("--prefill-sizes", type=int, nargs="+", default=[4000, 40000])
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--out", default="", help="write the raw JSON here")
    parser.add_argument("--append", default="", help="append a table row to this file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = profile(args)
    print(json.dumps(result, indent=2))
    print("\n" + _HEADER)
    print(_as_row(result))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
    if args.append:
        with open(args.append, "a", encoding="utf-8") as handle:
            handle.write("\n" + _as_row(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
