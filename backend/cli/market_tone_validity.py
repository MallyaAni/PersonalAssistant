"""The tone-validity study's arms: mask, leak test, embed, evaluate.

    python -m backend.cli.market_tone_validity mask --root data/market --out work
    python -m backend.cli.market_tone_validity leak-sample --out work --n 200
    python -m backend.cli.market_tone_validity leak-score --out work \\
        --answers work/leak_answers.jsonl
    python -m backend.cli.market_tone_validity embed --root data/market \\
        --out work --models E:/models --device cuda
    python -m backend.cli.market_tone_validity evaluate --root data/market \\
        --vec work/vec_chrono.npz --tone-masked work/tone_masked --out result.json

Registered in `docs/research/tone-validity-plan-2026-09-30.md` before any
of this was written. The question: does the sentiment analyst's edge
survive when the reader cannot know the company (arm B, the masked
re-read) or was trained only on text written before the release (arm C,
ChronoBERT into a walk-forward ridge)? Arm A is the stored tone as it is.

Every arm is measured exactly as `market_release_eval` measures a signal:
the newest release on or before each session (`release_text.active_index`),
the beta-adjusted forward residual, `harness.evaluate_scores` at twenty
sessions (sixty reported), on one shared set of (session, name) cells so
coverage cannot flatter anyone. The per-period ICs are kept so IC(B) -
IC(A) has a paired t.

The arms need the book panel and the tone block the desk feeds
`sentiment.opine`, which is what `desk.run` builds them from; the rest of
the desk (fundamentals, levels, regime) is not consulted here.

Nothing here calls a model server or writes to the store. The masked
re-score (arm B) is run by the operator's tone client on the masked
texts this writes; the leak-test answers come back the same way.
"""

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk import sentiment
from backend.cli.market_release_eval import (
    COST_BPS,
    MIN_NAMES,
    RIDGE_LAMBDAS,
    _fitted,
    _ridge,
)
from backend.market import (
    chrono_embed,
    language,
    release_mask,
    release_text,
    tone_leak,
)
from backend.market.harness import evaluate_scores, walk_forward_folds
from backend.market.store import MarketStore
from backend.market.universe import OVERLAY, book_sides, build_universe

# The plan's windows: the in-window period the criteria are judged on and
# the post-cutoff period the reader cannot have trained on.
IN_WINDOW: tuple[date, date] = (date(2016, 1, 4), date(2025, 5, 31))
POST_WINDOW: tuple[date, date | None] = (date(2025, 6, 1), None)
HORIZONS: tuple[int, ...] = (20, 60)
PRIMARY_HORIZON = 20
TRAIN_SESSIONS = 750
TEST_SESSIONS = 126
EMBARGO = 5
# Criterion 1, tone inflated.
INFLATED_DELTA = -0.015
INFLATED_T = -2.0
POST_A_FLOOR = 0.01
IN_A_FLOOR = 0.03
C_CEILING = 0.02
# Criterion 2, the incumbent stands.
STANDS_DELTA = 0.010
NOISE_T = 2.0
HALF_OF_A = 0.5
ARM_A = "A stored tone"
ARM_B = "B masked tone"
ARM_C = "C chrono ridge"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser with one subcommand per step."""
    parser = argparse.ArgumentParser(description="Tone-validity study arms.")
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("mask", help="mask every stored release")
    m.add_argument("--root", required=True, type=Path)
    m.add_argument("--out", required=True, type=Path)
    m.add_argument("--names", type=Path, default=None, help="JSON {ticker: [names]}")
    s = sub.add_parser("leak-sample", help="sample masked releases for the leak test")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--n", type=int, default=tone_leak.LEAK_N)
    s.add_argument("--seed", type=int, default=0)
    k = sub.add_parser("leak-score", help="score the reader's leak answers")
    k.add_argument("--out", required=True, type=Path)
    k.add_argument("--answers", required=True, type=Path)
    e = sub.add_parser("embed", help="embed the original texts point-in-time")
    e.add_argument("--root", required=True, type=Path)
    e.add_argument("--out", required=True, type=Path)
    e.add_argument("--models", required=True, type=Path)
    e.add_argument("--device", default="cuda")
    e.add_argument("--arm", choices=("chrono", "nomic"), default="chrono")
    v = sub.add_parser("evaluate", help="measure the arms on shared cells")
    v.add_argument("--root", required=True, type=Path)
    v.add_argument("--vec", type=Path, default=None)
    v.add_argument("--tone-masked", default="none")
    v.add_argument("--out", required=True, type=Path)
    v.add_argument("--train", type=int, default=TRAIN_SESSIONS)
    v.add_argument("--test", type=int, default=TEST_SESSIONS)
    v.add_argument("--embargo", type=int, default=EMBARGO)
    return parser


# --- masking -----------------------------------------------------------------


# Ticker -> company name for the book, from the universe file.
def issuer_names(universe: Sequence[Any] | None = None) -> dict[str, tuple[str, ...]]:
    """Return {ticker: names} for every book name.

    `build_universe` keeps the constituent file's name over the overlay's
    ("Supermicro" over "Super Micro"), so both are gathered here: a release
    writes whichever the company uses.
    """
    members = build_universe() if universe is None else universe
    sides = book_sides(tuple(members))
    overlay = {m.ticker: m.name for m in OVERLAY}
    out: dict[str, tuple[str, ...]] = {}
    for m in members:
        if m.ticker in sides:
            names = [n for n in (m.name, overlay.get(m.ticker, "")) if n]
            out[m.ticker] = tuple(dict.fromkeys(names))
    return out


# Every stored release text for the book, as (ticker, record) pairs.
def stored_texts(
    store: MarketStore, tickers: Sequence[str]
) -> list[tuple[str, release_text.ReleaseText]]:
    """Return the book's release texts from the store, oldest first per name."""
    out: list[tuple[str, release_text.ReleaseText]] = []
    for ticker in tickers:
        frame = store.read_frame(release_text.RELEASE_TEXT_KIND, ticker)
        if frame is None:
            continue
        out.extend((ticker, r) for r in release_text.texts_from_frame(frame[0]))
    return out


