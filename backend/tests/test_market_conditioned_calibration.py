"""Independent numerical and causal acceptance for the declared calibration."""

import numpy as np
import pytest

from backend.market import calendar
from backend.market import market_conditioned_calibration as model


# Produce completed exchange dates and identifiable market features without a model.
def evidence():
    _, exchange = calendar.reviewed_sessions()
    dates = np.arange("2018-01-01", "2021-04-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates, busdaycal=exchange)]
    t = np.arange(len(dates), dtype=float)
    forecast = np.expm1(0.005 * np.sin(t / 7))
    context = np.c_[
        0.03 * np.sin(t / 23),
        -0.1 + 0.05 * np.cos(t / 43),
        0.01 + 0.003 * np.sin(t / 17),
        0.5 + 0.2 * np.cos(t / 31),
    ]
    design = np.c_[np.ones(len(t)), np.log1p(forecast), context]
    outcome = np.expm1(
        design @ [0.002, 0.4, 0.1, 0.02, -0.3, 0.001] + 0.0001 * np.cos(t)
    )
    endpoints = np.busday_offset(dates, 2, busdaycal=exchange)
    return dates, endpoints, forecast, outcome, context, np.ones(len(t), dtype=bool)


# Solve the raw unscaled design independently and compare mean and leverage.
def test_raw_matrix_oracle_and_context_sensitivity():
    data = evidence()
    fit = model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))
    selected = fit.selected
    design = np.c_[
        np.ones(len(selected)), np.log1p(data[2][selected]), data[4][selected]
    ]
    y = np.log1p(data[3][selected])
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    context = np.array([0.01, -0.05, 0.015, 0.6])
    query = np.r_[1.0, np.log1p(0.004), context]
    mean, multiplier = fit.predict(0.004, context)
    assert fit.rank == 6
    assert mean == pytest.approx(query @ coefficients, abs=1e-12)
    leverage = query @ np.linalg.inv(design.T @ design) @ query
    assert multiplier == pytest.approx(np.sqrt(len(y) / (len(y) - 6) * (1 + leverage)))
    stressed = context.copy()
    stressed[0], stressed[1] = -0.05, -0.25
    assert fit.predict(0.004, stressed)[0] < mean


# Unobserved later outcomes and market features cannot alter an earlier fitted model.
def test_future_prefix_and_caller_mutation_do_not_change_fit():
    data = evidence()
    month = np.datetime64("2020-08-03")
    old = model.fit_market_log(*data, fit_date=month)
    changed = tuple(value.copy() for value in data)
    future = changed[0] >= month
    changed[2][future], changed[3][future], changed[4][future] = np.nan, 999, np.nan
    new = model.fit_market_log(*changed, fit_date=month)
    assert old.receipt() == new.receipt()
    before = old.predict(0.004, data[4][400])
    data[2][:], data[3][:], data[4][:] = 999, -1, np.nan
    assert before == old.predict(0.004, changed[4][400])
    for values in (
        old.center,
        old.scale,
        old.coefficients,
        old.directions,
        old.singular_values,
        old.selected,
    ):
        assert not values.flags.writeable


# The fixed freeze excludes later endpoints even when the declared calendar extends.
def test_freeze_window_and_exact_endpoint_enforcement():
    _, exchange = calendar.reviewed_sessions()
    dates = np.arange("2022-01-01", "2026-10-02", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates, busdaycal=exchange)]
    n = len(dates)
    endpoints = np.busday_offset(dates, 2, busdaycal=exchange)
    context = np.tile([0.01, -0.1, 0.01, 0.5], (n, 1))
    fit = model.fit_market_log(
        dates,
        endpoints,
        np.zeros(n),
        np.zeros(n),
        context,
        np.ones(n, bool),
        fit_date=np.datetime64("2026-09-01"),
    )
    assert fit.cutoff == "2026-08-17"
    assert endpoints[fit.selected].max() < np.datetime64(fit.cutoff)
    first = np.searchsorted(dates, np.datetime64(fit.fit_date))
    assert fit.selected.min() >= first - 756
    bad = endpoints.copy()
    bad[fit.selected[0]] += np.timedelta64(1, "D")
    with pytest.raises(ValueError, match=r"D\+2"):
        model.fit_market_log(
            dates,
            bad,
            np.zeros(n),
            np.zeros(n),
            context,
            np.ones(n, bool),
            fit_date=np.datetime64("2026-09-01"),
        )


