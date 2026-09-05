"""What companies say, as dated features: the language layer over EDGAR.

The EDGAR layer gives the pipeline every results release and its exact
acceptance time. This module gets the release's text (the EX-99.1 exhibit
of the 8-K, located through the filing's index page, since exhibit file
names are whatever the filer chose), hands it to the trading agent's
release reader, and keeps the scores as an immutable frame per company
beside the events and facts.

`tone_features` turns the stored scores into per-(session, name) inputs
with the same point-in-time rule as everything else: a release's scores are
known from its reaction session onwards, carried forward until the next
release, with the change against the previous release beside them. Names
with no scored release get neutral fills and an indicator.

A batch run through hundreds of companies takes hours on the local model,
so scoring is resumable: each finished company becomes a frame, and a
company in progress keeps a partial file that a rerun picks up.
"""

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from backend.market.edgar import (
    EarningsEvent,
    Pacer,
    Transport,
    _get_json,
    html_to_text,
    sec_transport,
)
from backend.market.panel import Panel

_INDEX_PAGE_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index.html"
)
_ARCHIVE_ROOT = "https://www.sec.gov"

TONE_KIND = "edgar_tone"
SCORE_NAMES: tuple[str, ...] = (
    "guidance",
    "demand",
    "pricing",
    "capex",
    "supply_constrained",
)
FEATURE_NAMES: tuple[str, ...] = tuple(
    [f"tone_{name}" for name in SCORE_NAMES]
    + [f"tone_{name}_change" for name in SCORE_NAMES]
    + ["has_tone"]
)
FEATURE_COUNT = len(FEATURE_NAMES)


@dataclass(frozen=True, slots=True)
class ToneRecord:
    """One release's scores, dated by when the market could first react."""

    accession: str
    reaction_date: date
    guidance: float
    demand: float
    pricing: float
    capex: float
    supply_constrained: float
    summary: str
    model: str
    prompt_version: str
    truncated: bool


# Fetch a page as text with the SEC pacing and retries.
def _get_text(
    url: str, transport: Transport, pacer: Pacer, sleep: Callable[[float], None]
) -> str:
    last = "no attempt"
    for attempt in range(1, 4):
        pacer.wait()
        try:
            status, body = transport(url)
        except Exception as exc:  # network layer
            last = f"transport error: {exc}"
            sleep(2.0 * attempt)
            continue
        if status == 200:
            return body.decode("utf-8", errors="replace")
        last = f"HTTP {status}"
        if status in (403, 429, 500, 502, 503):
            sleep(2.0 * attempt)
            continue
        break
    raise RuntimeError(f"{url}: {last}")


