"""Keep every earnings release as text, then as a vector, resumably.

    python -m backend.cli.market_release_text fetch                 # the book
    python -m backend.cli.market_release_text fetch --tickers ADBE
    python -m backend.cli.market_release_text embed --base-url http://172.16.8.3:8004
    python -m backend.cli.market_release_text status

`fetch` walks each ticker's stored EDGAR events, pulls the EX-99.1 press
release from the filing index the same way the tone reader does (paced for
SEC), and stores the plain text as one immutable `edgar_release_text` frame
per ticker in today's partition. A ticker already stored is skipped; one
interrupted mid-way resumes from its partial file. About 5,500 releases
for the book at SEC's asked-for pace is half an hour.

`embed` turns each stored text into a vector with the deployment's own
embedding service and stores `edgar_release_vec` frames, with the model
name recorded so a vector is never mistaken for another model's. The
service is reachable from the desktop over the LAN on the Spark's
published port; nothing here needs the GPU.

Why the text is kept: see `backend/market/release_text.py`.
"""

import argparse
import time
from datetime import date, datetime
from pathlib import Path

from backend.config.settings import settings
from backend.market import edgar, language, release_text
from backend.market.store import MarketStore
from backend.market.universe import book_sides, build_universe, tickers_with_role


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the release-text tool."""
    parser = argparse.ArgumentParser(description="Keep earnings releases as text.")
    parser.add_argument("command", choices=("fetch", "embed", "status"))
    parser.add_argument("--tickers", default="")
    parser.add_argument("--roles", default="")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2015, 1, 1))
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--base-url", default=settings.EMBEDDING_BASE_URL)
    parser.add_argument("--model", default=settings.EMBEDDING_MODEL)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    return parser


# The tickers a run applies to; the book by default, never the universe.
def _select(args: argparse.Namespace) -> tuple[str, ...]:
    universe = build_universe()
    if args.tickers:
        return tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    if args.roles:
        roles = tuple(r.strip() for r in args.roles.split(",") if r.strip())
        return tickers_with_role(universe, *roles)
    return tuple(sorted(book_sides(universe)))


# The events stored for a ticker, as the tone tool rebuilds them.
def _events(store: MarketStore, ticker: str, asof: date, since: date):
    frame = store.read_frame("edgar_events", ticker, asof)
    if frame is None:
        return None, 0
    columns, meta = frame
    cik = int(meta.get("cik", "0"))
    events = [
        edgar.EarningsEvent(
            accepted=datetime.fromisoformat(columns["accepted"][i]),
            filed=columns["filed"][i],
            accession=columns["accession"][i],
            items=columns["items"][i],
        )
        for i in range(len(columns.get("accepted", [])))
    ]
    return [e for e in events if e.filed >= since], cik


# Fetch one ticker's releases into a text frame. Returns how many were
# stored, or None when the ticker was already done.
def _fetch_one(
    store: MarketStore, ticker: str, asof: date, since: date, pacer: edgar.Pacer
) -> int | None:
    if store.has_frame(release_text.RELEASE_TEXT_KIND, asof, ticker):
        return None
    events, cik = _events(store, ticker, asof, since)
    if events is None:
        print(f"{ticker:6} no EDGAR events stored; run market_edgar first")
        return 0
    partial = release_text.partial_path(store.root, asof, ticker)
    done = release_text.read_partial(partial)
    for event in events:
        if event.accession in done:
            continue
        try:
            text = language.fetch_release_text(cik, event, pacer=pacer)
        except Exception as exc:  # one bad filing, not one lost name
            print(f"{ticker:6} {event.accession} fetch failed: {exc}", flush=True)
            continue
        if text is None:
            continue
        body, cut = release_text.clip(text)
        record = release_text.ReleaseText(
            accession=event.accession,
            reaction_date=event.reaction_date,
            text=body,
            chars=len(text),
            truncated=cut,
        )
        release_text.append_partial(partial, record)
        done[event.accession] = record
    store.write_frame(
        release_text.RELEASE_TEXT_KIND,
        asof,
        ticker,
        release_text.text_frame(list(done.values())),
        metadata={"cik": str(cik), "since": since.isoformat()},
    )
    if partial.exists():
        partial.unlink()
    return len(done)


# Embed one ticker's stored texts into a vector frame. Returns how many, or
# None when already done or nothing to embed.
def _embed_one(
    store: MarketStore, ticker: str, asof: date, base_url: str, model: str
) -> int | None:
    if store.has_frame(release_text.RELEASE_VEC_KIND, asof, ticker):
        return None
    frame = store.read_frame(release_text.RELEASE_TEXT_KIND, ticker, asof)
    if frame is None:
        return None
    texts = release_text.texts_from_frame(frame[0])
    if not texts:
        return 0
    vectors = release_text.embed([t.text for t in texts], base_url, model)
    records = [
        release_text.ReleaseVector(
            accession=t.accession,
            reaction_date=t.reaction_date,
            model=model,
            vector=tuple(v),
        )
        for t, v in zip(texts, vectors, strict=True)
    ]
    store.write_frame(
        release_text.RELEASE_VEC_KIND,
        asof,
        ticker,
        release_text.vector_frame(records),
        metadata={"model": model, "width": str(len(vectors[0]))},
    )
    return len(records)


# What is stored, so a run says what is left rather than repeating.
def _status(store: MarketStore, tickers: tuple[str, ...], asof: date) -> None:
    for kind in (release_text.RELEASE_TEXT_KIND, release_text.RELEASE_VEC_KIND):
        done = [t for t in tickers if store.has_frame(kind, asof, t)]
        rows = 0
        for t in done:
            frame = store.read_frame(kind, t, asof)
            if frame:
                rows += len(frame[0].get("accession", []))
        print(f"{kind}: {len(done)} of {len(tickers)} names, {rows:,} releases")


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    asof = args.asof or date.today()
    tickers = _select(args)
    if args.command == "status":
        _status(store, tickers, asof)
        return
    started = time.time()
    if args.command == "fetch":
        pacer = edgar.Pacer()
        for index, ticker in enumerate(tickers, start=1):
            count = _fetch_one(store, ticker, asof, args.since, pacer)
            note = "already stored" if count is None else f"{count:3d} releases"
            print(
                f"{index:3d}/{len(tickers)} {ticker:6} {note} "
                f"({time.time() - started:.0f}s)"
            )
    else:
        for index, ticker in enumerate(tickers, start=1):
            count = _embed_one(store, ticker, asof, args.base_url, args.model)
            note = (
                "already stored or no text" if count is None else f"{count:3d} vectors"
            )
            print(
                f"{index:3d}/{len(tickers)} {ticker:6} {note} "
                f"({time.time() - started:.0f}s)"
            )
    _status(store, tickers, asof)


if __name__ == "__main__":
    main()
