"""The leak test: can the reader still tell who and when after masking?

Masking is checked before any masked score is read (the plan's arm B).
On a fixed sample of masked releases the same model is asked which
company issued the release and which fiscal quarter and year it reports.
The masking passes when it names the company on fewer than 5% and the
year on fewer than 10%; otherwise it is tightened and the check re-run.
The check is not a trial.

The sample and the scoring live here; the model call is made by the
operator's tone client on the prompts `sample_leak` writes, and the
answers come back as JSONL for `score_leak`.
"""

import json
import random
import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from backend.market import release_mask

# The ceilings the plan fixed.
LEAK_COMPANY_MAX = 0.05
LEAK_YEAR_MAX = 0.10
LEAK_N = 200
# A release reports a quarter that ended within about this many days
# before its reaction date, so the "year" a reader may name is the
# reaction year or, early in the year, the one before.
QUARTER_LAG_DAYS = 100


# The years a reader may legitimately name for a release.
def truth_years(reaction_date: date) -> list[int]:
    """Return the reaction year and, early in the year, the year before."""
    years = [reaction_date.year]
    if reaction_date.timetuple().tm_yday <= QUARTER_LAG_DAYS:
        years.append(reaction_date.year - 1)
    return years


# A deterministic sample of masked releases with the leak question attached.
def sample_leak(
    rows: Sequence[Mapping[str, Any]],
    names: Mapping[str, str],
    n: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Return `n` sampled rows with prompt and truth, in a fixed order."""
    picked = sorted(rows, key=lambda r: (r["ticker"], r["accession"]))
    random.Random(seed).shuffle(picked)
    out = []
    for row in picked[:n]:
        when = date.fromisoformat(row["reaction_date"])
        out.append(
            {
                "accession": row["accession"],
                "ticker": row["ticker"],
                "reaction_date": row["reaction_date"],
                "prompt": release_mask.leak_prompt(row["text"]),
                "truth": {
                    "company": names.get(row["ticker"], ""),
                    "tickers": [row["ticker"]],
                    "years": truth_years(when),
                },
            }
        )
    return out


# Whether an answer names the company: any distinctive token of a name
# variant, or a ticker, anywhere in the answer's company field.
def company_hit(answer: str, company: str, tickers: Sequence[str]) -> bool:
    """Return True when `answer` identifies the issuer."""
    text = answer.lower()
    tokens = {
        tok.lower()
        for variant in release_mask.name_variants(company)
        for tok in re.findall(r"[A-Za-z][\w-]+", variant)
        if len(tok) >= release_mask.MIN_VARIANT_CHARS
        and tok.lower() not in release_mask.GENERIC_WORDS
        and tok.lower() not in release_mask.SUFFIXES
    }
    tokens |= {t.lower() for t in tickers if len(t) >= 2}
    return any(re.search(rf"(?<!\w){re.escape(tok)}(?!\w)", text) for tok in tokens)


# The four-digit year an answer names, or None.
def answer_year(value: Any) -> int | None:
    """Return the year in an answer's year field, accepting FY24 forms."""
    text = str(value or "")
    four = re.search(r"(?:19|20)\d\d", text)
    if four:
        return int(four.group(0))
    two = re.search(r"(?<!\d)(\d\d)(?!\d)", text)
    return 2000 + int(two.group(1)) if two else None


# The reader's answer as a dict, whether it came as JSON text or an object.
def parse_answer(value: Any) -> dict[str, Any]:
    """Return {company, quarter, year} from a raw answer."""
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "")
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"company": text, "quarter": "", "year": ""}


# Score the answers against the sample's truth.
def score_leak(
    sample: Sequence[Mapping[str, Any]], answers: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the leak result: shares naming the company and the year, pass."""
    company = year = answered = 0
    for row in sample:
        raw = answers.get(row["accession"])
        if raw is None:
            continue
        answered += 1
        parsed = parse_answer(raw)
        truth = row["truth"]
        if company_hit(
            str(parsed.get("company", "")), truth["company"], truth["tickers"]
        ):
            company += 1
        if answer_year(parsed.get("year")) in truth["years"]:
            year += 1
    company_share = company / answered if answered else float("nan")
    year_share = year / answered if answered else float("nan")
    passed = bool(
        answered and company_share < LEAK_COMPANY_MAX and year_share < LEAK_YEAR_MAX
    )
    return {
        "sampled": len(sample),
        "answered": answered,
        "company_hits": company,
        "company_share": company_share,
        "year_hits": year,
        "year_share": year_share,
        "company_max": LEAK_COMPANY_MAX,
        "year_max": LEAK_YEAR_MAX,
        "pass": passed,
    }


# Read the answers file: one JSON object per line with `accession` and
# `answer` (an object or the model's text).
def read_answers(path: Path) -> dict[str, Any]:
    """Return {accession: answer} from a JSONL of the reader's replies."""
    out: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[str(row["accession"])] = row.get("answer", row.get("text", ""))
    return out
