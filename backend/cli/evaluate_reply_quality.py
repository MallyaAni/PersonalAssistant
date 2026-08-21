"""Compare two candidate models on the replies they actually produce.

    python -m backend.cli.evaluate_reply_quality \
        --a-base-url http://spark-b524.local:8888 --a-model deepseek-v4-flash \
        --b-base-url http://vllm-qwen:8000    --b-model qwen/qwen3.8-27b

The other evaluators score decisions with a known right answer. This scores
prose, which has none, so it is built the only way that survives contact with
a real comparison:

- **Identical context.** Both candidates answer through the production
  assembly - `_build_system_prompt` plus the turn-context message that carries
  the evidence under cache-aware ordering - with the same evidence. Any
  difference is the model, not the harness.
- **Blind and swapped.** The judge never learns which candidate is which, and
  every case is judged twice with the positions exchanged. Order bias in a
  judge is real and this cancels it.
- **Disagreement is a tie.** If a case wins in one ordering and loses in the
  other, the judge is not seeing a difference it can hold on to, and it is
  recorded as a tie rather than as half a point. That is the honest reading and
  it costs nothing to compute.
- **Reported per category.** A model can gain overall while losing every
  grounding case. `evaluate_tool_selection` learned this the hard way - two
  models tied 45/50 to 44/50 with opposite failure modes underneath - so the
  breakdown is the output and the total is a footnote.

The judge is Claude, run headless through the Claude Code binary already on
this machine. It is neutral in the way that matters: it is not either
candidate, so the self-preference effect that makes a model rate its own output
higher cannot apply to either side. Cases are batched into one judging call
because the per-call overhead is roughly 15k tokens of harness against a few
hundred of content, so batching is what makes a full run cheap.

Nothing about a case is matched as a string. `standard` describes what a good
answer does and the judge reads it; no case requires a phrase, because an
answer is not better for containing a word.
"""

import argparse
import json
import os
import re
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.config.settings import settings
from backend.core.llm import create_inference_provider
from backend.services.reply_quality_cases import REPLY_CASES, ReplyCase

_JUDGE_SYSTEM = (
    "You are a strict, impartial evaluator of assistant answers. "
    "You output only valid JSON, with no preamble and no code fence."
)

# Tools would let the judge look things up, which would score its own research
# rather than the answers in front of it.
_JUDGE_TOOLS_OFF = (
    "Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Agent,"
    "Artifact,Skill,ToolSearch,NotebookEdit,Monitor,Task"
)


@dataclass(frozen=True, slots=True)
class Verdict:
    """One judged comparison, already resolved to the real candidate names."""

    case: int
    category: str
    winner: str  # "a", "b", or "tie"
    why: str


# Build a client for one candidate without touching the configured roles, so a
# comparison never depends on editing settings and cannot leave them changed.
def _client(base_url: str, model: str, adapter: str, reasoning: str):
    return create_inference_provider(
        adapter=adapter or settings.INFERENCE_ADAPTER,
        base_url=base_url,
        model=model,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=reasoning,
    )


# Assemble the production context for one case.
def _context_of(case: ReplyCase) -> dict[str, Any]:
    return {
        "search": [dict(item) for item in case.search],
        "recalled_turns": [dict(turn) for turn in case.recalled_turns],
    }


# Answer one case with one candidate, through the real prompt assembly.
#
# Prior turns are replayed as real messages, the same way `assistant_node`
# builds them, because a follow-up that depends on what came before is most of
# real use and cannot be measured from a single message.
def _answer(client: Any, case: ReplyCase, max_tokens: int) -> str:
    context = _context_of(case)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt(context)}
    ]
    for asked, answered in case.history:
        messages.append({"role": "user", "content": asked})
        messages.append({"role": "assistant", "content": answered})
    # Under cache-aware ordering the evidence blocks live in their own message
    # after the history, not in the system prompt. Skipping this sent every
    # candidate the question with no evidence at all, so the whole comparison
    # measured recollection rather than grounding.
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": case.prompt})
    return "".join(client.stream_chat(messages, max_tokens=max_tokens)).strip()


