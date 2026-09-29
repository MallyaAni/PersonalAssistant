"""The support/resistance fill conventions in the fill-timing engine.

What has to hold (docs/research/sr-levels-plan-2026-09-29.md):

- On hand-built bars:
  - `level_dip` buys at the first close from slot 2 inside a support zone
    while below the open, never earlier;
  - a zone above the open is passed over;
  - no zone fills at the official close;
  - the confluence variant needs two distinct levels;
  - sells mirror;
  - missing zones are refused.
- `cube_prices` is exactly `sr_fills` on zones from `sr_levels`, at the
  fills' own split-safe scale.
- The controls are untouched:
  - `session_scale` is the old inline arithmetic;
  - the fill-timing trial's rows, best and verdict are byte-identical with
    the SR pair priced beside it;
  - a cube session the panel lacks no longer breaks the scale.
- A world whose every dip bottoms at the prior day's low makes `level_dip`
  REPLACE the board's rule. Bridge noise RECORDS.
- The criteria at their edges.
- `--only` with the SR pair adds `dip_or_close` and nothing else.
- The command writes `sr_level_fill.json`.
"""

from __future__ import annotations

import io
import json
import math

import numpy as np
import pytest

from backend.cli import market_fill_timing as cli
from backend.market import fill_timing as ft
from backend.market import sr_levels
from backend.market.panel import Panel
from backend.market.session_anatomy import json_ready
from backend.market.sip_cube import SessionCube
from backend.tests import test_fill_timing as base
from backend.tests import test_fill_timing_levels as lv

SLOTS = base.SLOTS


# A hand-built session opening at 100 whose closes fall a tenth a bar
# from 99.9, so every close from slot 0 is below the open; flat volume.
def _falling(auction: float = math.nan) -> dict:
    close = 99.9 - 0.1 * np.arange(SLOTS)
    return {
        "open": np.concatenate([[100.0], close[:-1]]),
        "high": close + 0.05,
        "low": close - 0.05,
        "close": close,
        "volume": np.full(SLOTS, 100.0),
        "auction_open": auction,
    }


# The support and resistance confluence rows of one session: `support` and
# `resistance` map slots to the confluence of a zone holding that close.
def _zones(
    support: dict[int, int] | None = None, resistance: dict[int, int] | None = None
):
    grid = {
        "support": np.zeros(SLOTS, dtype=np.int64),
        "resistance": np.zeros(SLOTS, dtype=np.int64),
    }
    for side, marks in (("support", support or {}), ("resistance", resistance or {})):
        for slot, count in marks.items():
            grid[side][slot] = count
    return sr_levels.CloseZones(grid["support"], grid["resistance"])


# The SR trial's registered constants.
def test_sr_constants_are_the_plans():
    assert ft.SR_CONVENTIONS == ("level_dip", "level_dip_confluence")
    assert ft.SR_MIN_CONFLUENCE == {"level_dip": 1, "level_dip_confluence": 2}
    assert ft.SR_TRIALS == 2
    assert (ft.REPLACE_BP, ft.REPLACE_T) == (2.0, 2.0)
    assert ft.KNOWN_CONVENTIONS == ft.ALL_CONVENTIONS + ft.SR_CONVENTIONS
    assert ft.ALL_CONVENTIONS == ft.CONVENTIONS + ft.LEVEL_CONVENTIONS
    assert set(ft.SR_CONVENTIONS) <= set(ft.WAITING)
    assert ft.SR_PLAN == "docs/research/sr-levels-plan-2026-09-29.md"