# Default dates remain counted while only defined non-default logs enter regression.
def test_true_defaults_and_missing_admitted_context():
    data = evidence()
    data[3][100] = -1
    fit = model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))
    assert fit.defaults == 1
    assert fit.observations + fit.defaults == len(fit.selected)
    data[4][200, 2] = np.nan
    with pytest.raises(ValueError, match="market context"):
        model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))


# Constant and dependent predictors cannot imply certainty outside their affine span.
def test_constant_and_collinear_prediction_refusal():
    data = evidence()
    data[2][:] = 0
    data[4][:] = [0.01, -0.1, 0.01, 0.5]
    fit = model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))
    assert fit.rank == 1
    assert np.isfinite(fit.predict(0, data[4][0])).all()
    with pytest.raises(ValueError, match="outside identified"):
        fit.predict(0.01, data[4][0])
    data = evidence()
    data[4][:, 0] = np.log1p(data[2])
    fit = model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))
    assert fit.rank == 5
    query = data[4][400].copy()
    assert np.isfinite(fit.predict(data[2][400], query)).all()
    query[0] += 0.01
    with pytest.raises(ValueError, match="outside identified"):
        fit.predict(data[2][400], query)


# Calendar, maturity, numeric and query domain defects cannot become silent fits.
@pytest.mark.parametrize(
    "defect",
    ["calendar", "month", "support", "forecast", "outcome", "short", "future_month"],
)
def test_invalid_training_contract_is_refused(defect):
    data = list(evidence())
    month = np.datetime64("2020-08-03")
    if defect == "calendar":
        data = [np.delete(v, 10, axis=0) for v in data]
    elif defect == "month":
        month = np.datetime64("2020-08-04")
    elif defect == "support":
        data[5] = data[5].astype(int)
    elif defect == "forecast":
        data[2][100] = -1
    elif defect == "outcome":
        data[3][100] = -1.01
    elif defect == "short":
        data[5][:500] = False
    else:
        month = np.datetime64("2022-02-01")
    with pytest.raises(ValueError, match="calendar|monthly|daily|Admitted|252"):
        model.fit_market_log(*data, fit_date=month)


# A missing or impossible query never produces an actionable numerical prediction.
@pytest.mark.parametrize("forecast", [True, np.nan, np.inf, -1, 1j])
def test_invalid_forecast_is_refused(forecast):
    data = evidence()
    fit = model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))
    with pytest.raises(ValueError, match="current forecast"):
        fit.predict(forecast, data[4][400])


# Backdated caller endpoints cannot admit the two still-unknown opening outcomes.
def test_purging_uses_exchange_dates_instead_of_caller_claimed_maturity():
    data = evidence()
    month = np.datetime64("2020-08-03")
    old = model.fit_market_log(*data, fit_date=month)
    first = np.searchsorted(data[0], month)
    data[1][first - 2 : first] = month - np.timedelta64(10, "D")
    data[2][first - 2 : first] = 0.9
    data[3][first - 2 : first] = 999
    data[4][first - 2 : first] = np.nan
    new = model.fit_market_log(*data, fit_date=month)
    assert old.receipt() == new.receipt()


# Invalid market domains and extreme arithmetic cannot imply a useful mean forecast.
@pytest.mark.parametrize(
    ("field", "value"),
    [(0, np.nan), (1, -1.1), (1, 0.1), (2, -0.1), (3, 1.1), (0, 1e308)],
)
def test_invalid_context_and_numeric_query_tail_are_refused(field, value):
    data = evidence()
    fit = model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))
    context = data[4][400].copy()
    context[field] = value
    with pytest.raises(ValueError, match="market context|calibration arithmetic"):
        fit.predict(data[2][400], context)


# Excessive fitted arithmetic fails explicitly while leaving every input unchanged.
def test_fit_numeric_tail_is_refused_without_clipping():
    data = evidence()
    data[4][:, 0] = 1e308
    original = data[4].copy()
    with pytest.raises(ValueError, match="fitted market calibration arithmetic"):
        model.fit_market_log(*data, fit_date=np.datetime64("2020-08-03"))
    np.testing.assert_array_equal(data[4], original)
