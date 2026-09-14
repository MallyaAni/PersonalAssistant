"""The desk endpoint: the day's record and its changes reach the page, and
only for the user whose token asks. A stale live snapshot is served but
marked stale, never presented as the current candle. A named extra account
reads the desk but cannot replace the operator's shared holdings."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


# The existing desk route reads the persisted independent paper run without changing it.
@pytest.mark.asyncio
async def test_forward_paper_summary_is_read_from_persisted_account(
    tmp_path, monkeypatch
):
    from backend.market import board_paper

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-11", {"AAPL": "A+"}, [("AAPL", 0.1)], [])
    before = board_paper.initialize(tmp_path, 100_000)
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get("/api/v1/market/desk_user/desk")
        assert response.status_code == 200
        assert response.json()["board_paper"]["cash"] == 100_000
        assert response.json()["board_paper"]["equity"] == 100_000
    assert board_paper.latest(tmp_path) == before


# Recorded recommendations remain accessible even before a nightly replay file exists.
@pytest.mark.asyncio
async def test_recorded_ticker_history_without_simulated_history(tmp_path, monkeypatch):
    from backend.tests.test_forward_evidence import observations
    from backend.tests.test_recommendation_history import archive

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    archive(tmp_path, observations())
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get("/api/v1/market/desk_user/desk/history/AAPL")
        assert response.status_code == 200, response.text
        result = response.json()
        assert len(result["recommendations"]["observations"]) == 3
        assert result["backtest"] is None
        missing = await client.get("/api/v1/market/desk_user/desk/history/MISSING")
        assert missing.status_code == 404


# Read dated quote decisions over HTTP and prove the preview changes no stored state.
@pytest.mark.asyncio
async def test_decision_preview_preserves_context_and_files(tmp_path, monkeypatch):
    from backend.market import execution_quotes, holdings
    from backend.tests.test_decision_view import setup

    record, snapshot, quoted, _ = setup()
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(execution_quotes, "fetch", lambda symbols: quoted)
    folder = tmp_path / "desk" / f"asof={record['session']}"
    folder.mkdir(parents=True)
    (folder / "desk.json").write_text(json.dumps(record))
    (tmp_path / "desk/live.json").write_text(json.dumps(snapshot))
    holdings.save(tmp_path, [holdings.Holding("S11", 10, 100, "2026-09-10")])
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}
    token = issue_user_token("desk_user", scopes=["memory:read", "memory:write"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get("/api/v1/market/desk_user/desk/mine?equity=100000")
        assert response.status_code == 200, response.text
        result = response.json()["decisions"]
        assert result["holdings"] == {"S11": 10}
        assert result["equity"] == 100000
        assert result["session"] == record["session"]
        assert result["rows"]["S11"]["quote"]["feed"] == "sip"
        invalid = await client.get("/api/v1/market/desk_user/desk/mine?equity=inf")
        assert invalid.status_code == 422
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")} == before


# Write a dated desk fixture for the real HTTP handlers to read.
def _write(root, session, grades, book, flags, curve=None):
    path = root / "desk" / f"asof={session}" / "desk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "session": session,
                "regime": {
                    "flags": flags,
                    "selection_confidence": 0.5,
                    "exposure": 1.0,
                },
                "grades": {t: {"grade": g} for t, g in grades.items()},
                "book": [{"ticker": t, "weight": w} for t, w in book],
                "briefs": {},
                "curve": curve,
            }
        ),
        encoding="utf-8",
    )


# Exercise funding over HTTP and prove the read-only preview leaves holdings intact.
@pytest.mark.asyncio
async def test_funding_preview_uses_saved_holdings_without_writing_cash(
    tmp_path, monkeypatch
):
    from backend.market import holdings

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(
        tmp_path,
        "2026-09-04",
        {"AAA": "A+", "BBB": "A"},
        [("AAA", 0.15), ("BBB", 0.15)],
        [],
    )
    holdings.save(tmp_path, [holdings.Holding("AAA", 100, 9, "2026-09-01")])
    (tmp_path / "desk" / "live.json").write_text(
        json.dumps({"quotes": {"AAA": {"last": 10}, "BBB": {"last": 20}}})
    )
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}
    token = issue_user_token(
        "desk_user", ttl_seconds=60, scopes=["memory:read", "memory:write"]
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/market/desk_user/desk/funding-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={"equity": 10000, "available_cash": 200},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["estimated_cost"] == 190
        assert {r["ticker"]: r["additional_shares"] for r in result["rows"]} == {
            "AAA": 5,
            "BBB": 7,
        }
        denied = await client.post(
            "/api/v1/market/someone_else/desk/funding-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={"equity": 10000, "available_cash": 200},
        )
        assert denied.status_code == 403
        read_token = issue_user_token(
            "desk_user", ttl_seconds=60, scopes=["memory:read"]
        )
        denied_scope = await client.post(
            "/api/v1/market/desk_user/desk/funding-preview",
            headers={"Authorization": f"Bearer {read_token}"},
            json={"equity": 10000, "available_cash": 200},
        )
        assert denied_scope.status_code == 403
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")} == before


# Exercise the research preview with disk-backed decisions and reject expired evidence.
@pytest.mark.asyncio
async def test_research_preview_reads_targets_without_mutating_holdings(
    tmp_path, monkeypatch
):
    from backend.market import deskrecord, holdings, intraday_research

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-04", {"AAA": "A+", "BBB": "A"}, [("AAA", 0.15)], [])
    holdings.save(tmp_path, [holdings.Holding("AAA", 100, 9, "2026-09-01")])
    record, _ = deskrecord.latest_pair(tmp_path)
    now = datetime.now(UTC)
    decision = {
        "status": "available",
        "session": record["session"],
        "as_of": now.isoformat(),
        "valid_until": (now + timedelta(minutes=10)).isoformat(),
        "bar": now.isoformat(),
        "macro": {"exposure": 0.5},
        "record_sha256": intraday_research.record_hash(record),
        "targets": {"AAA": 0.05, "BBB": 0.15},
        "prices": {"AAA": 10, "BBB": 20},
    }
    path = tmp_path / "desk" / "intraday-research" / "latest.json"
    path.parent.mkdir()
    path.write_text(json.dumps(decision))
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}
    token = issue_user_token("desk_user", scopes=["memory:read", "memory:write"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(
            "/api/v1/market/desk_user/desk/funding-preview",
            json={"equity": 10000, "available_cash": 200, "mode": "intraday_research"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["estimated_cost"] == 200
        assert result["rows"][0]["additional_shares"] == 10
        assert result["reductions"][0]["reduction_shares"] == 50
        assert {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")} == before
        decision["valid_until"] = (now - timedelta(seconds=1)).isoformat()
        path.write_text(json.dumps(decision))
        expired = await client.post(
            "/api/v1/market/desk_user/desk/funding-preview",
            json={"equity": 10000, "available_cash": 200, "mode": "intraday_research"},
        )
        assert expired.status_code == 422
        assert "expired" in expired.text


@pytest.mark.asyncio
async def test_the_endpoint_returns_the_record_and_the_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-03", {"SNDK": "A", "MU": "A+"}, [("MU", 0.07)], [])
    _write(tmp_path, "2026-09-04", {"SNDK": "A+", "MU": "B"}, [("SNDK", 0.08)], ["x"])
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
        earlier = await client.get(
            "/api/v1/market/desk_user/desk/2026-09-03",
            headers={"Authorization": f"Bearer {token}"},
        )
        missing = await client.get(
            "/api/v1/market/desk_user/desk/2020-01-01",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["latest"]["session"] == "2026-09-04"
    assert payload["summary"]["counts"] == {"A+": 1, "A": 0, "B": 1, "C": 0}
    assert payload["changes"]["since"] == "2026-09-03"
    assert payload["changes"]["upgrades"] == [
        {"ticker": "SNDK", "from": "A", "to": "A+"}
    ]
    assert {o["ticker"]: o["action"] for o in payload["changes"]["orders"]} == {
        "MU": "sell",
        "SNDK": "buy",
    }
    assert payload["changes"]["flags_raised"] == ["x"]
    assert payload["sessions"] == ["2026-09-03", "2026-09-04"]
    assert earlier.status_code == 200
    assert earlier.json()["record"]["session"] == "2026-09-03"
    assert missing.status_code == 404


# The newest earnings release read reaches the drill-down the day an 8-K
# lands: the tone and the numbers the release reader scored, straight from
# the store the release reader writes (not from the nightly grade, which has
# not seen it yet). A name with no release on file answers read None rather
# than erroring, so the page can hide the block quietly.
@pytest.mark.asyncio
async def test_the_earnings_read_reaches_the_drill_down(tmp_path, monkeypatch):
    from backend.market import language
    from backend.market.store import MarketStore

    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    record = language.ToneRecord(
        accession="0000320193-26-000001",
        reaction_date=date(2026, 9, 11),
        guidance=1.0,
        demand=1.0,
        pricing=0.0,
        capex=1.0,
        supply_constrained=0.0,
        summary="Oracle guides Q2 FY27 revenue growth of 30-34%",
        model="deepseek-v4-flash",
        prompt_version="release_tone/2",
        truncated=False,
        quarter_end=date(2026, 8, 31),
        revenue_usd_m=19345.0,
        eps_usd=1.56,
        net_income_usd_m=4679.0,
        gross_margin_pct=None,
    )
    MarketStore(tmp_path).write_frame(
        language.TONE_KIND,
        date(2026, 9, 12),
        "ORCL",
        language.tone_frame([record]),
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/earnings/ORCL",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    read = response.json()["read"]
    assert read["reaction_date"] == "2026-09-11"
    assert read["guidance"] == 1.0
    assert read["demand"] == 1.0
    assert read["pricing"] == 0.0
    assert read["revenue_usd_m"] == 19345.0
    assert read["eps_usd"] == 1.56
    assert read["net_income_usd_m"] == 4679.0
    assert read["quarter_end"] == "2026-08-31"
    assert read["gross_margin_pct"] is None
    assert read["summary"] == "Oracle guides Q2 FY27 revenue growth of 30-34%"


@pytest.mark.asyncio
async def test_a_name_without_a_release_read_answers_none(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/earnings/ORCL",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["read"] is None


@pytest.mark.asyncio
async def test_no_record_is_an_empty_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": "desk_user", "latest": None, "sessions": []}


@pytest.mark.asyncio
async def test_another_users_token_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code in (401, 403), response.text


@pytest.mark.asyncio
async def test_a_user_who_is_not_the_operator_is_refused_with_their_own_token(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+"}, [("SNDK", 0.08)], [])
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/someone_else/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403, response.text


# An account named in MARKET_DESK_USERS opens the desk like the primary
# operator; a user outside both still cannot.
@pytest.mark.asyncio
async def test_a_named_extra_user_opens_the_desk(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    monkeypatch.setattr(settings, "MARKET_DESK_USERS", "vjmallya, guest")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+"}, [("SNDK", 0.08)], [])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        allowed = await client.get(
            "/api/v1/market/vjmallya/desk",
            headers={
                "Authorization": (
                    f"Bearer {issue_user_token('vjmallya', ttl_seconds=60)}"
                )
            },
        )
        refused = await client.get(
            "/api/v1/market/stranger/desk",
            headers={
                "Authorization": (
                    f"Bearer {issue_user_token('stranger', ttl_seconds=60)}"
                )
            },
        )
    assert allowed.status_code == 200, allowed.text
    assert refused.status_code == 403, refused.text


# The desk's holdings are one shared book, so writing them is the primary
# operator's alone. A named extra account reads the desk and cannot replace
# the operator's saved list with its own; the persisted file keeps the
# operator's rows after the extra account's attempt.
@pytest.mark.asyncio
async def test_an_extra_account_cannot_overwrite_the_operators_holdings(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    monkeypatch.setattr(settings, "MARKET_DESK_USERS", "vjmallya, guest")
    owner = {
        "Authorization": f"Bearer {issue_user_token('ani.mallya', ttl_seconds=60)}"
    }
    extra = {"Authorization": f"Bearer {issue_user_token('vjmallya', ttl_seconds=60)}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        saved = await client.put(
            "/api/v1/market/ani.mallya/desk/holdings",
            headers=owner,
            json=[
                {
                    "ticker": "AAA",
                    "shares": 10.0,
                    "entry_price": 100.0,
                    "entry_date": "2026-09-01",
                }
            ],
        )
        assert saved.status_code == 200, saved.text
        refused = await client.put(
            "/api/v1/market/vjmallya/desk/holdings",
            headers=extra,
            json=[
                {
                    "ticker": "BBB",
                    "shares": 10.0,
                    "entry_price": 50.0,
                    "entry_date": "2026-09-01",
                }
            ],
        )
        assert refused.status_code == 403, refused.text
        owner_read = await client.get(
            "/api/v1/market/ani.mallya/desk/holdings", headers=owner
        )
        extra_read = await client.get(
            "/api/v1/market/vjmallya/desk/holdings", headers=extra
        )
    assert [h["ticker"] for h in owner_read.json()["holdings"]] == ["AAA"]
    assert [h["ticker"] for h in extra_read.json()["holdings"]] == ["AAA"]


def test_market_desk_operators_parse_the_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    monkeypatch.setattr(settings, "MARKET_DESK_USERS", " vjmallya, ,guest")
    assert settings.market_desk_operators == frozenset(
        {"ani.mallya", "vjmallya", "guest"}
    )


# A snapshot older than a candle is served but marked stale, so the page does
# not present a closed-market file as the current candle; a fresh one is not.
@pytest.mark.asyncio
async def test_the_live_snapshot_is_marked_stale_when_older_than_a_candle(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    live_dir = tmp_path / "desk"
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "live.json").write_text(
        json.dumps(
            {
                "as_of": (datetime.now(UTC) - timedelta(hours=26)).isoformat(
                    timespec="seconds"
                ),
                "quotes": {"SNDK": {"t": "SNDK", "p": 10.0, "pc": 9.0}},
            }
        ),
        encoding="utf-8",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/live",
            headers={"Authorization": f"Bearer {issue_user_token('desk_user')}"},
        )
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["stale"] is True
    assert body["age_seconds"] > 15 * 60


# Freshness is measured from a real candle during an open session.
@pytest.mark.asyncio
async def test_a_fresh_live_snapshot_is_not_stale(tmp_path, monkeypatch):
    from backend.market import desk_freshness

    # Freeze an open session so freshness does not depend on the test's day.
    class Clock(datetime):
        # Return a time just after a real regular-session candle.
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 11, 14, 0, tzinfo=UTC)

    monkeypatch.setattr(desk_freshness, "datetime", Clock)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    live_dir = tmp_path / "desk"
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "live.json").write_text(
        json.dumps(
            {
                "as_of": Clock.now().isoformat(),
                "quotes": {"SNDK": {"last": 10.0, "bar": "2026-09-11T13:45:00+00:00"}},
            }
        ),
        encoding="utf-8",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/live",
            headers={"Authorization": f"Bearer {issue_user_token('desk_user')}"},
        )
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["stale"] is False


# HTTP responses must reject stale evidence even when its file was just written.
@pytest.mark.asyncio
async def test_new_snapshot_with_old_candle_keeps_the_evening_grade(
    tmp_path, monkeypatch
):
    from backend.api.v1 import market

    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-10", {"AAA": "B"}, [("AAA", 0.08)], [])
    record_path = tmp_path / "desk/asof=2026-09-10/desk.json"
    record = json.loads(record_path.read_text())
    record["grades"]["AAA"].update(
        stances={"technical": 0, "value": 0},
        ranks={"technical": 0.5, "value": 0.5},
        score=0,
    )
    record_path.write_text(json.dumps(record))
    (tmp_path / "desk/live.json").write_text(
        json.dumps(
            {
                "as_of": datetime.now(UTC).isoformat(),
                "decision_session": "2026-09-10",
                "quotes": {"AAA": {"last": 105, "bar": "2026-09-10T13:45:00+00:00"}},
                "technical": {"AAA": {"now": 0.9, "close": 0.5, "stance": 1}},
                "technical_detail": {
                    "AAA": {"now": 0.9, "short": {}, "medium": {}, "long": {}}
                },
            }
        )
    )

    # A stale read must stop before the model boundary.
    def unexpected_model(*args, **kwargs):
        pytest.fail("stale evidence called the model")

    monkeypatch.setattr(market, "_model_live_read", unexpected_model)
    auth = {"Authorization": f"Bearer {issue_user_token('desk_user')}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/api/v1/market/desk_user/desk/live", headers=auth)
        mine = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 10000}, headers=auth
        )
        read = await client.get(
            "/api/v1/market/desk_user/desk/live/read/AAA", headers=auth
        )
    assert live.status_code == mine.status_code == read.status_code == 200
    assert live.json()["stale"] is True
    assert live.json()["stale_symbols"] == ["AAA"]
    assert mine.json()["grades_live"] == {}
    row = mine.json()["rows"][0]
    assert row["grade_live"] == row["grade"] == "B"
    assert row["grade_source"] == "evening"
    assert read.json()["stale"] is True
    assert read.json()["read_at"] is None
    assert read.json()["data_at"] == "2026-09-10T13:45:00+00:00"


# Durable event intent pauses live plans without overwriting the nightly archive.
@pytest.mark.asyncio
async def test_live_event_cycle_pauses_planning_and_cash_preview(tmp_path, monkeypatch):
    from backend.agents.trading.desk import paper

    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-04", {"AAA": "A+"}, [("AAA", 0.08)], [])
    (tmp_path / "desk" / "live.json").write_text(
        json.dumps({"quotes": {"AAA": {"last": 10}}})
    )
    paper.save_state(
        tmp_path,
        paper.PaperState(event_cycle={"id": "event", "baseline": {"AAA": 100}}),
    )
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}
    token = issue_user_token(
        "desk_user", ttl_seconds=60, scopes=["memory:read", "memory:write"]
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        desk = (await client.get("/api/v1/market/desk_user/desk")).json()
        mine = (
            await client.get("/api/v1/market/desk_user/desk/mine?equity=10000")
        ).json()
        preview = await client.post(
            "/api/v1/market/desk_user/desk/funding-preview",
            json={"equity": 10000, "available_cash": 5000},
        )
    assert desk["event_status"]["active"]
    assert desk["intraday_research"]["event_paused"]
    assert all(row["event_paused"] for row in mine["rows"])
    assert preview.status_code == 200
    assert preview.json()["estimated_cost"] == 0
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}


# The person's own positions round-trip through the API, a bad row is
# refused whole, and the board against them says what to do with each
# name held or targeted, the name the desk does not rate included.
@pytest.mark.asyncio
async def test_holdings_are_saved_and_the_board_is_computed_against_them(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+", "MU": "B"}, [("SNDK", 0.08)], [])
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    rows = [
        {
            "ticker": "mu",
            "shares": 10,
            "entry_price": 100.0,
            "entry_date": "2026-09-01",
        },
        {
            "ticker": "IREN",
            "shares": 100,
            "entry_price": 35.0,
            "entry_date": "2026-08-28",
        },
    ]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        before = await client.get(
            "/api/v1/market/desk_user/desk/holdings", headers=auth
        )
        saved = await client.put(
            "/api/v1/market/desk_user/desk/holdings", json=rows, headers=auth
        )
        bad = await client.put(
            "/api/v1/market/desk_user/desk/holdings",
            json=[{"ticker": "MU", "shares": 0, "entry_price": 1, "entry_date": "x"}],
            headers=auth,
        )
        mine = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 10000}, headers=auth
        )
    assert before.json()["holdings"] == []
    assert [h["ticker"] for h in saved.json()["holdings"]] == ["MU", "IREN"]
    assert bad.status_code == 422
    assert "positive" in bad.json()["detail"]
    board = {r["ticker"]: r for r in mine.json()["rows"]}
    assert mine.json()["session"] == "2026-09-04"
    assert board["SNDK"]["action"] == "buy"
    assert board["MU"]["action"] == "sell"
    assert board["MU"]["grade"] == "B"
    # IREN is held but the desk does not cover it: an explicit review state,
    # not a sell instruction.
    assert board["IREN"]["action"] == "uncovered"
    assert not board["IREN"]["in_book"]
    assert board["IREN"]["shares"] == 100
    assert board["IREN"]["rebalance_due"] is True  # no paper clock yet


# The practice account's live state comes from the broker, and a missing
# key is an answer with a reason, not an error.
@pytest.mark.asyncio
@pytest.mark.parametrize("activity_fails", [None, "broker", "network"])
async def test_the_paper_account_is_read_live(tmp_path, monkeypatch, activity_fails):
    from backend.market import alpaca_trading

    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")

    class Fake:
        def account(self):
            return alpaca_trading.Account(101000.0, 5000.0, 5000.0, 100000.0)

        def positions(self):
            return [alpaca_trading.Position("ADBE", 42.0, 12600.0, 290.0, 300.0, 420.0)]

        def open_orders(self):
            return [{"symbol": "HPE", "side": "buy", "qty": "201", "status": "new"}]

        # Return a partial fill observed today, independent of the evening record.
        def fill_activity(self, session):
            if activity_fails == "network":
                raise OSError("connection timed out")
            if activity_fails:
                raise alpaca_trading.AlpacaTradingError("history offline")
            return {
                "session": session.isoformat(),
                "complete": True,
                "fills": [
                    {
                        "symbol": "HPE",
                        "side": "buy",
                        "qty": 2.5,
                        "price": 50.0,
                        "filled_at": "2026-09-14T13:32:00Z",
                    }
                ],
            }

    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: Fake())
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/api/v1/market/desk_user/desk/paper", headers=auth)
        monkeypatch.setattr(
            alpaca_trading,
            "client_from_env",
            lambda: (_ for _ in ()).throw(alpaca_trading.AlpacaTradingError("no key")),
        )
        missing = await client.get("/api/v1/market/desk_user/desk/paper", headers=auth)
    body = live.json()
    assert body["equity"] == 101000.0
    assert body["day_pl"] == 1000.0
    assert body["positions"][0]["symbol"] == "ADBE"
    if activity_fails:
        assert body["activity"] == {
            "reason": "Today's fill history could not be loaded"
        }
    else:
        assert body["activity"]["complete"] is True
        assert body["activity"]["fills"][0]["qty"] == 2.5
    assert body["orders"] == [
        {"symbol": "HPE", "side": "buy", "qty": 201.0, "status": "new"}
    ]
    assert missing.json()["reason"] == "no key"


# The record's track-record curve reaches the desk endpoint, and a record
# written before the curve existed answers without one.
@pytest.mark.asyncio
async def test_the_desk_returns_the_track_record_curve(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(
        tmp_path,
        "2026-09-04",
        {"SNDK": "A+"},
        [("SNDK", 0.08)],
        [],
        curve={"backtest": {"dates": ["2026-09-03"], "rules": [0.0]}, "paper": None},
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["curve"]["backtest"]["rules"] == [0.0]
    assert response.json()["latest"]["curve"]["backtest"]["dates"] == ["2026-09-03"]


# The drill-down reads the nightly history file for one name, and refuses a
# stranger the same way every other desk route does.
@pytest.mark.asyncio
async def test_the_history_endpoint_reads_the_nightly_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "SNDK.json").write_text(
        json.dumps(
            {
                "ticker": "SNDK",
                "asof": "2026-09-04",
                "horizon": 20,
                "rows": [
                    {"date": "2026-09-02", "grade": "B", "votes": 1.0},
                    {"date": "2026-09-03", "grade": "A+", "votes": 2.0},
                ],
                "backtest": {"rule_return": 0.05},
            }
        ),
        encoding="utf-8",
    )
    # A nightly record for 09-03 said A, not the A+ the replay gives it: the
    # row must carry what the desk said that night and be marked as said.
    rec = tmp_path / "desk" / "asof=2026-09-03"
    rec.mkdir(parents=True)
    (rec / "desk.json").write_text(
        json.dumps(
            {
                "session": "2026-09-03",
                "grades": {
                    "SNDK": {"grade": "A", "votes": 2.0, "stances": {"technical": 1}}
                },
            }
        ),
        encoding="utf-8",
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        found = await client.get(
            "/api/v1/market/desk_user/desk/history/SNDK", headers=auth
        )
        lower = await client.get(
            "/api/v1/market/desk_user/desk/history/sndk", headers=auth
        )
        missing = await client.get(
            "/api/v1/market/desk_user/desk/history/NVDA", headers=auth
        )
    assert found.status_code == 200
    assert found.json()["ticker"] == "SNDK"
    rows = {r["date"]: r for r in found.json()["rows"]}
    assert rows["2026-09-03"]["grade"] == "A"
    assert rows["2026-09-03"]["stances"] == {"technical": 1}
    assert rows["2026-09-03"]["said"] is True
    assert rows["2026-09-02"]["grade"] == "B"
    assert rows["2026-09-02"]["said"] is False
    assert [r["grade"] for r in found.json()["rows"]] == ["B", "A"]
    assert lower.json()["ticker"] == "SNDK"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_the_history_endpoint_refuses_a_stranger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/someone_else/desk/history/SNDK",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403, response.text


# The persisted intraday plan reaches the page as the balancer wrote it, and
# a desk with no plan yet answers 404 rather than inventing one.
@pytest.mark.asyncio
async def test_the_intraday_plan_is_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    plan = tmp_path / "desk" / "intraday.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        json.dumps(
            {
                "as_of": "2026-09-09T13:32:29+00:00",
                "session": "2026-09-08",
                "top_buys": [
                    {
                        "ticker": "SNDK",
                        "grade_live": "A+",
                        "target_weight": 0.04,
                        "leaves_if": "a buy only while it holds an A grade",
                    }
                ],
                "changed": ["first plan of the session"],
            }
        ),
        encoding="utf-8",
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        found = await client.get("/api/v1/market/desk_user/desk/intraday", headers=auth)
        # A desk with no plan: the root has no intraday.json yet.
        (plan.parent / "intraday.json").unlink()
        missing = await client.get(
            "/api/v1/market/desk_user/desk/intraday", headers=auth
        )
        # A stranger is refused before the file is read.
        monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
        stranger_token = issue_user_token(
            "someone_else", ttl_seconds=60, scopes=["memory:read"]
        )
        refused = await client.get(
            "/api/v1/market/someone_else/desk/intraday",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
    body = found.json()
    assert found.status_code == 200
    assert body["session"] == "2026-09-08"
    assert body["top_buys"][0]["ticker"] == "SNDK"
    assert body["top_buys"][0]["leaves_if"].startswith("a buy only")
    assert missing.status_code == 404
    assert refused.status_code == 403


# The autopsy reads the caller's own trading passages and returns the model's
# three sections, and answers with a plain reason when there is nothing to read.
@pytest.mark.asyncio
async def test_the_autopsy_reads_the_persons_own_documents(tmp_path, monkeypatch):
    from backend.api.v1 import market as market_api
    from backend.core.dependencies import get_agent_memory_manager

    payload = {
        "patterns": [{"behaviour": "cut winners early", "evidence": "twice"}],
        "costs": [
            {
                "what": "left on the table",
                "amount": "not stated",
                "source": "journal",
            }
        ],
        "plan": {"stop": ["hold winners"], "start": [], "keep": ["journaled"]},
        "unknowns": [],
    }

    class FakeWriter:
        def chat(
            self, messages, max_tokens=1024, response_schema=None, temperature=None
        ):
            return {"content": json.dumps(payload)}

    class FakeKnowledge:
        # Return the owner's document passages at the knowledge boundary.
        async def search(self, user_id, query, top_k):
            assert user_id == "trader"
            return [
                {
                    "content": "bought at 40, sold at 32",
                    "document": {"title": "journal"},
                }
            ]

    from backend.memory.retrieval import SemanticRetrievalPolicy
    from backend.services.agent_memory_manager import AgentMemoryManager

    manager = AgentMemoryManager(None, None, SemanticRetrievalPolicy(), "test")
    manager.knowledge = FakeKnowledge()
    app.dependency_overrides[get_agent_memory_manager] = lambda: manager
    monkeypatch.setattr(market_api, "get_structured_llm_client", lambda: FakeWriter())
    try:
        token = issue_user_token("trader", ttl_seconds=60, scopes=["memory:read"])
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/market/trader/trading/autopsy",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_agent_memory_manager, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["patterns"][0]["behaviour"] == "cut winners early"
    assert body["result"]["costs"][0]["amount"] == "not stated"
    assert body["sources"] == ["journal"]
    assert body["passages_used"] == 1


# Empty knowledge produces an actionable response through the real facade.
@pytest.mark.asyncio
async def test_the_autopsy_without_documents_explains_why(tmp_path, monkeypatch):
    from backend.core.dependencies import get_agent_memory_manager

    class EmptyKnowledge:
        # Represent a user with no relevant uploaded passages.
        async def search(self, user_id, query, top_k):
            return []

    from backend.memory.retrieval import SemanticRetrievalPolicy
    from backend.services.agent_memory_manager import AgentMemoryManager

    manager = AgentMemoryManager(None, None, SemanticRetrievalPolicy(), "test")
    manager.knowledge = EmptyKnowledge()
    app.dependency_overrides[get_agent_memory_manager] = lambda: manager
    try:
        token = issue_user_token("trader", ttl_seconds=60, scopes=["memory:read"])
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/market/trader/trading/autopsy",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_agent_memory_manager, None)
    assert response.status_code == 200
    body = response.json()
    assert body["result"] is None
    assert "No trading documents" in body["reason"]


# The live endpoints serve the candle the balancer persisted, without a quote
# fetch or an analyst run of their own: /desk/live returns the snapshot, and
# /desk/mine builds its board from the snapshot's quotes and technical read.
@pytest.mark.asyncio
@pytest.mark.parametrize("growth_model", [False, True])
async def test_the_live_endpoints_serve_the_persisted_snapshot(
    tmp_path, monkeypatch, growth_model
):
    from backend.market import desk_freshness

    class Clock(datetime):
        # Keep this acceptance path inside the next regular session.
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 8, 14, 0, tzinfo=UTC)

    monkeypatch.setattr(desk_freshness, "datetime", Clock)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+", "MU": "B"}, [("SNDK", 0.08)], [])
    # The live grade re-read needs a technical stance on each name.
    record_path = tmp_path / "desk" / "asof=2026-09-04" / "desk.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    for grade in record["grades"].values():
        grade["stances"] = {"technical": 1}
        if growth_model:
            grade["stances"].update(fundamental=1, sentiment=1, value=1)
            grade["ranks"] = {"value": 0.8}
    if growth_model:
        record["provenance"] = {"rule": {"inputs": ["expectations-gap"]}}
    record_path.write_text(json.dumps(record), encoding="utf-8")
    desk = tmp_path / "desk"
    desk.mkdir(parents=True, exist_ok=True)
    (desk / "live.json").write_text(
        json.dumps(
            {
                "as_of": "2026-09-08T14:00:00+00:00",
                "decision_session": "2026-09-04",
                "quotes": {
                    "SNDK": {"last": 120.0, "bar": "2026-09-08T13:45:00+00:00"},
                    "MU": {"last": 45.0},
                },
                "technical": {"SNDK": {"now": 0.81, "close": 0.7}},
                "value": {"SNDK": {"now": 0.1, "close": 0.1, "stance": -1}},
                "technical_detail": {"SNDK": {"now": 0.81}},
            }
        ),
        encoding="utf-8",
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/api/v1/market/desk_user/desk/live", headers=auth)
        mine = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 10000}, headers=auth
        )
    assert live.status_code == 200
    body = live.json()
    assert body["as_of"] == "2026-09-08T14:00:00+00:00"
    assert body["quotes"]["SNDK"]["last"] == 120.0
    assert body["stale_symbols"] == ["MU"]
    assert body["technical"]["SNDK"]["now"] == 0.81
    assert body["technical_detail"] == {"SNDK": {"now": 0.81}}
    board = {r["ticker"]: r for r in mine.json()["rows"]}
    assert board["SNDK"]["technical_now"] == 0.81
    assert board["SNDK"]["last"] == 120.0
    if growth_model:
        for row in (board["SNDK"], mine.json()["grades_live"]["SNDK"]):
            assert row["grade_live"] == "A+"
            assert row["value_now"] is None
            assert row["stances_live"]["value"] == 1
            assert row["ranks_live"]["value"] == 0.8
