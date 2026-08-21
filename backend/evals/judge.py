"""One judge for every evaluation: headless Claude, batched, JSON verdicts.

The reply-quality harness proved the pattern - Claude run headless through the
Claude Code binary already on this machine, neutral because it is never the
model under test, billed to the operator's own subscription. This module is
that machinery extracted so the next evaluation does not rebuild it: the
pairwise reply harness, the Scout content judge, and whatever agent comes
after all call the same function.

What the caller owns is the instruction and the meaning of a verdict. What
this owns is everything that went wrong the first time around: the binary is
found via CLAUDE_CODE_EXECPATH, tools are disabled so the judge scores what
is in front of it rather than its own research, output is demanded as bare
JSON but a fenced or chatty reply is still recovered rather than costing the
run, and per-call overhead (~15k tokens of harness) means batching is the
difference between one cheap call and thirty expensive ones - so callers
send arrays of cases, not single ones.

Two disciplines transfer from the reply harness to every future user:
calibrate before trusting (feed the judge known-true and known-false cases
first; 6/6 there is what earned the pattern its keep), and persist verdicts
to disk - the first run's reasoning survived only in a terminal, and the
flag that should have saved it was broken in a way nothing had ever
exercised.
"""

import json
import os
import re
import subprocess

_JUDGE_SYSTEM = (
    "You are a strict, impartial evaluator. You output only valid JSON, "
    "with no preamble and no code fence."
)

# Tools would let the judge look things up, which would score its own
# research rather than the material in front of it.
_TOOLS_OFF = (
    "Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Agent,"
    "Artifact,Skill,ToolSearch,NotebookEdit,Monitor,Task"
)


class JudgeError(RuntimeError):
    """The judge could not produce verdicts; the run should stop loudly."""


# Recover the JSON array from a judge reply. Bare JSON is demanded and usually
# delivered, but tolerating a fence or a sentence of preamble costs three
# lines and turns an occasional total loss of a run into nothing.
def parse_verdicts(text: str) -> list[dict]:
    body = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", body, re.DOTALL)
    if fenced:
        body = fenced.group(1)
    start, end = body.find("["), body.rfind("]")
    if start == -1 or end == -1:
        raise JudgeError(f"judge returned no JSON array: {text[:300]}")
    return json.loads(body[start : end + 1])


def run_judge(
    instruction: str,
    model: str = "fable",
    timeout: int = 600,
    system: str = _JUDGE_SYSTEM,
) -> list[dict]:
    """One batched judging call; returns the parsed verdict array.

    `model` defaults to the operator's Fable subscription. The instruction
    must tell the judge the exact array shape to return - this function
    parses, it does not interpret.
    """
    executable = os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"
    completed = subprocess.run(
        [
            executable,
            "-p",
            instruction,
            "--model",
            model,
            "--system-prompt",
            system,
            "--disallowed-tools",
            _TOOLS_OFF,
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise JudgeError(f"judge failed: {completed.stderr.strip()[:400]}")
    payload = json.loads(completed.stdout)
    if payload.get("is_error"):
        raise JudgeError(f"judge errored: {str(payload.get('result'))[:400]}")
    return parse_verdicts(str(payload.get("result", "")))
