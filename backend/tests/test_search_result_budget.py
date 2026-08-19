"""How much of a search actually reaches the model.

Three fixed numbers in the internet MCP server decided this and silently
outranked the settings that appeared to: each result was clipped to 500
characters, the payload to 3,500, and the tool's own `max_results` argument
defaulted to 5 and was passed straight through, so `SEARCH_MAX_RESULTS` and
`SEARCH_MAX_CONTENT_CHARS` were applied by the provider and then discarded here.

500 characters is about eighty words. A benchmark table, a specification or a
model comparison never reached the prompt, so answers were assembled from
titles - which is why a question about which models to host kept being answered
from training rather than from the results.
"""

import importlib
import json
import os
from types import SimpleNamespace

import pytest


def _server(monkeypatch: pytest.MonkeyPatch, **env: str):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    import backend.mcp.servers.internet as internet

    return importlib.reload(internet)


def _results(count: int, content: str):
    return SimpleNamespace(
        provider="tavily",
        results=[
            SimpleNamespace(
                title=f"result {index}",
                url=f"https://example.test/{index}",
                content=content,
                score=0.9,
                provider="tavily",
            )
            for index in range(count)
        ],
    )


def test_a_result_keeps_the_configured_number_of_characters(monkeypatch):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="40000"
    )

    encoded = internet._encode_results(_results(1, "x" * 5_000))

    kept = json.loads(encoded)["results"][0]["content"]
    assert len(kept) == 1_500


# The payload bound exists so the generic MCP truncation never lands mid-JSON,
# which would corrupt the result rather than shorten it.
def test_the_payload_stays_within_its_budget_and_stays_valid_json(monkeypatch):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="4000"
    )

    encoded = internet._encode_results(_results(20, "x" * 1_500))

    assert len(encoded) <= 4_000
    parsed = json.loads(encoded)
    assert parsed["results"]
    assert all(item["url"] for item in parsed["results"])


# Raising the budget has to actually raise it, which is the failure this
# replaces: the setting moved and the payload did not.
def test_a_larger_budget_carries_more_evidence(monkeypatch):
    small = _server(monkeypatch, SEARCH_RESULT_CHARS="500", SEARCH_PAYLOAD_CHARS="3500")
    tight = json.loads(small._encode_results(_results(8, "x" * 2_000)))["results"]

    large = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="20000"
    )
    wide = json.loads(large._encode_results(_results(8, "x" * 2_000)))["results"]

    assert sum(len(item["content"]) for item in wide) > sum(
        len(item["content"]) for item in tight
    )


# The scalable property. More sources used to mean the later ones vanished -
# twelve became six with no trace, and the ones lost were simply the last, not
# the weakest. The budget is divided now, so a bigger result set means a shorter
# excerpt from each rather than sources disappearing.
@pytest.mark.parametrize("count", [4, 8, 12, 30])
def test_every_source_survives_however_many_come_back(monkeypatch, count: int):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="10000"
    )

    payload = json.loads(internet._encode_results(_results(count, "x" * 3_000)))

    assert len(payload["results"]) == count
    assert "dropped_for_space" not in payload
    assert len(payload["results"][0]["content"]) >= internet._MIN_RESULT_CHARS


def test_a_bigger_result_set_shortens_the_excerpt_rather_than_losing_sources(
    monkeypatch,
):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="10000"
    )

    few = json.loads(internet._encode_results(_results(4, "x" * 3_000)))["results"]
    many = json.loads(internet._encode_results(_results(12, "x" * 3_000)))["results"]

    assert len(many[0]["content"]) < len(few[0]["content"])
    assert len(many) == 12


# When the payload genuinely cannot carry a useful excerpt from everything, the
# loss is reported rather than silent: a model reading five sources should know
# whether five was all there were.
def test_an_unavoidable_drop_is_counted(monkeypatch):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="1200"
    )

    payload = json.loads(internet._encode_results(_results(40, "x" * 3_000)))

    assert payload["dropped_for_space"] > 0
    assert len(payload["results"]) + payload["dropped_for_space"] == 40


# The failure a fixed set of sizes hides. Once the sources outgrew the budget
# the count kept was computed from what remained after paying for all of them,
# which had already gone negative - so forty sources kept nineteen and eighty
# kept one. More evidence coming back must never mean less of it arriving.
def test_more_sources_never_means_fewer_kept(monkeypatch):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="10000"
    )

    kept = [
        len(
            json.loads(internet._encode_results(_results(count, "x" * 3_000)))[
                "results"
            ]
        )
        for count in range(1, 200)
    ]

    assert all(later >= earlier for earlier, later in zip(kept, kept[1:], strict=False))
    assert kept[-1] > 1


