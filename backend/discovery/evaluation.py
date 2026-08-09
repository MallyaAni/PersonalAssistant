"""Score the discovery pipeline against digests it actually produced.

Every ranking change made here so far was judged by reading a handful of results
and forming an impression. That is how a change that improved eight hand-picked
candidates was reported as improving attribution, and then made the same mistake
on the first real digest anyone looked at — more confidently than before.

So this exists to answer one question repeatably: **of the finds that reached a
real digest, how many should have been there, and was the reason given for them
right?** The cases are the real items, labelled once. A change that helps moves
the numbers; a change that only feels better does not.

Two things are measured apart, because they fail for different reasons and are
fixed in different places:

- **filtering** — a page of happenings is not a happening. Deterministic, needs
  no model, so it runs anywhere and belongs in the test suite;
- **attribution** — the interest a digest names as the reason. Needs the local
  model and the cross-encoder, so it is opt-in.

The labels are judgements, not ground truth handed down from anywhere. They live
beside this module in JSON precisely so they can be argued with: correct one and
the score follows.
"""

import json
from dataclasses import dataclass
from pathlib import Path

_CASES_PATH = Path(__file__).with_name("evaluation_cases.json")


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One find that reached a real digest, with what it should have been."""

    title: str
    url: str
    summary: str
    locality: str
    interests: tuple[str, ...]
    # "happening" or "listing".
    kind: str
    # The interest a digest should name, or None when none should be.
    interest: str | None
    place_matches: bool
    note: str | None = None

    @property
    def is_listing(self) -> bool:
        return self.kind == "listing"


@dataclass(frozen=True, slots=True)
class FilterScore:
    """How well the deterministic filters separate happenings from listings."""

    listings: int
    listings_rejected: int
    happenings: int
    happenings_kept: int
    # Every happening wrongly rejected, by title, because one of these is worse
    # than several listings admitted: a digest that drops real finds is quietly
    # broken in a way nobody can see.
    wrongly_rejected: tuple[str, ...] = ()
    still_admitted: tuple[str, ...] = ()

    @property
    def listing_recall(self) -> float:
        return self.listings_rejected / self.listings if self.listings else 1.0

    @property
    def happening_retention(self) -> float:
        return self.happenings_kept / self.happenings if self.happenings else 1.0

    def as_dict(self) -> dict[str, object]:
        return {
            "listing_recall": round(self.listing_recall, 4),
            "happening_retention": round(self.happening_retention, 4),
            "listings": self.listings,
            "listings_rejected": self.listings_rejected,
            "happenings": self.happenings,
            "happenings_kept": self.happenings_kept,
            "wrongly_rejected": list(self.wrongly_rejected),
            "still_admitted": list(self.still_admitted),
        }


@dataclass(frozen=True, slots=True)
class AttributionScore:
    """How often the interest named as the reason is the right one."""

    judged: int
    correct: int
    wrong: tuple[str, ...] = ()
    missed: tuple[str, ...] = ()

    @property
    def accuracy(self) -> float:
        return self.correct / self.judged if self.judged else 1.0

    def as_dict(self) -> dict[str, object]:
        return {
            "accuracy": round(self.accuracy, 4),
            "judged": self.judged,
            "correct": self.correct,
            # Naming the wrong interest is worse than naming none: it is a
            # stated reason that happens to be false.
            "wrong": list(self.wrong),
            "missed": list(self.missed),
        }


# Read the labelled cases. A missing or unreadable file is fatal on purpose:
# scoring against nothing would report a perfect run.
def load_cases(path: Path | None = None) -> tuple[EvaluationCase, ...]:
    payload = json.loads((path or _CASES_PATH).read_text(encoding="utf-8"))
    return tuple(
        EvaluationCase(
            title=case["title"],
            url=case["url"],
            summary=case.get("summary", ""),
            locality=case.get("locality", ""),
            interests=tuple(case.get("interests", ())),
            kind=case["kind"],
            interest=case.get("interest"),
            place_matches=bool(case.get("place_matches", True)),
            note=case.get("note"),
        )
        for case in payload["cases"]
    )


# Score the deterministic filter: does it reject pages of things while keeping
# things? `reject` is passed in rather than imported so a candidate change can
# be scored against the same cases before it is adopted.
def score_filtering(
    cases: tuple[EvaluationCase, ...],
    reject: "object",
) -> FilterScore:
    listings = rejected = happenings = kept = 0
    wrongly_rejected: list[str] = []
    still_admitted: list[str] = []
    for case in cases:
        is_rejected = bool(reject(case.title, case.url))  # type: ignore[operator]
        if case.is_listing:
            listings += 1
            if is_rejected:
                rejected += 1
            else:
                still_admitted.append(case.title)
        else:
            happenings += 1
            if is_rejected:
                wrongly_rejected.append(case.title)
            else:
                kept += 1
    return FilterScore(
        listings=listings,
        listings_rejected=rejected,
        happenings=happenings,
        happenings_kept=kept,
        wrongly_rejected=tuple(wrongly_rejected),
        still_admitted=tuple(still_admitted),
    )


# Score attribution from an already-computed decision per case, so this module
# needs no model and the caller decides how the interest was chosen.
def score_attribution(
    cases: tuple[EvaluationCase, ...],
    named: dict[str, str | None],
) -> AttributionScore:
    judged = correct = 0
    wrong: list[str] = []
    missed: list[str] = []
    for case in cases:
        if case.is_listing:
            # A listing should never have reached a digest at all; judging the
            # reason given for one would score the wrong question.
            continue
        judged += 1
        chosen = named.get(case.title)
        if chosen == case.interest:
            correct += 1
        elif chosen is None:
            missed.append(f"{case.title} (wanted {case.interest})")
        else:
            wrong.append(f"{case.title} -> {chosen} (wanted {case.interest})")
    return AttributionScore(
        judged=judged, correct=correct, wrong=tuple(wrong), missed=tuple(missed)
    )
