"""Offline reinforcement learning over the desk's own history.

    python -m backend.cli.market_offline_rl
    python -m backend.cli.market_offline_rl --candidates 32 --seeds 3

The question
------------
The online agents in `market_allocation_rl` had to discover good books by
trial from a Sharpe-shaped reward, and with sixty-odd independent periods
they fit the path. Offline RL asks a narrower question that the same
history can answer: given what the rule did and what nearby alternatives
would have earned, is there a policy in the neighbourhood of the rule
that does better, out of sample?

The logged dataset is the rule's decisions replayed. On every session the
rule can size, its own book is logged with its realised reward, and so
are `candidates` perturbations of it - the same names tilted by
log-normal noise, an equal-weight version, a random three-quarters of
the names, and a version that moves some weight onto names the rule left
out - each scored by the same reward on the same window. Every logged
action was available at the time; none of them is a future the agent
should not have seen. The reward is the book's return over the next
REBALANCE sessions divided by its realised volatility, at the rule's own
gross, so leverage is not rewarded.

Two learners, both in-support by construction:

  critic-selected   a permutation-invariant critic Q(state, book) fit by
                    regression on the logged rewards; on a test session
                    it scores the same family of candidates and the book
                    it rates highest is taken
  advantage-weighted a policy that scores every name and makes the book
                    by softmax, trained to imitate the logged books
                    weighted by exp(advantage / beta), where the
                    advantage is a logged reward minus the mean reward of
                    every book logged on that session (AWR, Peng et al.
                    2019). It moves toward what worked and stays where
                    data exists.

This is horizon one: the book chosen on a session does not change the
next session's state, so it is offline contextual-bandit optimisation,
and it is called RL here because the reward, not a label, is what is
learned from. Walk-forward, refit every REFIT sessions on everything
before the fold with the reward horizon purged, seeds averaged into one
action per session, and every contender paired with the rule on the same
sessions.

Results
-------
Recorded below once the run is read.
"""

import argparse

import numpy as np
import torch
from torch import nn

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import risk, simulate
from backend.cli.market_allocation_rl import (
    DEVICE,
    MIN_TRAIN,
    REBALANCE,
    REFIT,
    Policy,
    Problem,
    _build,
    _hac_t,
    _reward,
    _state,
)
from backend.market import sizing
from backend.market.store import MarketStore

CANDIDATES = 32
CRITIC_EPOCHS = 30
POLICY_EPOCHS = 30
HIDDEN = 32
ADVANTAGE_CLIP = 5.0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Offline RL over the desk's history.")
    parser.add_argument("--candidates", type=int, default=CANDIDATES)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--skip-simulation", action="store_true")
    parser.add_argument("--data-dir", default="data/market")
    return parser


# The family of books logged around the rule's on one session: the rule
# itself, equal weight on its names, and `count` perturbations.
def _family(rule: np.ndarray, rng: np.random.Generator, count: int) -> list[np.ndarray]:
    gross = float(rule.sum())
    held = rule > 0
    out = [rule.copy()]
    equal = np.where(held, 1.0, 0.0)
    out.append(equal / equal.sum() * gross)
    unheld = np.flatnonzero(~held)
    for k in range(count):
        mode = k % 4
        if mode in (0, 1, 3):
            sigma = 1.0 if mode == 1 else 0.4
            tilted = np.where(
                held, rule * np.exp(sigma * rng.standard_normal(len(rule))), 0.0
            )
        else:
            keep = held & (rng.random(len(rule)) < 0.75)
            tilted = np.where(keep if keep.any() else held, 1.0, 0.0)
        if mode == 3 and len(unheld):
            extra = rng.choice(unheld, size=min(3, len(unheld)), replace=False)
            tilted = tilted / tilted.sum() * 0.85
            tilted[extra] += 0.15 / len(extra)
        out.append(tilted / tilted.sum() * gross)
    return out


