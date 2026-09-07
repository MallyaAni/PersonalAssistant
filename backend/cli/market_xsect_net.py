"""A cross-sectional network trained on the yardstick the desk is judged by.

    python -m backend.cli.market_xsect_net
    python -m backend.cli.market_xsect_net --steps A B
    python -m backend.cli.market_xsect_net --steps C D --epochs 60

The earlier networks were asked to do something they could not represent.
The desk's score is a rank across the ninety names on a session; a network
that sees one name at a time has no way to compute a rank, whatever
weights it learns. This one reads the whole session at once and is
trained with a ranking loss: maximise the correlation between its scores
and the forward beta-adjusted return ranks, which is exactly the number
the harness reports.

A ladder, so a failure can be told apart from a bug:

  step A  target = the desk's own graded score. If the network cannot
          reproduce a rule it is handed the inputs to, the training is
          broken and nothing after it means anything.
  step B  target = the real forward return rank, same inputs. Can it beat
          the rule using the rule's own evidence?
  step C  same, with the raw evidence instead of the analysts' ranks, so
          the network chooses its own weighting from the ground up.
  step D  step C plus a cross-name attention layer, so a name can be
          scored in the light of the others.

Walk-forward with the harness's folds, three seeds averaged per fold,
every step reported on the cells every step scored, and each step also
rank-blended with the desk's fixed grade.

Results
-------
Against the current analysts, seventeen folds at twenty sessions:

                                       h20 rank IC     t   net Sharpe
  the desk's fixed grade                   0.0530              1.03
  step A, imitating the rule               0.0537   3.31       1.00
  step B, the real forward rank            0.0052   0.42   negative
  step B blended with the grade            0.0395

At sixty sessions step B reads 0.0137 (t 0.66), also at a negative
Sharpe. Steps C and D, given eighty-seven raw features instead of the
analysts' ranks, went negative when first run and were not repeated.

An earlier run of step A beat the rule it copied, 0.049 against 0.043,
and the reason was not information - it saw exactly the rule's inputs -
but smoothing: the hard edges of a stance flipping at a percentile and a
grade landing in one of four buckets. Continuous conviction gave the rule
that without a network, and the gap closed. Nothing in this ladder argues
for a network in the decision path.
"""

import argparse
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from backend.agents.trading.desk import desk as trading_desk
from backend.market import baselines, edgar, language, levels, technical, valuation
from backend.market.harness import evaluate_scores, walk_forward_folds
from backend.market.levels_pit import point_in_time_levels
from backend.market.model import load_edgar_features, load_tone_features
from backend.market.store import MarketStore

HORIZON = 20
TRAIN, TEST, EMBARGO = 750, 125, 5
HIDDEN = 128
BATCH = 64
MIN_NAMES = 15
MIN_TRAIN_SESSIONS = 200
COST_BPS = 10.0
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
STEPS = ("A", "B", "C", "D")
ANALYSTS = ("fundamental", "technical", "sentiment", "value")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Run the cross-sectional ladder.")
    parser.add_argument("--steps", nargs="+", choices=STEPS, default=list(STEPS))
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--data-dir", default="data/market")
    return parser


@dataclass(frozen=True)
class Data:
    """The two feature sets, the two targets, and which cells count."""

    analyst_x: np.ndarray  # (T, N, 5) the analysts' ranks and rotation, centred
    raw_x: np.ndarray  # (T, N, F) every raw feature as a session rank, centred
    label_rank: np.ndarray  # (T, N) rank of the forward beta-adjusted residual
    grade_rank: np.ndarray  # (T, N) rank of the desk's own graded score
    eligible: np.ndarray  # (T, N) book names with a price
    labelled: np.ndarray  # (T, N) eligible cells with a label


# Every feature turned into its rank within the session, which is the form
# the desk's own rules use and the only form in which "compared with the
# other names today" is expressible. Centred at zero; missing reads zero.
def _session_ranks(features: dict[str, np.ndarray], in_book: np.ndarray):
    stack = []
    for values in features.values():
        masked = np.where(in_book[None, :], values, np.nan)
        ranks = baselines.percentile_rank(masked)
        stack.append(np.where(np.isfinite(ranks), ranks - 0.5, 0.0))
    return np.stack(stack, axis=2).astype(np.float32)


# The analysts' ranks and rotation: what the rule itself reads.
def _analyst_features(report) -> dict[str, np.ndarray]:
    features = {name: report.opinions[name].ranks() for name in ANALYSTS}
    features["rotation"] = report.regime.rotation.ranks()
    return features


