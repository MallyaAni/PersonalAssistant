"""Raw conversion uses dated splits and preserves unsupported execution inputs."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from backend.market import live_execution_inputs as adapter
from backend.market.panel import Panel
from backend.market.sip_cube import SessionCube


# Supply matching split-adjusted daily and unconverted raw intraday prices.
def inputs():
    dates = np.array(["2026-09-14", "2026-09-15"], dtype="datetime64[D]")
    daily = np.full((2, 2), 50.0)
    panel = Panel(
        dates,
        ("AAA", "SPY"),
        daily.copy(),
        daily + 1,
        daily - 1,
        daily.copy(),
        daily - 2,
        np.ones_like(daily),
        {},
        "SPY",
    )
    cube = cube_fixture("AAA", dates, [100.0, 50.0])
    return dict(
        panel=panel,
        grades=np.array([[2, 0], [3, 0]], dtype=np.int16),
        eligible=np.ones((2, 2), dtype=bool),
        cubes={"AAA": cube},
        actions={
            "AAA": [{"date": "2026-09-15", "kind": "split", "value": 2.0}],
            "SPY": [],
        },
        basis_as_of={"AAA": "2026-09-15", "SPY": "2026-09-15"},
        complete_through={"AAA": "2026-09-15", "SPY": "2026-09-15"},
        dividend_price_basis="raw_ex_date_share_dollars",
        provenance={
            "daily_source": "synthetic-original",
            "actions_source": "synthetic-dated",
        },
    )


# Supply passive prices separately from the original stock-selection universe.
def passive_fixture(args):
    dates = args["panel"].dates
    return adapter.prepare_passive(
        dates,
        args["panel"].tickers,
        ("CHILD",),
        np.full((len(dates), 1), 20.0),
        np.full((len(dates), 26, 1), 21.0),
        np.full((len(dates), 1), 22.0),
        first_session=str(dates[0]),
        complete_through=str(dates[-1]),
        provenance={"source": "synthetic_raw_passive_history"},
        price_basis=adapter.CUBE_BASIS,
    )


# Inherited assets never become new candidates or alter original execution inputs.
def test_passive_prices_preserve_selection_grades_and_execution_arrays():
    args = inputs()
    original = adapter.prepare(**args)
    args["passive"] = passive_fixture(args)
    result = adapter.prepare(**args)
    assert result.tickers == original.tickers
    assert "CHILD" not in result.tickers
    for field in (
        "grades",
        "eligible",
        "daily_close",
        "observation_close",
        "next_open",
    ):
        np.testing.assert_array_equal(getattr(result, field), getattr(original, field))
    assert result.passive.tickers == ("CHILD",)
    assert not result.passive.daily_close.flags.writeable
    assert (
        result.passive.provenance["use"] == "valuation_only_not_selection_or_execution"
    )
    assert "passive_provenance" not in original.provenance


# Only an explicitly supplied passive history can cover an inherited child security.
def test_distribution_child_can_be_covered_without_joining_selection_universe():
    args = inputs()
    args["actions"]["AAA"] = [
        {
            "date": "2026-09-15",
            "kind": "stock_distribution",
            "child": "CHILD",
            "numerator": 1,
            "denominator": 3,
            "parent_basis_fraction": 0.75,
            "basis_available_at": "2026-09-14T16:01:00-04:00",
            "fractional_policy": "cash_in_lieu_unknown",
            "share_basis": "post_split_action_date_shares",
            "source_receipt": {"source": "synthetic_declared_entitlement"},
        }
    ]
    with pytest.raises(ValueError, match="Covered child"):
        adapter.prepare(**args)
    args["passive"] = passive_fixture(args)
    result = adapter.prepare(**args)
    assert result.actions["AAA"][0]["child"] == "CHILD"
    assert result.tickers == ("AAA", "SPY")
    assert set(result.actions) == {"AAA", "SPY"}


# Refuse passive price reuse across sessions, selection names, altered bytes and units.
@pytest.mark.parametrize(
    "defect", ["overlap", "identity", "dates", "mutable", "bytes", "units"]
)
def test_passive_contract_rejects_unaligned_or_changed_inputs(defect):
    args = inputs()
    passive = passive_fixture(args)
    if defect == "overlap":
        passive = replace(passive, tickers=("AAA",))
    elif defect == "identity":
        passive = replace(passive, tickers=("ANOTHER_CHILD",))
    elif defect == "dates":
        passive = replace(passive, dates=passive.dates + np.timedelta64(1, "D"))
    elif defect in ("mutable", "bytes"):
        closing = passive.daily_close.copy()
        if defect == "bytes":
            closing[0, 0] = 999
            closing.flags.writeable = False
        passive = replace(passive, daily_close=closing)
    else:
        passive = replace(
            passive, provenance={**passive.provenance, "price_basis": "adjusted"}
        )
    args["passive"] = passive
    with pytest.raises(ValueError, match="passive"):
        adapter.prepare(**args)


# Coverage boundaries preserve delisting and missing marks without forward filling.
def test_passive_factory_rejects_prices_past_declared_terminal_session():
    args = inputs()
    with pytest.raises(ValueError, match="outside declared coverage"):
        adapter.prepare_passive(
            args["panel"].dates,
            args["panel"].tickers,
            ("CHILD",),
            np.full((2, 1), 20.0),
            np.full((2, 26, 1), 21.0),
            np.full((2, 1), 22.0),
            first_session="2026-09-14",
            complete_through="2026-09-14",
            provenance={"source": "synthetic"},
            price_basis=adapter.CUBE_BASIS,
        )


# Reject extended-hours data in slots after the exchange's actual early close.
def test_passive_factory_uses_reviewed_early_close_grid():
    dates = np.array(["2026-11-27"], dtype="datetime64[D]")
    bars = np.full((1, 26, 1), np.nan)
    bars[:, :14] = 20
    kwargs = dict(
        first_session="2026-11-27",
        complete_through="2026-11-27",
        provenance={"source": "synthetic"},
        price_basis=adapter.CUBE_BASIS,
    )
    adapter.prepare_passive(dates, ("AAA",), ("CHILD",), [[19]], bars, [[21]], **kwargs)
    bars[0, 14, 0] = 20
    with pytest.raises(ValueError, match="extended-hours"):
        adapter.prepare_passive(
            dates, ("AAA",), ("CHILD",), [[19]], bars, [[21]], **kwargs
        )


# Supply original archive bytes separately from reviewed economic declarations.
def reviewed_action_fixture():
    original = {
        "actions": {
            "AAA": [{"date": "2026-09-15", "kind": "split", "value": 2}],
            "SPY": [{"date": "2026-09-14", "kind": "dividend", "value": 0.2}],
        }
    }
    raw = json.dumps(original).encode()
    review = {
        "schema": "actual-policy-action-semantics/1",
        "original_actions_sha256": hashlib.sha256(raw).hexdigest(),
        "adoption_eligible": False,
        "first_session": "2026-09-14",
        "last_session": "2026-09-15",
        "events": [
            {
                "symbol": "AAA",
                "date": "2026-09-15",
                "archive_factor": 2,
                "classification": "same_security_split",
                "numerator": 2,
                "denominator": 1,
                "source": "https://issuer.example/synthetic-declaration",
            }
        ],
    }
    return raw, review


# Recover prices once while granting only separately declared economic shares.
def test_reviewed_split_separates_archive_and_share_units_without_double_adjustment():
    original, review = reviewed_action_fixture()
    result = adapter.review_action_export(original, json.dumps(review).encode())
    assert result["reviewed_events"] == 1
    assert result["unresolved"] == ()
    assert result["adoption_eligible"] is False
    assert result["execution_readiness"] == "pending_declaration_receipts"
    assert [row["kind"] for row in result["actions"]["AAA"]] == [
        "archive_adjustment",
        "share_split",
    ]
    args = inputs()
    args["actions"] = result["actions"]
    args["dividend_price_basis"] = "split_adjusted_archive_share_dollars"
    raw = adapter.prepare(**args)
    np.testing.assert_array_equal(raw.daily_close[:, 0], [100, 50])
    assert raw.actions["SPY"][0]["value"] == 0.2
    assert raw.actions["AAA"][1]["review_event"]["source"].startswith("https://")
    with pytest.raises(TypeError):
        result["actions"]["AAA"][1]["review_event"]["numerator"] = 99
    assert json.loads(original)["actions"]["AAA"][0]["kind"] == "split"


# Keep spin-offs and exchanges unresolved instead of granting archive-factor shares.
@pytest.mark.parametrize(
    "classification", ["security_distribution", "security_exchange"]
)
def test_review_retains_unresolved_economic_entitlements(classification):
    original, review = reviewed_action_fixture()
    review["events"][0].update(
        classification=classification, numerator=1, denominator=3, child="CHILD"
    )
    result = adapter.review_action_export(original, json.dumps(review).encode())
    assert result["execution_readiness"] == "incomplete"
    assert result["unresolved"][0]["review_event"]["child"] == "CHILD"
    assert [row["kind"] for row in result["actions"]["AAA"]] == [
        "archive_adjustment",
        "unresolved_entitlement",
    ]
    args = inputs()
    args["actions"] = result["actions"]
    with pytest.raises(ValueError, match="Explicit split/dividend units"):
        adapter.prepare(**args)


# A declared issuer exchange changes economic shares but does not rescale prices twice.
def test_reviewed_named_exchange_separates_price_factor_and_security_identity():
    original, review = reviewed_action_fixture()
    source = json.loads(original)
    source["actions"]["AAA"][0]["value"] = 0.2
    original = json.dumps(source).encode()
    review["original_actions_sha256"] = hashlib.sha256(original).hexdigest()
    review["events"][0].update(
        classification="security_exchange",
        archive_factor=0.2,
        numerator=1,
        denominator=5,
        old_security_id="old",
        new_security_id="new",
        fractional_policy="floor_no_compensation",
        terms_available_on="2026-09-13",
        fractional_source="https://issuer.example/synthetic-holder-terms",
    )
    result = adapter.review_action_export(original, json.dumps(review).encode())
    assert result["unresolved"] == ()
    assert [row["kind"] for row in result["actions"]["AAA"]] == [
        "archive_adjustment",
        "security_exchange",
    ]
    args = inputs()
    args["actions"] = result["actions"]
    raw = adapter.prepare(**args)
    np.testing.assert_array_equal(raw.daily_close[:, 0], [10, 50])
    assert raw.actions["AAA"][1]["old_security_id"] == "old"
    assert raw.actions["AAA"][1]["new_security_id"] == "new"
    combined = dict(result["actions"])
    combined["AAA"] = (
        *combined["AAA"],
        {"date": "2026-09-15", "kind": "share_split", "value": 2},
    )
    args["actions"] = combined
    with pytest.raises(ValueError, match="additional entitlement ordering"):
        adapter.prepare(**args)
    review["events"][0]["terms_available_on"] = "2026-09-15"
    with pytest.raises(ValueError, match="prior-day declaration"):
        adapter.review_action_export(original, json.dumps(review).encode())


# Legacy combined splits cannot be paired with a second economic share grant.
def test_legacy_split_plus_separate_share_grant_is_rejected():
    args = inputs()
    args["actions"]["AAA"].append(
        {"date": "2026-09-15", "kind": "share_split", "value": 2}
    )
    with pytest.raises(ValueError, match="duplicate entitlements"):
        adapter.prepare(**args)


# Reverse splits cannot retain tradable fractional securities without venue evidence.
def test_reverse_split_fractional_processing_is_not_inferred_from_ratio():
    _, review = reviewed_action_fixture()
    original = json.dumps(
        {"actions": {"AAA": [{"date": "2026-09-15", "kind": "split", "value": 1 / 6}]}}
    ).encode()
    review["original_actions_sha256"] = hashlib.sha256(original).hexdigest()
    review["events"][0].update(archive_factor=1 / 6, numerator=1, denominator=6)
    result = adapter.review_action_export(original, json.dumps(review).encode())
    assert result["unresolved"][0]["reason"] == "fractional_share_payment_unresolved"
    assert not any(row["kind"] == "share_split" for row in result["actions"]["AAA"])


# Supply sourced consolidation terms independently of the archive price factor.
def consolidation_fixture():
    return {
        "date": "2026-09-15",
        "kind": "share_consolidation",
        "numerator": 1,
        "denominator": 6,
        "effective_at": "2026-09-14T16:15:00-04:00",
        "fractional_policy": "cash_in_lieu_unknown",
        "effective_source": "https://issuer.example/synthetic-clock",
        "fractional_source": "https://issuer.example/synthetic-cash-terms",
        "source_receipt": {"declaration": "synthetic"},
    }


# Preserve raw price recovery while dispatching the separately dated cash entitlement.
def test_reviewed_consolidation_does_not_adjust_prices_twice():
    _, review = reviewed_action_fixture()
    original = json.dumps(
        {
            "actions": {
                "AAA": [{"date": "2026-09-15", "kind": "split", "value": 1 / 6}],
                "SPY": [],
            }
        }
    ).encode()
    review["original_actions_sha256"] = hashlib.sha256(original).hexdigest()
    review["events"][0].update(
        **{
            key: value
            for key, value in consolidation_fixture().items()
            if key not in ("kind", "source_receipt")
        },
        archive_factor=1 / 6,
    )
    result = adapter.review_action_export(original, json.dumps(review).encode())
    assert result["unresolved"] == ()
    assert [row["kind"] for row in result["actions"]["AAA"]] == [
        "archive_adjustment",
        "share_consolidation",
    ]
    args = inputs()
    args["actions"] = result["actions"]
    raw = adapter.prepare(**args)
    np.testing.assert_allclose(raw.daily_close[:, 0], [50 / 6, 50])
    assert raw.actions["AAA"][1]["effective_at"] == "2026-09-14T16:15:00-04:00"
    assert raw.split_factors[0, 0] == 1 / 6
    assert json.loads(original)["actions"]["AAA"][0]["kind"] == "split"


# Unknown clocks, duplicate share actions and delayed application never pass preflight.
@pytest.mark.parametrize(
    "defect",
    [
        "naive",
        "intraday",
        "late_day",
        "receipt",
        "clock_source",
        "cash_source",
        "forward",
        "duplicate_split",
        "exchange",
    ],
)
def test_consolidation_preparation_requires_source_clock_and_ordering(defect):
    args = inputs()
    row = consolidation_fixture()
    args["actions"]["AAA"] = [row]
    if defect == "naive":
        row["effective_at"] = "2026-09-14T16:15:00"
    elif defect == "intraday":
        row["effective_at"] = "2026-09-14T15:45:00-04:00"
    elif defect == "late_day":
        row["effective_at"] = "2026-09-13T16:15:00-04:00"
    elif defect == "receipt":
        row["source_receipt"] = {}
    elif defect == "clock_source":
        row.pop("effective_source")
    elif defect == "cash_source":
        row.pop("fractional_source")
    elif defect == "forward":
        row["numerator"] = 6
    elif defect == "duplicate_split":
        args["actions"]["AAA"].append(
            {"date": row["date"], "kind": "split", "value": 1 / 6}
        )
    else:
        args["actions"]["AAA"].append(
            {
                "date": row["date"],
                "kind": "security_exchange",
                "numerator": 1,
                "denominator": 5,
                "old_security_id": "old",
                "new_security_id": "new",
                "fractional_policy": "floor_no_compensation",
                "terms_available_on": "2026-09-14",
                "source_receipt": {"declaration": "synthetic"},
            }
        )
    expected = {
        "naive": "Aware consolidation",
        "intraday": "Intraday consolidation",
        "late_day": "first regular opening",
        "receipt": "source evidence",
        "clock_source": "source evidence",
        "cash_source": "source evidence",
        "forward": "Explicit reverse ratio",
        "duplicate_split": "additional entitlement ordering",
        "exchange": "additional entitlement ordering",
    }[defect]
    with pytest.raises(ValueError, match=expected):
        adapter.prepare(**args)


# Use the real early close rather than rejecting an after-close legal effective clock.
def test_consolidation_schedules_first_open_after_early_close():
    row = consolidation_fixture()
    row["effective_at"] = "2026-11-27T13:15:00-05:00"
    result = adapter._consolidation(row, np.datetime64("2026-11-30"))
    assert result["date"] == "2026-11-30"
    assert result["effective_at"] == row["effective_at"]


# Enforce exact coverage and original factors before compiling reviewed actions.
@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "missing",
        "extra",
        "duplicate",
        "factor",
        "ratio",
        "bool_ratio",
        "source",
        "scope",
        "self_child",
    ],
)
def test_review_refuses_changed_missing_or_ambiguous_evidence(change):
    original, review = reviewed_action_fixture()
    event = review["events"][0]
    if change == "hash":
        review["original_actions_sha256"] = "0" * 64
    elif change == "missing":
        review["events"] = []
    elif change == "extra":
        review["events"].append(dict(event, symbol="SPY"))
    elif change == "duplicate":
        review["events"].append(dict(event))
    elif change == "factor":
        event["archive_factor"] = 3
    elif change == "ratio":
        event["numerator"] = 3
    elif change == "bool_ratio":
        event["denominator"] = True
    elif change == "source":
        event["source"] = "not-source-evidence"
    elif change == "scope":
        review["last_session"] = "2026-09-14"
    else:
        event.update(classification="security_distribution", child="AAA")
    errors = {
        "hash": "exact original",
        "missing": "Missing economic",
        "extra": "absent from original",
        "duplicate": "Unique covered",
        "factor": "archive factor differs",
        "ratio": "same-security ratio differs",
        "bool_ratio": "positive integer",
        "source": "declaration URL",
        "scope": "Unique covered",
        "self_child": "Distinct explicit",
    }
    with pytest.raises(ValueError, match=errors[change]):
        adapter.review_action_export(original, json.dumps(review).encode())


# Reject duplicate serialized keys that would hide one declaration behind another.
def test_review_refuses_duplicate_serialized_keys():
    original, review = reviewed_action_fixture()
    encoded = json.dumps(review).encode()[:-1] + b',"events":[]}'
    with pytest.raises(ValueError, match="Duplicate action evidence key"):
        adapter.review_action_export(original, encoded)


# Split-adjusted dividends must become ex-date dollars before multiplying raw shares.
def test_dividend_amount_basis_is_required_and_dated_splits_recover_raw_cash():
    args = inputs()
    del args["dividend_price_basis"]
    args["actions"]["AAA"].insert(
        0, {"date": "2026-09-14", "kind": "dividend", "value": 0.2}
    )
    with pytest.raises(ValueError, match="dividend.*basis"):
        adapter.prepare(**args)
    args["dividend_price_basis"] = "split_adjusted_archive_share_dollars"
    result = adapter.prepare(**args)
    assert result.actions["AAA"][0]["value"] == pytest.approx(0.4)
    assert result.actions["AAA"][0]["source_value"] == 0.2
    args["dividend_price_basis"] = "raw_ex_date_share_dollars"
    raw = adapter.prepare(**args)
    assert raw.actions["AAA"][0]["value"] == 0.2
    assert args["actions"]["AAA"][0]["value"] == 0.2


# Convert compounded future splits without treating a same-day split as prior shares.
@pytest.mark.parametrize(
    ("ex_day", "expected"), [("2026-09-14", 1.2), ("2026-09-15", 0.6)]
)
def test_dividend_conversion_compounds_only_strictly_later_splits(ex_day, expected):
    args = inputs()
    args["basis_as_of"] = args["complete_through"] = "2026-10-01"
    args["dividend_price_basis"] = "split_adjusted_archive_share_dollars"
    args["actions"]["AAA"].extend(
        [
            {"date": ex_day, "kind": "dividend", "value": 0.2},
            {"date": "2026-10-01", "kind": "split", "value": 3.0},
        ]
    )
    args["actions"]["AAA"].sort(key=lambda row: row["date"])
    result = adapter.prepare(**args)
    dividend = next(row for row in result.actions["AAA"] if row["kind"] == "dividend")
    assert dividend["value"] == pytest.approx(expected)
    assert dividend["source_value"] == 0.2
    assert result.actions["SPY"] == ()


# Construct regular raw cubes without a fabricated opening or auction price.
def cube_fixture(ticker, dates, prices):
    opening = np.broadcast_to(np.array(prices)[:, None], (len(dates), 26)).copy()
    return SessionCube(
        ticker,
        dates.copy(),
        opening.copy(),
        opening + 2,
        opening - 2,
        opening.copy(),
        np.ones_like(opening),
        np.array(prices),
        {"early_close": 0, "incomplete": 0, "no_prior_close": 0},
        np.array(prices) + 1,
        np.ones(len(dates)),
    )


# Recover raw daily high, low and close using the same dated split factor.
def test_dated_split_recovery_and_raw_cube_clocks():
    args = inputs()
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(result.daily_close[:, 0], [100.0, 50.0])
    np.testing.assert_array_equal(result.daily_high[:, 0], [102.0, 51.0])
    np.testing.assert_array_equal(result.daily_low[:, 0], [98.0, 49.0])
    np.testing.assert_array_equal(result.split_factors[:, 0], [2.0, 1.0])
    np.testing.assert_array_equal(
        result.observation_close[:, :, 0], args["cubes"]["AAA"].close[:, :25]
    )
    np.testing.assert_array_equal(
        result.next_open[:, :, 0], args["cubes"]["AAA"].open[:, 1:26]
    )
    np.testing.assert_array_equal(result.session_open[:, 0], [100.0, 50.0])
    assert not np.array_equal(result.daily_close[:, 0], args["panel"].adj_close[:, 0])
    assert np.isnan(result.next_open[:, :, 1]).all()
    assert np.all(result.status[:, 1] == "missing_cube_session")


# Dividends remain explicit cash actions and never scale raw dollars.
def test_dividend_not_used_as_split_or_price_ratio():
    args = inputs()
    args["actions"]["AAA"].append(
        {"date": "2026-09-15", "kind": "dividend", "value": 3.0}
    )
    args["panel"] = replace(args["panel"], adj_close=np.full((2, 2), 1.0))
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(result.daily_close[:, 0], [100.0, 50.0])
    assert [row["kind"] for row in result.actions["AAA"]] == ["split", "dividend"]
    assert result.actions["AAA"][1]["value"] == 3.0


# Declare physical shares while keeping acquisition-cost allocation explicitly absent.
def unallocated_distribution_fixture():
    return {
        "date": "2026-09-15",
        "kind": "stock_distribution",
        "child": "SPY",
        "numerator": 1,
        "denominator": 5,
        "parent_basis_fraction": None,
        "basis_policy": "unallocated_at_effective_clock",
        "effective_at": "2026-09-14T17:00:00-04:00",
        "effective_source": "https://issuer.example/synthetic-legal-clock",
        "fractional_source": "https://issuer.example/synthetic-fractional-policy",
        "fractional_policy": "cash_in_lieu_unknown",
        "share_basis": "post_split_action_date_shares",
        "source_receipt": {"declaration": "synthetic-share-distribution"},
    }


# Physical grants never turn an archive factor into parent shares or tax basis.
def test_reviewed_unallocated_distribution_does_not_fabricate_basis_or_cash():
    original, review = reviewed_action_fixture()
    review["events"][0].update(
        **{
            key: value
            for key, value in unallocated_distribution_fixture().items()
            if key not in ("kind", "source_receipt")
        },
        classification="security_distribution",
    )
    result = adapter.review_action_export(original, json.dumps(review).encode())
    assert result["unresolved"] == ()
    assert [row["kind"] for row in result["actions"]["AAA"]] == [
        "archive_adjustment",
        "stock_distribution",
    ]
    args = inputs()
    args["actions"] = result["actions"]
    raw = adapter.prepare(**args)
    assert raw.actions["AAA"][1]["parent_basis_fraction"] is None
    assert "basis_available_at" not in raw.actions["AAA"][1]
    np.testing.assert_array_equal(raw.daily_close[:, 0], [100, 50])
    assert raw.tickers == args["panel"].tickers


# Later tax examples and ambiguous or unsourced terms cannot enter decisions.
@pytest.mark.parametrize(
    "defect",
    [
        "guess",
        "later_basis",
        "naive",
        "intraday",
        "delayed",
        "source",
        "policy",
        "same_day_split",
    ],
)
def test_unallocated_distribution_refuses_invented_or_mistimed_terms(defect):
    args = inputs()
    row = unallocated_distribution_fixture()
    args["actions"]["AAA"] = [row]
    if defect == "guess":
        row["parent_basis_fraction"] = 0.75
    elif defect == "later_basis":
        row["basis_available_at"] = "2026-09-15T16:00:00-04:00"
    elif defect == "naive":
        row["effective_at"] = "2026-09-14T17:00:00"
    elif defect == "intraday":
        row["effective_at"] = "2026-09-14T15:45:00-04:00"
    elif defect == "delayed":
        row["effective_at"] = "2026-09-13T17:00:00-04:00"
    elif defect == "source":
        row.pop("effective_source")
    elif defect == "policy":
        row.pop("basis_policy")
    else:
        args["actions"]["SPY"] = [
            {"date": row["date"], "kind": "share_split", "value": 2}
        ]
    expected = {
        "guess": "Unallocated distribution",
        "later_basis": "Unallocated distribution",
        "naive": "Aware distribution",
        "intraday": "Intraday distribution",
        "delayed": "first regular opening",
        "source": "fractional source required",
        "policy": "Explicit distribution basis allocation",
        "same_day_split": "additional entitlement ordering",
    }[defect]
    with pytest.raises(ValueError, match=expected):
        adapter.prepare(**args)


# Price adjustments change archive units without granting extra parent shares.
def test_archive_adjustment_and_child_distribution_have_distinct_units():
    args = inputs()
    args["actions"]["AAA"][0].update(kind="archive_adjustment", value=1.323)
    args["actions"]["AAA"].append(
        {
            "date": "2026-09-15",
            "kind": "stock_distribution",
            "child": "SPY",
            "numerator": 1,
            "denominator": 3,
            "parent_basis_fraction": 0.75,
            "basis_available_at": "2026-09-15T09:30:00-04:00",
            "fractional_policy": "cash_in_lieu_unknown",
            "share_basis": "post_split_action_date_shares",
            "source_receipt": {"source": "synthetic-explicit-entitlement"},
        }
    )
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(result.split_factors[:, 0], [1.323, 1])
    assert result.provenance["archive_factor_action_kinds"] == (
        "split",
        "archive_adjustment",
    )
    assert result.actions["AAA"][1]["numerator"] == 1
    assert result.actions["AAA"][1]["denominator"] == 3
    assert result.daily_close[0, 0] == pytest.approx(50 * 1.323)
    args["actions"]["AAA"][1]["basis_available_at"] = "2026-09-15T16:00:00-04:00"
    with pytest.raises(ValueError, match="later evidence"):
        adapter.prepare(**args)


# A coherently revised archive basis leaves historical raw decisions unchanged.
def test_future_split_is_only_archive_unit_conversion():
    original = inputs()
    initial = adapter.prepare(**original)
    revised = inputs()
    revised["panel"] = replace(
        revised["panel"],
        **{
            name: getattr(revised["panel"], name) / 2
            for name in ("open", "high", "low", "close", "adj_close")
        },
    )
    revised["actions"]["AAA"].append(
        {"date": "2026-10-01", "kind": "split", "value": 2.0}
    )
    # SPY's archived dollar basis is unchanged even when its coverage is newer.
    for name in ("open", "high", "low", "close", "adj_close"):
        getattr(revised["panel"], name)[:, 1] *= 2
    revised["basis_as_of"] = "2026-10-01"
    revised["complete_through"] = "2026-10-01"
    later = adapter.prepare(**revised)
    for name in (
        "daily_close",
        "daily_open",
        "daily_high",
        "daily_low",
        "observation_close",
        "next_open",
        "grades",
        "eligible",
    ):
        np.testing.assert_array_equal(getattr(initial, name), getattr(later, name))
    assert later.provenance["future_actions"].startswith("archive_units")


# A future split must not be hidden when the caller leaves prices on a newer basis.
def test_omitted_future_split_is_not_repaired_with_cube_price_ratios():
    args = inputs()
    baseline = adapter.prepare(**args)
    args["actions"]["AAA"].append({"date": "2026-10-01", "kind": "split", "value": 2.0})
    args["basis_as_of"] = args["complete_through"] = "2026-10-01"
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(
        result.daily_close[:, 0], baseline.daily_close[:, 0] * 2
    )
    np.testing.assert_array_equal(result.next_open, baseline.next_open)


# Keep original missing fields while allowing a next open independently of later OHLC.
def test_missing_bars_remain_missing_without_future_close_fill_veto():
    args = inputs()
    args["panel"].high[0, 0] = np.nan
    args["cubes"]["AAA"].close[0, 7] = np.nan
    args["cubes"]["AAA"].open[0, 4] = np.nan
    result = adapter.prepare(**args)
    assert np.isnan(result.daily_high[0, 0])
    assert np.isnan(result.observation_close[0, 7, 0])
    assert result.next_open[0, 6, 0] == 100.0
    assert np.isnan(result.next_open[0, 3, 0])
    assert result.status[0, 0] == "provided_missing_bars"
    np.testing.assert_array_equal(result.dates, args["panel"].dates)


# Preserve early-close daily sessions and never fabricate their excluded regular grid.
def test_early_close_sessions_remain_explicitly_unavailable():
    args = inputs()
    dates = np.array(["2026-11-25", "2026-11-27"], dtype="datetime64[D]")
    args["panel"] = replace(args["panel"], dates=dates)
    args["cubes"]["AAA"] = cube_fixture("AAA", dates[:1], [50.0])
    args["actions"] = {"AAA": [], "SPY": []}
    args["basis_as_of"] = args["complete_through"] = "2026-11-27"
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(result.full_session, [True, False])
    assert np.all(result.status[1] == "unsupported_early_close")
    assert np.isnan(result.observation_close[1]).all()
    assert np.isnan(result.next_open[1]).all()
    assert result.daily_close[1, 0] == 50.0


# Reject duplicate or descending cube sessions instead of choosing an arbitrary row.
@pytest.mark.parametrize("kind", ["duplicate", "descending", "ticker", "shape"])
def test_malformed_cube_grid_refused(kind):
    args = inputs()
    cube = args["cubes"]["AAA"]
    if kind == "duplicate":
        cube = replace(cube, dates=np.repeat(cube.dates[:1], 2))
    elif kind == "descending":
        cube = replace(cube, dates=cube.dates[::-1])
    elif kind == "ticker":
        cube = replace(cube, ticker="OTHER")
    else:
        cube = replace(cube, close=cube.close[:, :25])
    args["cubes"]["AAA"] = cube
    with pytest.raises(ValueError, match="cube|Cube"):
        adapter.prepare(**args)


# Require explicit action types, units, complete coverage and chronological facts.
@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "conflict",
        "negative",
        "unknown",
        "order",
        "absent",
        "coverage",
        "basis",
        "units",
    ],
)
def test_invalid_action_or_basis_contract_refused(kind):
    args = inputs()
    action = args["actions"]["AAA"][0]
    if kind in ("duplicate", "conflict"):
        args["actions"]["AAA"].append(
            {**action, "value": 3.0 if kind == "conflict" else 2.0}
        )
    elif kind == "negative":
        action["value"] = -2
    elif kind == "unknown":
        action["kind"] = "price_adjustment"
    elif kind == "order":
        args["actions"]["AAA"].append(
            {"date": "2026-09-14", "kind": "dividend", "value": 1.0}
        )
    elif kind == "absent":
        del args["actions"]["SPY"]
    elif kind == "coverage":
        args["complete_through"]["AAA"] = "2026-09-14"
    elif kind == "basis":
        args["basis_as_of"]["AAA"] = "2026-09-14"
    else:
        args["daily_price_basis"] = "already_raw"
    with pytest.raises(
        ValueError, match="action|basis|units|coverage|completeness|split-adjusted"
    ):
        adapter.prepare(**args)


# Returned execution grids and nested source metadata cannot mutate supplied sources.
def test_source_nonmutation_and_immutable_outputs():
    args = inputs()
    before = deepcopy(args)
    result = adapter.prepare(**args)
    for field in ("open", "high", "low", "close", "adj_close"):
        np.testing.assert_array_equal(
            getattr(args["panel"], field), getattr(before["panel"], field)
        )
    np.testing.assert_array_equal(
        args["cubes"]["AAA"].open, before["cubes"]["AAA"].open
    )
    assert args["actions"] == before["actions"]
    assert args["provenance"] == before["provenance"]
    with pytest.raises(ValueError, match="read-only"):
        result.next_open[0, 0, 0] = 1
    with pytest.raises(TypeError):
        result.actions["AAA"][0]["value"] = 9
    with pytest.raises(TypeError):
        result.provenance["supplied"]["daily_source"] = "changed"