# Mask every release and write one JSONL per name plus the summary. Two
# passes: the corpus rule first, over every issuer's texts, then the mask.
def run_mask(
    texts: Sequence[tuple[str, release_text.ReleaseText]],
    names: Mapping[str, Sequence[str]],
    out: Path,
    extra_names: Mapping[str, Sequence[str]] | None = None,
    min_issuers: int = release_mask.MIN_ISSUERS,
) -> dict[str, Any]:
    """Write `<out>/masked/<ticker>.jsonl`, `rare_tokens.json` and the summary."""
    extra_names = extra_names or {}
    tickers = sorted({t for t, _ in texts})
    (out / "masked").mkdir(parents=True, exist_ok=True)
    by_issuer: dict[str, list[str]] = {}
    for t, record in texts:
        by_issuer.setdefault(t, []).append(record.text)
    issuer_counts = release_mask.token_issuer_counts(by_issuer)
    rare = release_mask.rare_tokens(by_issuer, min_issuers)
    (out / "rare_tokens.json").write_text(
        json.dumps(
            {
                "min_issuers": min_issuers,
                "tokens": {k: issuer_counts[k] for k in sorted(rare)},
            },
            indent=1,
        )
    )
    totals: dict[str, int] = {}
    residual_any = {"year": 0, "month": 0, "name": 0}
    count = 0
    rare_share = 0.0
    for ticker in tickers:
        issuer = release_mask.MaskIssuer(
            names=(*names.get(ticker, ()), *extra_names.get(ticker, ())),
            tickers=(ticker,),
            other_tickers=tuple(t for t in names if t != ticker),
        )
        rows = []
        for t, record in texts:
            if t != ticker:
                continue
            masked = release_mask.mask(record.text, issuer, rare)
            left = release_mask.residuals(masked.text, issuer.names)
            tokens = release_mask.token_count(release_mask.unescape(record.text))
            for kind, n in masked.counts.items():
                totals[kind] = totals.get(kind, 0) + n
            for kind, n in left.items():
                residual_any[kind] += int(n > 0)
            count += 1
            rare_share += masked.counts["rare"] / tokens if tokens else 0.0
            rows.append(
                {
                    "accession": record.accession,
                    "ticker": ticker,
                    "reaction_date": record.reaction_date.isoformat(),
                    "text": masked.text,
                    "counts": masked.counts,
                    "tokens": tokens,
                    "residual": left,
                    "unescaped": True,
                }
            )
        rows.sort(key=lambda r: (r["reaction_date"], r["accession"]))
        with (out / "masked" / f"{ticker}.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
    summary = {
        "releases": count,
        "names": len(tickers),
        "replacements": totals,
        "residual_share": {
            k: (v / count if count else 0.0) for k, v in residual_any.items()
        },
        "min_issuers": min_issuers,
        "rare_tokens": len(rare),
        "rare_share_mean": rare_share / count if count else 0.0,
    }
    (out / "mask_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


# Every masked release under `<out>/masked`.
def read_masked(out: Path) -> list[dict[str, Any]]:
    """Return the masked records written by `run_mask`, by ticker then date."""
    rows: list[dict[str, Any]] = []
    for path in sorted((out / "masked").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


# --- embedding ---------------------------------------------------------------


# Embed the original texts with the checkpoint dated before each release.
def run_embed(
    texts: Sequence[tuple[str, release_text.ReleaseText]],
    models: Path,
    device: str,
    embedder: Callable[..., np.ndarray] = chrono_embed.embed_texts,
) -> dict[str, np.ndarray]:
    """Return the arrays of the vector file: one row per embeddable release."""
    groups: dict[str, list[tuple[str, release_text.ReleaseText]]] = {}
    skipped = 0
    for ticker, record in texts:
        checkpoint = chrono_embed.checkpoint_for(record.reaction_date)
        if checkpoint is None:
            skipped += 1
            continue
        groups.setdefault(checkpoint, []).append((ticker, record))
    accessions, tickers, dates, checkpoints, vectors = [], [], [], [], []
    for checkpoint in sorted(groups):
        items = groups[checkpoint]
        matrix = embedder([r.text for _, r in items], str(models / checkpoint), device)
        vectors.append(np.asarray(matrix, dtype=np.float32))
        accessions.extend(r.accession for _, r in items)
        tickers.extend(t for t, _ in items)
        dates.extend(r.reaction_date.isoformat() for _, r in items)
        checkpoints.extend([checkpoint] * len(items))
        print(f"{checkpoint}: {len(items)} releases", flush=True)
    if skipped:
        print(f"{skipped} releases before the first checkpoint's cutoff skipped")
    return {
        "accessions": np.array(accessions),
        "tickers": np.array(tickers),
        "reaction_dates": np.array(dates),
        "checkpoints": np.array(checkpoints),
        "vectors": (
            np.concatenate(vectors, axis=0) if vectors else np.zeros((0, 0), np.float32)
        ),
    }


# The vector file as (records for active_index, ticker_of, matrix).
def load_vectors(path: Path) -> tuple[list, dict[str, str], np.ndarray]:
    """Return the release records, their tickers and the (n, width) matrix."""
    with np.load(path) as data:
        accessions = [str(a) for a in data["accessions"]]
        tickers = [str(t) for t in data["tickers"]]
        dates = [date.fromisoformat(str(d)) for d in data["reaction_dates"]]
        matrix = np.asarray(data["vectors"], dtype=np.float32)
    records = [
        release_text.ReleaseVector(a, d, "chrono", ())
        for a, d in zip(accessions, dates, strict=True)
    ]
    return records, dict(zip(accessions, tickers, strict=True)), matrix


# --- evaluation --------------------------------------------------------------


# The masked-tone frames, from a store rooted at `path` or `<path>/<ticker>.jsonl`.
def load_masked_tone(path: Path, panel) -> np.ndarray | None:
    """Return the (T, N, K) tone block of the masked re-score, or None."""
    store = MarketStore(path)
    records: dict[str, Sequence[language.ToneRecord]] = {}
    for ticker in panel.tickers:
        frame = store.read_frame(language.TONE_KIND, ticker)
        if frame is not None:
            records[ticker] = language.records_from_frame(frame[0])
            continue
        partial = path / f"{ticker}.jsonl"
        if partial.exists():
            records[ticker] = tuple(language.read_partial(partial).values())
    if not records:
        return None
    return language.tone_features(panel, records)


# One arm's harness numbers plus its per-period ICs, keyed by date.
def _arm_result(scores, cells, panel, horizon) -> dict[str, Any]:
    masked = np.where(cells, scores, np.nan)
    report = evaluate_scores(
        masked, panel, horizon, cost_bps=COST_BPS, min_names=MIN_NAMES
    )
    return {
        "ic": report.mean_ic,
        "t": report.ic_tstat,
        "net_sharpe": report.net_sharpe,
        "periods": report.count,
        "period_ics": {str(p.date): p.rank_ic for p in report.periods},
    }


# The paired difference of two arms' per-period ICs on their common periods.
def paired(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, Any]:
    """Return mean and t of IC(b) - IC(a) over the periods both define."""
    keys = [k for k in a if k in b and np.isfinite(a[k]) and np.isfinite(b[k])]
    diffs = np.array([b[k] - a[k] for k in keys], dtype=float)
    if len(diffs) < 2 or diffs.std(ddof=1) == 0:
        return {
            "delta": float(diffs.mean()) if len(diffs) else float("nan"),
            "t": float("nan"),
            "periods": int(len(diffs)),
        }
    t = float(diffs.mean() / (diffs.std(ddof=1) / np.sqrt(len(diffs))))
    return {"delta": float(diffs.mean()), "t": t, "periods": int(len(diffs))}


# A (T,) mask of the sessions inside a window.
def window_mask(dates: np.ndarray, start: date, end: date | None) -> np.ndarray:
    """Return True for sessions in [start, end], end open when None."""
    stamps = np.asarray(dates).astype("datetime64[D]")
    mask = stamps >= np.datetime64(start)
    if end is not None:
        mask &= stamps <= np.datetime64(end)
    return mask


# Measure every present arm on the shared cells, per horizon and window.
def evaluate_arms(
    panel,
    sides: Mapping[str, str],
    tone_a: np.ndarray,
    tone_b: np.ndarray | None,
    vec: tuple[list, Mapping[str, str], np.ndarray] | None,
    horizons: Sequence[int] = HORIZONS,
    train: int = TRAIN_SESSIONS,
    test: int = TEST_SESSIONS,
    embargo: int = EMBARGO,
    windows: Mapping[str, tuple[date, date | None]] | None = None,
) -> dict[str, Any]:
    """Return the study payload: arms per horizon and window, criteria, verdict."""
    windows = windows or {"in_window": IN_WINDOW, "post_window": POST_WINDOW}
    in_book = np.array([t in sides for t in panel.tickers])
    arms: dict[str, np.ndarray] = {ARM_A: sentiment.opine(tone_a).ranks()}
    if tone_b is not None:
        arms[ARM_B] = sentiment.opine(tone_b).ranks()
    index = None
    if vec is not None:
        records, ticker_of, matrix = vec
        index, _since = release_text.active_index(
            panel.dates, panel.tickers, records, ticker_of
        )
        index = np.where(in_book[None, :], index, -1)
    payload: dict[str, Any] = {"horizons": {}}
    for horizon in horizons:
        scored = dict(arms)
        if index is not None:
            label = panel.forward_residual(horizon)
            folds = walk_forward_folds(len(panel.dates), train, test, horizon, embargo)
            models = {
                f"{ARM_C} (lambda {int(lam)})": (
                    lambda a, b, c, lam=lam: _ridge(a, b, c, lam)
                )
                for lam in RIDGE_LAMBDAS
            }
            fitted = _fitted(vec[2], index, label, folds, models)
            scored.update(fitted)
        per_window: dict[str, Any] = {}
        for name, (start, end) in windows.items():
            inside = window_mask(panel.dates, start, end)[:, None] & in_book[None, :]
            per_window[name] = _measure_window(scored, inside, panel, horizon)
            # C's out-of-sample cells begin a training window after the
            # panel starts, which shortens B against A on the shared cells;
            # the two tone arms alone are reported on their own cells too.
            if ARM_B in scored and len(scored) > 2:
                tone_only = {k: v for k, v in scored.items() if k in (ARM_A, ARM_B)}
                per_window[name]["tone_arms_only"] = _measure_window(
                    tone_only, inside, panel, horizon
                )
        payload["horizons"][str(horizon)] = per_window
    payload["criteria"] = criteria(payload["horizons"][str(PRIMARY_HORIZON)])
    payload["verdict"] = verdict(payload["criteria"])
    return payload


# Every arm on the cells all of them score, inside one window: the harness
# numbers per arm and each arm's paired difference against A.
def _measure_window(
    scored: Mapping[str, np.ndarray], inside: np.ndarray, panel, horizon: int
) -> dict[str, Any]:
    cells = inside.copy()
    for scores in scored.values():
        cells &= np.isfinite(scores)
    results = {
        arm: _arm_result(scores, cells, panel, horizon)
        for arm, scores in scored.items()
    }
    pairs = {
        arm: paired(results[ARM_A]["period_ics"], results[arm]["period_ics"])
        for arm in results
        if arm != ARM_A
    }
    return {"cells": int(cells.sum()), "arms": results, "paired_vs_A": pairs}


# The best ridge arm's name in a window's results, or None.
def _best_c(results: Mapping[str, Mapping[str, Any]]) -> str | None:
    names = [k for k in results if k.startswith(ARM_C)]
    if not names:
        return None
    return max(names, key=lambda k: np.nan_to_num(results[k]["ic"], nan=-9.0))


# The plan's criteria 1 and 2 at the primary horizon, and the stub for 3.
def criteria(windows: Mapping[str, Any]) -> dict[str, Any]:
    """Return the evaluated criteria from one horizon's window results."""
    inside = windows["in_window"]
    post = windows.get("post_window", {"arms": {}, "paired_vs_A": {}})
    in_a = inside["arms"][ARM_A]["ic"]
    post_a = post["arms"].get(ARM_A, {}).get("ic", float("nan"))
    pair_b = inside["paired_vs_A"].get(ARM_B)
    best_c = _best_c(inside["arms"])
    in_c = inside["arms"][best_c]["ic"] if best_c else float("nan")
    delta_b = pair_b["delta"] if pair_b else float("nan")
    t_b = pair_b["t"] if pair_b else float("nan")

    masked_drop = bool(delta_b <= INFLATED_DELTA and t_b <= INFLATED_T)
    post_fade = bool(post_a < POST_A_FLOOR and in_a > IN_A_FLOOR and in_c < C_CEILING)
    inflated = masked_drop or post_fade
    within = bool(abs(delta_b) <= STANDS_DELTA)
    b_noise_c_half = bool(abs(t_b) < NOISE_T and in_c >= HALF_OF_A * in_a)
    stands = (within or b_noise_c_half) and not inflated
    beats = [
        arm
        for arm, r in inside["arms"].items()
        if arm != ARM_A and np.nan_to_num(r["ic"], nan=-9.0) > in_a
    ]
    return {
        "ic_a_in_window": in_a,
        "ic_a_post_window": post_a,
        "ic_b_minus_a": delta_b,
        "paired_t_b_minus_a": t_b,
        "ic_c_in_window": in_c,
        "best_c": best_c,
        "1_tone_inflated": {
            "fires": inflated,
            "masked_drop": masked_drop,
            "post_fade": post_fade,
            "b_evaluable": pair_b is not None,
            "c_evaluable": best_c is not None,
            "post_evaluable": bool(np.isfinite(post_a)),
        },
        "2_incumbent_stands": {
            "fires": stands,
            "within_0.010": within,
            "b_noise_and_c_half": b_noise_c_half,
        },
        "3_replacement": {
            "status": (
                f"not run: {', '.join(beats)} beat A in-window; the T-S1 "
                "scorecard is a separate run"
                if beats
                else "not run: no arm beats A in-window"
            ),
            "arms_beating_a": beats,
        },
    }


# The one-word reading of the criteria, in the plan's order.
def verdict(crit: Mapping[str, Any]) -> str:
    """Return TONE INFLATED, INCUMBENT STANDS or RECORD."""
    if crit["1_tone_inflated"]["fires"]:
        return "TONE INFLATED"
    if crit["2_incumbent_stands"]["fires"]:
        return "INCUMBENT STANDS"
    return "RECORD"


# The verdict block, printed.
def print_verdict(payload: Mapping[str, Any]) -> None:
    """Print the arms at the primary horizon and the criteria."""
    windows = payload["horizons"][str(PRIMARY_HORIZON)]
    for name, window in windows.items():
        print(f"\n=== horizon {PRIMARY_HORIZON}, {name}: {window['cells']:,} cells ===")
        print(f"{'arm':32} {'rank IC':>9} {'t':>7} {'net Sharpe':>11} {'periods':>8}")
        for arm, r in window["arms"].items():
            print(
                f"{arm:32} {r['ic']:+9.4f} {r['t']:+7.2f} {r['net_sharpe']:+11.2f} "
                f"{r['periods']:8d}"
            )
        for arm, p in window["paired_vs_A"].items():
            print(f"  {arm} - A: {p['delta']:+.4f} (paired t {p['t']:+.2f})")
        extra = window.get("tone_arms_only")
        if extra:
            p = extra["paired_vs_A"][ARM_B]
            ic_a, ic_b = extra["arms"][ARM_A]["ic"], extra["arms"][ARM_B]["ic"]
            print(
                f"  tone arms alone, {extra['cells']:,} cells: A {ic_a:+.4f}, "
                f"B {ic_b:+.4f}, B - A {p['delta']:+.4f} "
                f"(paired t {p['t']:+.2f}, {p['periods']} periods)"
            )
    crit = payload["criteria"]
    print("\n=== criteria ===")
    print(f"1 tone inflated:    {crit['1_tone_inflated']}")
    print(f"2 incumbent stands: {crit['2_incumbent_stands']}")
    print(f"3 replacement:      {crit['3_replacement']['status']}")
    print(f"\nVERDICT: {payload['verdict']}")


# --- entry points ------------------------------------------------------------


# The book panel and the stored tone block, as the desk builds them.
def _panel_and_tone(root: Path):
    from backend.agents.trading.desk.desk import book_panel
    from backend.market.model import load_tone_features

    store = MarketStore(root)
    panel, sides = book_panel(store)
    tone = load_tone_features(store, panel)
    if tone is None:
        raise SystemExit("no edgar_tone frames in the store")
    return panel, sides, tone


# Run the tool.
def main() -> None:  # noqa: C901 - one branch per subcommand
    """Entry point: one subcommand per step of the study."""
    args = build_parser().parse_args()
    if args.command == "mask":
        names = issuer_names()
        extra = json.loads(args.names.read_text()) if args.names else {}
        texts = stored_texts(MarketStore(args.root), sorted(names))
        summary = run_mask(texts, names, args.out, extra)
        print(json.dumps(summary, indent=2))
    elif args.command == "leak-sample":
        sample = tone_leak.sample_leak(
            read_masked(args.out), issuer_names(), args.n, args.seed
        )
        with (args.out / "leak_sample.jsonl").open("w", encoding="utf-8") as fh:
            for row in sample:
                fh.write(json.dumps(row) + "\n")
        print(f"{len(sample)} masked releases sampled for the leak test")
    elif args.command == "leak-score":
        sample = [
            json.loads(line)
            for line in (args.out / "leak_sample.jsonl").read_text().splitlines()
            if line.strip()
        ]
        result = tone_leak.score_leak(sample, tone_leak.read_answers(args.answers))
        (args.out / "leak_result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        print("LEAK TEST " + ("PASS" if result["pass"] else "FAIL"))
    elif args.command == "embed":
        if args.arm != "chrono":
            raise NotImplementedError(
                "arm D (nomic-embed over the full text) is out of this build's "
                "scope; it needs the RTX's nomic modelling code verified first"
            )
        texts = stored_texts(MarketStore(args.root), sorted(issuer_names()))
        arrays = run_embed(texts, args.models, args.device)
        args.out.mkdir(parents=True, exist_ok=True)
        np.savez(args.out / "vec_chrono.npz", **arrays)
        print(f"{len(arrays['accessions'])} vectors written")
    elif args.command == "evaluate":
        panel, sides, tone_a = _panel_and_tone(args.root)
        tone_b = (
            None
            if args.tone_masked.lower() == "none"
            else load_masked_tone(Path(args.tone_masked), panel)
        )
        vec = load_vectors(args.vec) if args.vec else None
        payload = evaluate_arms(
            panel,
            sides,
            tone_a,
            tone_b,
            vec,
            train=args.train,
            test=args.test,
            embargo=args.embargo,
        )
        args.out.write_text(json.dumps(payload, indent=2, default=float))
        print_verdict(payload)


if __name__ == "__main__":
    main()