# The fill rule on hand-built bars. A support zone at slot 5 under the open
# buys at slot 5's close; a zone at slot 1 (before 10:15) is ignored even
# when the grid marks it. With no zone the fill is the official close, the
# auction print when present. The confluence variant skips a one-level
# zone for a two-level one. A zone whose close is above the open is not a
# buy. Sells mirror on resistance above the open.
def test_level_dip_fill_prices_on_hand_built_paths():
    row = _falling()
    close = row["close"]
    assert ft.fill_price(row, "level_dip", "buy", zones=_zones({5: 1})) == close[5]
    assert (
        ft.fill_price(row, "level_dip", "buy", zones=_zones({1: 3, 7: 1})) == close[7]
    )
    assert ft.fill_price(row, "level_dip", "buy", zones=_zones()) == close[-1]
    assert (
        ft.fill_price(_falling(auction=97.3), "level_dip", "buy", zones=_zones())
        == 97.3
    )
    assert (
        ft.fill_price(row, "level_dip_confluence", "buy", zones=_zones({5: 1, 9: 2}))
        == close[9]
    )
    assert (
        ft.fill_price(row, "level_dip", "buy", zones=_zones({5: 1, 9: 2})) == close[5]
    )
    # A close above the open is never a buy, whatever the grid says.
    above = _falling()
    above["close"] = 100.1 + 0.1 * np.arange(SLOTS)
    above["open"] = np.concatenate([[100.0], above["close"][:-1]])
    assert (
        ft.fill_price(above, "level_dip", "buy", zones=_zones({3: 2}))
        == above["close"][-1]
    )
    # Sells: a resistance zone above the open fills; one below does not.
    assert (
        ft.fill_price(above, "level_dip", "sell", zones=_zones(resistance={6: 1}))
        == above["close"][6]
    )
    assert (
        ft.fill_price(row, "level_dip", "sell", zones=_zones(resistance={6: 1}))
        == close[-1]
    )
    assert (
        ft.fill_price(above, "level_dip", "sell", zones=_zones(support={6: 3}))
        == above["close"][-1]
    )
    with pytest.raises(ValueError, match="needs the close zones"):
        ft.fill_price(row, "level_dip", "buy")
    with pytest.raises(ValueError, match="not an SR convention"):
        ft.sr_fills(lv._one_session(row), "dip_or_close", "buy", _zones())


# The engine's SR prices are `sr_fills` on the zones `sr_levels` builds from
# the panel and the cube, times the fills' own split-safe scale, on a world
# with per-name adjustment factors. The detail marks a fill at a level
# exactly where the price is not the official close.
def test_cube_prices_are_sr_fills_on_sr_levels_zones():
    factor = np.array([1.0, 0.5, 2.0, 0.9, 1.1])
    report, mask, cubes = base._world(t=260, n=5, seed=4, factor=factor[None, :])
    panel = report.panel
    zones = ft.sr_zones(cubes, panel)
    daily = sr_levels.daily_levels(panel)
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    fills = 0
    for convention in ft.SR_CONVENTIONS:
        prices = ft.cube_prices(cubes, panel, convention, zones=zones)
        for j, ticker in enumerate(panel.tickers[:-1]):
            cube = cubes[ticker]
            pos, ok, scale = ft.session_scale(cube, dates, panel.adj_close[:, j])
            levels = sr_levels.for_cube(cube, daily, j, pos, ok, scale)
            own = sr_levels.close_zones(levels, sr_levels.confluence(levels))
            np.testing.assert_array_equal(zones[ticker].support, own.support)
            np.testing.assert_array_equal(zones[ticker].resistance, own.resistance)
            for side, grid, hits in (
                ("buy", prices.buy, prices.detail.buy_hit),
                ("sell", prices.sell, prices.detail.sell_hit),
            ):
                price, hit = ft.sr_fills(cube, convention, side, own)
                np.testing.assert_allclose(grid[pos, j], price * scale, rtol=1e-12)
                np.testing.assert_array_equal(hits[pos, j], hit)
                fills += int(hit.sum())
        assert not prices.detail.no_sigma.any()
    assert fills > 0
    with pytest.raises(ValueError, match="needs the close zones"):
        ft.cube_prices(cubes, panel, "level_dip")
    with pytest.raises(ValueError, match="no close zones for"):
        ft.cube_prices(cubes, panel, "level_dip", zones={})


