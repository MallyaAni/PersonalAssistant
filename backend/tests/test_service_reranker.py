"""The service adapter must keep the local cross-encoder's promises.

Everything downstream of RerankProvider was calibrated on log-odds: the
attribution margin, the negative-score seeding, the strength rule. These pin
the two places the adapter could quietly break that - the probability-to-
log-odds conversion and the regrouping of arbitrary pairs into per-query
requests - plus the raise-on-malfunction contract PrecisionRanker relies on
to keep the embedding order.
"""

import json

import httpx
import pytest

from backend.config.settings import settings
from backend.embeddings.service_reranker import ServiceCrossEncoder, _log_odds


def _service(handler) -> ServiceCrossEncoder:
    return ServiceCrossEncoder(transport=httpx.MockTransport(handler))


def test_log_odds_restores_the_logit_scale():
    assert _log_odds(0.5) == pytest.approx(0.0)
    assert _log_odds(0.9) > 0 > _log_odds(0.1)
    # Saturated probabilities stay finite and ordered.
    assert _log_odds(1.0) > _log_odds(0.999) > 0
    assert _log_odds(0.0) < _log_odds(0.001) < 0


def test_pairs_are_grouped_by_query_and_scores_land_by_position(monkeypatch):
    monkeypatch.setattr(settings, "RERANKER_BASE_URL", "http://reranker")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        # Score each document by its stated relevance digit, reversed from
        # arrival order so alignment by index is actually exercised.
        results = [
            {"index": index, "relevance_score": float(document[-1]) / 10}
            for index, document in reversed(list(enumerate(payload["documents"])))
        ]
        return httpx.Response(200, json={"results": results})

    scores = _service(handler).score(
        [
            ("hiking profile", "trail day 9"),
            ("jazz profile", "quartet night 8"),
            ("hiking profile", "car expo 1"),
        ]
    )
    # Two distinct queries, two requests - not three.
    assert [payload["query"] for payload in seen] == [
        "hiking profile",
        "jazz profile",
    ]
    assert seen[0]["documents"] == ["trail day 9", "car expo 1"]
    # Scores return to the original pair positions, in log-odds.
    assert scores[0] == pytest.approx(_log_odds(0.9))
    assert scores[1] == pytest.approx(_log_odds(0.8))
    assert scores[2] == pytest.approx(_log_odds(0.1))
    assert scores[0] > scores[2]


def test_a_short_count_raises_rather_than_ranking(monkeypatch):
    monkeypatch.setattr(settings, "RERANKER_BASE_URL", "http://reranker")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"index": 0, "relevance_score": 0.5}]}
        )

    with pytest.raises(ValueError):
        _service(handler).score([("q", "one"), ("q", "two")])


def test_an_http_error_raises_rather_than_ranking(monkeypatch):
    monkeypatch.setattr(settings, "RERANKER_BASE_URL", "http://reranker")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(httpx.HTTPStatusError):
        _service(handler).score([("q", "one")])


def test_no_base_url_means_disabled(monkeypatch):
    monkeypatch.setattr(settings, "RERANKER_BASE_URL", " ")
    assert ServiceCrossEncoder().is_enabled() is False