# Render one comparison for the judge, with the candidates already anonymised.
def _render_case(index: int, case: ReplyCase, first: str, second: str) -> str:
    evidence = ""
    if case.search:
        supplied = "\n".join(
            f"  - {item['title']}: {item['content']}" for item in case.search
        )
        evidence += f"\nEvidence supplied to both:\n{supplied}\n"
    if case.recalled_turns:
        remarks = "\n".join(
            f"  - {turn['said']} (said {turn['when']})" for turn in case.recalled_turns
        )
        evidence += f"\nEarlier remarks by this user, supplied to both:\n{remarks}\n"
    if case.history:
        # Without this the judge reads a follow-up with no antecedent and
        # cannot tell a correct answer from a lucky one.
        turns = "\n".join(
            f"  user: {asked}\n  assistant: {answered}"
            for asked, answered in case.history
        )
        evidence += f"\nEarlier in this same conversation:\n{turns}\n"
    return (
        f"\n=== CASE {index} ===\n"
        f"User asked: {case.prompt}\n"
        f"{evidence}"
        f"What a good answer does: {case.standard}\n"
        f"\n--- ANSWER A ---\n{first}\n"
        f"\n--- ANSWER B ---\n{second}\n"
    )


# Ask the judge about a batch and return its verdict per case.
def _judge(block: str, count: int, judge_model: str, timeout: int) -> list[dict]:
    instruction = (
        "Judge which answer is better in each case below. Apply the stated "
        "standard for that case; it is the criterion, not a checklist of "
        "words. A shorter answer that is correct beats a longer one that is "
        "wrong or padded. An answer that declines to state something the "
        "evidence does not support is doing its job, not failing. Ignore "
        "which answer is longer, more formatted, or more confident-sounding "
        "except where the standard makes it relevant.\n\n"
        f"Return ONLY a JSON array of exactly {count} objects, in case order:\n"
        '[{"case": <int>, "winner": "A"|"B"|"tie", "why": "<one clause>"}]\n'
        f"{block}"
    )
    executable = os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"
    completed = subprocess.run(
        [
            executable,
            "-p",
            instruction,
            "--model",
            judge_model,
            "--system-prompt",
            _JUDGE_SYSTEM,
            "--disallowed-tools",
            _JUDGE_TOOLS_OFF,
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise SystemExit(f"judge failed: {completed.stderr.strip()[:400]}")
    payload = json.loads(completed.stdout)
    if payload.get("is_error"):
        raise SystemExit(f"judge errored: {str(payload.get('result'))[:400]}")
    return _parse_verdicts(str(payload.get("result", "")))


# Recover the JSON array from the judge's reply.
#
# It is instructed to emit bare JSON and does, but a fenced block costs one
# line to tolerate and turns an occasional total loss of a run into nothing.
def _parse_verdicts(text: str) -> list[dict]:
    body = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", body, re.DOTALL)
    if fenced:
        body = fenced.group(1)
    start, end = body.find("["), body.rfind("]")
    if start == -1 or end == -1:
        raise SystemExit(f"judge returned no JSON array: {text[:300]}")
    return json.loads(body[start : end + 1])


# Answer every case with one candidate and record what it said.
#
# Separate from judging because the two candidates usually cannot be resident
# at once: one 128GB box holds one large model, so comparing a challenger means
# taking the incumbent down. Collect each side whenever its turn on the
# hardware comes, judge the saved files afterwards.
def collect(
    args: argparse.Namespace,
    base_url: str,
    model: str,
    adapter: str,
    reasoning: str,
    already: dict[str, str] | None = None,
    destination: str = "",
) -> dict[str, str]:
    client = _client(base_url, model, adapter, reasoning)
    # Answers already collected are kept rather than regenerated. The set grows
    # as real turns go wrong, and a candidate costing minutes per answer should
    # not re-answer thirty cases to add six. It also means an interrupted run
    # resumes instead of restarting, which this one has needed twice.
    answers: dict[str, str] = dict(already or {})
    todo = [case for case in REPLY_CASES if case.prompt not in answers]
    if answers:
        print(f"  {len(answers)} already collected, {len(todo)} remaining")
    for index, case in enumerate(todo, start=1):
        print(f"  [{index}/{len(todo)}] {case.prompt[:56]}...", flush=True)
        answers[case.prompt] = _answer(client, case, args.max_tokens)
        if destination:
            _save(destination, model, answers, quiet=True)
    return answers


# Load answers recorded by an earlier collection run.
#
# Keyed by prompt rather than by position, so a case added to the set does not
# silently pair one model's answer with another model's different question.
def _load(path: str) -> tuple[str, dict[str, str]]:
    with open(path, encoding="utf-8") as handle:
        saved = json.load(handle)
    return str(saved.get("model", path)), dict(saved.get("answers", {}))


def _save(path: str, model: str, answers: dict[str, str], quiet: bool = False) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"model": model, "answers": answers}, handle, indent=2)
    if not quiet:
        print(f"  saved {len(answers)} answers for {model} to {path}")


