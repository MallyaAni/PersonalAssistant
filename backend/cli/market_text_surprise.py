"""The text-surprise study (A1): build the score tables, then evaluate them.

    python -m backend.cli.market_text_surprise build --root data/market \\
        --texts data/market --out work/text-surprise
    python -m backend.cli.market_text_surprise evaluate --root data/market \\
        --tables work/text-surprise --out work/text-surprise/text_surprise.json

Registered in `docs/research/text-surprise-plan-2026-10-01.md` before any
of this was written. Two arms (`backend.market.text_surprise`): A1-1, the
tone *change* against the company's previous release, in three fixed
variants; A1-3, a point-in-time word-surprise fitted to the sign of the
one-day beta-adjusted reaction. A1-2 (transcripts) is not registered.

`build` writes one parquet table per arm under `--out`, one row per
release: `tone_surprise.parquet` (the four ranked fields and their
change) from the stored `edgar_tone` frames, and `word_surprise.parquet`
(the reaction label, the refit year and the fitted log-odds) from the
release texts, with `word_surprise_fit.json` recording the C choice and
every refit. The texts are read from a store root holding
`edgar_release_text` frames, a directory of `<TICKER>.jsonl` partial
files, or one JSONL file whose rows carry ticker, accession,
reaction_date and text.

`evaluate` measures the arms exactly as the tone-validity study measured
its own, through `market_tone_validity._measure_window`: the stored tone
(`sentiment.opine(...).ranks()`) is arm A; every arm is scored on the
shared (session, name) cells of the book, at 20 and 60 sessions, in the
plan's windows (2018-01..2025-05, 2025-06.., and both as one for A1-3),
with the paired IC against A and the mean per-session rank correlation
with A. Before any arm is read, the null test: the level legs carried
forward through this study's own alignment must reproduce A's per-period
ICs bit for bit. The verdict lines apply the plan's IC floor; the T-S1
book gate is a separate scorecard run, and the step writes each arm's
stance table (`stances/<arm>.parquet`) for it and prints the command.

Nothing here calls a model server or writes to the store.
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk import sentiment
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_tone_validity as tv
from backend.cli.market_release_eval import MIN_NAMES
from backend.market import language, release_text, text_surprise
from backend.market.store import MarketStore

# The plan's windows: the in-window period the A1-1 criteria are judged
# on, the post-cutoff period the reader cannot have trained on, and both
# as one for A1-3, which is point-in-time by construction.
IN_WINDOW: tuple[date, date] = (date(2018, 1, 1), date(2025, 5, 31))
POST_WINDOW: tuple[date, date | None] = (date(2025, 6, 1), None)
ALL_WINDOW: tuple[date, date | None] = (date(2018, 1, 1), None)
WINDOWS: dict[str, tuple[date, date | None]] = {
    "in_window": IN_WINDOW,
    "post_window": POST_WINDOW,
    "all_window": ALL_WINDOW,
}
HORIZONS: tuple[int, ...] = (20, 60)
PRIMARY_HORIZON = 20
# The plan's criteria.
IC_FLOOR = 0.02
T_FLOOR = 2.0
PAIRED_T_FLOOR = -1.0
SIXTH_ANALYST_CORRELATION = 0.3
ARM_A = tv.ARM_A
ARM_LEVEL = "A1-0 level only (null)"
ARM_PREFIX_TONE = "A1-1 "
ARM_WORD = "A1-3 word surprise"
TONE_TABLE = "tone_surprise.parquet"
WORD_TABLE = "word_surprise.parquet"
WORD_FIT = "word_surprise_fit.json"
STANCE_DIR = "stances"
# The follow-up the book gate needs: the scorecard has no sixth-stance
# flag yet (`market_pit_scorecard` grades exactly five stances), so the
# stance table is written here and the command is recorded for the run
# that adds one, as `--structure-notch` was added for S1g.
SCORECARD_FOLLOW_UP = (
    "python -m backend.cli.market_pit_scorecard --graded-cap 0.25 --rank-ic "
    "--stance-table {table} --output {output}  "
    "(needs a --stance-table flag on the scorecard, a follow-up like "
    "research/structure-rules' --structure-notch; the T-S1 gate: +2 bp of "
    "equity a session at 25 bp over graded-equal-weight/5, NW t >= 2 on the "
    "model window, not negative after, 15 of 20 offsets, deflated Sharpe at "
    "the cumulative count >= 0.95)"
)


# The command line: `build` and `evaluate`.
def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser with one subcommand per step."""
    parser = argparse.ArgumentParser(description="Text-surprise study (A1).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="write the per-release score tables")
    b.add_argument("--root", required=True, type=Path, help="the market store")
    b.add_argument(
        "--texts",
        type=Path,
        default=None,
        help="release texts: a store root, a directory of <TICKER>.jsonl, or "
        "one JSONL file (default: --root)",
    )
    b.add_argument("--out", required=True, type=Path)
    b.add_argument(
        "--c",
        type=float,
        default=None,
        help="fix A1-3's C instead of choosing it on the first training set",
    )
    b.add_argument(
        "--skip-word", action="store_true", help="build the tone-surprise table only"
    )
    e = sub.add_parser("evaluate", help="measure the arms on shared cells")
    e.add_argument("--root", required=True, type=Path)
    e.add_argument("--tables", required=True, type=Path, help="the build output")
    e.add_argument("--out", required=True, type=Path, help="the payload (JSON)")
    e.add_argument(
        "--stances",
        type=Path,
        default=None,
        help="where the stance tables go (default: <tables>/stances)",
    )
    return parser


# --- texts -------------------------------------------------------------------


# Release texts from wherever the study keeps them: a store root with
# `edgar_release_text` frames (the tone-validity study's source), a
# directory of `<TICKER>.jsonl` partial files, or one JSONL file whose
# rows carry ticker, accession, reaction_date and text. Restricted to
# `tickers` when given.
def load_texts(
    path: Path, tickers: Sequence[str] | None = None
) -> list[text_surprise.TextRow]:
    """Return every release text found at `path`, oldest first per name."""
    rows: list[text_surprise.TextRow] = []
    wanted = set(tickers) if tickers is not None else None
    if path.is_dir() and (path / release_text.RELEASE_TEXT_KIND).is_dir():
        store = MarketStore(path)
        names = list(tickers) if tickers is not None else _stored_text_tickers(path)
        for ticker, record in tv.stored_texts(store, names):
            rows.append(
                text_surprise.TextRow(
                    ticker, record.accession, record.reaction_date, record.text
                )
            )
    elif path.is_dir():
        for file in sorted(path.glob("*.jsonl")):
            ticker = file.stem.split(".")[0]
            if wanted is not None and ticker not in wanted:
                continue
            rows.extend(_rows_from_jsonl(file, ticker))
    elif path.is_file():
        rows.extend(
            r
            for r in _rows_from_jsonl(path, None)
            if wanted is None or r.ticker in wanted
        )
    else:
        raise SystemExit(f"no release texts at {path}")
    rows.sort(key=lambda r: (r.ticker, r.reaction_date, r.accession))
    return rows


# Every ticker with a release-text frame under a store root, any partition.
def _stored_text_tickers(root: Path) -> list[str]:
    base = root / release_text.RELEASE_TEXT_KIND
    names = {
        p.stem
        for part in base.iterdir()
        if part.is_dir()
        for p in part.glob("*.parquet")
    }
    return sorted(names)


# Text rows from one JSONL file; `ticker` names the file's ticker when the
# rows carry none.
def _rows_from_jsonl(path: Path, ticker: str | None) -> list[text_surprise.TextRow]:
    out: list[text_surprise.TextRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        name = payload.get("ticker") or ticker
        if not name:
            raise SystemExit(f"{path}: a row carries no ticker")
        out.append(
            text_surprise.TextRow(
                str(name),
                str(payload["accession"]),
                date.fromisoformat(str(payload["reaction_date"])),
                str(payload["text"]),
            )
        )
    return out


# --- tables ------------------------------------------------------------------


# The tone-surprise table: one row per stored release of each name.
def tone_table(
    records: Mapping[str, Sequence[language.ToneRecord]],
) -> dict[str, list]:
    """Return the columns of the A1-1 table from the stored tone records."""
    columns: dict[str, list] = {"ticker": [], "accession": [], "reaction_date": []}
    for name in text_surprise.FIELDS:
        columns[f"level_{name}"] = []
        columns[f"change_{name}"] = []
    for ticker in sorted(records):
        for row in text_surprise.tone_surprise(records[ticker]):
            columns["ticker"].append(ticker)
            columns["accession"].append(row.accession)
            columns["reaction_date"].append(row.reaction_date.isoformat())
            for j, name in enumerate(text_surprise.FIELDS):
                columns[f"level_{name}"].append(float(row.level[j]))
                columns[f"change_{name}"].append(float(row.change[j]))
    return columns


# The tone-surprise rows a table encodes, per name.
def tone_rows_from_table(
    columns: Mapping[str, list],
) -> dict[str, list[text_surprise.SurpriseRow]]:
    """Return {ticker: [SurpriseRow, ...]} from the A1-1 table's columns."""
    out: dict[str, list[text_surprise.SurpriseRow]] = {}
    for i in range(len(columns["ticker"])):
        row = text_surprise.SurpriseRow(
            accession=str(columns["accession"][i]),
            reaction_date=date.fromisoformat(str(columns["reaction_date"][i])),
            level=tuple(float(columns[f"level_{n}"][i]) for n in text_surprise.FIELDS),
            change=tuple(
                float(columns[f"change_{n}"][i]) for n in text_surprise.FIELDS
            ),
        )
        out.setdefault(str(columns["ticker"][i]), []).append(row)
    return out


# The word-surprise table: one row per text, with its label and score.
def word_table(panel, result: text_surprise.WordSurprise) -> dict[str, list]:
    """Return the columns of the A1-3 table from a WordSurprise."""
    columns: dict[str, list] = {
        "ticker": [],
        "accession": [],
        "reaction_date": [],
        "reaction_session": [],
        "label": [],
        "label_sign": [],
        "fit_year": [],
        "c": [],
        "score": [],
    }
    for i, row in enumerate(result.rows):
        session = int(result.sessions[i])
        label = float(result.labels[i])
        columns["ticker"].append(row.ticker)
        columns["accession"].append(row.accession)
        columns["reaction_date"].append(row.reaction_date.isoformat())
        columns["reaction_session"].append(
            str(panel.dates[session]) if session >= 0 else ""
        )
        columns["label"].append(label)
        columns["label_sign"].append(
            0 if not np.isfinite(label) or label == 0.0 else (1 if label > 0 else -1)
        )
        columns["fit_year"].append(int(result.fit_years[i]))
        columns["c"].append(float(result.c))
        columns["score"].append(float(result.scores[i]))
    return columns


# The word-surprise scores a table encodes, as {ticker: [(date, score)]}.
def word_rows_from_table(
    columns: Mapping[str, list],
) -> dict[str, list[tuple[date, Sequence[float]]]]:
    """Return the carry-forward rows of the A1-3 table."""
    out: dict[str, list[tuple[date, Sequence[float]]]] = {}
    for i in range(len(columns["ticker"])):
        out.setdefault(str(columns["ticker"][i]), []).append(
            (
                date.fromisoformat(str(columns["reaction_date"][i])),
                (float(columns["score"][i]),),
            )
        )
    return out


# Write a column table as parquet (pyarrow, imported here as the store does).
def write_table(path: Path, columns: Mapping[str, list]) -> None:
    """Write `columns` to `path` as one parquet file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({k: pa.array(v) for k, v in columns.items()}), path)


# Read a parquet table back as columns.
def read_table(path: Path) -> dict[str, list]:
    """Return the columns of the parquet file at `path`."""
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pydict()


# --- build -------------------------------------------------------------------


# The stored tone records of every name in the panel.
def stored_tone_records(
    store: MarketStore, tickers: Sequence[str]
) -> dict[str, tuple[language.ToneRecord, ...]]:
    """Return {ticker: records} from the newest edgar_tone frames."""
    out: dict[str, tuple[language.ToneRecord, ...]] = {}
    for ticker in tickers:
        frame = store.read_frame(language.TONE_KIND, ticker)
        if frame is not None:
            out[ticker] = language.records_from_frame(frame[0])
    return out


# Build both tables and the fit record under `out`.
def run_build(
    root: Path, texts: Path | None, out: Path, c: float | None, skip_word: bool
) -> dict[str, Any]:
    """Write the A1-1 and A1-3 tables; return a summary."""
    panel, sides, _tone = tv._panel_and_tone(root)
    book = [t for t in panel.tickers if t in sides]
    records = stored_tone_records(MarketStore(root), book)
    tone = tone_table(records)
    out.mkdir(parents=True, exist_ok=True)
    write_table(out / TONE_TABLE, tone)
    summary: dict[str, Any] = {
        "tone_releases": len(tone["ticker"]),
        "tone_names": len(records),
        "tone_with_predecessor": int(
            np.isfinite(np.asarray(tone[f"change_{text_surprise.FIELDS[0]}"])).sum()
        ),
    }
    print(
        f"A1-1: {summary['tone_releases']} releases over {summary['tone_names']} "
        f"names, {summary['tone_with_predecessor']} with a predecessor",
        flush=True,
    )
    if skip_word:
        return summary
    rows = load_texts(texts or root, book)
    print(f"A1-3: {len(rows)} release texts", flush=True)
    result = text_surprise.word_surprise(panel, rows, c=c)
    write_table(out / WORD_TABLE, word_table(panel, result))
    fit = {
        "c": result.c,
        "selection": result.selection,
        "refits": list(result.refits),
        "texts": len(rows),
        "labelled": int(np.isfinite(result.labels).sum()),
        "scored": int(np.isfinite(result.scores).sum()),
        "purge": text_surprise.PURGE,
        "min_df": text_surprise.MIN_DF,
        "first_refit_year": text_surprise.FIRST_REFIT_YEAR,
    }
    (out / WORD_FIT).write_text(json.dumps(fit, indent=2, default=float))
    summary.update(word=fit)
    print(
        f"A1-3: C {result.c} ({result.selection}); {fit['scored']} of "
        f"{fit['texts']} texts scored",
        flush=True,
    )
    return summary


# --- evaluate ----------------------------------------------------------------


# Every arm's (T, N) percentile ranks: A from the stored tone block as the
# analyst ranks it, the null arm and the three A1-1 variants from the
# tone-surprise rows, A1-3 from the word-surprise rows when given.
def arm_ranks(
    panel,
    tone_a: np.ndarray,
    tone_rows: Mapping[str, Sequence[text_surprise.SurpriseRow]],
    word_rows: Mapping[str, Sequence[tuple[date, Sequence[float]]]] | None,
) -> dict[str, np.ndarray]:
    """Return {arm name: (T, N) ranks} for every arm present."""
    level, change = text_surprise.aligned_surprise(panel, tone_rows)
    arms = {
        ARM_A: sentiment.opine(tone_a).ranks(),
        ARM_LEVEL: Opinion("level", text_surprise.level_scores(level)).ranks(),
    }
    for variant, scores in text_surprise.variant_scores(level, change).items():
        arms[ARM_PREFIX_TONE + variant] = Opinion(variant, scores).ranks()
    if word_rows is not None:
        scores = text_surprise.carry_forward(panel, word_rows, 1)[:, :, 0]
        arms[ARM_WORD] = Opinion("word", scores).ranks()
    return arms


# The null test: the level arm against A on their shared cells, per
# horizon and window; every per-period IC must be equal to the bit.
def null_test(
    arms: Mapping[str, np.ndarray], panel, in_book: np.ndarray
) -> dict[str, Any]:
    """Return {"pass": bool, "checks": [...]} comparing the level arm with A."""
    checks: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        for name, (start, end) in WINDOWS.items():
            inside = tv.window_mask(panel.dates, start, end)[:, None] & in_book[None, :]
            window = tv._measure_window(
                {ARM_A: arms[ARM_A], ARM_LEVEL: arms[ARM_LEVEL]}, inside, panel, horizon
            )
            a = window["arms"][ARM_A]["period_ics"]
            b = window["arms"][ARM_LEVEL]["period_ics"]
            same_keys = list(a) == list(b)
            equal = same_keys and all(
                (np.isnan(a[k]) and np.isnan(b[k])) or a[k] == b[k] for k in a
            )
            checks.append(
                {
                    "horizon": horizon,
                    "window": name,
                    "periods": len(a),
                    "cells": window["cells"],
                    "equal": bool(equal),
                }
            )
    return {"pass": all(c["equal"] for c in checks), "checks": checks}


# One group of arms measured with A on their shared cells, with each arm's
# rank correlation with A on the same cells.
def _group(
    arms: Mapping[str, np.ndarray], inside: np.ndarray, panel, horizon: int
) -> dict[str, Any]:
    window = tv._measure_window(arms, inside, panel, horizon)
    cells = inside.copy()
    for scores in arms.values():
        cells &= np.isfinite(scores)
    window["correlation_with_A"] = {
        arm: text_surprise.mean_cross_sectional_correlation(
            arms[ARM_A], scores, cells, MIN_NAMES
        )
        for arm, scores in arms.items()
        if arm != ARM_A
    }
    return window


# Measure every arm on the shared cells, per horizon and window: A1-1's
# variants with A on their shared cells, A1-3 with A on its own, and all
# of them together.
def evaluate_arms(
    panel, sides: Mapping[str, str], arms: Mapping[str, np.ndarray]
) -> dict[str, Any]:
    """Return the study payload: groups per horizon and window, criteria, verdicts."""
    in_book = np.array([t in sides for t in panel.tickers])
    tone_arms = {
        k: v for k, v in arms.items() if k == ARM_A or k.startswith(ARM_PREFIX_TONE)
    }
    groups: dict[str, dict[str, np.ndarray]] = {"a1_1": tone_arms}
    if ARM_WORD in arms:
        groups["a1_3"] = {ARM_A: arms[ARM_A], ARM_WORD: arms[ARM_WORD]}
        groups["all"] = {**tone_arms, ARM_WORD: arms[ARM_WORD]}
    payload: dict[str, Any] = {
        "windows": {
            k: [s.isoformat(), e.isoformat() if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "horizons": {},
    }
    for horizon in HORIZONS:
        per_window: dict[str, Any] = {}
        for name, (start, end) in WINDOWS.items():
            inside = tv.window_mask(panel.dates, start, end)[:, None] & in_book[None, :]
            per_window[name] = {
                group: _group(members, inside, panel, horizon)
                for group, members in groups.items()
            }
        payload["horizons"][str(horizon)] = per_window
    payload["null_test"] = null_test(arms, panel, in_book)
    payload["criteria"] = criteria(
        payload["horizons"][str(PRIMARY_HORIZON)], payload["null_test"]["pass"]
    )
    payload["verdicts"] = {arm: verdict(c) for arm, c in payload["criteria"].items()}
    return payload


# The plan's IC floor per arm at the primary horizon: A1-1 on the
# in-window period, A1-3 on both windows as one. The paired IC against A
# must not be negative at t <= -1; the role follows the correlation with
# the level. The book gate is a separate run and is recorded as pending.
def criteria(windows: Mapping[str, Any], null_pass: bool) -> dict[str, Any]:
    """Return {arm: criteria} from the primary horizon's window results."""
    out: dict[str, Any] = {}
    reads = [("a1_1", "in_window")]
    if "a1_3" in windows["in_window"]:
        reads.append(("a1_3", "all_window"))
    for group, window in reads:
        block = windows[window][group]
        for arm, r in block["arms"].items():
            if arm == ARM_A:
                continue
            pair = block["paired_vs_A"][arm]
            corr = block["correlation_with_A"][arm]["mean"]
            ic, t = r["ic"], r["t"]
            clears = bool(
                np.isfinite(ic) and ic >= IC_FLOOR and np.isfinite(t) and t >= T_FLOOR
            )
            not_worse = not bool(
                np.isfinite(pair["delta"])
                and pair["delta"] < 0
                and np.isfinite(pair["t"])
                and pair["t"] <= PAIRED_T_FLOOR
            )
            post = windows["post_window"][group]["arms"].get(arm, {})
            out[arm] = {
                "window": window,
                "ic": ic,
                "t": t,
                "ic_post_window": post.get("ic", float("nan")),
                "t_post_window": post.get("t", float("nan")),
                "paired_delta_vs_A": pair["delta"],
                "paired_t_vs_A": pair["t"],
                "correlation_with_A": corr,
                "clears_ic_floor": clears,
                "not_worse_than_A": not_worse,
                "null_test_pass": bool(null_pass),
                "role": (
                    "sixth analyst"
                    if np.isfinite(corr) and corr < SIXTH_ANALYST_CORRELATION
                    else "replacement candidate"
                ),
                "book_gate": "pending: " + SCORECARD_FOLLOW_UP
                if clears and not_worse and null_pass
                else "not run: the IC floor was not cleared",
            }
    return out


# The one-line reading of one arm's criteria.
def verdict(crit: Mapping[str, Any]) -> str:
    """Return the arm's verdict line per the plan."""
    if not crit["null_test_pass"]:
        return (
            "INVALID: the null test failed; nothing here is comparable with the analyst"
        )
    if crit["clears_ic_floor"] and crit["not_worse_than_A"]:
        return (
            f"CANDIDATE ({crit['role']}): clears the IC floor on {crit['window']}; "
            "proposed as a stance only if the T-S1 book gate holds (pending)"
        )
    return "RECORD"


# Each arm's stance table in long form: (session, ticker, stance) for every
# non-zero stance under the analyst's own rule (top and bottom 30%, three
# sessions' persistence), for the scorecard follow-up.
def stance_table(panel, ranks: np.ndarray) -> dict[str, list]:
    """Return the columns of one arm's stance table."""
    scores = np.where(np.isfinite(ranks), ranks, np.nan)
    stances = Opinion("arm", scores).stances()
    t_index, n_index = np.nonzero(stances != 0)
    return {
        "session": [str(panel.dates[t]) for t in t_index],
        "ticker": [panel.tickers[n] for n in n_index],
        "stance": [int(stances[t, n]) for t, n in zip(t_index, n_index, strict=True)],
    }


# The payload, printed.
def print_payload(payload: Mapping[str, Any]) -> None:
    """Print the arms at the primary horizon, the null test and the verdicts."""
    null = payload["null_test"]
    print(
        f"null test (level legs reproduce A bit for bit): "
        f"{'PASS' if null['pass'] else 'FAIL'} over {len(null['checks'])} checks"
    )
    for horizon in HORIZONS:
        windows = payload["horizons"][str(horizon)]
        for name, groups in windows.items():
            for group, window in groups.items():
                print(
                    f"\n=== horizon {horizon}, {name}, {group}: "
                    f"{window['cells']:,} cells ==="
                )
                header = f"{'arm':30} {'rank IC':>9} {'t':>7} {'net Sharpe':>11}"
                print(f"{header} {'periods':>8}")
                for arm, r in window["arms"].items():
                    print(
                        f"{arm:30} {r['ic']:+9.4f} {r['t']:+7.2f} "
                        f"{r['net_sharpe']:+11.2f} {r['periods']:8d}"
                    )
                for arm, p in window["paired_vs_A"].items():
                    corr = window["correlation_with_A"][arm]
                    print(
                        f"  {arm} - A: {p['delta']:+.4f} (paired t {p['t']:+.2f}); "
                        f"rank correlation with A {corr['mean']:+.3f}"
                    )
    print("\n=== criteria (primary horizon) ===")
    for arm, crit in payload["criteria"].items():
        print(
            f"{arm}: IC {crit['ic']:+.4f} (t {crit['t']:+.2f}) on {crit['window']}, "
            f"post {crit['ic_post_window']:+.4f}, paired vs A "
            f"{crit['paired_delta_vs_A']:+.4f} (t {crit['paired_t_vs_A']:+.2f}), "
            f"corr {crit['correlation_with_A']:+.3f} -> {crit['role']}"
        )
    print("\n=== verdicts ===")
    for arm, line in payload["verdicts"].items():
        print(f"{arm}: {line}")


# Read the tables, measure, write the payload and the stance tables.
def run_evaluate(
    root: Path, tables: Path, out: Path, stances: Path | None
) -> dict[str, Any]:
    """Evaluate the built tables; return the payload."""
    panel, sides, tone_a = tv._panel_and_tone(root)
    tone_rows = tone_rows_from_table(read_table(tables / TONE_TABLE))
    word_path = tables / WORD_TABLE
    word_rows = (
        word_rows_from_table(read_table(word_path)) if word_path.exists() else None
    )
    arms = arm_ranks(panel, tone_a, tone_rows, word_rows)
    payload = evaluate_arms(panel, sides, arms)
    fit_path = tables / WORD_FIT
    if fit_path.exists():
        payload["word_surprise_fit"] = json.loads(fit_path.read_text())
    stance_root = stances or tables / STANCE_DIR
    payload["stance_tables"] = {}
    for arm, ranks in arms.items():
        if arm in (ARM_A, ARM_LEVEL):
            continue
        path = stance_root / (arm.replace(" ", "_").replace("/", "_") + ".parquet")
        write_table(path, stance_table(panel, ranks))
        payload["stance_tables"][arm] = str(path)
    payload["scorecard_follow_up"] = SCORECARD_FOLLOW_UP
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print_payload(payload)
    return payload


# Run the tool.
def main() -> None:
    """Entry point: one subcommand per step of the study."""
    args = build_parser().parse_args()
    if args.command == "build":
        summary = run_build(args.root, args.texts, args.out, args.c, args.skip_word)
        print(json.dumps(summary, indent=2, default=float))
    elif args.command == "evaluate":
        run_evaluate(args.root, args.tables, args.out, args.stances)


if __name__ == "__main__":
    main()