# The logged dataset for a range of sessions: per session, its state, the
# family of books, and each book's reward.
def _log(problem: Problem, sessions, count: int, seed: int):
    rng = np.random.default_rng(seed)
    states, books, rewards, owner = [], [], [], []
    for t in sessions:
        family = _family(problem.rule[t], rng, count)
        states.append(_state(problem, t))
        for book in family:
            books.append(book)
            rewards.append(_reward(problem, book, t))
            owner.append(len(states) - 1)
    return (
        torch.stack(states),
        torch.tensor(np.array(books), dtype=torch.float32, device=DEVICE),
        torch.tensor(rewards, dtype=torch.float32, device=DEVICE),
        torch.tensor(owner, device=DEVICE),
    )


class Critic(nn.Module):
    """Q(state, book): per-name embeddings pooled by sum, so names commute."""

    def __init__(self, width: int) -> None:
        super().__init__()
        self.per_name = nn.Sequential(
            nn.Linear(width + 1, HIDDEN),
            nn.Tanh(),
            nn.Linear(HIDDEN, HIDDEN),
            nn.Tanh(),
        )
        self.head = nn.Sequential(
            nn.Linear(HIDDEN, HIDDEN), nn.Tanh(), nn.Linear(HIDDEN, 1)
        )

    def forward(self, state, book):
        """Return one value per (state, book) pair."""
        joined = torch.cat([state, book[..., None] * 10.0], dim=-1)
        return self.head(self.per_name(joined).sum(dim=-2)).squeeze(-1)


# Fit the critic by regression on the logged rewards.
def _train_critic(states, books, rewards, owner, seed: int) -> Critic:
    torch.manual_seed(seed)
    critic = Critic(states.shape[-1]).to(DEVICE)
    opt = torch.optim.Adam(critic.parameters(), lr=1e-3, weight_decay=1e-4)
    target = (rewards - rewards.mean()) / (rewards.std() + 1e-6)
    n = len(rewards)
    for _epoch in range(CRITIC_EPOCHS):
        order = torch.randperm(n, device=DEVICE)
        for i in range(0, n, 1024):
            rows = order[i : i + 1024]
            loss = (
                (critic(states[owner[rows]], books[rows]) - target[rows]) ** 2
            ).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
    critic.eval()
    return critic


# The advantage of every logged book: its reward less the mean reward of
# the books logged on the same session.
def _advantages(rewards, owner, sessions: int):
    total = torch.zeros(sessions, device=DEVICE).index_add(0, owner, rewards)
    count = torch.zeros(sessions, device=DEVICE).index_add(
        0, owner, torch.ones_like(rewards)
    )
    baseline = total / count.clamp(min=1)
    adv = rewards - baseline[owner]
    return adv / (adv.std() + 1e-6)


# Advantage-weighted regression: imitate the logged books, each weighted
# by exp(advantage), through the cross-entropy between the book's shape
# and the policy's softmax.
def _train_policy(states, books, rewards, owner, seed: int) -> Policy:
    torch.manual_seed(seed)
    policy = Policy(states.shape[-1]).to(DEVICE)
    opt = torch.optim.Adam(policy.parameters(), lr=3e-3, weight_decay=1e-4)
    weight = torch.exp(
        _advantages(rewards, owner, len(states)).clamp(max=ADVANTAGE_CLIP)
    )
    shape = books / books.sum(dim=-1, keepdim=True).clamp(min=1e-9)
    n = len(rewards)
    for _epoch in range(POLICY_EPOCHS):
        order = torch.randperm(n, device=DEVICE)
        for i in range(0, n, 1024):
            rows = order[i : i + 1024]
            logp = torch.log_softmax(policy(states[owner[rows]]), dim=-1)
            loss = -(weight[rows, None] * shape[rows] * logp).sum(dim=-1).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
    policy.eval()
    return policy


# A book over the book's names put through the desk's own name and theme
# caps, exactly as the live allocation applies them.
def _capped(problem: Problem, book: np.ndarray) -> np.ndarray:
    full = np.zeros(len(problem.panel.tickers))
    full[problem.cols] = book
    config = risk.BOOK_CONFIG
    limited = sizing.apply_limits(
        full,
        problem.panel.themes,
        problem.panel.tickers,
        config.name_cap,
        config.theme_cap,
        float(book.sum()),
    )
    return limited[problem.cols]


