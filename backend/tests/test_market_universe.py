"""The research universe: the committed file, the overlay, the themes."""

from datetime import UTC, datetime

from backend.cli.market_universe import parse_constituents_html, write_constituents
from backend.market.universe import (
    AI_COMPUTE,
    BENCHMARK,
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    MEMORY_STORAGE,
    build_universe,
    load_constituents,
    source_symbol,
    theme_map,
    tickers_with_role,
)

_PAGE = (
    """
<html><body>
<table id="constituents" class="wikitable">
<tbody><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th>
<th>GICS Sub-Industry</th><th>HQ</th></tr>
"""
    + "".join(
        f'<tr><td><a href="#">{sym}</a></td><td>{name}</td>'
        f"<td>{sector}</td><td>{sub}</td><td>x</td></tr>"
        for sym, name, sector, sub in [
            ("NVDA", "Nvidia", "Information Technology", "Semiconductors"),
            ("BRK.B", "Berkshire &amp; Co", "Financials", "Multi-Sector Holdings"),
            (
                "SNDK",
                "SanDisk",
                "Information Technology",
                "Technology Hardware, Storage &amp; Peripherals",
            ),
        ]
        + [(f"T{i:03d}", f"Name {i}", "Industrials", "Machinery") for i in range(400)]
    )
    + "</tbody></table></body></html>"
)


# The committed universe holds the focus names, is deduplicated, and the
# market benchmark is present.
def test_committed_universe_is_well_formed():
    universe = build_universe()
    tickers = [m.ticker for m in universe]
    assert len(tickers) == len(set(tickers))
    assert tickers_with_role(universe, FOCUS) == ("CRWV", "IREN", "SNDK")
    assert MARKET_BENCHMARK in tickers_with_role(universe, BENCHMARK)
    assert len(tickers_with_role(universe, MEMBER)) > 450
    themes = theme_map(universe)
    assert AI_COMPUTE in themes["CRWV"]
    assert MEMORY_STORAGE in themes["SNDK"]
    assert AI_COMPUTE in themes["NVDA"]  # from GICS: Semiconductors


# The page parser reads Wikipedia's table shape, and the file round-trips.
def test_constituents_parse_and_round_trip(tmp_path):
    rows = parse_constituents_html(_PAGE)
    assert ("NVDA", "Nvidia", "Information Technology", "Semiconductors") in rows
    assert ("BRK.B", "Berkshire & Co", "Financials", "Multi-Sector Holdings") in rows
    path = tmp_path / "constituents.csv"
    write_constituents(rows, path, datetime(2026, 9, 5, tzinfo=UTC))
    loaded = {m.ticker: m for m in load_constituents(path)}
    assert loaded["BRK-B"].sector == "Financials"  # source symbol form
    assert loaded["NVDA"].themes == (AI_COMPUTE,)
    assert path.read_text(encoding="utf-8").startswith(
        "# S&P 500 constituents as of 2026-09-05"
    )


# The overlay adds themes to a constituent and keeps its GICS data, adds
# non-constituents, and its role wins.
def test_overlay_merges_with_constituents(tmp_path):
    rows = parse_constituents_html(_PAGE)
    path = tmp_path / "constituents.csv"
    write_constituents(rows, path, datetime(2026, 9, 5, tzinfo=UTC))
    universe = {m.ticker: m for m in build_universe(load_constituents(path))}
    assert universe["SNDK"].role == FOCUS
    assert universe["SNDK"].sub_industry.startswith("Technology Hardware")
    assert MEMORY_STORAGE in universe["SNDK"].themes
    assert universe["NVDA"].themes[0] == AI_COMPUTE
    assert MEMORY_STORAGE in universe["NVDA"].themes
    assert universe["CRWV"].role == FOCUS
    assert universe["CRWV"].sector == ""


# Class shares use the data source's hyphen form.
def test_source_symbol_form():
    assert source_symbol("brk.b") == "BRK-B"
    assert source_symbol(" NVDA ") == "NVDA"
