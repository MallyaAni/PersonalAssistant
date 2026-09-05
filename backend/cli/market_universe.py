"""Rebuild the committed constituent file from a free public source.

The broad universe is the current S&P 500 with each member's GICS sector
and sub-industry, read from Wikipedia's constituents table — the one free
source that carries the industry classification. The file is committed so
every run reads the same universe and so the date it was taken is on
record, which is the date the survivorship caveat applies to.

    python -m backend.cli.market_universe --refresh
    python -m backend.cli.market_universe --show
"""

import argparse
import csv
import html
import re
from datetime import UTC, datetime
from pathlib import Path

from backend.market.universe import (
    BENCHMARK,
    CONSTITUENTS_PATH,
    FOCUS,
    MEMBER,
    build_universe,
    load_constituents,
)

_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


# Strip tags and entities from one table cell.
def _clean(cell: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", cell)).strip()


# Parse the constituents table out of the page HTML into rows of
# (ticker, name, sector, sub_industry). Pure, so a test can feed it a saved
# page and never touch the network.
def parse_constituents_html(page: str) -> list[tuple[str, str, str, str]]:
    """Return (ticker, name, sector, sub_industry) rows from the S&P 500 page."""
    match = re.search(r'<table[^>]*id="constituents"[^>]*>(.*?)</table>', page, re.S)
    if not match:
        raise ValueError("constituents table not found in page")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(1), re.S)
    header = [_clean(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.S)]
    try:
        symbol = header.index("Symbol")
        security = header.index("Security")
        sector = header.index("GICS Sector")
        sub_industry = header.index("GICS Sub-Industry")
    except ValueError as exc:
        raise ValueError(f"unexpected constituents header: {header}") from exc
    out: list[tuple[str, str, str, str]] = []
    for row in rows[1:]:
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) <= max(symbol, security, sector, sub_industry):
            continue
        out.append((cells[symbol], cells[security], cells[sector], cells[sub_industry]))
    if len(out) < 400:
        raise ValueError(f"only {len(out)} constituents parsed; page shape changed?")
    return out


# Fetch the page with the same impersonating transport the market fetcher
# uses; Wikipedia does not need it but one transport is one to maintain.
def _fetch_page(url: str) -> str:
    from curl_cffi import requests

    response = requests.get(url, impersonate="chrome", timeout=30)
    response.raise_for_status()
    return response.text


# Write the constituent CSV with a dated header comment.
def write_constituents(
    rows: list[tuple[str, str, str, str]], path: Path, taken: datetime
) -> None:
    """Write constituent rows to `path` with a comment recording the date taken."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(
            f"# S&P 500 constituents as of {taken.date().isoformat()}, "
            f"from {_SP500_URL}\n"
        )
        writer = csv.writer(handle)
        writer.writerow(["ticker", "name", "sector", "sub_industry"])
        for row in sorted(rows):
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the universe tool."""
    parser = argparse.ArgumentParser(
        description="Rebuild or show the research universe."
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Re-fetch the constituent file."
    )
    parser.add_argument(
        "--show", action="store_true", help="Print the universe by role and theme."
    )
    parser.add_argument(
        "--path", type=Path, default=CONSTITUENTS_PATH, help="Constituent CSV path."
    )
    return parser


# Run the tool: refresh the file and/or print the universe.
def main() -> None:
    """Entry point: refresh the constituents and/or show the universe."""
    args = build_parser().parse_args()
    if args.refresh:
        rows = parse_constituents_html(_fetch_page(_SP500_URL))
        write_constituents(rows, args.path, datetime.now(tz=UTC))
        print(f"{len(rows)} constituents written to {args.path}")
    if args.show or not args.refresh:
        universe = build_universe(load_constituents(args.path))
        by_role = {FOCUS: 0, MEMBER: 0, BENCHMARK: 0}
        by_theme: dict[str, int] = {}
        for member in universe:
            by_role[member.role] += 1
            for theme in member.themes:
                by_theme[theme] = by_theme.get(theme, 0) + 1
        print(
            f"universe: {len(universe)} tickers  "
            + "  ".join(f"{k}={v}" for k, v in by_role.items())
        )
        print("themes:   " + "  ".join(f"{k}={v}" for k, v in sorted(by_theme.items())))


if __name__ == "__main__":
    main()