# The raw evidence beneath the analysts: filings, tone, tape, levels,
# multiples and cheapness, size, momentum, relative volume and the regime.
def _raw_features(store: MarketStore, report) -> dict[str, np.ndarray]:
    panel = report.panel
    rows, names = panel.adj_close.shape
    features: dict[str, np.ndarray] = {}
    extra = load_edgar_features(store, panel)
    for i, name in enumerate(edgar.FEATURE_NAMES):
        features[f"edgar_{name}"] = extra[:, :, i]
    tone = load_tone_features(store, panel)
    for i, name in enumerate(language.FEATURE_NAMES):
        features[f"tone_{name}"] = tone[:, :, i]
    tech = technical.technical_features(panel)
    for i, name in enumerate(technical.TECHNICAL_NAMES):
        features[f"tech_{name}"] = tech[:, :, i]
    loc = levels.level_features(panel)
    for i, name in enumerate(levels.LEVEL_NAMES):
        features[f"level_{name}"] = loc[:, :, i]
    pit = point_in_time_levels(store, panel)
    ratios = valuation.multiples(
        panel,
        pit["revenue"],
        pit["earnings"],
        pit["equity"],
        pit["shares"],
        pit["revenue_growth"],
    )
    peers = valuation.groups_from(panel, report.sides)
    for name in valuation.MULTIPLES:
        features[f"mult_{name}"] = ratios.get(name)
        features[f"cheap_{name}"] = valuation.cheapness(ratios.get(name), peers)
    features["market_cap"] = np.log(ratios.market_cap)
    features["momentum_120"] = baselines.momentum(panel, 120, 21)
    features["momentum_20"] = baselines.momentum(panel, 20, 1)
    volume = np.where(panel.volume > 0, panel.volume, np.nan)
    with np.errstate(all="ignore"):
        logvol = np.log(volume)
        avg20 = np.full((rows, names), np.nan)
        for t in range(19, rows):
            avg20[t] = np.nanmean(logvol[t - 19 : t + 1], axis=0)
        features["relative_volume"] = logvol - avg20
    states = report.regime.states
    for name, series in (
        ("regime_participation", [s.participation_percentile for s in states]),
        ("regime_ai_trend", [s.ai_trend_60 for s in states]),
        ("regime_corr", [s.ai_vs_software_correlation for s in states]),
        ("regime_drawdown", [s.ai_drawdown for s in states]),
    ):
        features[name] = np.repeat(np.array(series)[:, None], names, axis=1)
    return features


# Everything the ladder needs, built once.
def _data(store: MarketStore, report) -> Data:
    panel = report.panel
    in_book = np.array([t in report.sides for t in panel.tickers])
    eligible = in_book[None, :] & np.isfinite(panel.adj_close)
    eligible[:, panel.index(panel.benchmark)] = False
    label_rank = baselines.percentile_rank(panel.forward_residual(HORIZON))
    grade_rank = baselines.percentile_rank(
        np.where(in_book[None, :], report.scores, np.nan)
    )
    return Data(
        analyst_x=_session_ranks(_analyst_features(report), in_book),
        raw_x=_session_ranks(_raw_features(store, report), in_book),
        label_rank=label_rank,
        grade_rank=grade_rank,
        eligible=eligible,
        labelled=eligible & np.isfinite(label_rank),
    )


class CrossSection(nn.Module):
    """Scores every name on a session, optionally letting them see each other."""

    def __init__(self, features: int, attend: bool) -> None:
        super().__init__()
        self.encode = nn.Sequential(
            nn.Linear(features, HIDDEN),
            nn.LayerNorm(HIDDEN),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN),
            nn.LayerNorm(HIDDEN),
            nn.GELU(),
        )
        self.attend = (
            nn.MultiheadAttention(HIDDEN, 4, batch_first=True) if attend else None
        )
        self.out = nn.Linear(HIDDEN, 1)

    def forward(self, x, mask):
        """Return one score per name; `mask` marks the names that count."""
        h = self.encode(x)
        if self.attend is not None:
            attended, _w = self.attend(h, h, h, key_padding_mask=~mask)
            h = h + torch.nan_to_num(attended)
        return self.out(h).squeeze(-1)


# The loss the harness measures: one minus the correlation between the
# scores and the target ranks, within each session.
def _session_loss(scores, targets, mask):
    total = 0.0
    count = 0
    for i in range(scores.shape[0]):
        m = mask[i]
        if m.sum() < MIN_NAMES:
            continue
        a = scores[i][m]
        b = targets[i][m]
        a = (a - a.mean()) / (a.std() + 1e-6)
        b = (b - b.mean()) / (b.std() + 1e-6)
        total = total + (1.0 - (a * b).mean())
        count += 1
    return total / max(count, 1)


# Train one network on the given sessions and return it in eval mode.
def _train(x_gpu, y_gpu, ok, idx, attend: bool, seed: int, epochs: int):
    torch.manual_seed(seed)
    model = CrossSection(x_gpu.shape[2], attend).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-2)
    model.train()
    for _epoch in range(epochs):
        perm = idx[torch.randperm(len(idx), device=DEVICE)]
        for i in range(0, len(perm), BATCH):
            batch = perm[i : i + BATCH]
            opt.zero_grad()
            loss = _session_loss(
                model(x_gpu[batch], ok[batch]), y_gpu[batch], ok[batch]
            )
            loss.backward()
            opt.step()
    model.eval()
    return model


