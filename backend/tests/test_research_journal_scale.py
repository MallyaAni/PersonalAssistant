"""Independent monetary conditioning tests for research journal buy scales.

These cases do not run a strategy or regenerate market outcomes. The complete
journal fixture is hand-calculated; direct checks isolate both monetary bounds
while the complete replay still checks funding, fills, fees and carried state.
"""

import math

import pytest

from backend.market import research_journal_replay as verifier
from backend.tests.test_research_journal_replay import Fixture, _rehash


# Isolate scale conditioning with explicit observed and independently requested spend.
def _scale_case(requested, actual, expected, *, observed=None, account=1.0, rate=0.0):
    observed = requested if observed is None else observed
    replay = verifier._Replay({"symbols": ["BUY", "HELD"]}, {}, verifier._result())
    replay.cash = expected * requested
    replay.positions = [0.0, max(0.0, account - replay.cash)]
    event = {
        "scale": actual,
        "buy_budget": actual * observed,
        "submitted_units": [observed / (1 + rate), replay.positions[1]],
        "positions_before": [0.0, replay.positions[1]],
    }
    return replay, event, expected, requested / (1 + rate), [1.0, 1.0], rate


# Build two real arithmetic batches whose cash grouping differs below one ULP of NAV.
def _rounding_snapshot():
    rate, held = 0.001, 0.004
    first_open = 249.75021473526473
    notional = held * first_open
    observed_cash = 1.0 - (notional + notional * rate)
    independent_cash = 1.0 - notional - notional * rate
    assert observed_cash != independent_cash
    assert abs(observed_cash - independent_cash) < 1e-15
    target = held + 2e-7 / (250.0 * (1 + rate))
    requested = (target - held) * 250.0 * (1 + rate)
    scale = observed_cash / requested
    after = held + (target - held) * scale
    fixture = Fixture([[first_open], [first_open], [250.0]], cost=10, cash=1.0)
    fixture.mark(0, 1.0)
    first = fixture.decision(0, [held])
    fixture.fill(first, 1, [held], [held], observed_cash, 1.0, 1.0)
    fixture.mark(1, observed_cash + held * first_open)
    second = fixture.decision(1, [target])
    fixture.fill(second, 2, [target], [after], 0.0, observed_cash, scale)
    fixture.mark(2, after * 250.0)
    return fixture.snapshot(), independent_cash, requested


# Reproduce the actual numerical boundary with a portable single-symbol state fixture.
def test_observed_market_scale_roundoff_is_bounded_in_currency_without_state_reset():
    replay = verifier._Replay({"symbols": ["SPY"]}, {}, verifier._result())
    replay.cash = 1.533795830159302e-7
    replay.positions = [0.004140770703665485]
    price = 235.4623713740325
    rate = 0.001
    target = 0.004140771354568469
    observed_cash = 1.533795833257903e-7
    requested = (target - replay.positions[0]) * price
    spend = requested * (1 + rate)
    expected = replay.cash / spend
    actual = observed_cash / spend
    event = {
        "scale": actual,
        "buy_budget": observed_cash,
        "submitted_units": [target],
        "positions_before": list(replay.positions),
    }
    before = replay.cash, list(replay.positions)
    assert not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
    assert spend > 1e-12
    replay.check_scale(event, expected, requested, [price], rate)
    assert (replay.cash, replay.positions) == before
    measured = replay.result["currency_scale_checks"]
    assert measured["count"] == 1
    assert measured["max_requested_spend"] == pytest.approx(spend, rel=1e-14)
    assert measured["max_currency_difference"] == pytest.approx(
        3.0986008405573695e-16, rel=1e-9, abs=1e-25
    )
    assert measured["max_currency_difference"] < measured["max_bound"] == 1e-12
    assert replay.result["small_notional_scale_checks"]["count"] == 0