# The bound is what keeps the generic MCP truncation from landing mid-JSON, so
# it has to hold at every size rather than at the ones with a test.
def test_no_result_count_can_overrun_the_payload(monkeypatch):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="10000"
    )

    for count in (1, 5, 17, 40, 99, 200):
        encoded = internet._encode_results(_results(count, "x" * 3_000))
        assert len(encoded) <= 10_000, f"{count} sources overran the payload"
        json.loads(encoded)


# Every size test above used content that serializes to its own length, so all
# of them passed while a live search came out 148 characters over the bound.
# Real pages carry newlines, quotes and backslashes, and each costs two
# characters serialized - a cost the plan cannot see, because it measures the
# payload with the excerpts still empty.
@pytest.mark.parametrize("count", [1, 3, 8, 20, 60])
def test_escaped_content_cannot_overrun_the_payload(monkeypatch, count: int):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="10000"
    )
    # Every character here doubles in length once serialized.
    hostile = '"\\\n\t' * 1_000

    encoded = internet._encode_results(_results(count, hostile))

    assert len(encoded) <= 10_000, f"{count} sources of escaped text overran"
    assert len(json.loads(encoded)["results"]) >= 1


# Escaping must cost excerpt length, not sources: the correction that brings an
# overrun back inside the bound has to shorten what each result carries rather
# than quietly discarding results that were already accounted for.
def test_the_escape_correction_shortens_rather_than_drops(monkeypatch):
    internet = _server(
        monkeypatch, SEARCH_RESULT_CHARS="1500", SEARCH_PAYLOAD_CHARS="10000"
    )

    plain = json.loads(internet._encode_results(_results(8, "x" * 3_000)))
    escaped = json.loads(internet._encode_results(_results(8, '"\n' * 1_500)))

    assert len(escaped["results"]) == len(plain["results"]) == 8
    assert len(escaped["results"][0]["content"]) < len(plain["results"][0]["content"])


def test_the_generic_tool_bound_is_configurable(monkeypatch):
    import backend.mcp.invocation as invocation
    from backend.config.settings import settings

    assert invocation._MAX_RESULT_CHARS == settings.MCP_MAX_RESULT_CHARS
    # The search payload must stay under it, or truncation lands mid-JSON.
    assert settings.SEARCH_PAYLOAD_CHARS < settings.MCP_MAX_RESULT_CHARS


# Every variable the subprocess reads has to be listed in `inherit_env`, or it
# takes its own default and the setting silently does nothing.
def test_the_subprocess_inherits_the_budgets_it_reads():
    from pathlib import Path

    declared = Path(__file__).resolve().parents[2] / ".env"
    if not declared.exists():  # pragma: no cover - depends on the checkout
        pytest.skip("no .env in this checkout")
    text = declared.read_text(encoding="utf-8")
    if "inherit_env" not in text:  # pragma: no cover
        pytest.skip("MCP servers are not configured here")

    for name in ("SEARCH_RESULT_CHARS", "SEARCH_PAYLOAD_CHARS", "SEARCH_MAX_RESULTS"):
        assert f'"{name}"' in text, f"{name} is read by the server but not inherited"


def test_the_tool_argument_cannot_exceed_the_configured_count(monkeypatch):
    internet = _server(monkeypatch, SEARCH_MAX_RESULTS="8")
    asked: dict[str, int] = {}

    class Provider:
        async def search(self, query: str, max_results: int = 0):
            asked["max_results"] = max_results
            return _results(1, "x")

    monkeypatch.setattr(internet, "_build_search_provider", lambda: Provider())

    import asyncio

    asyncio.run(internet.search_web("q", max_results=50))
    assert asked["max_results"] == 8

    asyncio.run(internet.search_web("q", max_results=2))
    assert asked["max_results"] == 2

    asyncio.run(internet.search_web("q"))
    assert asked["max_results"] == 8


@pytest.fixture(autouse=True)
def _restore_module():
    yield
    os.environ.pop("SEARCH_RESULT_CHARS", None)
    os.environ.pop("SEARCH_PAYLOAD_CHARS", None)
    import backend.mcp.servers.internet as internet

    importlib.reload(internet)