# One step of the ladder: walk-forward out-of-sample scores for a feature
# set and a target, seeds averaged within each fold.
def _run_step(data: Data, name: str, x: np.ndarray, target, attend, args, panel):
    rows, names = target.shape
    x_gpu = torch.tensor(x, device=DEVICE)
    y_gpu = torch.tensor(
        np.nan_to_num(target, nan=0.5).astype(np.float32), device=DEVICE
    )
    ok = torch.tensor(data.labelled & np.isfinite(target), device=DEVICE)
    score_mask = torch.tensor(data.eligible, device=DEVICE)
    out = np.full((rows, names), np.nan, dtype=np.float32)
    for train, test in walk_forward_folds(rows, TRAIN, TEST, HORIZON, EMBARGO):
        sessions = [
            t for t in range(train.start, train.stop) if int(ok[t].sum()) >= MIN_NAMES
        ]
        if len(sessions) < MIN_TRAIN_SESSIONS:
            continue
        idx = torch.tensor(sessions, device=DEVICE)
        block = torch.arange(test.start, test.stop, device=DEVICE)
        acc = torch.zeros((test.stop - test.start, names), device=DEVICE)
        for seed in range(args.seeds):
            model = _train(x_gpu, y_gpu, ok, idx, attend, seed, args.epochs)
            with torch.no_grad():
                acc += model(x_gpu[block], score_mask[block])
        acc /= args.seeds
        span = np.arange(test.start, test.stop)
        out[span] = np.where(data.eligible[span], acc.cpu().numpy(), np.nan)
        print(f"  {name}: fold to {panel.dates[test.stop - 1]}", flush=True)
    return out


# One line of the final table: rank IC, t and net Sharpe at both horizons.
def _report(name: str, scores: np.ndarray, panel) -> None:
    line = f"{name:44}"
    for h in (20, 60):
        r = evaluate_scores(scores, panel, h, cost_bps=COST_BPS, min_names=MIN_NAMES)
        line += f" {r.mean_ic:+8.4f} (t {r.ic_tstat:+5.2f}) Sh {r.net_sharpe:+5.2f}"
    print(line)


# How closely step A's scores track the rule they were asked to copy.
def _imitation(fitted: np.ndarray, grade_rank: np.ndarray) -> float:
    covered = np.isfinite(fitted) & np.isfinite(grade_rank)
    rows = []
    for t in range(fitted.shape[0]):
        m = covered[t]
        if m.sum() >= MIN_NAMES:
            a, b = fitted[t, m], grade_rank[t, m]
            if a.std() > 0 and b.std() > 0:
                rows.append(np.corrcoef(a, b)[0, 1])
    return float(np.mean(rows)) if rows else float("nan")


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    report = trading_desk.run(store)
    panel = report.panel
    data = _data(store, report)
    print(
        f"analyst inputs {data.analyst_x.shape[2]}, raw inputs "
        f"{data.raw_x.shape[2]}, device {DEVICE}"
    )
    ladder = {
        "A": (
            "can it reproduce the desk's own rule?",
            data.analyst_x,
            data.grade_rank,
            False,
        ),
        "B": (
            "same inputs, the real forward rank",
            data.analyst_x,
            data.label_rank,
            False,
        ),
        "C": (
            "raw evidence instead of the analysts' ranks",
            data.raw_x,
            data.label_rank,
            False,
        ),
        "D": (
            "raw evidence, names attending to each other",
            data.raw_x,
            data.label_rank,
            True,
        ),
    }
    results: dict[str, np.ndarray] = {}
    for step in STEPS:
        if step not in args.steps:
            continue
        title, x, target, attend = ladder[step]
        print(f"\nstep {step}: {title}")
        results[step] = _run_step(data, step, x, target, attend, args, panel)
        if step == "A":
            tracked = _imitation(results[step], data.grade_rank)
            print(f"  correlation with the rule it was asked to copy: {tracked:+.3f}")

    print(f"\n{'score':44} {'h20':>26} {'h60':>26}")
    common = data.eligible.copy()
    for scores in results.values():
        common &= np.isfinite(scores)
    fixed = np.where(common, report.scores, np.nan)
    _report("the desk's fixed grade (same cells)", fixed, panel)
    for step, scores in results.items():
        masked = np.where(common, scores, np.nan)
        _report(f"network, step {step}", masked, panel)
        _report(
            f"network step {step} + fixed grade",
            baselines.rank_blend(masked, fixed),
            panel,
        )


if __name__ == "__main__":
    main()