# Reconcile multiple batches while carrying independently calculated cash.
def test_three_session_rounding_journal_reconciles_without_widening_tolerances():
    snapshot, independent_cash, requested = _rounding_snapshot()
    report = verifier.verify_snapshot(snapshot)
    assert report["ok"], report["errors"]
    assert report["integrity_verified"]
    assert report["accounting_verified"]
    assert report["complete"]
    assert len(report["marks"]) == 3
    assert report["marks"][1]["cash"] == independent_cash
    assert report["marks"][1]["cash"] != snapshot["events"][4]["cash"]
    assert report["currency_scale_checks"]["count"] == 1
    assert report["currency_scale_checks"]["max_requested_spend"] == pytest.approx(
        requested, rel=1e-12
    )
    assert (
        report["currency_scale_checks"]["max_currency_difference"]
        <= report["currency_scale_checks"]["max_bound"]
    )
    assert report["small_notional_scale_checks"]["count"] == 0
    assert report["tolerance"] == {"relative": 1e-10, "absolute": 1e-12}
    assert verifier.REL_TOL == 1e-10
    assert verifier.ABS_TOL == 1e-12
    assert 0 < report["max_reconciliation_residual"]["cash"] < 1e-12
    assert report["adoption_eligible"] is False


# Reject forged scales even when their monetary effect fits the allowance.
@pytest.mark.parametrize("requested", [1e-16, 1e-7])
def test_scale_must_match_recorded_funding_even_for_monetarily_small_errors(requested):
    replay, event, expected, amount, prices, rate = _scale_case(
        requested, 0.4000001, 0.399999999
    )
    event["buy_budget"] = 0.4 * requested
    assert abs(event["scale"] - expected) * requested < 1e-12
    with pytest.raises(verifier.JournalError, match="recorded funding formula"):
        replay.check_scale(event, expected, amount, prices, rate)
    assert replay.result["currency_scale_checks"]["count"] == 0


# A zero requested buy has scale zero, not an arbitrary number excused by zero spend.
def test_zero_requested_spend_does_not_allow_an_invented_scale():
    replay, event, expected, amount, prices, rate = _scale_case(0.0, 0.5, 0.0)
    with pytest.raises(verifier.JournalError, match="recorded funding formula"):
        replay.check_scale(event, expected, amount, prices, rate)


# Preserve the tiny-request counter alongside the bounded currency check.
def test_genuinely_tiny_request_preserves_its_existing_diagnostic_counter():
    replay, event, expected, amount, prices, rate = _scale_case(1e-16, 0.4, 0.0)
    replay.check_scale(event, expected, amount, prices, rate)
    measured = replay.result["currency_scale_checks"]
    small = replay.result["small_notional_scale_checks"]
    assert measured["count"] == small["count"] == 1
    assert measured["max_requested_spend"] == small["max_requested_spend"] == 1e-16
    assert measured["max_bound"] == small["max_bound"] == 1e-12
    assert measured["max_currency_difference"] == pytest.approx(4e-17, abs=1e-30)
    assert replay.cash == 0.0


# Material currency effects remain failures across small, ordinary and large accounts.
@pytest.mark.parametrize(
    ("requested", "actual", "expected", "account"),
    [(1e-7, 0.0001, 0.0, 1.0), (1.0, 0.500001, 0.5, 1.0), (1e6, 0.5, 0.49999999, 1e6)],
)
def test_material_money_difference_is_not_excused_by_scale_conditioning(
    requested, actual, expected, account
):
    replay, event, expected, amount, prices, rate = _scale_case(
        requested, actual, expected, account=account
    )
    assert abs(actual - expected) * requested > 1e-12 * max(1, account)
    with pytest.raises(verifier.JournalError, match="materially sized mismatch"):
        replay.check_scale(event, expected, amount, prices, rate)
    assert replay.result["currency_scale_checks"]["count"] == 0


