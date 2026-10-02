"""Exercise price permissions through actual funded research accounting."""

import json
from copy import deepcopy

import numpy as np
import pytest

from backend.market import specialist_timing as timing
from backend.market import specialist_timing_account as funded
from backend.tests.test_open_source_forecast_evaluation import fixture as source_fixture
from backend.tests.test_specialist_timing import future, payload, samples


# Select the common nineteen-session account from the source's longer warm-up history.
def fixture():
    source, _, panel, grades, eligible = source_fixture()
    panel, grades, eligible = funded.frozen.common_panel(
        source, panel, grades, eligible
    )
    return source, None, panel, grades, eligible


# Supply a complete fixed denominator with synthetic paths and separate economic labels.
def cases():
    result = {}
    for session in funded.SESSIONS:
        for symbol in funded.frozen.COHORT:
            raw = payload(session)
            raw["symbol"] = symbol
            prepared = timing.prepare(raw)
            result[session, symbol] = {
                "status": "forecast",
                "prepared": prepared,
                "paths": samples(prepared),
                "future": future(prepared, opening=97),
                "basis": {
                    "status": "available",
                    "decision_input": False,
                    "official_close": 100,
                },
            }
    return result


# Preserve cash, position marks and NAV across the same funded execution ledger.
def test_funded_paths_preserve_account_and_complete_denominator():
    _, _, panel, grades, eligible = fixture()
    account = funded.account(
        panel, grades, eligible, cases(), line="kronos-path", cost_bps=10
    )
    np.testing.assert_allclose(
        account["nav"],
        account["cash"] + (account["positions"] * panel.adj_close).sum(axis=1),
    )
    assert len(account["decisions"]) == 24
    assert np.all(account["cash"] >= 0)
    assert np.all(account["positions"] >= 0)
    assert account["nav"][0] == 1
    assert account["fees"].sum() > 0
    idle = [
        row
        for row in account["decisions"]
        if abs(row["planned_delta_adjusted_units"]) <= 1e-14
    ]
    assert idle
    assert all(row["funded_status"] == "no_intent" for row in idle)
    assert account["fill_proof"] is False
    assert account["no_funding_retry"]


# Intrabar touches and model expiry never create a purchase or a close-price fallback.
def test_missed_permissions_remain_cash():
    _, _, panel, grades, eligible = fixture()
    data = cases()
    for row in data.values():
        row["future"] = future(row["prepared"], opening=100)
    candidate = funded.account(
        panel, grades, eligible, data, line="kronos-path", cost_bps=25
    )
    control = funded.account(
        panel, grades, eligible, data, line="next-open", cost_bps=25
    )
    np.testing.assert_array_equal(candidate["nav"], 1)
    assert control["positions"].sum() > 0
    assert candidate["positions"].sum() == 0
    assert any(row.get("touches_not_fills", 0) for row in candidate["decisions"])


# Missing forecasts retain holdings without inventing liquidation prices.
def test_missing_exit_retains_holdings():
    _, _, panel, grades, eligible = fixture()
    data = cases()
    grades[10] = 0
    for symbol in funded.frozen.COHORT:
        data["2026-09-21", symbol] = {
            "status": "unavailable",
            "reason": "missing_model_evidence",
        }
    candidate = funded.account(
        panel, grades, eligible, data, line="kronos-path", cost_bps=10
    )
    np.testing.assert_array_equal(
        candidate["positions"][10], candidate["positions"][-1]
    )
    assert candidate["positions"][-1].sum() > 0
    assert any(
        row.get("reason") == "missing_model_evidence" for row in candidate["decisions"]
    )


# Label conversion changes economic price units without modifying the causal permission.
def test_label_basis_never_changes_forecast_bound():
    data = cases()["2026-09-04", "NVDA"]
    original = funded.opportunity(data, "NVDA", "2026-09-04", "buy", "2026-09-03", 100)
    changed = deepcopy(data)
    changed["basis"]["official_close"] = 1000
    other = funded.opportunity(changed, "NVDA", "2026-09-04", "buy", "2026-09-03", 100)
    assert original["permission_sha256"] == other["permission_sha256"]
    assert other["adjusted_proxy_price"] == pytest.approx(
        original["adjusted_proxy_price"] / 10
    )
    assert original["unit_probe_not_trade_quantity"]


