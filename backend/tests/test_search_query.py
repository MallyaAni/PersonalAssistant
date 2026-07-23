from backend.search.query import normalize_search_query


# Verify common explicit-search wording leaves only the factual subject.
def test_search_prefix_and_citation_suffix_are_removed():
    assert (
        normalize_search_query(
            "Search online for the latest stable Python release and cite the source."
        )
        == "the latest stable Python release"
    )


# Verify ordinary factual questions remain unchanged.
def test_ordinary_query_is_preserved():
    assert normalize_search_query("What is the latest Python release?") == (
        "What is the latest Python release?"
    )
