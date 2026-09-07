"""Can a policy learn the book better than the rule that writes it?

    python -m backend.cli.market_allocation_rl
    python -m backend.cli.market_allocation_rl --seeds 3 --episodes 400

The supervised experiments answered a narrower question: given the
analysts' views, predict the forward ranking. This asks the thing the desk
actually does - choose weights - and rewards the agent for the outcome
rather than for a label. That is the reinforcement-learning framing, and
it is worth measuring rather than reasoning about.

  state    each name's four analyst convictions and its recent realised
           volatility, plus the regime's participation percentile,
           exposure and tightening flag
  action   a weight per name, non-negative, summing to the gross the rule
           itself would carry that session, so the agent cannot win by
           simply holding more
  reward   the book's realised return over the next REBALANCE sessions
           divided by its realised volatility over the same window - a
           Sharpe-shaped reward, so leverage is not rewarded

Two contenders, both against the desk's own rule on identical states:

  policy gradient   REINFORCE with a moving baseline, the standard
                    continuous-action approach
  cross-entropy     a derivative-free search over policy parameters,
                    which is often stronger than gradients when the
                    reward is noisy - and this reward is very noisy

Walk-forward, refit every REFIT sessions on everything before the fold
with the reward horizon purged at the boundary, so no policy is scored on
a window it trained through. Every contender sees the same states and the
same gross. Equal weight on the rule's own names is reported beside them,
because it is the null the sizing engine has to beat.

The prior is that this fails, and the reason is arithmetic rather than
architectural: about 1,300 sessions at a twenty-session horizon is roughly
65 independent periods, and a policy with thousands of parameters facing
65 observations fits the path rather than the process.

Results
-------
Ten folds, three seeds averaged into one action per session, 2,164 test
sessions, mean reward per rebalance window. Recorded above
`risk.desk_targets`. The paired difference from the rule carries three t
statistics: naive, Newey-West over the twenty-session reward window
(consecutive sessions' rewards share nineteen days of returns), and on
every twentieth session so that no two windows overlap.

                                mean    vs rule   naive   Newey-West   every 20th
  the desk's rule              +0.611
  equal weight, same names     +0.605   -0.006    -1.28     -0.46        +0.09
  policy gradient (REINFORCE)  +0.579   -0.032    -2.43     -0.72        -0.33
  cross-entropy search         +0.585   -0.026    -2.57     -0.79        -0.38

Neither agent beat the rule; both were slightly worse and neither
difference is distinguishable from zero once the overlap is counted. The
first run of this command printed t of +0.25 and +0.69 for the agents:
its pairing tiled the rule's rewards against seed-major policy rewards
and was misaligned across folds. The means, which carried the
conclusion, were unchanged by the fix. The line that matters is the
second: equal weight on the same names scored the same as the whole
sizing apparatus. Together with the volatility result in
`market_volatility`, the weighting is not where the risk-adjusted return
is decided. The selection is.
"""

import argparse
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import risk
from backend.market import sizing
from backend.market.store import MarketStore

ANALYSTS = ("fundamental", "technical", "sentiment", "value")
REBALANCE = 20
REFIT = 252
MIN_TRAIN = 500
VOL_LOOKBACK = 60
NOISE = 0.3  # exploration on the policy's scores
CE_ROUNDS = 12
CE_DRAWS = 24
CE_ELITE = 6
CE_SAMPLE = 60
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Learn the book's weights.")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--episodes", type=int, default=400)
    parser.add_argument("--data-dir", default="data/market")
    return parser


@dataclass(frozen=True)
class Problem:
    """The desk's state, its rule's weights, and the returns that score them."""

    simple: np.ndarray  # (T, M) simple returns of the book's names, 0 where none
    states: np.ndarray  # (T, M, 5) four convictions and log realised volatility
    regime: np.ndarray  # (T, 3) participation percentile, exposure, tightening
    rule: np.ndarray  # (T, M) the rule's weights, zero where it could not run
    dates: np.ndarray
    cols: np.ndarray  # (M,) the book's columns in the panel
    panel: object  # the panel, for the desk's own caps

    @property
    def features(self) -> int:
        """Return the width of one name's state, regime included."""
        return self.states.shape[-1] + self.regime.shape[1]


# What the rule does on every session it can run, so the agent has
# something to beat and a gross to be held to. The rule's gross is the
# ceiling: an agent that beats it by holding more has learned leverage.
def _rule_weights(report, cols: np.ndarray) -> np.ndarray:
    panel = report.panel
    rows = panel.adj_close.shape[0]
    out = np.zeros((rows, len(cols)))
    for t in range(MIN_TRAIN - REBALANCE, rows):
        try:
            _positions, targets = risk.desk_targets(
                report.scores[t],
                report.graded.grades[t],
                panel,
                report.regime.states[t],
                risk.BOOK_CONFIG,
            )
        except Exception:  # a session the rule cannot size is left empty
            continue
        out[t] = targets[cols]
    return out


