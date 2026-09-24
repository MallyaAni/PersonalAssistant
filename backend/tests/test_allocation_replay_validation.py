"""Fail-closed input and source-binding boundaries for the research adapter.

Execution, allocation transitions and causality live in test_allocation_replay.
These tiny synthetic fixtures exercise type/shape refusal, source ownership and
invalid ledger-state rejection without fitting models or rerunning any study.
"""

from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.market import allocation_replay as allocation
from backend.market.panel import Panel
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot


# Supply a complete four-session source with both index sleeves and two stocks.
def _case():
    dates = np.array(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        dtype="datetime64[D]",
    )
    prices = np.full((4, 4), 100.0)
    panel = Panel(
        dates=dates,
        tickers=("AAA", "BBB", "SPY", "QQQ"),
        open=prices.copy(),
        high=prices.copy(),
        low=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
        volume=np.full_like(prices, 1000),
        themes={},
        benchmark="SPY",
    )
    rows = [
        allocation.AllocationInstruction(
            session=str(session),
            information_through=str(session),
            evidence_id=f"synthetic-{session}",
            stock_scale=0.5,
            spy_weight=0.0,
            qqq_weight=0.0,
            stock_weights={"AAA": 0.6, "BBB": 0.4} if index == 0 else None,
        )
        for index, session in enumerate(dates[:-1])
    ]
    return panel, rows


# Construct a real recorder with exact source copies, never a mock execution ledger.
def _journal(panel, **overrides):
    values = {
        "sessions": panel.dates,
        "symbols": panel.tickers,
        "opens": simulate.adjusted_open(panel),
        "closes": panel.adj_close,
        "cost_bps": 10.0,
    }
    values.update(overrides)
    return ResearchJournal(
        **values,
        run_id="allocation-validation",
        account_id="synthetic",
        policy_id=allocation.EXECUTION_POLICY,
        provenance={"evidence_basis": "synthetic-boundary-test"},
    )


