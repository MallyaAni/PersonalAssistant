"""A fixed, bounded public-filing corpus for the offline grounded-text comparison."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from backend.agents.trading.grounded_release import MAX_CHARS, text_hash
from backend.cli.market_grounded_release import write_report
from backend.market import edgar, language
from backend.market.store import MarketStore

TICKERS = ("AAOI", "ORCL", "NVDA", "MU", "ADBE", "INTC")
CUTOFFS = (date(2022, 12, 31), date(2026, 9, 30))
ASOF = date(2026, 9, 30)
MAX_HTML_BYTES = 4_000_000


# Select by ticker and filing date only, without consulting prices or model scores.
def select_events(store: MarketStore) -> list[dict]:
    selected = []
    for ticker in TICKERS:
        frame = store.read_frame("edgar_events", ticker, ASOF)
        for cutoff in CUTOFFS:
            row = {
                "id": f"{ticker}-{cutoff.year}",
                "ticker": ticker,
                "cutoff": cutoff.isoformat(),
            }
            if frame is None:
                selected.append({**row, "status": "missing_events"})
                continue
            columns, meta = frame
            eligible = [
                i
                for i, filed in enumerate(columns["filed"])
                if date.fromisoformat(str(filed)) <= cutoff
                and "2.02" in str(columns["items"][i]).replace(" ", "").split(",")
            ]
            if not eligible:
                selected.append({**row, "status": "missing_event"})
                continue
            index = max(
                eligible,
                key=lambda i: (str(columns["accepted"][i]), columns["accession"][i]),
            )
            accession = columns["accession"][index]
            cik = int(meta["cik"])
            selected.append(
                {
                    **row,
                    "status": "selected",
                    "cik": cik,
                    "accession": accession,
                    "published_at": str(columns["accepted"][index]),
                    "filed": str(columns["filed"][index]),
                    "index_url": (
                        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                        f"{accession.replace('-', '')}/{accession}-index.html"
                    ),
                }
            )
    return selected


# Fetch one allowlisted SEC archive document, paced and without hidden retries.
def fetch_html(url: str, cik: int, pacer: edgar.Pacer, transport) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.sec.gov"
        or not parsed.path.startswith(f"/Archives/edgar/data/{cik}/")
    ):
        raise ValueError("Source URL is outside the selected SEC issuer archive")
    pacer.wait()
    status, body = transport(url)
    if status != 200:
        raise ValueError(f"SEC returned HTTP {status}")
    if len(body) > MAX_HTML_BYTES:
        raise ValueError("Source exceeds the HTML byte bound")
    return body.decode("utf-8", errors="replace")


# Collect only the registered sample, preserving failures and full-text eligibility.
def collect(store: MarketStore, transport=edgar.sec_transport) -> dict:
    rows = select_events(store)
    pacer = edgar.Pacer()
    consecutive_failures = 0
    for row in rows:
        if row["status"] != "selected":
            continue
        if consecutive_failures >= 3:
            row["status"] = "not_fetched_after_three_failures"
            continue
        try:
            index = fetch_html(row["index_url"], row["cik"], pacer, transport)
            row["index_sha256"] = text_hash(index)
            url = language.press_release_href(language.parse_index_page(index))
            if url is None:
                raise ValueError("No results exhibit in the filing index")
            row["source_url"] = url
            html = fetch_html(url, row["cik"], pacer, transport)
            text = edgar.html_to_text(html)
            if not text.strip():
                raise ValueError("Empty extracted release")
            row.update(
                status="ready" if len(text) <= MAX_CHARS else "oversize",
                source_html_sha256=text_hash(html),
                text=text,
                source_sha256=text_hash(text),
                source_chars=len(text),
                retrieved_at=datetime.now(UTC).isoformat(),
            )
            consecutive_failures = 0
        except Exception as exc:
            row.update(status="fetch_failed", error=type(exc).__name__)
            if isinstance(exc, ValueError):
                row["error_detail"] = str(exc)
            consecutive_failures += 1
        print(f"{row['id']}: {row['status']}", flush=True)
    return {"scope": "fixed public-release extraction corpus", "rows": rows}


# Collect into a new research artifact, never the live market store.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing corpus")
    result = collect(MarketStore(args.data_dir))
    write_report(args.output, result)
    print(
        f"{sum(row['status'] == 'ready' for row in result['rows'])}/{len(result['rows'])} ready"
    )


if __name__ == "__main__":
    main()