# The problem as the agent sees it, from the desk's own report.
def _build(report) -> Problem:
    panel = report.panel
    in_book = np.array([t in report.sides for t in panel.tickers])
    in_book[panel.index(panel.benchmark)] = False
    cols = np.flatnonzero(in_book)
    simple = np.expm1(panel.log_returns())[:, cols]
    simple = np.where(np.isfinite(simple), simple, 0.0)
    convictions = np.nan_to_num(
        np.stack([report.opinions[k].conviction()[:, cols] for k in ANALYSTS], axis=-1)
    )
    vol = sizing.realised_volatility(panel, VOL_LOOKBACK)[:, cols]
    with np.errstate(all="ignore"):
        log_vol = np.nan_to_num(np.log(np.maximum(vol, 1e-4)))
    states = np.concatenate([convictions, log_vol[..., None]], axis=-1)
    regime = np.array(
        [
            [s.participation_percentile, s.exposure, 1.0 if s.tightening else 0.0]
            for s in report.regime.states
        ]
    )
    return Problem(
        simple, states, regime, _rule_weights(report, cols), panel.dates, cols, panel
    )


# The book's Sharpe-shaped reward over the window after `t`.
def _reward(problem: Problem, weights: np.ndarray, t: int) -> float:
    block = problem.simple[t + 1 : t + 1 + REBALANCE]
    if not len(block):
        return 0.0
    daily = block @ weights
    spread = float(daily.std())
    if spread <= 1e-9:
        return 0.0
    return float(daily.mean() * REBALANCE) / (spread * np.sqrt(REBALANCE))


# Every name's state on session `t`, the regime appended to each row.
def _state(problem: Problem, t: int) -> torch.Tensor:
    regime = np.repeat(problem.regime[t][None, :], problem.states.shape[1], axis=0)
    rows = np.concatenate([problem.states[t], regime], axis=-1)
    return torch.tensor(rows, dtype=torch.float32, device=DEVICE)


class Policy(nn.Module):
    """Scores every name from its own state; a softmax makes the book."""

    def __init__(self, width: int) -> None:
        super().__init__()
        self.body = nn.Sequential(nn.Linear(width, 32), nn.Tanh(), nn.Linear(32, 1))

    def forward(self, x):
        """Return one score per name."""
        return self.body(x).squeeze(-1)


# Scores to weights: a softmax scaled to the gross the rule carried.
def _weights(scores: torch.Tensor, gross: float) -> torch.Tensor:
    return torch.softmax(scores, dim=-1) * gross


# REINFORCE with a moving baseline, one session per episode.
def _policy_gradient(problem: Problem, sessions, seed: int, episodes: int) -> Policy:
    torch.manual_seed(seed)
    policy = Policy(problem.features).to(DEVICE)
    opt = torch.optim.Adam(policy.parameters(), lr=3e-3)
    baseline = 0.0
    rng = np.random.default_rng(seed)
    for _episode in range(episodes):
        t = int(rng.choice(sessions))
        gross = float(problem.rule[t].sum())
        if gross <= 0:
            continue
        scores = policy(_state(problem, t))
        # A stochastic book, so the gradient has something to learn from.
        noisy = scores + torch.randn_like(scores) * NOISE
        w = _weights(noisy, gross)
        reward = _reward(problem, w.detach().cpu().numpy(), t)
        baseline = 0.9 * baseline + 0.1 * reward
        logp = torch.log_softmax(noisy, dim=-1)
        loss = -(logp * w.detach()).sum() * (reward - baseline)
        opt.zero_grad()
        loss.backward()
        opt.step()
    return policy


# Mean reward of a policy over a sample of sessions, no gradient.
def _score(problem: Problem, policy: Policy, picks) -> float:
    total = 0.0
    with torch.no_grad():
        for t in picks:
            t = int(t)
            gross = float(problem.rule[t].sum())
            if gross <= 0:
                continue
            w = _weights(policy(_state(problem, t)), gross)
            total += _reward(problem, w.cpu().numpy(), t)
    return total / max(len(picks), 1)


