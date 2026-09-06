"""Score every results release with the local model, resumably.

    python -m backend.cli.market_tone --refresh --roles focus
    python -m backend.cli.market_tone --refresh --since 2022-01-01 --concurrency 4
    python -m backend.cli.market_tone --status

For each ticker with stored EDGAR events, fetch each release's press
release from the filing index (paced for SEC), score it with the trading
agent's release reader on the structured model, and store the scores as an
immutable `edgar_tone` frame in today's partition. A ticker already in the
partition is skipped; a ticker interrupted mid-way resumes from its partial
file. Model calls run on `--concurrency` threads, each with its own client,
while the SEC fetches stay serial and paced.

The model endpoint is the structured role from settings, overridable with
--llm-url and --llm-model for a run from a host whose .env names another
runtime.
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.agents.trading.release_tone import PROMPT_VERSION, ReleaseToneReader
from backend.config.settings import settings
from backend.core.llm import OpenAICompatibleInferenceProvider
from backend.market import edgar, language
from backend.market.store import MarketStore
from backend.market.universe import build_universe, tickers_with_role


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the tone tool."""
    parser = argparse.ArgumentParser(description="Score results releases.")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--tickers", default="")
    parser.add_argument("--roles", default="")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2015, 1, 1))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--llm-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    return parser


# The tickers a run applies to.
def _select(args: argparse.Namespace) -> tuple[str, ...]:
    if args.tickers:
        return tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    roles = tuple(r.strip() for r in args.roles.split(",") if r.strip())
    return tickers_with_role(build_universe(), *roles)


# One model client per worker thread: the provider serialises requests per
# instance, so concurrency needs instances.
def _clients(args: argparse.Namespace) -> tuple[list[ReleaseToneReader], str]:
    return clients(args.llm_url, args.llm_model, args.concurrency)


# One reader per concurrent call against the configured runtime.
def clients(
    llm_url: str = "", llm_model: str = "", concurrency: int = 4
) -> tuple[list[ReleaseToneReader], str]:
    """Return (readers, model name) for the runtime."""
    url = (
        llm_url
        or settings.ROUTING_LLM_BASE_URL
        or settings.MAIN_LLM_BASE_URL
        or settings.LLM_BASE_URL
    )
    model = (
        llm_model
        or settings.ROUTING_LLM_MODEL
        or settings.MAIN_LLM_MODEL
        or settings.LLM_MODEL
    )
    return [
        ReleaseToneReader(
            OpenAICompatibleInferenceProvider(
                url, model, settings.LLM_API_KEY, timeout_seconds=600.0
            )
        )
        for _ in range(max(1, concurrency))
    ], model


# The scores already stored for a ticker in the newest partition before
# `asof`, so a new day scores only the releases it has not seen. A change
# of prompt version starts over: the old scores are not comparable.
def prior_records(
    store: MarketStore, ticker: str, asof: date
) -> dict[str, language.ToneRecord]:
    """Return {accession: ToneRecord} carried forward from earlier partitions."""
    frame = store.read_frame(language.TONE_KIND, ticker, asof - timedelta(days=1))
    if frame is None:
        return {}
    columns, meta = frame
    if meta.get("prompt_version") != PROMPT_VERSION:
        return {}
    return {r.accession: r for r in language.records_from_frame(columns)}


# Score every listed ticker's unscored releases; return how many were scored.
def refresh_tickers(
    store: MarketStore,
    tickers: tuple[str, ...],
    asof: date,
    *,
    since: date = date(2015, 1, 1),
    llm_url: str = "",
    llm_model: str = "",
    concurrency: int = 4,
) -> int:
    """Refresh the tone layer for `tickers` into the as-of partition."""
    readers, model = clients(llm_url, llm_model, concurrency)
    pacer = edgar.Pacer()
    total = 0
    for ticker in tickers:
        if store.has_frame(language.TONE_KIND, asof, ticker):
            continue
        scored, _missing, stored = _refresh_ticker(
            store, ticker, asof, since, readers, model, pacer
        )
        if stored >= 0:
            total += scored
    return total


