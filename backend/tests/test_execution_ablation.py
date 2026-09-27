"""The execution ablation prices every registered variant and reads its verdict honestly.

On the pit scorecard's synthetic report (six names, SPY, 320 sessions, a
dated membership file), every variant in `VARIANTS` runs or is refused with
a recorded reason; "plain" and "live" are `simulate.run` with the scorecard's
own option sets, element for element; removing an option changes exactly
the named keys; the verdict applies its floors and the reconstruction check
on a hand-built payload; and the command runs end to end.
"""

import io
import json
import math

import numpy as np
import pytest

from backend.agents.trading.desk import (
    event_risk,
    paper,
    point_in_time,
    policy_v4,
    simulate,
)
from backend.cli import market_execution_ablation as cli
from backend.cli import market_pit_scorecard as sc
from backend.market import execution_ablation as ea
from backend.tests.test_market_pit_scorecard import (  # noqa: F401 - fixture
    _report,
    history,
)

REMOVED_VARIANTS = tuple(v for v in ea.VARIANTS if v.base == ea.LIVE and v.removed)


# The variant set is fixed and named: two ends, one removal per live option
# (exit_at_close carrying deferred_buys with it), two additions from plain,
# and every name is unique.
def test_variants_are_registered_and_named():
    names = [v.name for v in ea.VARIANTS]
    assert len(names) == len(set(names)) == 10
    assert names[:2] == [ea.PLAIN, ea.LIVE]
    removed = {v.removed for v in REMOVED_VARIANTS}
    assert ("block_overbought",) in removed and ("event",) in removed
    assert ("exit_at_close", "deferred_buys") in removed
    assert {v.removed[0] for v in REMOVED_VARIANTS} == set(ea.LIVE_OPTIONS)
    assert "deferred_buys" in ea.variant("live-exit_at_close").note
    assert {v.added for v in ea.VARIANTS if v.base == ea.PLAIN and v.added} == {
        ("exit_at_close",),
        ("event",),
    }
    assert set(simulate.LIVE_POLICY) | {ea.EVENT} == set(ea.LIVE_OPTIONS)
    with pytest.raises(KeyError):
        ea.variant("nothing")


# "plain" is the scorecard's plain option set and "live" is `_live_options`,
# element for element (the FOMC path compared as an array).
def test_plain_and_live_reproduce_the_scorecard_options():
    panel = _report().panel
    assert ea.variant_options(ea.variant(ea.PLAIN), panel) == dict(
        use_exits=False, rebalance=paper.REBALANCE_EVERY
    )
    live = ea.variant_options(ea.variant(ea.LIVE), panel)
    expected = sc._live_options(panel)
    assert set(live) == set(expected)
    for key, value in expected.items():
        if key == "event_exposure":
            np.testing.assert_array_equal(live[key], value)
        else:
            assert live[key] == value, key
    assert live["event_lifecycle"] is True
    for key in simulate.LIVE_POLICY:
        assert live[key] is True


# Removing an option from live changes exactly the named keys, and adding
# one to plain adds exactly those keys.
def test_removal_and_addition_change_exactly_the_named_keys():
    panel = _report().panel
    live = ea.variant_options(ea.variant(ea.LIVE), panel)
    for v in REMOVED_VARIANTS:
        options = ea.variant_options(v, panel)
        assert set(options) == set(live)
        changed = {
            k
            for k in live
            if not (
                np.array_equal(options[k], live[k])
                if isinstance(live[k], np.ndarray)
                else options[k] == live[k]
            )
        }
        expected = set()
        for option in v.removed:
            expected |= (
                {"event_exposure", "event_lifecycle"}
                if option == ea.EVENT
                else {option}
            )
        assert changed == expected, v.name
        for option in v.removed:
            if option == ea.EVENT:
                assert (
                    options["event_exposure"] is None
                    and options["event_lifecycle"] is False
                )
            else:
                assert options[option] is False
    plain = ea.variant_options(ea.variant(ea.PLAIN), panel)
    close = ea.variant_options(ea.variant("plain+exit_at_close"), panel)
    assert (
        set(close) - set(plain) == {"exit_at_close"} and close["exit_at_close"] is True
    )
    event = ea.variant_options(ea.variant("plain+event"), panel)
    assert set(event) - set(plain) == {"event_exposure", "event_lifecycle"}
    np.testing.assert_array_equal(event["event_exposure"], event_risk.live_path(panel))
    with pytest.raises(KeyError):
        ea.variant_options(ea.Variant("x", ea.LIVE, removed=("no_such_option",)), panel)
    with pytest.raises(ValueError):
        ea.variant_options(ea.Variant("x", "neither"), panel)