# Reject malformed calendars before interpreting any instruction as an allocation.
@pytest.mark.parametrize(
    "dates",
    [
        np.array([], dtype="datetime64[D]"),
        np.array(["2024-01-02"], dtype="datetime64[D]"),
        np.array([["2024-01-02", "2024-01-03"]]),
        np.array(["2024-01-03", "2024-01-02", "2024-01-04", "2024-01-05"]),
        np.array(["2024-01-02", "2024-01-02", "2024-01-04", "2024-01-05"]),
        np.array(["2024-01-02T16:00:00"] * 4),
        np.array(["2024-13-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        np.array([20240102, 20240103, 20240104, 20240105]),
        np.array([True, False, True, False]),
    ],
)
def test_source_calendar_requires_ordered_unique_plain_dates(dates):
    panel, rows = _case()
    with pytest.raises(ValueError, match="calendar|source session"):
        allocation.replay(replace(panel, dates=dates), rows)


# Keep symbol identity explicit, unique, well formed and inclusive of both indexes.
@pytest.mark.parametrize(
    "symbols",
    [
        (),
        ("AAA", "BBB", "SPY"),
        ("AAA", "BBB", "QQQ"),
        ("AAA", "AAA", "SPY", "QQQ"),
        (" AAA", "BBB", "SPY", "QQQ"),
        ("AAA", "BBB ", "SPY", "QQQ"),
        ("", "BBB", "SPY", "QQQ"),
        (None, "BBB", "SPY", "QQQ"),
        (True, "BBB", "SPY", "QQQ"),
        (42, "BBB", "SPY", "QQQ"),
    ],
)
def test_source_symbols_cannot_be_missing_duplicated_or_coerced(symbols):
    panel, rows = _case()
    with pytest.raises(ValueError, match="symbols.*SPY.*QQQ"):
        allocation.replay(replace(panel, tickers=symbols), rows)


# Only an ordered symbol sequence can bind security identity to price columns.
@pytest.mark.parametrize("kind", ["set", "frozenset", "dict", "string", "bytes"])
def test_symbol_containers_cannot_silently_define_an_ambiguous_column_order(kind):
    panel, rows = _case()
    if kind == "set":
        symbols = set(panel.tickers)
    elif kind == "frozenset":
        symbols = frozenset(panel.tickers)
    elif kind == "dict":
        symbols = dict.fromkeys(panel.tickers)
    elif kind == "string":
        symbols = "AAABBBSPYQQQ"
    else:
        symbols = b"AAABBBSPYQQQ"
    with pytest.raises(ValueError, match="symbols|tickers|ordered|sequence"):
        allocation.replay(replace(panel, tickers=symbols), rows)


# Explicit list and tuple order bind identical prices, instructions and accounts.
@pytest.mark.parametrize("container", [list, tuple])
def test_explicit_symbol_sequence_order_is_preserved(container):
    panel, rows = _case()
    plain = allocation.replay(panel, rows)
    ordered = replace(panel, tickers=container(panel.tickers))
    observed = allocation.replay(ordered, rows)
    np.testing.assert_array_equal(observed["nav"], plain["nav"])
    np.testing.assert_array_equal(observed["positions"], plain["positions"])
    assert observed["instruction_path"] == plain["instruction_path"]


# Refuse every price matrix that is not aligned to the entire source grid.
@pytest.mark.parametrize("field", ["open", "close", "adj_close"])
@pytest.mark.parametrize("shape", [(), (4,), (3, 4), (4, 3), (4, 4, 1)])
def test_source_price_matrices_require_the_full_two_dimensional_grid(field, shape):
    panel, rows = _case()
    with pytest.raises(ValueError, match="source|prices|shape|grid"):
        allocation.replay(replace(panel, **{field: np.full(shape, 100.0)}), rows)


# Do not silently coerce text/objects or discard imaginary parts of source prices.
@pytest.mark.parametrize("field", ["open", "close", "adj_close"])
@pytest.mark.parametrize("dtype", [bool, str, object, complex])
def test_source_price_matrices_reject_non_real_numeric_dtypes(field, dtype):
    panel, rows = _case()
    values = np.full((4, 4), 100.0, dtype=dtype)
    if dtype is complex:
        values += 7j
    with pytest.raises(ValueError, match="real|numeric|source|prices"):
        allocation.replay(replace(panel, **{field: values}), rows)


# Real integer and floating-point matrices remain accepted without coercion tricks.
@pytest.mark.parametrize("dtype", [np.int64, np.float32, np.float64])
def test_source_price_matrices_accept_real_numeric_arrays(dtype):
    panel, rows = _case()
    panel = replace(
        panel,
        open=panel.open.astype(dtype),
        close=panel.close.astype(dtype),
        adj_close=panel.adj_close.astype(dtype),
    )
    result = allocation.replay(panel, rows)
    assert np.isfinite(result["nav"]).all()


# Explicit numeric missing cells are not invalid dtype or an instruction to invest.
def test_unused_numeric_nan_prices_are_preserved_without_blocking_the_account():
    panel, rows = _case()
    for prices in (panel.open, panel.close, panel.adj_close):
        prices[:, 3] = np.nan
    result = allocation.replay(panel, rows)
    assert np.isfinite(result["nav"]).all()
    assert np.all(result["positions"][:, 3] == 0)


# Index arguments are integers, not booleans, strings or silently truncated numbers.
@pytest.mark.parametrize("first", [True, False, np.bool_(True), 1.0, "1", None, np.nan])
def test_first_source_index_has_a_strict_integer_type(first):
    panel, rows = _case()
    with pytest.raises(ValueError, match="first"):
        allocation.replay(panel, rows, first=first)


# Numeric account settings cannot disguise booleans, strings or nonfinite numbers.
@pytest.mark.parametrize("field", ["cost_bps", "start_equity"])
@pytest.mark.parametrize(
    "value", [True, np.bool_(False), "10", None, 1j, np.nan, np.inf, -np.inf]
)
def test_cost_and_initial_equity_require_finite_real_numbers(field, value):
    panel, rows = _case()
    with pytest.raises(ValueError, match=field):
        allocation.replay(panel, rows, **{field: value})


# Instructions must be a materialized sequence of the explicit instruction type.
@pytest.mark.parametrize("kind", ["mapping", "iterator", "dictionary_row", "none_row"])
def test_instruction_container_and_row_types_are_not_inferred(kind):
    panel, rows = _case()
    if kind == "mapping":
        supplied = {row.session: row for row in rows}
    elif kind == "iterator":
        supplied = iter(rows)
    elif kind == "dictionary_row":
        supplied = [{"session": rows[0].session}, *rows[1:]]
    else:
        supplied = [None, *rows[1:]]
    with pytest.raises(ValueError, match="instruction"):
        allocation.replay(panel, supplied)


# Rebalance intent is an explicit Boolean rather than truthiness of another value.
@pytest.mark.parametrize("value", [0, 1, "false", None, np.bool_(True)])
def test_rebalance_does_not_coerce_non_boolean_values(value):
    panel, rows = _case()
    rows[0] = replace(rows[0], rebalance=value)
    with pytest.raises(ValueError, match="rebalance"):
        allocation.replay(panel, rows)


# Every sleeve multiplier or index weight is independently finite and bounded.
@pytest.mark.parametrize("field", ["stock_scale", "spy_weight", "qqq_weight"])
@pytest.mark.parametrize(
    "value",
    [True, np.bool_(False), "0.5", None, 1j, np.nan, np.inf, -np.inf, -0.1, 1.1],
)
def test_sleeve_values_refuse_bad_types_and_individual_range_violations(field, value):
    panel, rows = _case()
    rows[0] = replace(rows[0], **{field: value})
    with pytest.raises(ValueError, match="stock|scale|index|weight|finite"):
        allocation.replay(panel, rows)


# A stock weight obeys the same real, finite, long-only bounds as sleeve weights.
@pytest.mark.parametrize(
    "value",
    [True, np.bool_(False), "0.5", None, 1j, np.nan, np.inf, -np.inf, -0.1, 1.1],
)
def test_stock_weight_values_cannot_be_coerced_or_oversubscribed(value):
    panel, rows = _case()
    rows[0] = replace(rows[0], stock_weights={"AAA": value})
    with pytest.raises(ValueError, match="stock|weight|finite"):
        allocation.replay(panel, rows)


# Missing composition is distinct from malformed containers pretending to be a basket.
@pytest.mark.parametrize("value", [True, 0.0, [], [("AAA", 1.0)], "AAA"])
def test_stock_composition_requires_a_mapping_when_supplied(value):
    panel, rows = _case()
    rows[0] = replace(rows[0], stock_weights=value)
    with pytest.raises(ValueError, match="stock_weights.*mapping"):
        allocation.replay(panel, rows)


# Provenance identities remain actual text rather than stringified arbitrary values.
@pytest.mark.parametrize("value", [None, False, 7])
def test_evidence_id_rejects_non_string_values(value):
    panel, rows = _case()
    rows[0] = replace(rows[0], evidence_id=value)
    with pytest.raises(ValueError, match="evidence_id"):
        allocation.replay(panel, rows)


# Date-only declarations cannot silently truncate a timestamp or coerce a Boolean.
@pytest.mark.parametrize("value", ["2024-01-02T12:00:00", True, 20240102])
def test_information_boundary_requires_plain_daily_precision(value):
    panel, rows = _case()
    rows[0] = replace(rows[0], information_through=value)
    with pytest.raises(ValueError, match="information_through"):
        allocation.replay(panel, rows)


# A journal with another calendar, symbol order, prices or fee schedule is refused.
@pytest.mark.parametrize("mismatch", ["calendar", "symbols", "opens", "closes", "cost"])
def test_optional_journal_must_match_every_bound_source_input(mismatch):
    panel, rows = _case()
    overrides = {}
    if mismatch == "calendar":
        overrides["sessions"] = panel.dates + np.timedelta64(10, "D")
    elif mismatch == "symbols":
        overrides["symbols"] = ("BBB", "AAA", "SPY", "QQQ")
    elif mismatch in ("opens", "closes"):
        prices = panel.open.copy()
        prices[1, 0] += 1
        overrides[mismatch] = prices
    else:
        overrides["cost_bps"] = 25.0
    journal = _journal(panel, **overrides)
    with pytest.raises(ValueError, match="Journal.*producer inputs"):
        allocation.replay(panel, rows, journal=journal)
    assert journal.snapshot()["events"] == []


# Source and instruction copies survive caller changes after journal binding.
def test_original_input_mutation_during_open_cannot_rewrite_execution_or_path(
    monkeypatch,
):
    panel, rows = _case()
    plain = allocation.replay(panel, rows)
    journal = _journal(panel)
    original_open = journal.open_account

    # Change only caller-owned originals after the adapter and recorder took copies.
    def mutate_original_inputs(session, cash, positions):
        original_open(session, cash, positions)
        panel.dates[:] += np.timedelta64(30, "D")
        panel.open[:] *= 3
        panel.close[:] *= 5
        panel.adj_close[:] *= 7
        rows[0].stock_weights.clear()

    monkeypatch.setattr(journal, "open_account", mutate_original_inputs)
    observed = allocation.replay(panel, rows, journal=journal)
    for name in (
        "dates",
        "nav",
        "cash",
        "cash_fraction",
        "positions",
        "fees",
        "turnover",
    ):
        np.testing.assert_array_equal(observed[name], plain[name])
    assert observed["decisions"] == plain["decisions"]
    assert observed["instruction_path"] == plain["instruction_path"]
    snapshot = journal.snapshot()
    assert snapshot["prices"]["open"] == [[100.0] * 4] * 4
    assert snapshot["prices"]["close"] == [[100.0] * 4] * 4
    assert all(
        event["metadata"]["instruction_path_sha256"]
        == plain["instruction_path"]["sha256"]
        for event in snapshot["events"]
        if event["type"] == "decision"
    )
    replayed = verify_snapshot(snapshot)
    assert replayed["ok"], replayed["errors"]


# Refuse nonfinite or negative state even if the ledger returns without error.
@pytest.mark.parametrize("field", ["cash", "shares", "traded"])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, -0.1])
def test_post_fill_invalid_account_state_cannot_escape_as_a_result(
    monkeypatch, field, value
):
    panel, rows = _case()
    original_fill = simulate._Book._fill

    # Exercise the real fill first, then inject the state a producer guard must reject.
    def corrupt_after_fill(book, *args, **kwargs):
        original_fill(book, *args, **kwargs)
        if field == "shares":
            book.shares[0] = value
        else:
            setattr(book, field, value)

    monkeypatch.setattr(simulate._Book, "_fill", corrupt_after_fill)
    with pytest.raises(ValueError, match="account|cash|units|traded|state|NAV"):
        allocation.replay(panel, rows)