# The learned book kept to as many names as the rule holds - its largest
# ones, renormalised to the same gross - so its choice of names is
# measured apart from the diffuse weighting a softmax gives everything.
def _sparse(book: np.ndarray, count: int) -> np.ndarray:
    count = max(int(count), 1)
    out = np.zeros_like(book)
    keep = np.argsort(book)[-count:]
    out[keep] = book[keep]
    return out / max(float(out.sum()), 1e-12) * float(book.sum())


# How concentrated a book is: its largest weight and its effective number
# of names, 1 / sum of squared shares.
def _concentration(book: np.ndarray) -> tuple[float, float]:
    share = book / max(float(book.sum()), 1e-12)
    return float(book.max()), float(1.0 / max(float((share**2).sum()), 1e-12))


# One fold: train on the purged history, act on the test sessions.
def _fold(problem, train, test, args, out, shape_of, chosen, chosen_sparse, leans):
    states, books, rewards, owner = _log(problem, train, args.candidates, seed=0)
    critics = [
        _train_critic(states, books, rewards, owner, s) for s in range(args.seeds)
    ]
    policies = [
        _train_policy(states, books, rewards, owner, s) for s in range(args.seeds)
    ]
    rng = np.random.default_rng(1)
    with torch.no_grad():
        for t in test:
            gross = float(problem.rule[t].sum())
            state = _state(problem, t)
            family = _family(problem.rule[t], rng, args.candidates)
            candidates = torch.tensor(
                np.array(family), dtype=torch.float32, device=DEVICE
            )
            scores = sum(
                c(state[None].expand(len(family), -1, -1), candidates) for c in critics
            )
            picked = family[int(scores.argmax())]
            shape = sum(torch.softmax(p(state), dim=-1) for p in policies) / len(
                policies
            )
            learned = (shape * gross).cpu().numpy()
            capped = _capped(problem, learned)
            sparse = _capped(
                problem, _sparse(learned, int((problem.rule[t] > 0).sum()))
            )
            books = {
                "the desk's rule": problem.rule[t],
                "equal weight, same names": family[1],
                "equal weight, whole book": np.full(len(learned), gross / len(learned)),
                "critic-selected book": picked,
                "advantage-weighted policy": learned,
                "advantage-weighted, capped": capped,
                "advantage-weighted, top names": sparse,
            }
            for name, book in books.items():
                out[name].append(_reward(problem, book, t))
                shape_of[name].append(_concentration(book))
            chosen[t] = capped
            chosen_sparse[t] = sparse
            leans.append(_leans(problem, capped, t))
            out["best logged candidate (hindsight)"].append(
                max(_reward(problem, b, t) for b in family)
            )


# Mean, spread, and the paired difference from the rule on the same
# sessions with three t statistics: naive, Newey-West over the reward
# window, and on every REBALANCE-th session so no two windows overlap.
def _summarise(name: str, values, rule) -> None:
    v, r = np.array(values), np.array(rule)
    line = f"{name:36} {v.mean():+8.4f} {v.std():8.4f} {len(v):6d}"
    if name != "the desk's rule":
        diff = v - r
        naive = diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)) + 1e-12)
        hac = _hac_t(diff, REBALANCE - 1)
        apart = diff[::REBALANCE]
        sparse = apart.mean() / (apart.std(ddof=1) / np.sqrt(len(apart)) + 1e-12)
        line += (
            f"   vs rule {diff.mean():+8.4f}  t naive {naive:+5.2f}"
            f"  Newey-West {hac:+5.2f}  every {REBALANCE}th {sparse:+5.2f}"
        )
    print(line)


# Rank correlation of a book's weights with each per-name input and with
# the rule's weight on the same session: what the policy leans on.
def _leans(problem: Problem, book: np.ndarray, t: int) -> np.ndarray:
    from scipy.stats import spearmanr

    columns = [problem.states[t][:, i] for i in range(problem.states.shape[-1])]
    columns.append(problem.rule[t])
    return np.array([spearmanr(book, c).statistic for c in columns])


