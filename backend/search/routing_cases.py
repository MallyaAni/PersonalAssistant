"""Labelled queries for measuring web-search routing quality.

Curated locally rather than vendored from a benchmark, so the set can be
extended without licensing questions. The taxonomy follows FreshQA's, which
labels a question by whether its answer changes: fast-changing and
slow-changing answers need live data, never-changing ones do not.

The hard cases are deliberately over-represented. Routing on temporal
vocabulary alone recalled only 45.6% of changing questions when measured
against FreshQA, because people rarely say "current" when they mean it, so
volatile questions phrased without any temporal marker carry the most signal
about whether routing actually works.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoutingCase:
    """One labelled query and whether answering it needs live web data."""

    query: str
    needs_search: bool
    # Grouping for reporting, so a regression can be traced to a shape of
    # question rather than only to an aggregate percentage.
    category: str


ROUTING_CASES: tuple[RoutingCase, ...] = (
    # --- changing answers, stated with an explicit temporal marker ----------
    # Real misses from the iMessage channel: a named event's tickets and a
    # market's hours are availability questions however casually asked.
    RoutingCase(
        "do i need tickets to see the dc grand prix?", True, "implicit_volatile"
    ),
    RoutingCase("what is the latest python version", True, "explicit_temporal"),
    RoutingCase("who won the 2026 super bowl", True, "explicit_temporal"),
    RoutingCase("current CEO of OpenAI", True, "explicit_temporal"),
    RoutingCase("what happened this week in tech", True, "explicit_temporal"),
    RoutingCase("weather in Lisbon", True, "explicit_temporal"),
    RoutingCase("search for the mars mission", True, "explicit_temporal"),
    RoutingCase("as of today how many states are there", True, "explicit_temporal"),
    RoutingCase("give me up-to-date inflation figures", True, "explicit_temporal"),
    RoutingCase("what is the newest iPhone", True, "explicit_temporal"),
    # --- changing answers with no temporal marker at all --------------------
    RoutingCase("who is the CEO of OpenAI", True, "implicit_volatile"),
    RoutingCase("is it raining in Seattle", True, "implicit_volatile"),
    RoutingCase("what happened with the Nvidia earnings", True, "implicit_volatile"),
    RoutingCase("how much does a Tesla Model 3 cost", True, "implicit_volatile"),
    RoutingCase("what is the stock price of Apple", True, "implicit_volatile"),
    RoutingCase("who is the prime minister of Canada", True, "implicit_volatile"),
    RoutingCase("how many users does Threads have", True, "implicit_volatile"),
    RoutingCase("what is the exchange rate for euros", True, "implicit_volatile"),
    RoutingCase("when is the next SpaceX launch", True, "implicit_volatile"),
    RoutingCase("when did OpenAI release GPT-5", True, "implicit_volatile"),
    RoutingCase(
        "who holds the world record in the marathon", True, "implicit_volatile"
    ),
    RoutingCase("how many countries use the euro", True, "implicit_volatile"),
    RoutingCase("is the M4 MacBook out yet", True, "implicit_volatile"),
    RoutingCase("who is the mayor of Chicago", True, "implicit_volatile"),
    RoutingCase("what is the price of gold", True, "implicit_volatile"),
    # --- answers that are settled and cannot change -------------------------
    RoutingCase("what is the capital of France", False, "stable_fact"),
    RoutingCase("who wrote Pride and Prejudice", False, "stable_fact"),
    RoutingCase("what happened in 1999", False, "stable_fact"),
    RoutingCase("when did the Berlin Wall fall", False, "stable_fact"),
    RoutingCase("how many bones are in the human body", False, "stable_fact"),
    # --- skills and reasoning the model performs itself ---------------------
    RoutingCase("explain how a b-tree works", False, "skill"),
    RoutingCase("write me a haiku about rain", False, "skill"),
    RoutingCase("convert 30 celsius to fahrenheit", False, "skill"),
    RoutingCase("what is the derivative of x squared", False, "skill"),
    RoutingCase("translate hello into Spanish", False, "skill"),
    RoutingCase("refactor this function for me", False, "skill"),
    RoutingCase("explain the difference between TCP and UDP", False, "skill"),
    RoutingCase("summarise the text I just pasted", False, "skill"),
    RoutingCase("write a regular expression for an email", False, "skill"),
    # --- questions about the user's own stored context ----------------------
    RoutingCase("what is my name", False, "private_memory"),
    RoutingCase("summarise our last conversation", False, "private_memory"),
    RoutingCase("what did I tell you about my project", False, "private_memory"),
    # --- the user narrating their own life: a time word does not make this a
    #     web query, which is the failure that sent "I graduated last month"
    #     to the internet -------------------------------------------------------
    RoutingCase("I graduated from university last month", False, "personal_statement"),
    RoutingCase("I moved to Seattle last year", False, "personal_statement"),
    RoutingCase("I visited the Grand Canyon last week", False, "personal_statement"),
    RoutingCase("I saw a great film yesterday", False, "personal_statement"),
    RoutingCase("I started a new job in 2026", False, "personal_statement"),
    RoutingCase("I recently adopted a rescue dog", False, "personal_statement"),
    # A real information signal still wins inside a first-person sentence.
    RoutingCase(
        "I moved to Lisbon, what is the weather there now", True, "personal_statement"
    ),
    # --- a volatile question whose subject the conversation never names -------
    # These used to be labelled needs_search=True (volatile, so search live).
    # The router - held to the floor the retired regex-plus-classifier cascade
    # set - now returns no tool for all of them, and it is right: with no
    # named merger, game, strike, or market in the conversation, a search
    # would guess a subject and answer confidently about the wrong one. That
    # is the failure the 2026-08-27 subject-copy rule was added to stop, so
    # the correct behaviour is to hold back and let the reply ask which.
    # Measured 2026-09-01: removing the no-tool clause from the router prompt
    # made recall WORSE (0.774, adding the euro and states cases), so these
    # are not a routing defect - the labels were, and they encode behaviour
    # the incident rule deliberately replaced. Recall is then 26/26 on this
    # set rather than a fabricated miss.
    RoutingCase("did the merger go through", False, "unnamed_subject"),
    RoutingCase("has the strike ended", False, "unnamed_subject"),
    RoutingCase("any news about the merger", False, "unnamed_subject"),
    RoutingCase("what time does the game start", False, "unnamed_subject"),
    RoutingCase(
        "is the farmers market open this sunday", False, "unnamed_subject"
    ),
)