# Every variant's options are accepted by `simulate.run`, and "plain" is
# `simulate.run` with the plain options element for element on the
# restricted report with the policy's allocator.
def test_every_variant_runs_and_plain_matches_simulate(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    since = sc._since(report.panel, 1)
    for v in ea.VARIANTS:
        curve = ea.price(restricted, mask, v, since, 10.0)
        assert curve.label == v.name and len(curve.dates) == len(curve.daily)
    plain = ea.price(restricted, mask, ea.variant(ea.PLAIN), since, 10.0)
    direct = simulate.run(
        restricted,
        since=since,
        cost_bps=10.0,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        allocator=policy_v4.allocator(mask),
    )
    np.testing.assert_array_equal(plain.dates, direct.dates)
    np.testing.assert_array_equal(plain.daily, direct.returns)
    live = ea.price(restricted, mask, ea.variant(ea.LIVE), since, 10.0)
    direct_live = simulate.run(
        restricted,
        since=since,
        cost_bps=10.0,
        allocator=policy_v4.allocator(mask),
        **sc._live_options(report.panel),
    )
    np.testing.assert_array_equal(live.daily, direct_live.returns)


# The payload holds every variant on every window at every cost, counts
# the trials, pairs every variant against both plain and live, and never
# refuses anything on this book.
def test_run_variants_payload(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    payload = ea.run_variants(report, restricted, mask, None, 2, (10.0, 25.0))
    names = {v.name for v in ea.VARIANTS}
    assert payload["trials"] == 10 and payload["refused"] == {}
    assert payload["ran"] == [v.name for v in ea.VARIANTS]
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert {r["line"] for r in payload["rows"]} == names
    assert len(payload["rows"]) == 10 * len(sc.WINDOWS) * 2
    for row in payload["rows"]:
        assert row["offsets"] == 2
        assert {
            "median_cagr",
            "worst_cagr",
            "median_drawdown",
            "median_sharpe",
            "offsets_above_plain",
            "sessions",
        } <= set(row)
    plain_rows = [r for r in payload["rows"] if r["line"] == ea.PLAIN]
    assert all(r["offsets_above_plain"] == 0 for r in plain_rows)
    pairs = {(p["line"], p["against"]) for p in payload["paired"]}
    assert pairs == {(n, ea.PLAIN) for n in names - {ea.PLAIN}} | {
        (n, ea.LIVE) for n in names - {ea.LIVE}
    }
    for p in payload["paired"]:
        assert {"mean_daily_bp", "hac_t", "psr", "sessions"} <= set(p)
    described = {v["name"]: v["options"] for v in payload["variants"]}
    assert described[ea.LIVE]["event_exposure"] == "event_risk.live_path(panel)"
    assert described["live-event"]["event_exposure"] is None
    # A variant that reproduces plain has a zero paired difference against it.
    same = [
        p
        for p in payload["paired"]
        if p["line"] == "plain+event" and p["against"] == ea.PLAIN
    ]
    assert same and all(abs(p["mean_daily_bp"]) < 1e-9 for p in same)


# A variant `simulate.run` refuses is recorded with the reason and left
# out of the rows, never silently skipped; the rest still run.
def test_refused_variant_is_recorded(history, monkeypatch):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    broken = ea.Variant(
        "live-broken", ea.LIVE, removed=("exit_at_close",), note="keeps deferred_buys"
    )
    monkeypatch.setattr(ea, "VARIANTS", ea.VARIANTS + (broken,))
    payload = ea.run_variants(report, restricted, mask, None, 1, (10.0,))
    assert payload["trials"] == 11
    assert "live-broken" in payload["refused"]
    assert "deferred_buys requires exit_at_close" in payload["refused"]["live-broken"]
    assert "live-broken" not in {r["line"] for r in payload["rows"]}
    assert "live-broken" not in payload["ran"] and ea.LIVE in payload["ran"]
    assert len({r["line"] for r in payload["rows"]}) == 10
    verdict = ea.verdict(payload)
    assert verdict["options"]["live-broken"]["measured"] is False
    assert verdict["options"]["live-broken"]["decision"] == ea.KEEP
    assert "requires exit_at_close" in verdict["options"]["live-broken"]["refused"]


# A payload with the given per-variant CAGRs, t statistics and reported
# differences at 25 bp.
def _payload(
    choosing: dict[str, float],
    t: dict[str, float],
    reported_bp: dict[str, float],
    reported_cagr=None,
):
    rows, paired = [], []
    for name, cagr in choosing.items():
        rows.append(
            {"line": name, "cost_bps": 25.0, "window": ea.CHOOSING, "median_cagr": cagr}
        )
        rows.append(
            {
                "line": name,
                "cost_bps": 25.0,
                "window": ea.REPORTED,
                "median_cagr": (reported_cagr or {}).get(name, 0.1),
            }
        )
        if name != ea.LIVE:
            paired.append(
                {
                    "line": name,
                    "against": ea.LIVE,
                    "cost_bps": 25.0,
                    "window": ea.CHOOSING,
                    "mean_daily_bp": (cagr - choosing[ea.LIVE]) * 1e4 / 252,
                    "hac_t": t.get(name, 0.0),
                }
            )
            paired.append(
                {
                    "line": name,
                    "against": ea.LIVE,
                    "cost_bps": 25.0,
                    "window": ea.REPORTED,
                    "mean_daily_bp": reported_bp.get(name, 0.0),
                    "hac_t": 0.0,
                }
            )
    return {"costs_bps": [10.0, 25.0], "rows": rows, "paired": paired, "refused": {}}


# The verdict's floors on a hand-built payload: a removal earning 1.5
# points with t 2.5 and not worse later is REMOVE (registered); one
# earning 1.5 points with t 1.5 is KEEP; one earning 0.8 points with t 3
# is KEEP; one earning 2 points with t 3 but worse later is KEEP; one that
# costs points is KEEP with a negative effect. The reconstruction sums the
# single removals against the plain-minus-live gap.
def test_verdict_floors_and_reconstruction():
    choosing = {ea.PLAIN: 0.277, ea.LIVE: 0.233}
    for v in REMOVED_VARIANTS:
        choosing[v.name] = 0.233
    choosing["live-green_day_skip"] = 0.248  # +1.5 pt
    choosing["live-deferred_buys"] = 0.248  # +1.5 pt, weak t
    choosing["live-block_overbought"] = 0.241  # +0.8 pt
    choosing["live-live_midcycle"] = 0.253  # +2.0 pt, worse later
    choosing["live-event"] = 0.223  # -1.0 pt
    t = {
        "live-green_day_skip": 2.5,
        "live-deferred_buys": 1.5,
        "live-block_overbought": 3.0,
        "live-live_midcycle": 3.0,
    }
    reported = {
        "live-green_day_skip": 0.5,
        "live-deferred_buys": 0.5,
        "live-block_overbought": 0.5,
        "live-live_midcycle": -0.5,
    }
    verdict = ea.verdict(_payload(choosing, t, reported))
    assert verdict["cost_bps"] == 25.0
    assert verdict["gap_points"] == pytest.approx(4.4)
    decisions = {k: v["decision"] for k, v in verdict["options"].items()}
    assert decisions["live-green_day_skip"] == ea.REMOVE
    assert decisions["live-deferred_buys"] == ea.KEEP
    assert decisions["live-block_overbought"] == ea.KEEP
    assert decisions["live-live_midcycle"] == ea.KEEP
    assert decisions["live-event"] == ea.KEEP
    assert decisions["live-exit_at_close"] == ea.KEEP
    assert verdict["options"]["live-event"]["choosing_points"] == pytest.approx(-1.0)
    assert verdict["options"]["live-live_midcycle"]["passes_choosing"] is True
    assert verdict["options"]["live-live_midcycle"]["not_worse_reported"] is False
    assert verdict["remove"] == ["live-green_day_skip"]
    assert len(verdict["keep"]) == len(REMOVED_VARIANTS) - 1
    # 1.5 + 1.5 + 0.8 + 2.0 - 1.0 + 0.0 = 4.8 against a 4.4 gap.
    assert verdict["sum_of_single_removals"] == pytest.approx(4.8)
    assert verdict["interaction_points"] == pytest.approx(-0.4)
    assert "REMOVE (registered): live-green_day_skip" in verdict["text"]
    assert "gap +4.4 pt" in verdict["text"]
    # Nothing to remove: the text says so.
    flat = ea.verdict(
        _payload(
            {
                ea.PLAIN: 0.277,
                ea.LIVE: 0.233,
                **{v.name: 0.233 for v in REMOVED_VARIANTS},
            },
            {},
            {},
        )
    )
    assert flat["remove"] == [] and "every option is KEEP" in flat["text"]
    # Without 25 bp the verdict reads the largest cost; without live it is not measured.
    empty = ea.verdict(
        {"costs_bps": [10.0], "rows": [], "paired": [], "refused": {"live": "x"}}
    )
    assert empty["cost_bps"] == 10.0 and empty["text"].startswith("not measured")
    assert math.isnan(empty["gap_points"])


# The command end to end on the synthetic book: the file, the payload
# shape, the trial count and the verdict text; `--json` prints the payload.
def test_cli_end_to_end(history, tmp_path):
    calls = []

    def fake_desk(store):
        calls.append(str(store.root))
        return _report()

    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--offsets",
            "2",
            "--costs",
            "25",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    assert calls == [str(tmp_path)]
    target = tmp_path / "desk" / "execution_ablation.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == "execution_ablation"
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["trials"] == 10 and len(payload["variants"]) == 10
    assert payload["offsets"] == 2 and payload["costs_bps"] == [25.0]
    assert len(payload["rows"]) == 10 * 3
    assert set(payload["windows"]) == {"2016-2023", "2024-2026", "all"}
    assert payload["refused"] == {}
    assert payload["membership_history"] == str(history)
    verdict = payload["verdict"]
    assert verdict["cost_bps"] == 25.0
    assert set(verdict["options"]) == {v.name for v in REMOVED_VARIANTS}
    assert all(
        v["decision"] in (ea.REMOVE, ea.KEEP) for v in verdict["options"].values()
    )
    assert verdict["text"].startswith("2016-2023 at 25 bp") or verdict[
        "text"
    ].startswith("not measured")
    text = out.getvalue()
    assert "execution ablation for graded-equal-weight/4" in text
    assert "10 registered variants" in text
    assert "live-exit_at_close" in text and "plain+event" in text
    assert "verdict:" in text and "Reconstruction" in text
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--offsets",
            "1",
            "--costs",
            "10",
            "--json",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    printed = json.loads(out.getvalue())
    assert printed["offsets"] == 1 and printed["verdict"]["cost_bps"] == 10.0