# Derivative-free search: keep the parameter draws that scored best and
# resample around them.
def _cross_entropy(problem: Problem, sessions, seed: int) -> Policy:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    template = Policy(problem.features).to(DEVICE)
    flat = torch.nn.utils.parameters_to_vector(template.parameters()).detach()
    mean = torch.zeros_like(flat)
    std = torch.ones_like(flat) * 0.5
    sample = min(len(sessions), CE_SAMPLE)
    for _round in range(CE_ROUNDS):
        draws = [mean + std * torch.randn_like(mean) for _ in range(CE_DRAWS)]
        picks = rng.choice(sessions, size=sample, replace=False)
        scored = []
        for draw in draws:
            torch.nn.utils.vector_to_parameters(draw, template.parameters())
            scored.append((_score(problem, template, picks), draw))
        scored.sort(key=lambda pair: -pair[0])
        elite = torch.stack([d for _s, d in scored[:CE_ELITE]])
        mean, std = elite.mean(0), elite.std(0) + 1e-3
    torch.nn.utils.vector_to_parameters(mean, template.parameters())
    return template


# One reward per test session for a trained policy.
def _evaluate(problem: Problem, policy: Policy, sessions) -> list[float]:
    out = []
    with torch.no_grad():
        for t in sessions:
            gross = float(problem.rule[t].sum())
            if gross <= 0:
                continue
            w = _weights(policy(_state(problem, t)), gross).cpu().numpy()
            out.append(_reward(problem, w, t))
    return out


# A t statistic that survives overlapping windows: Newey-West with a
# Bartlett kernel over `lag` autocovariances. Consecutive sessions' rewards
# share REBALANCE - 1 days of returns, so the naive t overstates by about
# the square root of REBALANCE.
def _hac_t(diff: np.ndarray, lag: int) -> float:
    n = len(diff)
    d = diff - diff.mean()
    var = float(d @ d) / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2.0 * (1.0 - k / (lag + 1)) * float(d[:-k] @ d[k:]) / n
    return float(diff.mean() / np.sqrt(max(var, 1e-12) / n))


# Mean, spread and count, and the paired difference from the rule on the
# same sessions with three t statistics: naive, Newey-West over the reward
# window, and on every REBALANCE-th session so no two windows overlap.
def _summarise(name: str, values, reference=None) -> None:
    values = np.array(values, dtype=float)
    if not len(values):
        print(f"{name:34} no observations")
        return
    line = f"{name:34} {values.mean():+8.4f} {values.std():8.4f} {len(values):6d}"
    if reference is not None:
        diff = values - np.array(reference, dtype=float)
        naive = diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)) + 1e-12)
        apart = diff[::REBALANCE]
        sparse = apart.mean() / (apart.std(ddof=1) / np.sqrt(len(apart)) + 1e-12)
        line += (
            f"   vs rule {diff.mean():+8.4f}  t naive {naive:+5.2f}"
            f"  Newey-West {_hac_t(diff, REBALANCE - 1):+5.2f}"
            f"  every {REBALANCE}th {sparse:+5.2f}"
        )
    print(line)


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(args.data_dir))
    problem = _build(report)
    rows, names = problem.rule.shape
    can_run = problem.rule.sum(axis=1) > 0
    rule_rewards: list[float] = []
    equal_rewards: list[float] = []
    pg_rewards: list[float] = []
    ce_rewards: list[float] = []
    cuts = list(range(MIN_TRAIN, rows - REBALANCE, REFIT))
    print(f"{names} names, {problem.features} state features, {len(cuts)} folds")
    for number, cut in enumerate(cuts, start=1):
        train = [t for t in range(MIN_TRAIN - REBALANCE, cut - REBALANCE) if can_run[t]]
        test = [t for t in range(cut, min(cut + REFIT, rows - REBALANCE)) if can_run[t]]
        if len(train) < 100 or not test:
            continue
        for t in test:
            gross = float(problem.rule[t].sum())
            rule_rewards.append(_reward(problem, problem.rule[t], t))
            equal = np.where(problem.rule[t] > 0, 1.0, 0.0)
            if equal.sum() > 0:
                equal_rewards.append(_reward(problem, equal / equal.sum() * gross, t))
        # One action per session: the seeds' rewards averaged, so every
        # contender pairs with the rule session by session.
        pg_seeds, ce_seeds = [], []
        for seed in range(args.seeds):
            pg = _policy_gradient(problem, train, seed, args.episodes)
            pg_seeds.append(_evaluate(problem, pg, test))
            ce = _cross_entropy(problem, train, seed)
            ce_seeds.append(_evaluate(problem, ce, test))
        pg_rewards.extend(np.mean(pg_seeds, axis=0))
        ce_rewards.extend(np.mean(ce_seeds, axis=0))
        print(f"  fold {number}/{len(cuts)} to {problem.dates[cut]}", flush=True)
    print(f"\n{'policy':34} {'mean reward':>10} {'sd':>8} {'n':>6}")
    _summarise("the desk's rule", rule_rewards)
    _summarise("equal weight, same names", equal_rewards, rule_rewards)
    _summarise("policy gradient (REINFORCE)", pg_rewards, rule_rewards)
    _summarise("cross-entropy search", ce_rewards, rule_rewards)


if __name__ == "__main__":
    main()
