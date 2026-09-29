"""The frozen M3 model and the laggard shadow's command, on the CPU with tiny data.

What has to hold (backend/market/stage3_final.py and
docs/research/laggard-shadow-plan-2026-09-29.md):

- `next_fold` is `io.folds`'s fold at test_start = the session count, and
  refuses a window with no fit part.
- `fit_final` trains the grid on that fold with `stage3_nn`'s own code,
  keeps every seed of the configuration with the best validation score,
  and its validation forecasts are what `predict_final` gives for those
  rows from the model in memory, from the saved file and after a second
  load (identical).
- A saved model loads with torch's weights-only loader; its id is the
  file's sha256; a dataset with other daily columns is refused; a row
  whose ticker has no window gets NaN.
- The command:
  - `fit` saves the model and its parity record;
  - `parity` passes on the same machine and fails on a tampered record;
  - `nightly` forecasts only forward dates with cube sessions, never
    twice, marks book names without their own session's cube as
    unclean, scores the matured dates and writes the summary.
"""

import dataclasses
import io as textio
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from backend.cli import market_laggard_shadow as cli  # noqa: E402
from backend.market import laggard_shadow as shadow  # noqa: E402
from backend.market import stage3_final as final  # noqa: E402
from backend.market import stage3_io as io  # noqa: E402
from backend.market import stage3_nn as nn3  # noqa: E402

CHANNELS = len(io.SEQ_CHANNELS)
STEPS = io.STEPS_PER_SESSION
TWO = (
    {"lr": 3e-3, "dropout": 0.0, "width": 8},
    {"lr": 1e-3, "dropout": 0.1, "width": 8},
)
NAMES = np.array(["AAA", "BBB", "CCC", "DDD", "EEE"])


# Consecutive calendar dates from `start`.
def _dates(n, start="2026-06-01"):
    return np.datetime64(start, "D") + np.arange(n)


# A random sequence tensor over the names and sessions; `invalid` lists
# (name, session) cells without a cube.
def _tensor(names, sessions, seed=0, invalid=()):
    rng = np.random.default_rng(seed)
    shape = (len(names), len(sessions), STEPS, CHANNELS)
    seq = rng.normal(size=shape).astype(np.float16)
    seq[..., -1] = 0
    seq[:, :, 0, -1] = 1
    valid = np.ones(shape[:2], dtype=bool)
    for n, s in invalid:
        valid[n, s] = False
        seq[n, s] = 0
    return io.SeqTensor(np.asarray(names), np.asarray(sessions), seq, valid)


# A T-S1 dataset with a row for every (date, name): a daily signal column,
# a noise column, grades (A+ for the first three names, A for the fourth, B
# for the last) and r = signal + noise, NaN on the last `immature` dates.
def _s1(dates, names, seed=2, immature=0):
    rng = np.random.default_rng(seed)
    count = len(dates) * len(names)
    signal = rng.normal(size=count)
    raw = signal + rng.normal(size=count)
    date_col = np.repeat(np.asarray(dates), len(names))
    if immature:
        raw[date_col >= np.asarray(dates)[-immature]] = np.nan
    grades = np.tile(np.array([3, 3, 3, 2, 1][: len(names)]), len(dates))
    x = np.stack([signal, rng.normal(size=count)], axis=1)
    return io.Stage3Data(
        kind=io.S1,
        dates=date_col,
        tickers=np.tile(np.asarray(names), len(dates)),
        slot=np.zeros(count, dtype=np.int8),
        x=x.astype(np.float32),
        feature_names=("d_signal", "d_noise"),
        y=io.rank_gauss(raw, date_col).astype(np.float32),
        extra={"r": raw.astype(np.float32), "grade": grades.astype(np.int8)},
    )


# Small CPU settings: two configurations, two seeds, a 10-session validation
# block and a gap of 3.
def _settings(**overrides):
    base = {"grid": TWO, "seeds": (0, 1), "max_epochs": 2, "patience": 1, "batch": 32,
            "validation": 10, "gap": 3, "device": "cpu"}
    return nn3.Settings(**{**base, **overrides})


# next_fold is the walk-forward's fold at test_start = n, and needs a fit part.
def test_next_fold_is_the_walk_forwards_next_fold():
    fold = final.next_fold(80, gap=3, validation=10)
    planned = io.folds(81, refit=50, gap=3, min_train=30, validation=10)
    assert planned[-1].test_start == 80
    assert (fold.window_end, fold.val_start, fold.fit_end) == (
        planned[-1].window_end, planned[-1].val_start, planned[-1].fit_end,
    ) == (77, 67, 64)
    assert fold.test_start == fold.test_end == 80
    with pytest.raises(ValueError, match="no fit part"):
        final.next_fold(20, gap=5, validation=10)


