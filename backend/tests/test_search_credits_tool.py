"""The search meter: read from the provider, offered to the operator, silent
when a scheduled check finds nothing to say."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.mcp.servers import internet
from backend.search.tavily import TavilyUsageClient
from backend.services.mcp_tool_orchestration_service import MCPToolPlan
from backend.tasks.quiet import NOTHING_TO_REPORT, is_nothing_to_report
from backend.tools.actions import ToolboxAction
from backend.tools.registry import describe_action, waiting_line
from backend.workers.imessage_chat import TurnResult
from backend.workers.task_runner import TaskRunner

_USAGE_BODY = {
    "key": {"usage": 993, "limit": None, "search_usage": 993},
    "account": {"current_plan": "Researcher", "plan_usage": 993, "plan_limit": 1000},
}


def _client(body: dict | None, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/usage"
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(status, json=body if body is not None else {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_the_usage_report_carries_plan_spent_limit_and_remaining() -> None:
    client = TavilyUsageClient("https://api.tavily.com", "k", client=_client(_USAGE_BODY))
    assert await client.report() == {
        "plan": "Researcher",
        "spent": 993,
        "limit": 1000,
        "remaining": 7,
    }
    assert await client.spent() == 993


@pytest.mark.asyncio
async def test_an_unreadable_usage_endpoint_reports_unknown_not_zero() -> None:
    assert await TavilyUsageClient("https://api.tavily.com", "k", client=_client(None, 500)).report() is None
    assert await TavilyUsageClient("https://api.tavily.com", None).report() is None


@pytest.mark.asyncio
async def test_the_internet_server_reports_the_meter(monkeypatch) -> None:
    async def report():
        return {"plan": "Researcher", "spent": 993, "limit": 1000, "remaining": 7}

    monkeypatch.setattr(internet, "_usage_report", report)
    payload = json.loads(await internet.search_credits())
    assert payload["provider"] == "tavily"
    assert (payload["spent"], payload["limit"], payload["remaining"]) == (993, 1000, 7)
    assert payload["percent_used"] == 99.3


@pytest.mark.asyncio
async def test_the_internet_server_says_unknown_when_the_meter_cannot_be_read(monkeypatch) -> None:
    async def report():
        return None

    monkeypatch.setattr(internet, "_usage_report", report)
    payload = json.loads(await internet.search_credits())
    assert payload["error"] == "usage_unavailable"
    assert "not zero" in payload["detail"]


def test_the_meter_has_its_own_label_and_waiting_line() -> None:
    action = ToolboxAction(
        plan=MCPToolPlan(
            server_id="internet", tool_name="search_credits", arguments={}, expected_fingerprint="f"
        )
    )
    assert describe_action(action) == ("Search credits", "")
    assert waiting_line(action) in {"🧾 Checking the search meter…", "💳 Counting the credits…"}


def test_the_silence_token_is_recognised_with_the_decoration_models_add() -> None:
    assert is_nothing_to_report(NOTHING_TO_REPORT)
    assert is_nothing_to_report("  NOTHING_TO_REPORT.\n")
    assert is_nothing_to_report('"NOTHING_TO_REPORT"')
    assert is_nothing_to_report("**NOTHING_TO_REPORT**")
    assert not is_nothing_to_report("NOTHING_TO_REPORT - credits are fine at 800")
    assert not is_nothing_to_report("Search credits are nearly gone: 7 of 1,000 left.")


@pytest.mark.asyncio
async def test_a_quiet_firing_is_finished_without_a_message(monkeypatch) -> None:
    runner = TaskRunner(lambda *a: None, base_url="http://test")
    finished: list[tuple] = []
    sent: list[tuple] = []

    async def finish(run_id, status, task=None, output=None, error_code=None):
        finished.append((run_id, status, output, error_code))

    async def deliver(address, turn):
        sent.append((address, turn.reply))

    async def address_for(user_id):
        return "+17039290948"

    monkeypatch.setattr(runner, "_finish", finish)
    monkeypatch.setattr(runner, "_address_for", address_for)
    monkeypatch.setattr(runner.chat, "_deliver", deliver)

    await runner._deliver("run-1", {"channel": "imessage", "user_id": "ani.mallya"}, TurnResult("NOTHING_TO_REPORT"))
    assert finished == [("run-1", "quiet", "NOTHING_TO_REPORT", None)]
    assert sent == []

    await runner._deliver(
        "run-2",
        {"channel": "imessage", "user_id": "ani.mallya"},
        TurnResult("Search credits are nearly gone: 7 of 1,000 left."),
    )
    assert sent == [("+17039290948", "Search credits are nearly gone: 7 of 1,000 left.")]
    assert finished[-1][:2] == ("run-2", "delivered")


def test_the_meter_summary_names_who_serves() -> None:
    from backend.mcp.servers.internet import _meter_summary

    tavily = {"plan": "Researcher", "spent": 1000, "limit": 1000, "remaining": 0}
    brave = {"used": 4, "limit": 900, "remaining": 896, "period": "this calendar month"}
    text = _meter_summary(tavily, brave)
    assert text.startswith("Searches are served by brave right now")
    assert "Brave has 896 of 900" in text and "Tavily has 0 of 1000" in text
    spent = _meter_summary(tavily, {"used": 900, "limit": 900, "remaining": 0, "period": "m"})
    assert spent.startswith("Every search rung is spent")
