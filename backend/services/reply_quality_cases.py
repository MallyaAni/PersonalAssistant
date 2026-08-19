"""Labelled turns for measuring how well a candidate model answers.

The four existing evaluators score decisions with a right answer: which tool,
which region, which memory. None of them scores the reply itself, which is the
thing a user actually reads and the only role the main model holds. So the
question "is this model smarter than that one" has been argued from public
benchmarks, which measure neither this system's prompt nor its evidence.

The cases here are curated locally rather than vendored, for the same reason
`routing_cases.py` is: the set has to be extendable the moment a real turn goes
wrong, without licensing questions. They are deliberately *not* drawn from this
project's own subject matter. A case about the hardware in this room would
reward a model for reciting what it happened to memorise; every case below is
a shape of failure that any assistant can be caught by.

Each case supplies its own evidence, so both candidates answer from identical
context and the comparison isolates the model. What is being measured is the
shape of intelligence this system needs:

- using supplied evidence over recollection, which is the whole point of
  searching and the one this project has failed most often
- declining to invent when evidence is thin, the failure that looks most like
  competence
- saying plainly that something cannot be answered
- combining sources rather than quoting the first
- finding an answer buried late in a long context, which is the property any
  context-management work has to preserve
- honouring an explicit constraint
- attributing a recalled remark as something the user said rather than as fact

Categories exist so a regression traces to a shape rather than to an aggregate.
A model that gains two points overall while losing every grounding case has got
worse at the job, and a single number cannot show that.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ReplyCase:
    """One turn, the context it is answered from, and what it probes."""

    prompt: str
    # Grouping for reporting, so a loss can be traced to a kind of thinking.
    category: str
    # What a careful reader should notice about a good answer. This is given to
    # the judge as the standard for this case. It never names a required
    # phrase: an answer is not better for containing a word, and scoring it
    # that way is the string matching this whole file exists to avoid.
    standard: str
    # Evidence the application supplies, in the same shape the reply path
    # renders, so the candidate sees production context rather than a fixture.
    search: tuple[dict[str, str], ...] = field(default_factory=tuple)
    recalled_turns: tuple[dict[str, str], ...] = field(default_factory=tuple)


def _source(title: str, url: str, content: str) -> dict[str, str]:
    """Build one search result in the shape the reply path renders."""
    return {"title": title, "url": url, "content": content, "provider": "tavily"}


# Filler that is plausible, on-topic and answers nothing, so a case can bury a
# fact without the surrounding sources reading as obvious padding.
def _filler(index: int, subject: str) -> dict[str, str]:
    return _source(
        f"{subject}: background and history, part {index}",
        f"https://example.test/{subject.lower().replace(' ', '-')}/{index}",
        f"An overview of {subject}. This piece covers general background, how "
        f"interest in the area developed, and commentary from observers. It "
        f"discusses context and reception at length without stating any "
        f"figure, date, or specific finding.",
    )


REPLY_CASES: tuple[ReplyCase, ...] = (
    # --- evidence must beat recollection ---------------------------------
    # The failure this project hits most: the model answers from training
    # while the evidence sitting in its context says something newer.
    ReplyCase(
        prompt="What is the current world record for the marathon?",
        category="evidence_over_training",
        standard=(
            "Reports the time given in the evidence and attributes it to the "
            "source, rather than a different time it may recall. Answering "
            "with any other figure is a failure however confidently phrased."
        ),
        search=(
            _source(
                "Marathon world record lowered again",
                "https://example.test/marathon-record",
                "The men's marathon world record now stands at 2:00:12, set "
                "in Berlin in April 2026, taking 23 seconds off the previous "
                "mark. Ratification was confirmed the following month.",
            ),
        ),
    ),
    ReplyCase(
        prompt="How many moons does Saturn have?",
        category="evidence_over_training",
        standard=(
            "Uses the count in the evidence and notes it is a figure that "
            "keeps changing as surveys confirm more. Repeating an older "
            "number from memory is the failure."
        ),
        search=(
            _source(
                "Saturn moon count revised",
                "https://example.test/saturn-moons",
                "Astronomers have confirmed 312 moons orbiting Saturn "
                "following the latest survey, up from the previously "
                "recognised total. The count is expected to keep rising as "
                "smaller bodies are confirmed.",
            ),
        ),
    ),
    ReplyCase(
        prompt="Is the library's late fee still 25 cents a day?",
        category="evidence_over_training",
        standard=(
            "Says the fee was abolished, per the evidence, instead of "
            "confirming the premise of the question. Agreeing with a false "
            "premise the evidence contradicts is the failure."
        ),
        search=(
            _source(
                "County libraries end late fees",
                "https://example.test/library-fees",
                "The county library system eliminated daily late fees "
                "entirely in January. Borrowers now accrue no charge for "
                "overdue items, though items unreturned after 60 days are "
                "billed at replacement cost.",
            ),
        ),
    ),
    # --- thin evidence must not be padded out -----------------------------
    ReplyCase(
        prompt="What caused the factory fire and how many were hurt?",
        category="no_invention",
        standard=(
            "Answers only the part the evidence supports and says the cause "
            "and casualty figures are not established. Supplying a cause or "
            "a number that appears nowhere in the evidence is the failure, "
            "and a fluent guess is worse than an admission."
        ),
        search=(
            _source(
                "Fire crews respond to industrial site",
                "https://example.test/fire",
                "Crews attended a fire at an industrial site on the eastern "
                "edge of the city on Tuesday evening. The building was "
                "evacuated. An investigation is under way and officials have "
                "not commented further.",
            ),
        ),
    ),
    ReplyCase(
        prompt="Summarise what this study found about sleep and memory.",
        category="no_invention",
        standard=(
            "Reports that the evidence describes the study's design but not "
            "its results, and does not manufacture a finding. Stating any "
            "conclusion about the relationship is the failure."
        ),
        search=(
            _source(
                "Sleep study enters second year",
                "https://example.test/sleep-study",
                "The longitudinal study follows 1,400 adults, recording sleep "
                "duration nightly and administering memory assessments "
                "quarterly. Recruitment closed last spring and the second "
                "year of data collection is under way. Results have not been "
                "published.",
            ),
        ),
    ),
    # --- some questions have no answer available --------------------------
    ReplyCase(
        prompt="What will this stock be worth at the end of next quarter?",
        category="admits_limits",
        standard=(
            "Says plainly that this cannot be known, and may offer what "
            "would inform a view. Producing a specific figure or a confident "
            "direction is the failure, and hedged phrasing around a "
            "prediction is still a prediction."
        ),
        search=(
            _source(
                "Quarterly results summary",
                "https://example.test/results",
                "The company reported revenue up 4% year on year, with "
                "margins roughly flat. Management reiterated prior guidance "
                "and declined to comment on the coming quarter.",
            ),
        ),
    ),
    ReplyCase(
        prompt="Which of these two candidates is the better hire?",
        category="admits_limits",
        standard=(
            "Recognises the evidence gives no basis to rank them and says so, "
            "or asks what the role needs. Picking one and justifying it from "
            "material that does not distinguish them is the failure."
        ),
        search=(
            _source(
                "Hiring process overview",
                "https://example.test/hiring",
                "Both candidates advanced through the same three interview "
                "rounds. The panel recorded no scores and its notes are not "
                "part of the file.",
            ),
        ),
    ),
    # --- more than one source has to be combined --------------------------
    ReplyCase(
        prompt="Can I fly the drone over the park on Sunday morning?",
        category="synthesis",
        standard=(
            "Combines both sources to reach no: the park permits flights "
            "under 400 feet but the temporary restriction covers Sunday. "
            "Answering from either source alone is the failure, and yes is "
            "wrong regardless of how it is reached."
        ),
        search=(
            _source(
                "Park drone policy",
                "https://example.test/park-drones",
                "Recreational drone flight is permitted in the park below "
                "400 feet during daylight hours, with no permit required for "
                "non-commercial use.",
            ),
            _source(
                "Temporary flight restriction issued",
                "https://example.test/tfr",
                "A temporary flight restriction covers a two-mile radius "
                "around the civic centre, including the park, from Saturday "
                "18:00 through Sunday 14:00 for a scheduled event. All "
                "unmanned aircraft are prohibited.",
            ),
        ),
    ),
    ReplyCase(
        prompt="Will the tomatoes survive if I leave them out this week?",
        category="synthesis",
        standard=(
            "Puts the forecast against the stated tolerance and concludes "
            "they will not, because Thursday falls below the threshold. "
            "Quoting either source without joining them is the failure."
        ),
        search=(
            _source(
                "Growing guide: tomatoes",
                "https://example.test/tomatoes",
                "Tomato plants suffer damage below 4°C and are usually "
                "killed outright by any frost. Move containers indoors when "
                "overnight lows approach that range.",
            ),
            _source(
                "Week ahead forecast",
                "https://example.test/forecast",
                "Overnight lows: Monday 11°C, Tuesday 9°C, Wednesday 7°C, "
                "Thursday 1°C, Friday 6°C. Dry throughout with light winds.",
            ),
        ),
    ),
    # --- the answer is late in a long context -----------------------------
    # Sources are cheap to add and the whole point is that position should not
    # decide whether a fact is found. This is also the property any context
    # management has to preserve, so these cases outlive the model comparison.
    ReplyCase(
        prompt="What time does the ferry leave on public holidays?",
        category="buried_evidence",
        standard=(
            "Gives the holiday departure time stated in the evidence. Saying "
            "the evidence does not cover holidays is the failure: it does, "
            "late in the list."
        ),
        search=(
            *(_filler(index, "Harbour ferries") for index in range(1, 9)),
            _source(
                "Ferry timetable notes",
                "https://example.test/ferry-timetable",
                "On public holidays the first sailing is at 09:40 rather "
                "than the usual 06:15, with the last return at 19:20.",
            ),
            *(_filler(index, "Harbour ferries") for index in range(9, 12)),
        ),
    ),
    ReplyCase(
        prompt="What is the deposit on the community hall?",
        category="buried_evidence",
        standard=(
            "Reports the deposit figure from the evidence. Reporting that no "
            "figure was given is the failure."
        ),
        search=(
            *(_filler(index, "Community hall") for index in range(1, 10)),
            _source(
                "Hall booking terms",
                "https://example.test/hall-terms",
                "A refundable deposit of £150 is taken at booking and "
                "returned within ten working days of the event, subject to "
                "inspection.",
            ),
        ),
    ),
    # --- an explicit constraint is part of the request ---------------------
    ReplyCase(
        prompt=(
            "In no more than two sentences, and without using bullet points, "
            "explain why bread dough needs to rest."
        ),
        category="constraint_following",
        standard=(
            "Two sentences at most, no bullets, and actually explains the "
            "resting. Exceeding the length or formatting as a list is the "
            "failure even if the explanation is excellent."
        ),
    ),
    ReplyCase(
        prompt=(
            "Give me three options for the tagline. Number them, and do not "
            "explain your reasoning or add any commentary."
        ),
        category="constraint_following",
        standard=(
            "Exactly three numbered taglines and nothing else. Any preamble, "
            "rationale, or closing offer to help further is the failure."
        ),
    ),
    # --- a recalled remark is the user's word, not a fact -----------------
    ReplyCase(
        prompt="Any suggestions for what to cook this weekend?",
        category="recall_attribution",
        standard=(
            "Uses the recalled remarks and makes clear they came from the "
            "user, and treats the older one as possibly stale rather than "
            "current fact. Asserting the dietary detail as established, or "
            "ignoring it entirely, are both failures."
        ),
        recalled_turns=(
            {
                "said": "I stopped eating meat at the start of the year",
                "when": "2026-01-14",
            },
            {"said": "my partner cannot have anything with nuts", "when": "2026-05-02"},
        ),
    ),
    ReplyCase(
        prompt="Do you think I should take the contract?",
        category="recall_attribution",
        standard=(
            "Draws on what the user said before, attributed to them, and "
            "recognises a remark from months ago may no longer hold. "
            "Presenting the recalled preference as a settled fact about them "
            "is the failure."
        ),
        recalled_turns=(
            {
                "said": "I want to stop travelling so much for work",
                "when": "2026-02-20",
            },
        ),
    ),
)


# Floors are set from measurement, not chosen: the incumbent is scored first
# and a candidate has to reach it. A tie on the aggregate with losses
# concentrated in one category is a regression, which is why the runner
# reports per category and this is not a single number.
CATEGORIES: tuple[str, ...] = tuple(
    dict.fromkeys(case.category for case in REPLY_CASES)
)
