"""The tone refresh's time budget: it stops between names, keeps what it scored.

What has to hold: with a deadline already past no name is scored and the
refresh says how many carry earlier scores; with no deadline every name is
visited; a deadline reached mid-run stops before the next name, never
inside one.
"""

from datetime import date

import pytest

from backend.cli import market_tone


def _fake_readers(monkeypatch, visited):
    monkeypatch.setattr(market_tone, "clients", lambda *a, **k: ([object()], "m"))
    monkeypatch.setattr(market_tone, "current_frame_exists", lambda *a: False)

    def refresh_ticker(
        store, ticker, asof, since, readers, model, pacer, deadline=None
    ):
        visited.append(ticker)
        return 3, 0, 3

    monkeypatch.setattr(market_tone, "_refresh_ticker", refresh_ticker)


def test_a_past_deadline_scores_nothing_and_says_so(monkeypatch, capsys):
    visited = []
    _fake_readers(monkeypatch, visited)
    scored = market_tone.refresh_tickers(
        None, ("A", "B", "C"), date(2026, 9, 15), deadline=0.0
    )
    assert scored == 0
    assert visited == []
    assert "3 names carry earlier scores" in capsys.readouterr().out


def test_no_deadline_visits_every_name(monkeypatch):
    visited = []
    _fake_readers(monkeypatch, visited)
    assert market_tone.refresh_tickers(None, ("A", "B"), date(2026, 9, 15)) == 6
    assert visited == ["A", "B"]


def test_a_deadline_reached_mid_run_stops_before_the_next_name(monkeypatch):
    visited = []
    _fake_readers(monkeypatch, visited)
    clock = iter([0.0, 10.0, 10.0, 10.0])  # one reading per name visited
    monkeypatch.setattr(market_tone.time, "monotonic", lambda: next(clock))
    scored = market_tone.refresh_tickers(
        None, ("A", "B", "C"), date(2026, 9, 15), deadline=5.0
    )
    assert visited == ["A"]
    assert scored == 3


# A name whose fetch fails is named and skipped; the names after it are
# still scored, and the failed name is listed for the next run.
def test_one_names_failure_does_not_abandon_the_rest(monkeypatch, capsys):
    visited = []
    monkeypatch.setattr(market_tone, "clients", lambda *a, **k: ([object()], "m"))
    monkeypatch.setattr(market_tone, "current_frame_exists", lambda *a: False)

    def refresh_ticker(
        store, ticker, asof, since, readers, model, pacer, deadline=None
    ):
        visited.append(ticker)
        if ticker == "B":
            raise RuntimeError("B: earnings refresh incomplete (1 failures)")
        return 2, 0, 2

    monkeypatch.setattr(market_tone, "_refresh_ticker", refresh_ticker)
    scored = market_tone.refresh_tickers(None, ("A", "B", "C"), date(2026, 9, 15))
    assert visited == ["A", "B", "C"]
    assert scored == 4
    out = capsys.readouterr().out
    assert "B: earnings refresh incomplete" in out
    assert "1 names incomplete (B)" in out


# The deadline bites inside a name: past it, no more releases are fetched
# and fetched ones are not scored; they count as failures, so the name is
# retried next run and its frame is not stored as complete.
def test_the_deadline_stops_fetching_and_scoring_within_a_name(monkeypatch, tmp_path):
    from datetime import datetime
    from types import SimpleNamespace

    from backend.market import edgar, language
    from backend.market.store import MarketStore

    store = MarketStore(tmp_path)
    events = [
        edgar.EarningsEvent(
            accepted=datetime(2026, 1, 1 + i, 12),
            filed=date(2026, 1, 1 + i),
            accession=f"acc-{i}",
            items=("2.02",),
        )
        for i in range(3)
    ]
    store.write_frame(
        "edgar_events",
        date(2026, 9, 15),
        "AAA",
        {
            "accepted": [e.accepted.isoformat() for e in events],
            "filed": [e.filed for e in events],
            "accession": [e.accession for e in events],
            "items": [",".join(e.items) for e in events],
        },
        {"cik": "1"},
    )
    fetched = []
    monkeypatch.setattr(
        language,
        "fetch_release_text",
        lambda cik, event, pacer=None: fetched.append(event.accession) or "text",
    )
    scored = []
    reader = SimpleNamespace(
        score_sync=lambda text: scored.append(text)
        or SimpleNamespace(
            guidance=0,
            demand=0,
            pricing=0,
            capex=0,
            supply_constrained=False,
            summary="",
            truncated=False,
            quarter_end=None,
            revenue_usd_m=None,
            eps_usd=None,
            net_income_usd_m=None,
            gross_margin_pct=None,
        ),
    )
    # The deadline is already past: nothing is fetched or scored, the name
    # is reported incomplete, and no frame is stored.
    with pytest.raises(RuntimeError, match="incomplete"):
        market_tone._refresh_ticker(
            store,
            "AAA",
            date(2026, 9, 15),
            date(2015, 1, 1),
            [reader],
            "m",
            edgar.Pacer(sleep=lambda s: None),
            deadline=0.0,
        )
    assert fetched == []
    assert scored == []
    assert not store.has_frame(language.TONE_KIND, date(2026, 9, 15), "AAA")
