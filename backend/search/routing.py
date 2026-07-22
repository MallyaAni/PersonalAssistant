import re
from dataclasses import dataclass

# Deterministic signals that a request depends on information a local model
# cannot hold. The application owns this decision: a model cannot detect its own
# staleness, because a fact learned in training is indistinguishable from a
# currently true one. Over-triggering costs one search; under-triggering returns
# a confident stale answer, so these patterns deliberately err toward searching.
_SIGNALS: tuple[tuple[str, str], ...] = (
    # An explicit user instruction to consult the web always wins.
    (r"\b(search|google|look\s+up|browse|online)\b", "explicit_request"),
    # Specific signals precede generic ones so the logged reason stays useful:
    # first match wins, and "current prime minister" is more informative than
    # the bare recency term it also contains.
    (r"\bwho\s+is\s+the\s+(current|present)\b", "current_holder"),
    (r"\b(latest|newest|current|currently|recent|recently)\b", "recency_term"),
    (r"\b(today|tonight|yesterday|now|right\s+now|at\s+the\s+moment)\b", "time_term"),
    (r"\b(this|last|next)\s+(week|month|year|quarter)\b", "relative_period"),
    (r"\bas\s+of\b", "as_of"),
    (r"\bup[-\s]?to[-\s]?date\b", "up_to_date"),
    (r"\b(news|headline|headlines)\b", "news"),
    # Whoever holds a role changes over time, so the question is volatile even
    # with no temporal word. Restricted to roles that actually turn over: a
    # question like "who is the author of" is stable and must not match.
    (
        r"\bwho\s+(is|are)\s+the\s+(current\s+|present\s+)?"
        r"(ceo|cto|cfo|president|prime\s+minister|chancellor|governor|mayor|"
        r"chair|chairman|chairwoman|head\s+coach|manager|owner|leader)\b",
        "role_holder",
    ),
    (
        r"\b(price|stock|shares?|share\s+price|exchange\s+rate|earnings|revenue|"
        r"market\s+cap|valuation|ipo)\b",
        "market_data",
    ),
    # "how much does X cost" carries no temporal marker but prices move.
    (
        r"\bhow\s+much\s+(does|do|is|are|was|were)\b.*\b(cost|worth|charge|pay)\b"
        r"|\b(cost|price)\s+of\b",
        "cost_query",
    ),
    (r"\b(weather|forecast)\b", "weather"),
    # Conditions phrased without the word "weather".
    (
        r"\bis\s+it\s+(raining|snowing|sunny|cloudy|windy|hot|cold|warm|freezing)\b",
        "weather",
    ),
    # Schedules and upcoming events are only knowable from live data.
    (
        r"\bwhat\s+time\s+(does|do|is|are)\b|\bwhen\s+(is|does|are)\s+the\s+next\b",
        "schedule",
    ),
    # Counts of a live population move constantly; bounded to volatile nouns so
    # a stable question such as "how many bones are in the body" is unaffected.
    (
        r"\bhow\s+many\s+(users|subscribers|customers|employees|downloads|"
        r"followers|installs|members)\b",
        "live_metric",
    ),
    (r"\b(release[ds]?\s+date|released|launch(?:ed|es)?)\b", "release_timing"),
    (r"\b(score|standings|fixtures?|results?)\s+(for|of|in)\b", "live_results"),
    (r"\b(version|latest\s+version)\s+of\b", "version_query"),
)

_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in _SIGNALS
)

# A four-digit year at or after this is treated as beyond any local model's data.
_YEAR_PATTERN = re.compile(r"\b(20[2-9][0-9])\b")


@dataclass(frozen=True, slots=True)
class SearchDecision:
    """Application decision about whether one request requires live web data."""

    should_search: bool
    reason: str


class SearchRoutingPolicy:
    """Deterministic policy deciding when a request needs live web results.

    The model never selects this path. Routing stays in the application so a
    stale-but-fluent answer cannot be produced simply because the model failed
    to notice its own knowledge cutoff.
    """

    # Bound the year check to the running year so the rule ages with the system.
    def __init__(self, current_year: int, enabled: bool = True) -> None:
        self.current_year = current_year
        self.enabled = enabled

    # Classify one query using ordered deterministic signals.
    def decide(self, query: str) -> SearchDecision:
        if not self.enabled:
            return SearchDecision(should_search=False, reason="disabled")
        if not query or not query.strip():
            return SearchDecision(should_search=False, reason="empty_query")

        for pattern, reason in _COMPILED:
            if pattern.search(query):
                return SearchDecision(should_search=True, reason=reason)

        for match in _YEAR_PATTERN.finditer(query):
            if int(match.group(1)) >= self.current_year:
                return SearchDecision(
                    should_search=True,
                    reason="current_or_future_year",
                )

        return SearchDecision(should_search=False, reason="no_signal")