# Pure: the (type, name, href) rows of a filing index page.
def parse_index_page(html: str) -> list[tuple[str, str, str]]:
    """Return (document type, file name, href) for each document in the index."""
    documents: list[tuple[str, str, str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        href = re.search(r'href="([^"]+)"', row)
        if len(cells) >= 4 and href:
            documents.append((cells[3], cells[2], href.group(1)))
    return documents


# The archive URL of the first EX-99.1 (or any EX-99) document, or None.
def press_release_href(documents: Sequence[tuple[str, str, str]]) -> str | None:
    """Return the href of the press-release exhibit in an index listing."""
    ranked = sorted(
        (d for d in documents if d[0].upper().startswith("EX-99")),
        key=lambda d: (0 if d[0].upper() == "EX-99.1" else 1, d[1]),
    )
    if not ranked:
        return None
    href = ranked[0][2]
    if href.startswith("/ix?doc="):
        href = href[len("/ix?doc=") :]
    return href if href.startswith("http") else _ARCHIVE_ROOT + href


# The plain text of an event's press release, or None when the filing has
# no EX-99 exhibit.
def fetch_release_text(
    cik: int,
    event: EarningsEvent,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Return the press-release text for an 8-K, or None if it has none."""
    pacer = pacer or Pacer(sleep=sleep)
    folder = event.accession.replace("-", "")
    page = _get_text(
        _INDEX_PAGE_URL.format(cik=cik, folder=folder, accession=event.accession),
        transport,
        pacer,
        sleep,
    )
    href = press_release_href(parse_index_page(page))
    if href is None:
        return None
    return html_to_text(_get_text(href, transport, pacer, sleep))


# --- storage ---------------------------------------------------------------


# Serialise records for the store's frames.
def tone_frame(records: Sequence[ToneRecord]) -> dict[str, list]:
    """Return the columns of a tone frame."""
    return {
        "accession": [r.accession for r in records],
        "reaction_date": [r.reaction_date for r in records],
        "guidance": [r.guidance for r in records],
        "demand": [r.demand for r in records],
        "pricing": [r.pricing for r in records],
        "capex": [r.capex for r in records],
        "supply_constrained": [r.supply_constrained for r in records],
        "summary": [r.summary for r in records],
        "model": [r.model for r in records],
        "prompt_version": [r.prompt_version for r in records],
        "truncated": [r.truncated for r in records],
    }


# Rebuild records from a stored frame.
def records_from_frame(columns: Mapping[str, list]) -> tuple[ToneRecord, ...]:
    """Return the ToneRecords a frame encodes, oldest reaction first."""
    rows = [
        ToneRecord(
            accession=columns["accession"][i],
            reaction_date=columns["reaction_date"][i],
            guidance=float(columns["guidance"][i]),
            demand=float(columns["demand"][i]),
            pricing=float(columns["pricing"][i]),
            capex=float(columns["capex"][i]),
            supply_constrained=float(columns["supply_constrained"][i]),
            summary=str(columns["summary"][i]),
            model=str(columns["model"][i]),
            prompt_version=str(columns["prompt_version"][i]),
            truncated=bool(columns["truncated"][i]),
        )
        for i in range(len(columns.get("accession", [])))
    ]
    return tuple(sorted(rows, key=lambda r: r.reaction_date))


# The partial file a long run appends to, one JSON record per line.
def partial_path(root: Path, asof: date, ticker: str) -> Path:
    """Return the path of a ticker's in-progress tone file."""
    return root / TONE_KIND / f"asof={asof.isoformat()}" / f"{ticker}.partial.jsonl"


# Append one record to the partial file.
def append_partial(path: Path, record: ToneRecord) -> None:
    """Append a record to the partial file, creating it if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(record)
    payload["reaction_date"] = record.reaction_date.isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


# Read the records already scored into a partial file.
def read_partial(path: Path) -> dict[str, ToneRecord]:
    """Return {accession: record} from a partial file, empty if absent."""
    if not path.exists():
        return {}
    out: dict[str, ToneRecord] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        payload["reaction_date"] = date.fromisoformat(payload["reaction_date"])
        record = ToneRecord(**payload)
        out[record.accession] = record
    return out


# --- features --------------------------------------------------------------


# Build the (T, N, FEATURE_COUNT) tone feature array for a panel.
def tone_features(
    panel: Panel, records: Mapping[str, Sequence[ToneRecord]]
) -> np.ndarray:
    """Return point-in-time release-tone features per (session, name)."""
    size = len(panel.dates)
    out = np.zeros((size, len(panel.tickers), FEATURE_COUNT), dtype=np.float32)
    calendar = panel.dates.astype("datetime64[D]")
    has_index = FEATURE_NAMES.index("has_tone")
    for column, ticker in enumerate(panel.tickers):
        rows = sorted(records.get(ticker, ()), key=lambda r: r.reaction_date)
        if not rows:
            continue
        # The session on or after each reaction date is when the scores are
        # first known; the window closes the session after, like the
        # reaction return, so use the reaction session itself here — the
        # text was public before it opened.
        positions = np.searchsorted(
            calendar,
            np.asarray([r.reaction_date for r in rows], dtype="datetime64[D]"),
            side="left",
        )
        previous: ToneRecord | None = None
        for index, record in enumerate(rows):
            start = int(positions[index])
            if start >= size:
                break
            end = int(positions[index + 1]) if index + 1 < len(rows) else size
            end = min(max(end, start), size)
            for k, name in enumerate(SCORE_NAMES):
                value = getattr(record, name)
                out[start:end, column, k] = value
                change = (
                    value - getattr(previous, name) if previous is not None else 0.0
                )
                out[start:end, column, len(SCORE_NAMES) + k] = change
            out[start:end, column, has_index] = 1.0
            previous = record
    return out


# The current UTC timestamp, for records.
def now_utc() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(tz=UTC)


__all__ = [
    "FEATURE_COUNT",
    "FEATURE_NAMES",
    "SCORE_NAMES",
    "TONE_KIND",
    "ToneRecord",
    "append_partial",
    "fetch_release_text",
    "parse_index_page",
    "partial_path",
    "press_release_href",
    "read_partial",
    "records_from_frame",
    "tone_features",
    "tone_frame",
    "_get_json",
]