# Fit, the parity with the in-memory forecasts, save, load (weights only),
# identical reloads, refusal of other columns and NaN for a missing window.
def test_fit_save_load_and_predict_agree(tmp_path):
    sessions = _dates(80)
    data = _s1(sessions, NAMES)
    tensor = _tensor(NAMES, sessions)
    result = final.fit_final(data, tensor, _settings())
    model = result.model
    assert model.config in [dict(c) for c in TWO] and model.seeds == (0, 1)
    assert len(model.state_dicts) == 2 and model.daily_columns == ("d_signal", "d_noise")
    assert model.meta["fold"]["validation_dates"] == [str(sessions[67]), str(sessions[76])]
    assert model.meta["fold"]["fit_end"] == str(sessions[63]) and model.meta["registered"] is False
    assert model.meta["fold"]["last_session"] == str(sessions[-1])
    rows = result.validation_rows
    assert len(rows) == 10 * len(NAMES)
    np.testing.assert_allclose(final.predict_final(model, data, tensor, rows), result.validation_forecast, atol=1e-5)
    path = tmp_path / "m.pt"
    model_id = final.save_final(path, model)
    assert model_id == final.sha256(path)
    loaded = final.load_final(path)
    assert loaded.config == model.config and loaded.meta["fold"] == model.meta["fold"]
    once = final.predict_final(loaded, data, tensor, rows)
    twice = final.predict_final(final.load_final(path), data, tensor, rows)
    assert np.array_equal(once, twice)
    np.testing.assert_allclose(once, result.validation_forecast, atol=1e-5)
    renamed = dataclasses.replace(data, feature_names=("d_signal", "d_other"))
    with pytest.raises(ValueError, match="daily columns"):
        final.predict_final(loaded, renamed, tensor, rows)
    short = _tensor(NAMES[:4], sessions)
    out = final.predict_final(loaded, data, short, np.array([0, 4]))
    assert np.isfinite(out[0]) and np.isnan(out[1])


# The command end to end: fit and parity; then two nights of the shadow on
# an export that runs past the training data, one forward date without
# any cube (waiting) and one with a book name's cube missing (unclean).
def test_command_fit_parity_and_nightly(tmp_path):
    train_sessions = _dates(80)
    data = _s1(train_sessions, NAMES)
    tensor = _tensor(NAMES, train_sessions)
    data_path = io.save_data(tmp_path / "train_s1.npz", data)
    seq_path = io.save_seq(tmp_path / "train_seq.npz", tensor)
    model_path = tmp_path / "models" / "m.pt"
    out = textio.StringIO()
    args = cli.build_parser().parse_args([
        "fit", "--data", str(data_path), "--seq", str(seq_path), "--out", str(model_path), "--device", "cpu",
        "--grid-first", "1", "--seeds", "0,1", "--max-epochs", "1", "--validation", "10", "--gap", "3",
        "--batch", "64",
    ])
    assert cli.run(args, out=out) == 0
    assert "model " in out.getvalue() and cli.parity_path(model_path).exists()
    check = cli.build_parser().parse_args(["parity", "--model", str(model_path), "--data", str(data_path), "--seq", str(seq_path)])
    text = textio.StringIO()
    assert cli.run(check, out=text) == 0 and "parity ok" in text.getvalue()
    record = dict(np.load(cli.parity_path(model_path)))
    record["forecast"] = record["forecast"] + 1.0
    np.savez(cli.parity_path(model_path), **record)
    assert cli.run(check, out=textio.StringIO()) == 1

    # Nightly: five forward sessions; the fourth has no cube at all and the
    # second lacks CCC's; the last two are immature.
    all_sessions = _dates(85)
    night = _s1(all_sessions, NAMES, immature=2)
    cube_sessions = np.delete(all_sessions, 83)
    night_tensor = _tensor(NAMES, cube_sessions, invalid=[(2, 81)])
    shadow_dir = tmp_path / "shadow"

    # The stand-in export writes tonight's files where the real one would.
    def exporter(root, folder, workers, out):
        io.save_data(folder / "stage3_s1.npz", night)
        io.save_seq(folder / "stage3_seq.npz", night_tensor)
        return 0

    nightly = cli.build_parser().parse_args(["nightly", "--model", str(model_path), "--dir", str(shadow_dir)])
    report = textio.StringIO()
    assert cli.run_nightly(nightly, report, exporter=exporter) == 0
    ledger = shadow.read_ledger(shadow_dir / "ledger.jsonl")
    forward = [str(d) for d in all_sessions[80:]]
    assert [e["date"] for e in ledger] == [forward[0], forward[1], forward[2], forward[4]]
    assert "waiting for cubes: " + forward[3] in report.getvalue()
    assert ledger[1]["unclean"] == ["CCC"] and ledger[0]["unclean"] == []
    assert all(e["n"] == 4 and e["model_id"] == final.sha256(model_path) for e in ledger)
    summary = json.loads((shadow_dir / "summary.json").read_text())
    # Sessions 80-82 have matured; 81 is unclean, so the primary has two.
    assert summary["scored"] == 3 and summary["unclean_scored"] == 1
    assert summary["primary"]["n"] == 2 and summary["verdict"]["label"] == "PENDING"
    scores = json.loads((shadow_dir / "scores.json").read_text())
    assert [s["date"] for s in scores] == forward[:3]
    # A second night on the same export adds nothing: every date is final.
    again = textio.StringIO()
    assert cli.run_nightly(nightly, again, exporter=exporter) == 0
    assert len(shadow.read_ledger(shadow_dir / "ledger.jsonl")) == 4
    # A failed export forecasts nothing.
    assert cli.run_nightly(nightly, textio.StringIO(), exporter=lambda *a: 3) == 3