# Judge two collected sets against each other in both orderings.
def _compare(
    args: argparse.Namespace,
    a_answers: dict[str, str],
    b_answers: dict[str, str],
) -> list[Verdict]:
    shared = [
        case
        for case in REPLY_CASES
        if case.prompt in a_answers and case.prompt in b_answers
    ]
    missing = len(REPLY_CASES) - len(shared)
    if missing:
        print(f"  note: {missing} case(s) absent from one side, skipped")
    if not shared:
        raise SystemExit("the two answer sets have no cases in common")
    answers = [
        (case, a_answers[case.prompt], b_answers[case.prompt]) for case in shared
    ]

    verdicts: list[Verdict] = []
    # Pass 1 shows A first, pass 2 shows B first. A judge that simply prefers
    # whichever it reads first will split, and the split is read as a tie.
    for swapped in (False, True):
        for start in range(0, len(answers), args.batch):
            chunk = answers[start : start + args.batch]
            block = "".join(
                _render_case(
                    number,
                    case,
                    b_answer if swapped else a_answer,
                    a_answer if swapped else b_answer,
                )
                for number, (case, a_answer, b_answer) in enumerate(chunk, start=1)
            )
            print(
                f"  judging cases {start + 1}-{start + len(chunk)}"
                f" ({'B first' if swapped else 'A first'})",
                flush=True,
            )
            for item in _judge(block, len(chunk), args.judge_model, args.judge_timeout):
                number = int(item.get("case", 0))
                if not 1 <= number <= len(chunk):
                    continue
                case = chunk[number - 1][0]
                shown = str(item.get("winner", "tie")).strip().upper()
                if shown == "A":
                    winner = "b" if swapped else "a"
                elif shown == "B":
                    winner = "a" if swapped else "b"
                else:
                    winner = "tie"
                verdicts.append(
                    Verdict(
                        case=start + number,
                        category=case.category,
                        winner=winner,
                        why=str(item.get("why", "")),
                    )
                )
    return verdicts


# Collapse the two orderings, treating a disagreement as the tie it is.
def _resolve(verdicts: list[Verdict]) -> dict[int, Verdict]:
    by_case: dict[int, list[Verdict]] = defaultdict(list)
    for verdict in verdicts:
        by_case[verdict.case].append(verdict)
    resolved: dict[int, Verdict] = {}
    for number, pair in by_case.items():
        winners = {item.winner for item in pair}
        # A winner needs both orderings saying the same thing. A case the
        # judge skipped or misnumbered in one pass has only one verdict, and
        # crediting it would bypass the swap that cancels order bias.
        if len(pair) == 2 and len(winners) == 1:
            agreed, why = pair[0].winner, pair[0].why
        elif len(winners) > 1:
            agreed, why = "tie", "orderings disagreed"
        else:
            agreed, why = "tie", "judged in only one ordering"
        resolved[number] = Verdict(number, pair[0].category, agreed, why)
    return resolved