# Missing opportunities and undeclared price marks cannot disappear from the comparison.
def test_missing_denominator_and_marks_refused():
    _, _, panel, grades, eligible = fixture()
    data = cases()
    del data["2026-09-04", "TSLA"]
    with pytest.raises(ValueError, match="complete fixed timing cohort"):
        funded.account(panel, grades, eligible, data, line="kronos-path", cost_bps=10)
    panel.adj_close[1, 0] = np.nan
    with pytest.raises(ValueError, match="Complete common economic marks"):
        funded.account(
            panel, grades, eligible, cases(), line="kronos-path", cost_bps=10
        )


# An earlier quantity must be independent of prices observed only later.
def test_later_open_does_not_resize_earlier_purchase():
    results = []
    for later_price in (170, 70):
        book = funded.simulate._Book(2, 1, 10, None, None, None)
        events = {
            "2026-09-04T10:00:00-04:00": [(0, 100)],
            "2026-09-04T12:15:00-04:00": [(1, later_price)],
        }
        funded.chronological_fills(
            book, np.array([0.006, 0.006]), events, session=1, line="kronos-path"
        )
        results.append(book.shares[0])
        assert book.cash >= 0
    assert results[0] == results[1] == 0.006


# Same-session sales remain in cash instead of paying for later purchases.
def test_earlier_sales_do_not_finance_later_buys():
    book = funded.simulate._Book(3, 0.2, 10, None, None, None)
    book.shares[0] = 0.01
    events = {
        "2026-09-04T10:00:00-04:00": [(0, 100)],
        "2026-09-04T11:00:00-04:00": [(1, 100)],
        "2026-09-04T12:15:00-04:00": [(2, 100)],
    }
    funded.chronological_fills(
        book, np.array([0, 0.003, 0.003]), events, session=1, line="kronos-path"
    )
    assert book.shares[1] * 100 * (1 + book.cost) == pytest.approx(0.2)
    assert book.shares[2] == 0
    assert book.cash == pytest.approx(0.999)


# The next-open control does not depend on corrupt unused future or model inputs.
def test_next_open_control_ignores_unused_model_and_future_defects():
    _, _, panel, grades, eligible = fixture()
    reference = funded.account(
        panel, grades, eligible, cases(), line="next-open", cost_bps=10
    )
    data = cases()
    for row in data.values():
        row["future"].append(deepcopy(row["future"][0]))
        row["paths"] = None
    observed = funded.account(
        panel, grades, eligible, data, line="next-open", cost_bps=10
    )
    np.testing.assert_array_equal(reference["nav"], observed["nav"])


# An availability-matched control cannot execute before permission observation.
def test_matched_control_fills_after_observation():
    _, _, panel, grades, eligible = fixture()
    result = funded.account(
        panel,
        grades,
        eligible,
        cases(),
        line="available-permission-first-open",
        cost_bps=10,
    )
    fills = [
        row
        for row in result["decisions"]
        if abs(row["executed_adjusted_units"]) > 1e-14
    ]
    assert fills
    assert all(timing.aware(row["proxy_at"]).hour >= 10 for row in fills)


# Reject mutation of frozen input bytes before using their contents.
def test_source_bytes_checked_before_loading(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"source": 1}')
    _, digest = funded.checked_json(path)
    path.write_text('{"source": 2}')
    with pytest.raises(ValueError, match="Timing evidence bytes changed"):
        funded.checked_json(path, digest)


# A full-denominator manifest cannot hide an omitted native forecast record.
def test_loader_refuses_incomplete_native_artifact(tmp_path):
    manifest = tmp_path / "manifest.json"
    basis = tmp_path / "basis.json"
    paths = tmp_path / "paths.json"
    manifest.write_text(json.dumps({"records": []}))
    _, source_hash = funded.checked_json(manifest)
    basis.write_text(json.dumps({"manifest_sha256": source_hash, "records": []}))
    _, basis_hash = funded.checked_json(basis)
    paths.write_text(
        json.dumps(
            {
                "manifest_sha256": source_hash,
                "basis_sha256": basis_hash,
                "checkpoint": funded.asdict(funded.forecasts.CHECKPOINTS["kronos"]),
                "runtime": {
                    "kronos_source_revision": funded.forecasts.CODE_REVISIONS["kronos"]
                },
                "device": "cpu",
                "seeds": list(timing.SEEDS),
                "version": timing.VERSION,
                "price_basis": "raw",
                "target": "remaining_regular_ohlcv_path",
                "records": [],
            }
        )
    )
    with pytest.raises(ValueError, match="All 24 timing opportunities"):
        funded.load_cases(manifest, paths, basis)