# Score one ticker's unscored releases and store the frame when complete.
def _refresh_ticker(
    store: MarketStore,
    ticker: str,
    asof: date,
    since: date,
    readers: list[ReleaseToneReader],
    model: str,
    pacer: edgar.Pacer,
) -> tuple[int, int, int]:
    events_frame = store.read_frame("edgar_events", ticker, asof)
    if events_frame is None:
        return 0, 0, -1
    columns, meta = events_frame
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
    events = [e for e in events if e.filed >= since]
    partial = language.partial_path(store.root, asof, ticker)
    done = prior_records(store, ticker, asof)
    done.update(language.read_partial(partial))
    todo = [e for e in events if e.accession not in done]

    # Fetch texts serially (SEC pacing), score concurrently.
    texts: list[tuple[edgar.EarningsEvent, str | None]] = []
    for event in todo:
        try:
            texts.append((event, language.fetch_release_text(cik, event, pacer=pacer)))
        except Exception as exc:
            print(f"{ticker:6} {event.accession} fetch failed: {exc}", flush=True)
            texts.append((event, None))

    def work(item: tuple[int, tuple[edgar.EarningsEvent, str | None]]):
        index, (event, text) = item
        if not text:
            return event, None
        return event, readers[index % len(readers)].score_sync(text)

    scored = 0
    missing = 0
    with ThreadPoolExecutor(max_workers=len(readers)) as pool:
        for event, tone in pool.map(work, enumerate(texts)):
            if tone is None:
                missing += 1
                continue
            record = language.ToneRecord(
                accession=event.accession,
                reaction_date=event.reaction_date,
                guidance=tone.guidance,
                demand=tone.demand,
                pricing=tone.pricing,
                capex=tone.capex,
                supply_constrained=tone.supply_constrained,
                summary=tone.summary,
                model=model,
                prompt_version=PROMPT_VERSION,
                truncated=tone.truncated,
            )
            language.append_partial(partial, record)
            done[record.accession] = record
            scored += 1
    records = sorted(done.values(), key=lambda r: r.reaction_date)
    store.write_frame(
        language.TONE_KIND,
        asof,
        ticker,
        language.tone_frame(records),
        {"cik": str(cik), "model": model, "prompt_version": PROMPT_VERSION},
    )
    if partial.exists():
        partial.unlink()
    return scored, missing, len(records)


# Run the tool.
def main() -> None:
    """Entry point: score releases and/or report what is stored."""
    args = build_parser().parse_args()
    tickers = _select(args)
    store = MarketStore(args.data_dir)
    asof = args.asof or datetime.now(tz=UTC).date()
    if args.refresh:
        readers, model = _clients(args)
        pacer = edgar.Pacer()
        started = time.time()
        total = 0
        for ticker in tickers:
            if store.has_frame(language.TONE_KIND, asof, ticker):
                print(f"{ticker:6} kept", flush=True)
                continue
            t0 = time.time()
            scored, missing, stored = _refresh_ticker(
                store, ticker, asof, args.since, readers, model, pacer
            )
            if stored < 0:
                print(f"{ticker:6} no EDGAR events stored; run market_edgar first")
                continue
            total += scored
            print(
                f"{ticker:6} ok      {scored:3d} scored, {missing:2d} without text, "
                f"{stored:3d} stored, {time.time() - t0:5.0f}s",
                flush=True,
            )
        minutes = (time.time() - started) / 60
        print(f"partition {asof}: {total} releases scored in {minutes:.1f} min")
    if args.status or not args.refresh:
        for ticker in tickers:
            frame = store.read_frame(language.TONE_KIND, ticker, args.asof)
            if frame is None:
                print(f"{ticker:6} MISSING")
                continue
            records = language.records_from_frame(frame[0])
            last = records[-1] if records else None
            print(
                f"{ticker:6} releases={len(records):3d} "
                f"last={last.reaction_date if last else '-'} "
                f"guidance={last.guidance if last else 0:+.2f} "
                f"demand={last.demand if last else 0:+.2f}"
            )


if __name__ == "__main__":
    main()