# Print the per-category breakdown, which is the actual result.
def _report(resolved: dict[int, Verdict], a_name: str, b_name: str) -> None:
    tally: dict[str, dict[str, int]] = defaultdict(lambda: {"a": 0, "b": 0, "tie": 0})
    for verdict in resolved.values():
        tally[verdict.category][verdict.winner] += 1

    width = max(len(name) for name in tally) if tally else 10
    print(f"\n{'category'.ljust(width)}  {a_name[:14]:>14}  {b_name[:14]:>14}  ties")
    print("-" * (width + 40))
    for category, counts in tally.items():
        print(
            f"{category.ljust(width)}  {counts['a']:>14}  "
            f"{counts['b']:>14}  {counts['tie']:>4}"
        )
    totals = {
        key: sum(counts[key] for counts in tally.values()) for key in ("a", "b", "tie")
    }
    print("-" * (width + 40))
    print(
        f"{'TOTAL'.ljust(width)}  {totals['a']:>14}  "
        f"{totals['b']:>14}  {totals['tie']:>4}"
    )

    decided = [v for v in resolved.values() if v.winner != "tie"]
    if decided:
        print("\nWhere they differed:")
        for verdict in sorted(decided, key=lambda item: item.category):
            name = a_name if verdict.winner == "a" else b_name
            print(f"  [{verdict.category}] case {verdict.case}: {name} - {verdict.why}")

    print(
        f"\n{totals['tie']} of {len(resolved)} cases were ties. A high tie rate "
        "means the choice between these models does not rest here."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two models on reply quality, judged blind by Claude.",
    )
    # Each side is either answered live or loaded from an earlier collection,
    # so a challenger can be measured on hardware the incumbent had to vacate.
    parser.add_argument("--a-base-url", default="")
    parser.add_argument("--a-model", default="")
    parser.add_argument("--a-adapter", default="")
    parser.add_argument("--a-reasoning", default="none")
    parser.add_argument("--a-answers", default="", help="load side A from file")
    parser.add_argument("--save-a", default="", help="write side A's answers here")
    parser.add_argument("--b-base-url", default="")
    parser.add_argument("--b-model", default="")
    parser.add_argument("--b-adapter", default="")
    parser.add_argument("--b-reasoning", default="none")
    parser.add_argument("--b-answers", default="", help="load side B from file")
    parser.add_argument("--save-b", default="", help="write side B's answers here")
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="answer and save without judging, for one model at a time",
    )
    parser.add_argument("--max-tokens", type=int, default=1_200)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--judge-model", default="opus")
    parser.add_argument("--judge-timeout", type=int, default=600)
    parser.add_argument("--json", action="store_true", help="emit raw verdicts")
    return parser


# Answer one side, from a live model or from a file recorded earlier.
def _side(args: argparse.Namespace, letter: str) -> tuple[str, dict[str, str]]:
    saved = getattr(args, f"{letter}_answers")
    if saved:
        return _load(saved)
    base_url = getattr(args, f"{letter}_base_url")
    model = getattr(args, f"{letter}_model")
    if not (base_url and model):
        raise SystemExit(
            f"side {letter.upper()} needs --{letter}-base-url and --{letter}-model,"
            f" or --{letter}-answers pointing at a collected file"
        )
    destination = getattr(args, f"save_{letter}")
    # Resume from whatever that file already holds, so growing the case set
    # costs only the new cases.
    already: dict[str, str] = {}
    if destination and Path(destination).exists():
        _, already = _load(destination)
    print(f"Answering with {model}:")
    answers = collect(
        args,
        base_url,
        model,
        getattr(args, f"{letter}_adapter"),
        getattr(args, f"{letter}_reasoning"),
        already=already,
        destination=destination,
    )
    if destination:
        _save(destination, model, answers)
    return model, answers


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Collecting one side is a whole run of its own when the two models cannot
    # share the hardware. Nothing is judged and nothing is compared.
    if args.collect_only:
        for letter in ("a", "b"):
            if getattr(args, f"{letter}_model"):
                _side(args, letter)
        if not (args.save_a or args.save_b):
            print("nothing saved: pass --save-a or --save-b with --collect-only")
        return 0

    a_name, a_answers = _side(args, "a")
    b_name, b_answers = _side(args, "b")
    print(f"\nComparing {a_name} against {b_name} over {len(REPLY_CASES)} cases.")
    resolved = _resolve(_compare(args, a_answers, b_answers))
    if args.json:
        print(
            json.dumps(
                # asdict, not vars: Verdict has __slots__ and therefore no
                # __dict__, so vars() raised and the flag that persists the
                # judge's reasoning never worked. The verdicts existed only in
                # terminal output, which is the one artefact worth keeping.
                [asdict(verdict) for verdict in resolved.values()],
                indent=2,
                default=str,
            )
        )
    _report(resolved, a_name, b_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
