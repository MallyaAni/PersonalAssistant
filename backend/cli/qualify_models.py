"""Measure local models against AniOS supervisor and presentation contracts."""

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.core.llm import InferenceProvider, create_inference_provider
from backend.presentations.provider import LLMPresentationProvider


@dataclass(slots=True)
class CaseResult:
    """One reproducible model-contract result with latency and failure evidence."""

    name: str
    passed: bool
    latency_seconds: float
    observed: str


# Define bounded synthetic capabilities without granting any execution authority.
def _supervisor_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "delegate_presentation_agent",
                "description": (
                    "Queue the specialized presentation subagent when the user asks "
                    "to create an editable slide deck or presentation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "slide_count": {"type": "integer", "minimum": 1},
                    },
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "invoke_web_search",
                "description": (
                    "Search the public internet for current information after "
                    "application privacy screening."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
    ]


# Return the single selected function name, or no selection for a direct response.
def _selected_tool(message: dict[str, Any]) -> str | None:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        return None
    function = calls[0].get("function") if isinstance(calls[0], dict) else None
    name = function.get("name") if isinstance(function, dict) else None
    return str(name) if name else None


# Time one synchronous operation and retain a short printable observation.
def _measure(name: str, operation: Any, expected: str | None) -> CaseResult:
    started = time.perf_counter()
    try:
        observed = operation()
        value = observed if isinstance(observed, str) else str(observed)
        passed = value == expected if expected is not None else bool(value)
    except Exception as exc:
        value = f"{type(exc).__name__}: {exc}"
        passed = False
    return CaseResult(
        name=name,
        passed=passed,
        latency_seconds=round(time.perf_counter() - started, 3),
        observed=value[:500],
    )


# Run the supervisor's routing contract against one local model.
def _qualify_supervisor(llm: InferenceProvider) -> list[CaseResult]:
    system = (
        "You are AniOS MainAgent. Choose at most one supplied capability only "
        "when it directly completes the request. Use the presentation agent for "
        "editable slide decks and web search only for current public facts. If no "
        "capability is needed, answer directly without calling a function."
    )
    cases = [
        (
            "delegate_explicit_presentation",
            "Create an editable presentation about horses with exactly 6 slides.",
            "delegate_presentation_agent",
        ),
        (
            "delegate_natural_presentation",
            "Put together a six-slide deck explaining battery storage.",
            "delegate_presentation_agent",
        ),
        (
            "select_current_web_search",
            "What is the weather in Boston right now?",
            "invoke_web_search",
        ),
        (
            "respond_without_capability",
            "Explain why the sky looks blue in two sentences.",
            None,
        ),
        (
            "do_not_exfiltrate_memory",
            "Remember that my passport number is private.",
            None,
        ),
    ]
    results = []
    for name, prompt, expected in cases:
        results.append(
            _measure(
                name,
                lambda prompt=prompt: (
                    _selected_tool(
                        llm.chat_with_tools(
                            [
                                {"role": "system", "content": system},
                                {"role": "user", "content": prompt},
                            ],
                            _supervisor_tools(),
                            256,
                        )
                    )
                    or "NO_TOOL"
                ),
                expected or "NO_TOOL",
            )
        )
    return results


# Run the specialized editable-deck contract against one local model.
async def _qualify_presentation(llm: InferenceProvider) -> list[CaseResult]:
    provider = LLMPresentationProvider(
        llm,
        max_tokens=2_048,
        plan_max_tokens=2_048,
        revision_max_tokens=1_024,
    )
    started = time.perf_counter()
    try:
        deck = None
        async for draft in provider.create_progress(
            "Create an executive presentation about horse care with exactly 2 slides."
        ):
            deck = draft.specification
        if deck is None:
            raise ValueError("Presentation provider emitted no progressive draft")
        observed = (
            f"slides={len(deck.slides)};titles={[slide.title for slide in deck.slides]}"
        )
        passed = len(deck.slides) == 2 and all(
            slide.title and slide.elements for slide in deck.slides
        )
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        passed = False
    return [
        CaseResult(
            name="typed_editable_two_slide_deck",
            passed=passed,
            latency_seconds=round(time.perf_counter() - started, 3),
            observed=observed[:500],
        )
    ]


# Evaluate one model for both the main-agent and presentation-agent roles.
async def _qualify_model(
    base_url: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    llm = create_inference_provider(
        adapter="openai_compatible",
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        reasoning_effort="none",
    )
    supervisor = await asyncio.to_thread(_qualify_supervisor, llm)
    presentation = await _qualify_presentation(llm)
    all_results = [*supervisor, *presentation]
    return {
        "model": model,
        "supervisor": [asdict(item) for item in supervisor],
        "presentation": [asdict(item) for item in presentation],
        "summary": {
            "passed": sum(item.passed for item in all_results),
            "total": len(all_results),
            "latency_seconds": round(
                sum(item.latency_seconds for item in all_results),
                3,
            ),
        },
    }


# Parse CLI options for repeatable local qualification runs.
def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


# Run models sequentially so one-GPU results are not distorted by contention.
async def _run(args: argparse.Namespace) -> dict[str, Any]:
    results = []
    for model in args.model:
        results.append(await _qualify_model(args.base_url, model, args.timeout_seconds))
    return {"suite": "anios-model-qualification-v1", "results": results}


# Print the evidence and optionally persist the same machine-readable report.
def main() -> None:
    args = _arguments()
    report = asyncio.run(_run(args))
    encoded = json.dumps(report, indent=2)
    print(encoded)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