# Equal executed spend cannot excuse a material scale-induced money difference.
def test_scale_induced_money_bound_is_independent_of_the_executed_spend_bound():
    replay, event, expected, amount, prices, rate = _scale_case(
        1e-7, 0.5, 1.0, observed=2e-7
    )
    assert event["scale"] * 2e-7 == expected * 1e-7
    assert abs(event["scale"] - expected) * 2e-7 > 1e-12
    with pytest.raises(verifier.JournalError, match="materially sized mismatch"):
        replay.check_scale(event, expected, amount, prices, rate)


# A small scale delta cannot hide a material difference in the money actually executed.
def test_executed_spend_bound_is_independent_of_the_scale_delta_bound():
    replay, event, expected, amount, prices, rate = _scale_case(
        0.001, 0.5, 0.4999999999, observed=0.002
    )
    assert abs(event["scale"] - expected) * 0.002 < 1e-12
    assert abs(event["scale"] * 0.002 - expected * 0.001) > 1e-12
    with pytest.raises(verifier.JournalError, match="materially sized mismatch"):
        replay.check_scale(event, expected, amount, prices, rate)


# Ordinary matching scales retain their existing exact path at every requested size.
@pytest.mark.parametrize("requested", [0.0, 1e-16, 1e-7, 1.0, 1e9])
def test_matching_scales_need_no_currency_exception_at_any_size(requested):
    scale = 0.5 if requested else 0.0
    replay, event, expected, amount, prices, rate = _scale_case(
        requested, scale, scale, account=max(1.0, requested)
    )
    replay.check_scale(event, expected, amount, prices, rate)
    assert replay.result["currency_scale_checks"]["count"] == 0
    assert replay.result["small_notional_scale_checks"]["count"] == 0


# Use account value for the currency bound, never the requested buy size.
def test_currency_bound_is_scaled_by_account_nav_not_buy_notional():
    replay, event, expected, amount, prices, rate = _scale_case(
        0.01, 0.50000001, 0.5, account=1000.0
    )
    replay.check_scale(event, expected, amount, prices, rate)
    measured = replay.result["currency_scale_checks"]
    assert measured["count"] == 1
    assert measured["max_bound"] == pytest.approx(1e-9)
    assert 1e-12 < measured["max_currency_difference"] < measured["max_bound"]


# Reject rehashed accounting corruption even after the rounding exception passes.
@pytest.mark.parametrize(
    ("field", "vector"),
    [
        ("cash_after", False),
        ("positions_after", True),
        ("filled_units", True),
        ("fees", True),
        ("fee_total", False),
        ("notional", True),
        ("gross_buys", False),
    ],
)
def test_currency_conditioning_does_not_hide_corrupted_fill_money_or_units(
    field, vector
):
    snapshot, _, _ = _rounding_snapshot()
    assert verifier.verify_snapshot(snapshot)["ok"]
    batch = snapshot["events"][6]
    if vector:
        batch[field][0] += 1e-6
    else:
        batch[field] += 1e-6
    report = verifier.verify_snapshot(_rehash(snapshot))
    assert report["integrity_verified"]
    assert not report["ok"]
    assert not report["accounting_verified"]
    assert field in report["errors"][0]


# Reject a fabricated journal scale despite its negligible monetary effect.
def test_full_journal_rejects_an_invented_scale_with_tiny_monetary_effect():
    snapshot, _, requested = _rounding_snapshot()
    snapshot["events"][6]["scale"] += 1e-6
    assert requested * 1e-6 < 1e-12
    report = verifier.verify_snapshot(_rehash(snapshot))
    assert report["integrity_verified"]
    assert not report["ok"]
    assert "recorded funding formula" in report["errors"][0]


# Scale range and number type remain strict even when no order would spend money.
@pytest.mark.parametrize("scale", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_zero_money_cannot_bypass_scale_type_or_range_guards(scale):
    replay, event, expected, amount, prices, rate = _scale_case(0.0, 0.0, 0.0)
    event["scale"] = scale
    with pytest.raises(verifier.JournalError, match="scale outside|finite number"):
        replay.check_scale(event, expected, amount, prices, rate)
