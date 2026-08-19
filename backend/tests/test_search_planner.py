"""Who writes the search query, and what happens when it finds nothing useful.

Asked for the best models to host on one DGX Spark for chat, vision and three
kinds of image work, the 4B router compressed four requirements into one
generic query. Five DGX Spark tutorials came back, none naming a model, and the
reply model filled the gap from training - so the answer named models that are
no longer current. One search per turn was the ceiling: results that are about
the subject but never state the answer look exactly like results that do.
"""

from typing import Any

from backend.services.search_planner import SearchPlanner


class StubLLM:
    """Answer from a fixed script and record what was asked."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.asked: list[str] = []
        self.system_prompts: list[str] = []

    def chat(self, messages: list[dict[str, Any]], *args: Any, **kwargs: Any):
        self.system_prompts.append(messages[0]["content"])
        self.asked.append(messages[-1]["content"])
        return {"content": self.replies.pop(0) if self.replies else ""}


class BrokenLLM:
    def chat(self, *args: Any, **kwargs: Any):
        raise RuntimeError("model unreachable")


def test_the_composed_query_is_returned_without_its_quotes():
    planner = SearchPlanner(StubLLM('"FLUX.2 dev VRAM requirements 2026"'))

    assert planner.compose("what runs on a spark", []) == (
        "FLUX.2 dev VRAM requirements 2026"
    )


def test_the_conversation_is_given_to_the_writer():
    llm = StubLLM("nemotron 3.5 lightning benchmarks")
    planner = SearchPlanner(llm)

    planner.compose(
        "is it better?",
        [{"role": "user", "content": "we run deepseek v4 flash"}],
    )

    # Without the preceding turn "is it better?" cannot be searched for at all.
    assert "deepseek v4 flash" in llm.asked[0]


def test_results_that_answer_the_question_end_the_search():
    planner = SearchPlanner(StubLLM("ENOUGH"))

    assert planner.refine("q", [{"title": "t", "content": "c"}], ["q"]) == ""


def test_results_that_miss_produce_a_better_query():
    planner = SearchPlanner(StubLLM("FLUX.2 dev fp8 VRAM 32GB benchmark"))

    better = planner.refine("q", [{"title": "tutorial", "content": "..."}], ["q"])

    assert better == "FLUX.2 dev fp8 VRAM 32GB benchmark"


# A model that ignores the instruction and returns the query it was already
# given would search the same thing until the round limit.
def test_a_repeated_query_is_refused():
    planner = SearchPlanner(StubLLM("dgx spark models"))

    assert planner.refine("q", [{"title": "t"}], ["DGX Spark models"]) == ""


def test_nothing_found_is_not_something_the_writer_can_diagnose():
    llm = StubLLM("another query")
    planner = SearchPlanner(llm)

    assert planner.refine("q", [], ["q"]) == ""
    assert llm.asked == []


# The improvement is optional; the turn is not. A model that cannot be reached
# has to leave the caller with what it already had.
def test_a_failed_call_costs_the_improvement_and_nothing_else():
    planner = SearchPlanner(BrokenLLM())

    assert planner.compose("q", []) == ""
    assert planner.refine("q", [{"title": "t"}], ["q"]) == ""


# The failure this whole file exists for, one layer up: asked to search for
# something that changes over time, the model reached for a year from its own
# training and wrote "2025" while it was August 2026. A query pinned to the
# wrong year returns what is already out of date, however good the model is.
def test_the_query_is_written_for_today_not_for_training():
    from datetime import UTC, datetime

    llm = StubLLM("some query")
    planner = SearchPlanner(llm, now=datetime(2026, 8, 18, tzinfo=UTC))

    planner.compose("best models to host", [])

    system = llm.system_prompts[0]
    assert "2026-08-18" in system


# Your own cutoff is the more useful of the two dates: today says when now is,
# the cutoff says which of your beliefs are already stale. The gap between them
# is exactly what a search is for. A release on 2026-08-11 was four months past
# the reply model's training and could not have been known at all.
def test_the_query_is_written_knowing_where_its_knowledge_stops():
    from datetime import UTC, datetime

    llm = StubLLM("some query")
    planner = SearchPlanner(
        llm, now=datetime(2026, 8, 18, tzinfo=UTC), cutoff="2026-04"
    )

    planner.compose("which model should I host", [])

    system = llm.system_prompts[0]
    assert "2026-04" in system
    assert "2026-08-18" in system


# With no cutoff configured the prompt must still read as a sentence rather
# than leaving a placeholder or crashing on the missing value.
def test_an_unconfigured_cutoff_still_produces_a_usable_prompt():
    llm = StubLLM("some query")

    SearchPlanner(llm).compose("q", [])

    system = llm.system_prompts[0]
    assert "{cutoff}" not in system
    assert "unstated date" in system


# The model reasoned for a paragraph and then wrote "Search: ..." despite being
# told to answer with the query alone. Its reasoning was right - it had spotted
# that the options were named but the deciding figure was not - and sending the
# paragraph to a search engine would have thrown that away.
def test_a_labelled_query_is_recovered_from_a_chatty_reply():
    reply = (
        "The results name V4 Pro and V4 Flash but never give the figure that "
        "decides between them for this hardware. The missing half is memory.\n"
        "Search: DeepSeek V4 Flash parameter count memory requirement"
    )
    planner = SearchPlanner(StubLLM(reply))

    assert planner.refine("q", [{"title": "t"}], ["prev"]) == (
        "DeepSeek V4 Flash parameter count memory requirement"
    )


def test_an_unlabelled_query_is_taken_from_the_last_line():
    planner = SearchPlanner(StubLLM("Some reasoning first.\nFLUX.2 dev VRAM fp8"))

    assert planner.refine("q", [{"title": "t"}], ["prev"]) == "FLUX.2 dev VRAM fp8"


# A verdict wrapped in commentary is still a verdict, not a query to run.
def test_enough_is_recognised_even_with_commentary_around_it():
    planner = SearchPlanner(
        StubLLM("ENOUGH - the results give both the options and the figures.")
    )

    assert planner.refine("q", [{"title": "t"}], ["prev"]) == ""


def test_list_markers_and_quotes_are_stripped():
    planner = SearchPlanner(StubLLM('- "DGX Spark 128GB unified memory"'))

    assert planner.compose("q", []) == "DGX Spark 128GB unified memory"


# Both of these were produced by the real model and both would have been sent
# to a search engine verbatim.
def test_a_not_enough_verdict_is_not_searched_for():
    planner = SearchPlanner(StubLLM("NOT ENOUGH"))

    assert planner.refine("q", [{"title": "t"}], ["prev"]) == ""


def test_a_label_the_model_invented_is_still_recognised():
    planner = SearchPlanner(
        StubLLM("Better search query: DeepSeek V4 Pro Flash memory requirement GB")
    )

    assert planner.refine("q", [{"title": "t"}], ["prev"]) == (
        "DeepSeek V4 Pro Flash memory requirement GB"
    )


# A whole sentence before a colon is prose, not a label, and taking only what
# follows it would throw away the part that says what to search for.
def test_a_sentence_before_a_colon_is_not_treated_as_a_label():
    planner = SearchPlanner(
        StubLLM(
            "The figure that decides this is the memory each one needs: "
            "DeepSeek V4 Pro VRAM GB"
        )
    )

    kept = planner.compose("q", [])

    assert "figure that decides" in kept


# The unconditional round. `refine` puts a yes/no in front of the model and it
# takes the answer that ends the work; this asks for a query instead, which has
# no cheap answer.
def test_another_angle_asks_for_a_query_rather_than_permission():
    llm = StubLLM("DeepSeek V4 Pro Flash parameter count memory GB")
    planner = SearchPlanner(llm)

    proposed = planner.another_angle(
        "which fits one spark", [{"title": "V4 family overview"}], ["deepseek v4"]
    )

    assert proposed == "DeepSeek V4 Pro Flash parameter count memory GB"
    # What has already been tried is stated, or it proposes the same thing.
    assert "deepseek v4" in llm.asked[0]


def test_another_angle_refuses_to_repeat_a_tried_query():
    planner = SearchPlanner(StubLLM("DeepSeek V4"))

    assert planner.another_angle("q", [{"title": "t"}], ["deepseek v4"]) == ""


# It is asked for a query, but a model may still answer the question it was
# not asked; a verdict is not something to search for.
def test_another_angle_treats_a_verdict_as_no_proposal():
    planner = SearchPlanner(StubLLM("ENOUGH"))

    assert planner.another_angle("q", [{"title": "t"}], ["prev"]) == ""


# Told to reply with a query, the model restated the instruction instead, and
# the sentence went to the search engine verbatim and returned nothing. Length
# separates a query from prose; an over-long reply is no proposal at all.
def test_a_restated_instruction_is_not_treated_as_a_query():
    prose = (
        "Given the search results so far mention the DGX Spark hardware "
        "constraints but don't name specific current model options that fit "
        "within those constraints, search for what exists now by category."
    )
    planner = SearchPlanner(StubLLM(prose))

    assert planner.compose("q", []) == ""
    assert planner.another_angle("q", [{"title": "t"}], ["prev"]) == ""


def test_a_real_query_of_ordinary_length_survives():
    planner = SearchPlanner(StubLLM("best open source vision language models 2026"))

    assert planner.compose("q", []) == "best open source vision language models 2026"