# The scale onto the panel's adjusted basis before this change, frozen
# verbatim from `cube_prices` (it assumed every cube session is on the
# panel).
def _frozen_scale(
    cube: SessionCube, panel, j: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    rows = len(dates)
    pos = np.searchsorted(dates, cube.dates)
    ok = (pos < rows) & (dates[np.minimum(pos, rows - 1)] == cube.dates)
    official = np.where(
        np.isfinite(cube.auction_open) & (cube.auction_open > 0),
        cube.auction_open,
        cube.close[:, -1],
    )
    with np.errstate(all="ignore"):
        scale = np.where(
            official > 0, panel.adj_close[pos[ok], j] / official[ok], np.nan
        )
    return pos, ok, scale


# The controls are untouched. `session_scale` gives the frozen scale
# bit for bit, on cubes with and without auction prints. The fill-timing
# trial's rows, best, verdict and gap are byte-identical whether or not the
# SR pair is priced beside it. A cube session missing from the panel now
# scales to NaN instead of breaking the arithmetic.
def test_controls_are_unchanged_beside_the_sr_pair():
    report, mask, cubes = base._world(t=200, n=6, seed=8)
    panel = report.panel
    first = next(iter(cubes))
    holes = cubes[first].auction_open.copy()
    holes[::3] = np.nan
    from dataclasses import replace

    cubes = {**cubes, first: replace(cubes[first], auction_open=holes)}
    for j, ticker in enumerate(panel.tickers[:-1]):
        pos, ok, scale = _frozen_scale(cubes[ticker], panel, j)
        new_pos, new_ok, full = ft.session_scale(
            cubes[ticker], panel.dates, panel.adj_close[:, j]
        )
        np.testing.assert_array_equal(new_pos, pos)
        np.testing.assert_array_equal(new_ok, ok)
        assert full[new_ok].tobytes() == scale.tobytes()
    plain = ft.study(report, cubes, mask, offsets=3)
    both = ft.study(
        report, cubes, mask, offsets=3, conventions=ft.CONVENTIONS + ft.SR_CONVENTIONS
    )
    assert "sr_level" not in plain
    assert both["conventions"] == list(ft.CONVENTIONS + ft.SR_CONVENTIONS)
    by_key = {(r["convention"], r["window"]): r for r in both["rows"]}
    for r in plain["rows"]:
        twin = by_key[(r["convention"], r["window"])]
        assert json.dumps(
            json_ready({k: twin[k] for k in r}), sort_keys=True
        ) == json.dumps(json_ready(r), sort_keys=True)
    for key in (
        "best",
        "verdict",
        "adopted",
        "criteria",
        "breakout_gate",
        "simulator_gap",
    ):
        assert json.dumps(json_ready(both[key]), sort_keys=True) == json.dumps(
            json_ready(plain[key]), sort_keys=True
        )
    # A cube with a session the panel lacks: NaN scale there, the rest kept.
    cube = cubes[first]
    extra = replace(
        cube,
        dates=np.concatenate([cube.dates, [cube.dates[-1] + np.timedelta64(400, "D")]]),
        open=np.vstack([cube.open, cube.open[-1:]]),
        high=np.vstack([cube.high, cube.high[-1:]]),
        low=np.vstack([cube.low, cube.low[-1:]]),
        close=np.vstack([cube.close, cube.close[-1:]]),
        volume=np.vstack([cube.volume, cube.volume[-1:]]),
        prior_close=np.append(cube.prior_close, np.nan),
        auction_open=np.append(cube.auction_open, 100.0),
        auction_volume=np.append(cube.auction_volume, np.nan),
    )
    _, ok, full = ft.session_scale(extra, panel.dates, panel.adj_close[:, 0])
    assert not ok[-1]
    assert math.isnan(full[-1])
    assert (
        full[:-1][ok[:-1]].tobytes()
        == ft.session_scale(cube, panel.dates, panel.adj_close[:, 0])[2].tobytes()
    )
    prices = ft.cube_prices({**cubes, first: extra}, panel, "next_open")
    np.testing.assert_array_equal(
        prices.buy, ft.cube_prices(cubes, panel, "next_open").buy
    )


# A world whose every session opens and closes at 100 and falls in a
# straight line to `100 x (1 - depth)` at slot 7 before climbing back, with
# volume only near the bottom, and daily bars to match (high 100, low the
# bottom). The bottom is the prior day's and week's low and a volume node:
# a real support. The board's rule buys at the first close 1% down; the
# level rule waits for the zone around the bottom.
def _floor_world(t: int = 620, n: int = 9, seed: int = 3, depth: float = 0.08):
    rng = np.random.default_rng(seed)
    dates = base._dates(t)
    tickers = base.NAMES[: n - 1] + ("SPY",)
    top, bottom = 100.0, 100.0 * (1.0 - depth)
    close = np.empty(SLOTS)
    close[:8] = top * (1.0 - depth * (np.arange(8) + 1) / 8.0)
    close[8:] = bottom + (top - bottom) * (np.arange(8, SLOTS) - 7) / 18.0
    opens = np.concatenate([[top], close[:-1]])
    volume = np.zeros(SLOTS)
    volume[6:10] = 1000.0
    flat = np.full((t, n), top)
    panel = Panel(
        dates=dates,
        tickers=tickers,
        open=flat,
        high=flat.copy(),
        low=np.full((t, n), bottom),
        close=flat.copy(),
        adj_close=flat.copy(),
        volume=np.full((t, n), 1e6),
        themes={k: () for k in tickers[:-1]},
        benchmark="SPY",
    )
    report = base._report(dates, flat, flat, base._grades(rng, t, n))
    from dataclasses import replace

    report = replace(report, panel=panel)
    mask = np.ones((t, n), dtype=bool)
    mask[:, -1] = False
    tile = lambda row: np.tile(row, (t, 1))  # noqa: E731 - one session's bars on every date
    cubes = {
        name: SessionCube(
            ticker=name,
            dates=dates,
            open=tile(opens),
            high=tile(np.maximum(opens, close)),
            low=tile(np.minimum(opens, close)),
            close=tile(close),
            volume=tile(volume),
            prior_close=np.full(t, np.nan),
            excluded={},
            auction_open=np.full(t, top),
            auction_volume=np.full(t, np.nan),
        )
        for name in tickers[:-1]
    }
    return report, mask, cubes


# Where every dip bottoms at a real support, waiting for the zone beats
# buying at the first 1%. Both SR conventions beat dip_or_close by more
# than the floor with a large t, are not worse on the reported window, fill
# at a level on most buys (sells find no zone above the open and go to the
# close), and REPLACE. Their gain per level fill is several points more
# than the board's.
def test_real_support_replaces_the_board_rule():
    report, mask, cubes = _floor_world()
    payload = ft.study(report, cubes, mask, offsets=3, conventions=ft.SR_CONVENTIONS)
    assert payload["conventions"] == ["next_open", "dip_or_close", *ft.SR_CONVENTIONS]
    rows = {(r["convention"], r["window"]): r for r in payload["rows"]}
    block = payload["sr_level"]
    for convention in ft.SR_CONVENTIONS:
        choose = rows[(convention, ft.CHOOSING)]
        assert choose["mean_daily_bp_vs_dip"] >= ft.REPLACE_BP
        assert choose["hac_t_vs_dip"] >= ft.REPLACE_T
        assert choose["offsets_above_dip"] == 3
        assert rows[(convention, ft.REPORTED)]["mean_daily_bp_vs_dip"] > 0
        assert block["criteria"][convention]["label"] == ft.REPLACES
        fills = block["fills"][convention][ft.CHOOSING]
        board = block["fills"]["dip_or_close"][ft.CHOOSING]
        assert fills["gain_bp_per_level_fill"] > board["gain_bp_per_level_fill"] + 200
        assert 0.3 < fills["level_fill_rate"] < 1.0
    assert block["replaces"] == list(ft.SR_CONVENTIONS)
    assert block["verdict"].startswith(ft.REPLACES)
    assert block["best"][ft.CHOOSING]["trials"] == ft.SR_TRIALS
    assert 0.0 <= block["best"][ft.CHOOSING]["deflated_sharpe"] <= 1.0
    assert block["min_confluence"] == ft.SR_MIN_CONFLUENCE
    assert block["constants"]["LEVELS"] == list(sr_levels.KINDS)
    # The fill-timing trial is not judged on a run of the SR pair alone.
    assert payload["verdict"].startswith("NOT JUDGED")
    assert "level" not in payload


# Bridge noise with no support in it: neither SR convention clears the
# floors against dip_or_close, and the verdict is RECORD.
def test_noise_records():
    report, mask, cubes = base._world(t=620, n=6, seed=2)
    payload = ft.study(report, cubes, mask, offsets=3, conventions=ft.SR_CONVENTIONS)
    block = payload["sr_level"]
    assert block["replaces"] == []
    assert block["verdict"].startswith(ft.RECORD)
    assert "keeps dip_or_close" in block["verdict"]
    for convention in ft.SR_CONVENTIONS:
        assert block["criteria"][convention]["label"] == ft.RECORD
        assert not block["criteria"][convention]["passes_choosing"]
    assert len(payload["rows"]) == 4 * 3


# The criteria on hand-built rows: each floor at its edge, the reported
# window's sign, and a missing number passing nothing.
def test_sr_verdict_applies_the_criteria():
    # A payload with level_dip's choosing bp and t and its reported bp.
    def payload(bp, t, later):
        return {
            "conventions": ["next_open", "dip_or_close", "level_dip"],
            "rows": [
                {
                    "convention": "level_dip",
                    "window": ft.CHOOSING,
                    "mean_daily_bp_vs_dip": bp,
                    "hac_t_vs_dip": t,
                },
                {
                    "convention": "level_dip",
                    "window": ft.REPORTED,
                    "mean_daily_bp_vs_dip": later,
                    "hac_t_vs_dip": 0.0,
                },
            ],
        }

    at_floor = ft.sr_verdict(payload(2.0, 2.0, 0.0))
    assert at_floor["replaces"] == ["level_dip"]
    assert at_floor["verdict"].startswith(ft.REPLACES)
    for bp, t, later in (
        (1.99, 3.0, 1.0),
        (3.0, 1.99, 1.0),
        (3.0, 3.0, -0.01),
        (3.0, 3.0, None),
        (math.nan, 3.0, 1.0),
    ):
        out = ft.sr_verdict(payload(bp, t, later))
        assert out["replaces"] == []
        assert out["criteria"]["level_dip"]["label"] == ft.RECORD
        assert out["verdict"].startswith(ft.RECORD)


# The conventions a run prices: the SR pair only when named, with
# next_open and dip_or_close added and never the trailing twin; the default
# sets never include them; an unknown name is still refused; the ledger
# accepts them and refuses an unknown one.
def test_select_conventions_with_the_sr_pair():
    assert ft.select_conventions(["level_dip"], False) == (
        "next_open",
        "dip_or_close",
        "level_dip",
    )
    assert ft.select_conventions(["level_dip_confluence", "level_dip"], True) == (
        "next_open",
        "dip_or_close",
        "level_dip",
        "level_dip_confluence",
    )
    assert not set(ft.select_conventions(None, False)) & set(ft.SR_CONVENTIONS)
    assert not set(ft.select_conventions(None, True)) & set(ft.SR_CONVENTIONS)
    assert ft.select_conventions(["vol_dip_0.5", "level_dip"], True) == (
        "next_open",
        "dip_or_close",
        "vol_dip_0.5",
        "trail_dip",
        "level_dip",
    )
    with pytest.raises(ValueError, match="unknown convention"):
        ft.select_conventions(["level_dip", "tea_leaves"], False)
    report, mask, cubes = base._world(t=60, n=4, seed=1)
    targets = ft.target_path(report, mask, None)
    zones = ft.sr_zones(cubes, report.panel)
    prices = ft.cube_prices(cubes, report.panel, "level_dip", zones=zones)
    priced = ft.price_book(targets, report, prices, "level_dip", 10.0)
    assert priced.fills > 0
    assert priced.waits is not None
    with pytest.raises(ValueError, match="unknown convention"):
        ft.price_book(targets, report, prices, "tea_leaves", 10.0)


# The command prices the SR pair from `--only`: dip_or_close is added, the
# payload goes to sr_level_fill.json (the other two files are left alone)
# with the SR block, and the text holds its table and verdict line. No
# forecasts are needed.
def test_cli_prices_the_sr_pair(tmp_path):
    membership, fake_desk, sessions, names, calls = base._sip_store(tmp_path)
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(membership),
            "--workers",
            "1",
            "--offsets",
            "2",
            "--only",
            "level_dip,level_dip_confluence",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    target = tmp_path / "desk" / cli.SR_FILE
    assert target.exists()
    assert not (tmp_path / "desk" / cli.FILE).exists()
    assert not (tmp_path / "desk" / cli.LEVEL_FILE).exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["conventions"] == [
        "next_open",
        "dip_or_close",
        "level_dip",
        "level_dip_confluence",
    ]
    block = payload["sr_level"]
    assert block["verdict"].startswith((ft.REPLACES, ft.RECORD))
    assert set(block["criteria"]) == set(ft.SR_CONVENTIONS)
    assert set(block["fills"]) == {"dip_or_close", *ft.SR_CONVENTIONS}
    assert len(payload["rows"]) == 4 * 3
    rows = {(r["convention"], r["window"]): r for r in payload["rows"]}
    assert rows[("level_dip", "all")]["dip_orders"] > 0
    assert rows[("next_open", "all")]["dip_fill_rate"] is None
    text = out.getvalue()
    assert "support/resistance trial" in text
    assert "support/resistance verdict:" in text
    assert "fill-timing verdict: NOT JUDGED" in text
    assert calls == [str(tmp_path)]
