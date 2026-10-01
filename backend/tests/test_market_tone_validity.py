"""The tone-validity arm runner and leak test, on a synthetic book.

What has to hold: every arm is measured on the same cells and the same
rebalance periods, so IC(B) - IC(A) has a paired t; the plan's criteria
fire when they should (a masked re-read that loses the edge reads as
"tone inflated", one that keeps it reads as "incumbent stands"); the
masking step writes what the reader needs and reports no residual year;
the leak score counts a company or year named fuzzily; and the embed step
groups releases by the checkpoint dated before them and keeps row order.
No store, no model, no network: loaders and the embedder are stubbed.
"""

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.cli import market_tone_validity as tv
from backend.market import language, release_mask, release_text, tone_leak
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory

NAMES = 40
SESSIONS = 1500
FIRST = date(2016, 1, 4)
QUARTER = 63
WINDOWS = {
    "in_window": (date(2016, 1, 4), date(2019, 6, 30)),
    "post_window": (date(2019, 7, 1), None),
}


# A history from a daily return series, one bar per calendar day.
def _history(ticker: str, returns: np.ndarray) -> TickerHistory:
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    bars = tuple(
        DailyBar(FIRST + timedelta(days=i), p, p * 1.01, p * 0.99, p, p, 1_000_000)
        for i, p in enumerate(prices)
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# A book where each name's return drifts with the tone of its last
# release, so a tone that is read correctly carries a large IC. Returns
# (panel, sides, tone per (release k, name)).
def _book(seed: int = 3):
    rng = np.random.default_rng(seed)
    releases = SESSIONS // QUARTER + 1
    tone = rng.choice([-1.0, 0.0, 1.0], size=(releases, NAMES))
    drift = np.repeat(tone, QUARTER, axis=0)[:SESSIONS]
    returns = 0.004 * drift + rng.normal(0.0, 0.01, size=(SESSIONS, NAMES))
    histories = {
        f"N{i:03d}": _history(f"N{i:03d}", returns[:, i]) for i in range(NAMES)
    }
    histories["SPY"] = _history("SPY", returns.mean(axis=1))
    panel = panel_from_histories(histories, "SPY", {})
    sides = {f"N{i:03d}": "ai" for i in range(NAMES)}
    return panel, sides, tone


# One tone record with every scored field set to `value`.
def _record(accession: str, when: date, value: float) -> language.ToneRecord:
    return language.ToneRecord(
        accession=accession,
        reaction_date=when,
        guidance=value,
        demand=value,
        pricing=value,
        capex=0.0,
        supply_constrained=0.0,
        summary="",
        model="test",
        prompt_version="release_tone/3",
        truncated=False,
    )


# Tone records per name from a (releases, names) tone matrix, one every
# quarter from the first session.
def _records(tone: np.ndarray) -> dict[str, tuple[language.ToneRecord, ...]]:
    out = {}
    for j in range(tone.shape[1]):
        ticker = f"N{j:03d}"
        out[ticker] = tuple(
            _record(f"{ticker}-{k}", FIRST + timedelta(days=k * QUARTER), tone[k, j])
            for k in range(tone.shape[0])
        )
    return out


# Release vectors whose first column carries the tone, as (records,
# ticker_of, matrix) the way `load_vectors` returns them.
def _vectors(tone: np.ndarray, seed: int = 5):
    rng = np.random.default_rng(seed)
    records, ticker_of, rows = [], {}, []
    for k in range(tone.shape[0]):
        for j in range(tone.shape[1]):
            ticker = f"N{j:03d}"
            accession = f"{ticker}-{k}"
            records.append(
                release_text.ReleaseVector(
                    accession, FIRST + timedelta(days=k * QUARTER), "chrono", ()
                )
            )
            ticker_of[accession] = ticker
            rows.append(np.concatenate([[tone[k, j]], rng.normal(size=7)]))
    return records, ticker_of, np.array(rows, dtype=np.float32)


# A masked re-read that loses the edge: every arm on the same cells, the
# paired t of B - A far below -2, C carrying the tone, verdict inflated.
def test_masked_noise_reads_as_tone_inflated():
    panel, sides, tone = _book()
    tone_a = language.tone_features(panel, _records(tone))
    noise = np.random.default_rng(11).choice([-1.0, 0.0, 1.0], size=tone.shape)
    tone_b = language.tone_features(panel, _records(noise))
    payload = tv.evaluate_arms(
        panel, sides, tone_a, tone_b, _vectors(tone), horizons=(20,), windows=WINDOWS
    )
    inside = payload["horizons"]["20"]["in_window"]
    arms = inside["arms"]
    assert set(arms) == {
        tv.ARM_A,
        tv.ARM_B,
        f"{tv.ARM_C} (lambda 100)",
        f"{tv.ARM_C} (lambda 1000)",
    }
    periods = {tuple(r["period_ics"]) for r in arms.values()}
    assert len(periods) == 1, "every arm is measured on the same rebalance dates"
    assert arms[tv.ARM_A]["periods"] >= 15
    assert arms[tv.ARM_A]["ic"] > 0.3
    assert abs(arms[tv.ARM_B]["ic"]) < 0.15
    assert arms[f"{tv.ARM_C} (lambda 100)"]["ic"] > 0.2
    pair = inside["paired_vs_A"][tv.ARM_B]
    assert pair["delta"] < -0.2
    assert pair["t"] < -2
    assert pair["periods"] >= 15
    crit = payload["criteria"]
    assert crit["1_tone_inflated"]["masked_drop"] is True
    assert crit["1_tone_inflated"]["fires"] is True
    assert crit["2_incumbent_stands"]["fires"] is False
    assert payload["verdict"] == "TONE INFLATED"
    assert payload["horizons"]["20"]["post_window"]["cells"] > 0
    # The tone arms alone are also reported on their own, larger cell set.
    alone = inside["tone_arms_only"]
    assert set(alone["arms"]) == {tv.ARM_A, tv.ARM_B}
    assert alone["cells"] > inside["cells"]
    assert alone["paired_vs_A"][tv.ARM_B]["periods"] > pair["periods"]
    assert json.dumps(payload)  # serialisable as written


# A masked re-read identical to the stored one: no difference, the
# incumbent stands; and with no B or C at all the result is a record.
def test_identical_masked_reread_stands_and_absent_arms_record():
    panel, sides, tone = _book()
    tone_a = language.tone_features(panel, _records(tone))
    payload = tv.evaluate_arms(
        panel, sides, tone_a, tone_a, None, horizons=(20,), windows=WINDOWS
    )
    assert payload["criteria"]["ic_b_minus_a"] == 0.0
    assert "tone_arms_only" not in payload["horizons"]["20"]["in_window"]
    assert payload["criteria"]["2_incumbent_stands"]["within_0.010"] is True
    assert payload["verdict"] == "INCUMBENT STANDS"
    alone = tv.evaluate_arms(
        panel, sides, tone_a, None, None, horizons=(20,), windows=WINDOWS
    )
    crit = alone["criteria"]
    assert crit["1_tone_inflated"]["b_evaluable"] is False
    assert crit["1_tone_inflated"]["c_evaluable"] is False
    assert alone["verdict"] == "RECORD"
    assert crit["3_replacement"]["status"].startswith("not run")


# One window's results with given ICs, for the criteria alone.
def _windows(in_a, post_a, delta_b, t_b, in_c):
    def arm(ic):
        return {"ic": ic, "t": 1.0, "net_sharpe": 0.0, "periods": 3, "period_ics": {}}

    inside = {
        "cells": 1,
        "arms": {tv.ARM_A: arm(in_a), tv.ARM_B: arm(in_a + delta_b)},
        "paired_vs_A": {tv.ARM_B: {"delta": delta_b, "t": t_b, "periods": 30}},
    }
    if in_c is not None:
        inside["arms"][f"{tv.ARM_C} (lambda 100)"] = arm(in_c)
        inside["paired_vs_A"][f"{tv.ARM_C} (lambda 100)"] = {
            "delta": in_c - in_a,
            "t": 0.0,
            "periods": 30,
        }
    post = {"cells": 1, "arms": {tv.ARM_A: arm(post_a)}, "paired_vs_A": {}}
    return {"in_window": inside, "post_window": post}


# The plan's criteria, clause by clause.
@pytest.mark.parametrize(
    ("in_a", "post_a", "delta_b", "t_b", "in_c", "verdict"),
    [
        (0.039, 0.030, -0.020, -2.5, 0.010, "TONE INFLATED"),  # masked drop
        (0.039, -0.005, -0.005, -0.5, 0.010, "TONE INFLATED"),  # post fade
        (0.039, -0.005, -0.005, -0.5, 0.025, "INCUMBENT STANDS"),  # C holds
        (0.039, 0.030, -0.020, -1.0, 0.030, "INCUMBENT STANDS"),  # noise + C half
        (0.039, 0.030, -0.020, -1.0, 0.010, "RECORD"),
        (0.039, 0.030, +0.030, +2.5, 0.010, "RECORD"),  # B better: not stands
    ],
)
def test_criteria(in_a, post_a, delta_b, t_b, in_c, verdict):
    crit = tv.criteria(_windows(in_a, post_a, delta_b, t_b, in_c))
    assert tv.verdict(crit) == verdict


# An arm that beats A in-window is named for the scorecard, which is not run.
def test_replacement_stub_names_the_arm():
    crit = tv.criteria(_windows(0.039, 0.030, +0.030, +2.5, 0.050))
    assert crit["3_replacement"]["arms_beating_a"] == [
        tv.ARM_B,
        f"{tv.ARM_C} (lambda 100)",
    ]
    assert "not run" in crit["3_replacement"]["status"]


# The paired statistic over common, finite periods only.
def test_paired():
    a = {"d1": 0.1, "d2": 0.2, "d3": float("nan"), "d4": 0.0}
    b = {"d1": 0.0, "d2": 0.0, "d3": 0.5, "d5": 1.0}
    out = tv.paired(a, b)
    assert out["periods"] == 2
    assert out["delta"] == pytest.approx(-0.15)
    assert out["t"] == pytest.approx(
        -0.15 / (np.std([-0.1, -0.2], ddof=1) / np.sqrt(2))
    )
    assert np.isnan(tv.paired({"d1": 0.1}, {"d1": 0.1})["t"])


# Masking every stored text writes one file per name, keeps the numbers,
# and reports no residual year; the leak sample is fixed by its seed.
def test_run_mask_and_leak_sample(tmp_path):
    texts = [
        (
            "NVDA",
            release_text.ReleaseText(
                "0001-24",
                date(2024, 8, 29),
                "NVIDIA (NASDAQ: NVDA) reported Q2 fiscal 2025 revenue of $30.0 "
                "billion on August 28, 2024, up 122%.",
                100,
                False,
            ),
        ),
        (
            "NVDA",
            release_text.ReleaseText(
                "0001-23",
                date(2023, 8, 24),
                "NVIDIA's revenue rose in 2023.",
                30,
                False,
            ),
        ),
        (
            "MU",
            release_text.ReleaseText(
                "0002-24",
                date(2024, 1, 5),
                "Micron Technology (MU) grew 5%.",
                30,
                False,
            ),
        ),
    ]
    names = {"NVDA": ("Nvidia",), "MU": ("Micron Technology", "Micron")}
    summary = tv.run_mask(texts, names, tmp_path, {"NVDA": ["NVIDIA Corporation"]})
    assert summary["releases"] == 3
    assert summary["names"] == 2
    assert summary["residual_share"] == {"year": 0.0, "month": 0.0, "name": 0.0}
    assert summary["replacements"]["company"] == 3
    assert summary["min_issuers"] == release_mask.MIN_ISSUERS
    # Two issuers: every considered token is rare, so the share is what the
    # corpus rule would take from these texts, and the list is written.
    assert summary["rare_tokens"] > 0
    assert 0.0 < summary["rare_share_mean"] < 1.0
    rare = json.loads((tmp_path / "rare_tokens.json").read_text())
    assert rare["min_issuers"] == release_mask.MIN_ISSUERS
    assert rare["tokens"]["NASDAQ"] == 1
    rows = tv.read_masked(tmp_path)
    assert [r["accession"] for r in rows] == ["0002-24", "0001-23", "0001-24"]
    nvda = next(r for r in rows if r["accession"] == "0001-24")
    assert "$30.0 billion" in nvda["text"]
    assert "up 122%" in nvda["text"]
    assert "NVIDIA" not in nvda["text"]
    assert "2024" not in nvda["text"]
    assert nvda["residual"] == {"year": 0, "month": 0, "name": 0}
    assert nvda["unescaped"] is True
    assert nvda["tokens"] > 0
    sample = tone_leak.sample_leak(rows, names, 2, seed=0)
    again = tone_leak.sample_leak(rows, names, 2, seed=0)
    assert [s["accession"] for s in sample] == [s["accession"] for s in again]
    assert len(sample) == 2
    assert sample[0]["prompt"].endswith("{company, quarter, year}.")
    assert sample[0]["truth"]["tickers"] == [sample[0]["ticker"]]
    assert sample[0]["truth"]["names"] == list(names[sample[0]["ticker"]])
    assert tone_leak.truth_years(date(2024, 1, 5)) == [2024, 2023]
    assert tone_leak.truth_years(date(2024, 8, 29)) == [2024]


# The leak score: a company named by any distinctive token or ticker, a
# year named in any form, answers as objects or as the model's text, and
# the pass rule at the plan's ceilings.
def test_score_leak():
    sample = [
        {
            "accession": f"a{i}",
            "truth": {
                "names": ["Micron Technology", "Micron"],
                "tickers": ["MU"],
                "years": [2024],
            },
        }
        for i in range(20)
    ]
    answers = {
        "a0": {"company": "micron", "quarter": "Q2", "year": "FY2024"},
        "a1": 'The company is MU Inc. {"company": "MU", "year": "24"}',
        "a2": {"company": "Technology Corp", "year": 2019},  # generic word: no hit
        "a3": {"company": "Unknown", "year": "2024"},
    }
    for i in range(4, 20):
        answers[f"a{i}"] = {"company": "unknown", "quarter": "", "year": "1999"}
    result = tone_leak.score_leak(sample, answers)
    assert result["answered"] == 20
    assert result["company_hits"] == 2
    assert result["year_hits"] == 3
    assert result["company_share"] == pytest.approx(0.10)
    assert result["year_share"] == pytest.approx(0.15)
    assert result["pass"] is False
    for i in range(3):
        answers[f"a{i}"] = {"company": "?", "year": "?"}
    answers["a3"] = {"company": "?", "year": "?"}
    passed = tone_leak.score_leak(sample, answers)
    assert passed["company_hits"] == 0
    assert passed["year_hits"] == 0
    assert passed["pass"] is True
    assert tone_leak.score_leak(sample, {})["answered"] == 0
    assert tone_leak.score_leak(sample, {})["pass"] is False
    assert tone_leak.answer_year("fiscal 2025") == 2025
    assert tone_leak.answer_year("Q3 '24") == 2024
    assert tone_leak.answer_year(None) is None


# The embed step groups by the checkpoint dated before each release,
# keeps row order within and across groups, skips releases before the
# first cutoff, and its file reads back into what `evaluate_arms` takes.
def test_run_embed_groups_by_checkpoint(tmp_path):
    calls = []

    def embedder(texts, model_dir, device):
        calls.append((model_dir, device, list(texts)))
        return np.array([[len(t), 1.0] for t in texts], dtype=np.float32)

    texts = [
        ("A", release_text.ReleaseText("a-1", date(2014, 6, 1), "old", 3, False)),
        ("A", release_text.ReleaseText("a-2", date(2016, 5, 1), "sixteen", 7, False)),
        ("B", release_text.ReleaseText("b-1", date(2015, 3, 1), "fifteen", 7, False)),
        ("B", release_text.ReleaseText("b-2", date(2016, 12, 31), "late", 4, False)),
    ]
    arrays = tv.run_embed(texts, tmp_path / "models", "cpu", embedder=embedder)
    assert [c[0] for c in calls] == [
        str(tmp_path / "models" / "chrono-bert-v1-20141231"),
        str(tmp_path / "models" / "chrono-bert-v1-20151231"),
    ]
    assert calls[0][2] == ["fifteen"]
    assert calls[1][2] == ["sixteen", "late"]
    assert list(arrays["accessions"]) == ["b-1", "a-2", "b-2"]
    assert list(arrays["tickers"]) == ["B", "A", "B"]
    assert list(arrays["checkpoints"]) == [
        "chrono-bert-v1-20141231",
        "chrono-bert-v1-20151231",
        "chrono-bert-v1-20151231",
    ]
    np.testing.assert_array_equal(arrays["vectors"][:, 0], [7.0, 7.0, 4.0])
    np.savez(tmp_path / "vec.npz", **arrays)
    records, ticker_of, matrix = tv.load_vectors(tmp_path / "vec.npz")
    assert [r.accession for r in records] == ["b-1", "a-2", "b-2"]
    assert records[1].reaction_date == date(2016, 5, 1)
    assert ticker_of == {"b-1": "B", "a-2": "A", "b-2": "B"}
    assert matrix.shape == (3, 2)
    assert matrix.dtype == np.float32


# The masked re-score is read from partial-style JSONL when no frame exists.
def test_load_masked_tone_from_jsonl(tmp_path):
    panel, _sides, tone = _book()
    records = _records(tone)
    for ticker in ("N000", "N001"):
        for record in records[ticker]:
            language.append_partial(tmp_path / f"{ticker}.jsonl", record)
    block = tv.load_masked_tone(tmp_path, panel)
    has = language.FEATURE_NAMES.index("has_tone")
    assert block is not None
    assert block.shape[:2] == (len(panel.dates), NAMES + 1)
    assert block[-1, panel.index("N000"), has] == 1.0
    assert block[-1, panel.index("N002"), has] == 0.0
    assert tv.load_masked_tone(tmp_path / "empty", panel) is None


# The book's issuer names come from the universe file.
def test_issuer_names_cover_the_book():
    names = tv.issuer_names()
    assert names["NVDA"]
    assert names["MU"]
    assert "SPY" not in names
    # Both the constituent file's name and the overlay's are kept.
    assert set(names["SMCI"]) == {"Supermicro", "Super Micro"}