LEAN_NAMES = ("fundamental", "technical", "sentiment", "value", "log vol", "the rule")


# The book-level test: the learned allocation behind the desk's own
# full-rule simulation - the same fills, costs and holding rules - from
# the first test session on, beside the rule and the whole-book null.
def _simulated(report, problem: Problem, chosen: dict, chosen_sparse: dict) -> None:
    first = min(chosen)
    since = problem.dates[first].astype("datetime64[D]").astype(object)
    width = len(problem.panel.tickers)

    def from_books(books):
        def allocator(report_, panel_, config, t):
            if t in books:
                full = np.zeros(width)
                full[problem.cols] = books[t]
                return full
            return simulate._targets(report_, panel_, config, t)

        return allocator

    def whole_book(report_, panel_, config, t):
        full = np.zeros(width)
        full[problem.cols] = float(problem.rule[t].sum()) / len(problem.cols)
        return full

    print(
        f"\nthe book from {since}, full rules: "
        f"{'annual':>8} {'vol':>7} {'Sharpe':>7} {'maxDD':>8} {'total':>9}"
    )
    for name, allocator in (
        ("the desk's rule", None),
        ("equal weight, whole book", whole_book),
        ("advantage-weighted, capped", from_books(chosen)),
        ("advantage-weighted, top names", from_books(chosen_sparse)),
    ):
        result = simulate.run(report, since=since, use_exits=False, allocator=allocator)
        s = result.stats()
        print(
            f"{name:36} {s['annual']:+8.1%} {s['volatility']:7.1%} {s['sharpe']:7.2f} "
            f"{s['drawdown']:8.1%} {s['total']:+9.1%}"
        )


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(args.data_dir))
    problem = _build(report)
    rows = problem.rule.shape[0]
    can_run = problem.rule.sum(axis=1) > 0
    cuts = list(range(MIN_TRAIN, rows - REBALANCE, REFIT))
    out: dict[str, list] = {
        k: []
        for k in (
            "the desk's rule",
            "equal weight, same names",
            "equal weight, whole book",
            "critic-selected book",
            "advantage-weighted policy",
            "advantage-weighted, capped",
            "advantage-weighted, top names",
            "best logged candidate (hindsight)",
        )
    }
    shape_of: dict[str, list] = {k: [] for k in out}
    chosen: dict[int, np.ndarray] = {}
    chosen_sparse: dict[int, np.ndarray] = {}
    leans: list[np.ndarray] = []
    names, folds = problem.rule.shape[1], len(cuts)
    print(f"{names} names, {folds} folds, {args.candidates} candidates per session")
    for number, cut in enumerate(cuts, start=1):
        train = [t for t in range(MIN_TRAIN - REBALANCE, cut - REBALANCE) if can_run[t]]
        test = [t for t in range(cut, min(cut + REFIT, rows - REBALANCE)) if can_run[t]]
        if len(train) < 100 or not test:
            continue
        _fold(problem, train, test, args, out, shape_of, chosen, chosen_sparse, leans)
        print(f"  fold {number}/{len(cuts)} to {problem.dates[cut]}", flush=True)
    print(f"\n{'policy':36} {'mean reward':>10} {'sd':>8} {'n':>6}")
    for name, values in out.items():
        _summarise(name, values, out["the desk's rule"])
    print(f"\n{'book':36} {'largest weight':>14} {'effective names':>16}")
    for name, shapes in shape_of.items():
        if shapes:
            largest, effective = np.mean(shapes, axis=0)
            print(f"{name:36} {largest:14.3f} {effective:16.1f}")
    if leans:
        mean = np.nanmean(np.array(leans), axis=0)
        print(
            "\nthe learned book's rank correlation with each input, mean over sessions:"
        )
        print(
            "  "
            + "  ".join(f"{n} {v:+.2f}" for n, v in zip(LEAN_NAMES, mean, strict=True))
        )
    if chosen and not args.skip_simulation:
        _simulated(report, problem, chosen, chosen_sparse)


if __name__ == "__main__":
    main()
