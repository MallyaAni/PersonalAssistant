"""When within the day should the desk's orders fill?

    python -m backend.cli.market_execution_rl
    python -m backend.cli.market_execution_rl --cost 3 --seeds 3
    python -m backend.cli.market_execution_rl --skip-ppo --years 2025 2026

The question
------------
The desk decides at the close and fills at the next open, market-on-open.
That is one schedule out of many. The same order could be worked across
the day's twenty-six fifteen-minute bars, or left to the closing auction.
Selection has been measured to exhaustion here; execution never was. It
is the one place the fifteen-minute bars carry dense, relevant
information, because the order is going to happen either way and the
only question is what it pays relative to the open.

The fill model
--------------
Twenty-seven slots: the opening auction at the session's opening print,
then each bar at its typical price, (high + low + close) / 3. A decision
for a bar is made at its start from what is known then - the open and
the closes before it - and the fill happens inside the bar. The two
auctions, open and close, cost nothing beyond the print; a fill inside a
bar pays `cost` basis points for crossing the spread. No market impact:
the paper book is small, and its largest order is a fraction of one
bar's volume.

The shortfall of a schedule is what it paid against the open, signed by
side, in basis points, plus the cost of its intraday fills. The open
scores zero by construction; it is the desk's own schedule.

  open          the desk today
  close         the closing auction
  TWAP          an equal slice in every bar
  VWAP shape    slices in proportion to the name's usual volume by slot
  first hour    equal over the first four bars
  last hour     equal over the last four bars
  direct        a policy that decides each bar's fraction of what is left
                from the state, trained by minimising the shortfall
                itself, which is differentiable because prices do not
                react to the order
  PPO           the same state and action as a reinforcement-learning
                problem - reward per step, a critic, clipped updates -
                so a claim about RL is a claim about RL

The state at each bar: time of day, the price against the open so far,
the last bar's return and the last four, realised volatility so far, the
last bar's volume against the name's usual for that slot, the book's
average move since the open that day, the overnight gap, the side, and
the fraction of the order still to fill.

The measurement
---------------
Walk-forward by year: for each test year the policies are trained on
every session before it and scored on the sessions inside it, so 2026 is
scored by policies that never saw it. Two populations. Every book name
on every clean session, both sides, is the general answer. The desk's
own orders - the positions the full-rule simulation opened and closed,
on the sessions it filled them - is the answer that matters, with fewer
observations; the rule re-decided every session gives every day a name
would enter or leave the book, the same kind of order many times over.
The t statistic clusters by session, since every order on a day shares
that day's tape.

What this cannot claim, written before the result: intraday fills are
modelled at a bar's typical price, which a small market order gets in a
liquid name and a large one does not; and the desk's order population is
the simulation's, which is the rule's choices replayed, not the paper
account's fills.

Results
-------
Five test years, 2022 to 2026, each scored by policies trained on the
years before it; three seeds; cost 2 bps per intraday fill. Pooled over
82,246 order-sessions on 1,162 sessions, every book name:

  schedule              buys bps      t    sells bps      t
  open (the desk)          0.00             0.00
  close                   +5.31   1.15      -5.31  -1.15
  TWAP                    +4.93   1.49      -1.08  -0.41
  first hour              +3.20   1.73      +0.80   0.26
  last hour               +7.13   1.56      -4.13  -0.94
  VWAP shape              +4.78   1.50      -1.43  -0.53
  direct policy           +2.40   2.23      -2.18  -0.51
  PPO                     +3.17   1.48      +0.20  -0.04

The desk's own orders, 344 over 57 sessions, each on its own side:

  schedule              all bps      t   buys bps      t  sells bps      t
  open (the desk)          0.00            0.00            0.00
  close                   +6.38  0.64    +49.31  0.86    -34.59  -0.42
  first hour              -3.21 -0.24    +36.64  1.96    -41.24  -2.02
  VWAP shape              +3.65  0.54    +40.45  0.88    -31.47  -0.58
  direct policy          -15.13 -0.69     +1.43 -0.69    -30.93  -0.46
  PPO                     -0.19  0.28    +30.11  0.97    -29.12  -0.91

The same kind of order many times over - the rule re-decided every
session, 2,394 entries and exits over 840 sessions:

  schedule              all bps      t   buys bps      t  sells bps      t
  open (the desk)          0.00            0.00            0.00
  close                   -9.82 -1.54     +4.03  0.92    -23.62  -2.77
  TWAP                    -1.81 -0.17     +8.26  1.58    -11.84  -1.84
  first hour              +4.53  1.62     +5.56  1.71     +3.51   0.24
  last hour               -8.48 -1.45     +6.04  1.07    -22.96  -2.72
  VWAP shape              -1.96 -0.27     +7.34  1.53    -11.23  -1.89
  direct policy           -8.56 -1.98     +0.12  0.12    -17.21  -2.31
  PPO                     +0.86  0.55     +5.70  1.67     -3.96  -1.10

  sells at the close, by year   2022 -14   2023 -34   2024 -38   2025 -36   2026 +15
                           t         -1.06      -2.27      -1.95      -1.47      -0.14

Prices drifted up through the session over these years, five basis
points open to close on average, so a buyer who waits pays and a seller
who waits earns, and neither is significant across a thousand sessions.
On the desk's own fill days the drift runs the way the desk decided:
names it buys keep rising through the day, names it sells keep falling.
The day after a signal continues the signal. The open is right for
buys - every later schedule pays two to eight basis points on them - and
the closing auction is right for sells on the larger population, 24
basis points better with t 2.8 over 840 sessions.

But not in every year. Four of the five test years favour the close for
sells and the fifth, 2026, the year the paper book trades, reads the
other way on 325 orders. That is the regime question the desk keeps
meeting, and the reason the book does not move on this: a change made on
2023-2025 and contradicted by 2026 is a fit. Market-on-open stays for
both sides. The forward record writes, beside every actual fill, what
the closing auction would have paid, so the sell question is answered by
the paper account itself as sessions accumulate. When that record agrees
with the history, the change is one time-in-force flag on the sells.

Neither agent found a schedule the fixed ones did not contain. The
direct policy learned to buy at the open and sell late, and paid a
little on buys for the imperfection; PPO learned less.
"""

import argparse
from dataclasses import dataclass
from datetime import date

import numpy as np
import torch
from torch import nn

from backend.market import intraday
from backend.market.universe import book_sides, build_universe

SLOTS = intraday.BARS + 1  # the opening auction, then every bar
TYPICAL_DAYS = 20
VOLUME_WARMUP = TYPICAL_DAYS
BAD_MOVE = 0.30
FEATURES = (
    "time",
    "vs_open",
    "r1",
    "r4",
    "vol",
    "volume_ratio",
    "market",
    "gap",
    "gap_known",
)
STATE = len(FEATURES) + 2  # plus the side and the fraction remaining
HIDDEN = 64
BATCH = 4_096
DIRECT_EPOCHS = 8
PPO_ITERATIONS = 40
PPO_EPISODES = 2_048
PPO_EPOCHS = 4
PPO_MINIBATCH = 512
PPO_CLIP = 0.2
PPO_ENTROPY = 1e-3
GAE_LAMBDA = 0.95
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="When should an order fill?")
    parser.add_argument("--cost", type=float, default=2.0, help="bps per intraday fill")
    parser.add_argument(
        "--years", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026]
    )
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--skip-ppo", action="store_true")
    parser.add_argument(
        "--skip-desk", action="store_true", help="skip the desk's own orders"
    )
    parser.add_argument("--data-dir", default="data/market")
    return parser


@dataclass(frozen=True)
class Orders:
    """Every candidate order: one row per name-session, both sides scored."""

    tickers: np.ndarray  # (n,) name of each row
    days: np.ndarray  # (n,) datetime64[D]
    rel: np.ndarray  # (n, SLOTS) fill price against the open, in bps
    x: np.ndarray  # (n, SLOTS, F) what is known at each slot's start
    slot_volume: np.ndarray  # (n, BARS) the name's usual share of volume by slot


# The typical price a fill inside each bar gets.
def _typical(close, high, low) -> np.ndarray:
    return (high + low + close) / 3.0


# The name's usual volume by slot over the previous TYPICAL_DAYS sessions,
# causal, NaN while the window is filling.
def _usual_volume(volume: np.ndarray) -> np.ndarray:
    n = len(volume)
    out = np.full(volume.shape, np.nan)
    cumulative = np.cumsum(volume, axis=0)
    for i in range(VOLUME_WARMUP, n):
        out[i] = (
            cumulative[i - 1]
            - (cumulative[i - 1 - TYPICAL_DAYS] if i > TYPICAL_DAYS else 0.0)
        ) / TYPICAL_DAYS
    return out


# What is known at the start of each slot, per session, before the market
# column is filled in (it needs every name on the day).
def _own_features(
    close, high, low, volume, open0, prev
) -> tuple[np.ndarray, np.ndarray]:
    n, bars = close.shape
    logc = np.log(close)
    log_open = np.log(open0)[:, None]
    r = np.zeros((n, bars))
    r[:, 1:] = np.diff(logc, axis=1)
    r[:, 0] = logc[:, 0] - log_open[:, 0]
    x = np.zeros((n, SLOTS, len(FEATURES)), dtype=np.float32)
    usual = _usual_volume(volume)
    with np.errstate(all="ignore"):
        gap = np.log(open0 / prev)
    known = np.isfinite(gap)
    x[:, :, 7] = np.where(known, gap, 0.0)[:, None]
    x[:, :, 8] = known[:, None]
    # Slot s >= 2 knows the closes of bars 0 .. s-2.
    for s in range(2, SLOTS):
        j = s - 2  # the last bar whose close is known
        x[:, s, 0] = (s - 1) / (SLOTS - 2)
        x[:, s, 1] = logc[:, j] - log_open[:, 0]
        x[:, s, 2] = r[:, j]
        x[:, s, 3] = r[:, max(0, j - 3) : j + 1].sum(axis=1)
        x[:, s, 4] = np.sqrt((r[:, : j + 1] ** 2).sum(axis=1))
        with np.errstate(all="ignore"):
            ratio = np.log(volume[:, j] / usual[:, j])
        x[:, s, 5] = np.where(np.isfinite(ratio), ratio, 0.0)
    x[:, 1, 0] = 0.0
    valid = np.isfinite(usual).all(axis=1)
    return x, valid


# Assemble every name's sessions into one order population, with the
# market column filled from the book's average move on each day.
def _orders(root, tickers) -> Orders:
    parts: list[tuple[str, tuple]] = []
    for ticker in tickers:
        got = intraday.episodes(root, ticker)
        if got is None:
            continue
        parts.append((ticker, got))
    names, days, rel, x, slot_volume = [], [], [], [], []
    for ticker, (d, close, high, low, volume, open0, prev) in parts:
        own, valid = _own_features(close, high, low, volume, open0, prev)
        typical = _typical(close, high, low)
        prices = np.concatenate([open0[:, None], typical], axis=1)
        relative = (prices / open0[:, None] - 1.0) * 1e4
        usual = _usual_volume(volume)
        with np.errstate(all="ignore"):
            share = usual / usual.sum(axis=1, keepdims=True)
        keep = (
            valid & np.isfinite(relative).all(axis=1) & np.isfinite(share).all(axis=1)
        )
        keep &= np.abs(relative).max(axis=1) < BAD_MOVE * 1e4
        names.append(np.array([ticker] * int(keep.sum())))
        days.append(d[keep])
        rel.append(relative[keep])
        x.append(own[keep])
        slot_volume.append(share[keep])
    orders = Orders(
        tickers=np.concatenate(names),
        days=np.concatenate(days),
        rel=np.concatenate(rel).astype(np.float32),
        x=np.concatenate(x),
        slot_volume=np.concatenate(slot_volume).astype(np.float32),
    )
    _fill_market(orders)
    return orders


# The book's average price-against-open at each slot on each day, as the
# market column of every order on that day.
def _fill_market(orders: Orders) -> None:
    order = np.argsort(orders.days, kind="stable")
    days = orders.days[order]
    starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
    stops = np.r_[starts[1:], len(days)]
    for a, b in zip(starts, stops, strict=True):
        rows = order[a:b]
        orders.x[rows, :, 6] = orders.x[rows, :, 1].mean(axis=0)[None, :]


# --- schedules -----------------------------------------------------------------


# The shortfall of fill fractions `f` (n, SLOTS) in bps, per order, for a
# given side: what was paid against the open plus the intraday cost.
def shortfall(
    f: np.ndarray, rel: np.ndarray, side: np.ndarray, cost: float
) -> np.ndarray:
    """Return (n,) shortfall in basis points; lower is better."""
    paid = (f * rel).sum(axis=1)
    return side * paid + cost * f[:, 1:-1].sum(axis=1)


# The fixed schedules, as fill-fraction matrices.
def _fixed(orders: Orders) -> dict[str, np.ndarray]:
    n = len(orders.rel)
    out = {}
    for name, slots in (
        ("open (the desk today)", [0]),
        ("close", [SLOTS - 1]),
        ("TWAP", list(range(1, SLOTS))),
        ("first hour", [1, 2, 3, 4]),
        ("last hour", [SLOTS - 4, SLOTS - 3, SLOTS - 2, SLOTS - 1]),
    ):
        f = np.zeros((n, SLOTS), dtype=np.float32)
        f[:, slots] = 1.0 / len(slots)
        out[name] = f
    vwap = np.zeros((n, SLOTS), dtype=np.float32)
    vwap[:, 1:] = orders.slot_volume
    out["VWAP shape"] = vwap
    return out


# --- the policies --------------------------------------------------------------


class Policy(nn.Module):
    """From the state at a slot, the fraction of what is left to fill now."""

    def __init__(self, stochastic: bool = False) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(STATE, HIDDEN), nn.Tanh(), nn.Linear(HIDDEN, HIDDEN), nn.Tanh()
        )
        self.head = nn.Linear(HIDDEN, 1)
        self.log_std = nn.Parameter(torch.zeros(1)) if stochastic else None
        self.value = nn.Linear(HIDDEN, 1) if stochastic else None
        with torch.no_grad():
            self.head.bias.fill_(-2.0)  # start near TWAP-ish patience

    def forward(self, state):
        """Return the logit of the fraction (and the value, when a critic exists)."""
        h = self.body(state)
        logit = self.head(h).squeeze(-1)
        if self.value is None:
            return logit, None
        return logit, self.value(h).squeeze(-1)


# Walk the slots with a policy, returning fill fractions (B, SLOTS) and,
# when asked, the per-step logits, log-probabilities and values for PPO.
def _rollout(policy: Policy, x, side, sample: bool = False, actions=None):
    n = x.shape[0]
    remaining = torch.ones(n, device=DEVICE)
    fills, logits, logps, values, taken = [], [], [], [], []
    for s in range(SLOTS):
        state = torch.cat([x[:, s], side[:, None], remaining[:, None]], dim=1)
        logit, value = policy(state)
        if actions is not None:
            z = actions[:, s]
        elif sample:
            z = logit + torch.exp(policy.log_std) * torch.randn_like(logit)
        else:
            z = logit
        if policy.log_std is not None:
            std = torch.exp(policy.log_std)
            logps.append(
                -0.5 * ((z - logit) / std) ** 2
                - torch.log(std)
                - 0.5 * np.log(2 * np.pi)
            )
        a = torch.sigmoid(z) if s < SLOTS - 1 else torch.ones_like(z)
        fill = a * remaining
        remaining = remaining * (1.0 - a)
        fills.append(fill)
        logits.append(logit)
        taken.append(z)
        if value is not None:
            values.append(value)
    stack = lambda items: torch.stack(items, dim=1) if items else None  # noqa: E731
    return stack(fills), stack(logps), stack(values), stack(taken)


# The shortfall as a tensor, for the direct policy's loss and PPO's reward.
def _shortfall_t(f, rel, side, cost: float):
    return side * (f * rel).sum(dim=1) + cost * f[:, 1:-1].sum(dim=1)


# Train the direct policy: minimise the mean shortfall over the training
# orders, both sides, by gradient through the fill fractions.
def _train_direct(
    x, rel, cost: float, seed: int, epochs: int = DIRECT_EPOCHS
) -> Policy:
    torch.manual_seed(seed)
    policy = Policy().to(DEVICE)
    opt = torch.optim.Adam(policy.parameters(), lr=1e-3)
    n = x.shape[0]
    for _epoch in range(epochs):
        order = torch.randperm(n, device=DEVICE)
        for i in range(0, n, BATCH):
            rows = order[i : i + BATCH]
            side = torch.where(
                torch.rand(len(rows), device=DEVICE) < 0.5, 1.0, -1.0
            ).to(DEVICE)
            f, _, _, _ = _rollout(policy, x[rows], side)
            loss = _shortfall_t(f, rel[rows], side, cost).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
    policy.eval()
    return policy


# Per-step rewards for PPO: the negative of each slot's contribution to
# the shortfall, so the episode's return is the negative shortfall.
def _step_rewards(f, rel, side, cost: float):
    per_slot = -(side[:, None] * f * rel)
    per_slot[:, 1:-1] = per_slot[:, 1:-1] - cost * f[:, 1:-1]
    return per_slot


# Generalised advantage estimation over the SLOTS steps, no discounting.
def _advantages(rewards, values):
    n, steps = rewards.shape
    adv = torch.zeros_like(rewards)
    last = torch.zeros(n, device=rewards.device)
    for t in reversed(range(steps)):
        nxt = values[:, t + 1] if t + 1 < steps else torch.zeros_like(last)
        delta = rewards[:, t] + nxt - values[:, t]
        last = delta + GAE_LAMBDA * last
        adv[:, t] = last
    return adv, adv + values


# One PPO update from a batch of sampled episodes.
def _ppo_update(policy, opt, x, rel, side, actions, old_logp, adv, ret) -> None:
    n = x.shape[0]
    for _epoch in range(PPO_EPOCHS):
        order = torch.randperm(n, device=DEVICE)
        for i in range(0, n, PPO_MINIBATCH):
            rows = order[i : i + PPO_MINIBATCH]
            _, logp, values, _ = _rollout(
                policy, x[rows], side[rows], actions=actions[rows]
            )
            ratio = torch.exp(logp - old_logp[rows])
            a = adv[rows]
            surrogate = torch.min(
                ratio * a, torch.clamp(ratio, 1 - PPO_CLIP, 1 + PPO_CLIP) * a
            )
            entropy = policy.log_std.mean()
            loss = (
                -surrogate.mean()
                + 0.5 * ((values - ret[rows]) ** 2).mean()
                - PPO_ENTROPY * entropy
            )
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
            opt.step()


# Train PPO on the training orders, both sides.
def _train_ppo(
    x, rel, cost: float, seed: int, iterations: int = PPO_ITERATIONS
) -> Policy:
    torch.manual_seed(seed)
    policy = Policy(stochastic=True).to(DEVICE)
    opt = torch.optim.Adam(policy.parameters(), lr=3e-4)
    n = x.shape[0]
    for _iteration in range(iterations):
        rows = torch.randint(0, n, (min(PPO_EPISODES, n),), device=DEVICE)
        side = torch.where(torch.rand(len(rows), device=DEVICE) < 0.5, 1.0, -1.0)
        with torch.no_grad():
            f, logp, values, actions = _rollout(policy, x[rows], side, sample=True)
            rewards = _step_rewards(f, rel[rows], side, cost)
            adv, ret = _advantages(rewards, values)
            adv = (adv - adv.mean()) / (adv.std() + 1e-6)
        _ppo_update(policy, opt, x[rows], rel[rows], side, actions, logp, adv, ret)
    policy.eval()
    return policy


# A policy's fill fractions on a test set for one side, seeds averaged.
def _schedule(policies, x, side_value: float) -> np.ndarray:
    side = torch.full((x.shape[0],), side_value, device=DEVICE)
    total = None
    with torch.no_grad():
        for policy in policies:
            f, _, _, _ = _rollout(policy, x, side)
            total = f if total is None else total + f
    return (total / len(policies)).cpu().numpy()


# --- measurement ---------------------------------------------------------------


# Mean shortfall and a t statistic clustered by session.
def _stat(values: np.ndarray, days: np.ndarray) -> tuple[float, float]:
    order = np.argsort(days, kind="stable")
    v, d = values[order], days[order]
    starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    per_day = np.add.reduceat(v, starts) / np.diff(np.r_[starts, len(v)])
    if len(per_day) < 3:
        return float(v.mean()), float("nan")
    spread = per_day.std(ddof=1) / np.sqrt(len(per_day))
    return float(v.mean()), (
        float(per_day.mean() / spread) if spread > 0 else float("inf")
    )


# Print one population's table, each side on its own: a schedule that
# does not depend on the side pays on buys exactly what it earns on sells,
# so the two together would only show the cost.
def _table(title, schedules: dict, rel, days, cost: float) -> None:
    sessions = len(np.unique(days))
    print(f"\n{title}: {len(rel):,} order-sessions over {sessions:,} sessions")
    print(f"{'schedule':26} {'buys bps':>9} {'t':>7} {'sells bps':>10} {'t':>7}")
    ones = np.ones(len(rel))
    for name, (f_buy, f_sell) in schedules.items():
        buys, tb = _stat(shortfall(f_buy, rel, ones, cost), days)
        sells, ts = _stat(shortfall(f_sell, rel, -ones, cost), days)
        print(f"{name:26} {buys:+9.2f} {tb:+7.2f} {sells:+10.2f} {ts:+7.2f}")


# The desk's own orders from the full-rule simulation: a buy on the
# session a position opened, a sell on the one it closed. At the desk's
# own cadence that is a few hundred orders; re-decided every session it
# is every day a name would enter or leave the book, the same kind of
# order many times over.
def _desk_orders(report, rebalance: int) -> set[tuple[str, str, int]]:
    from backend.agents.trading.desk import simulate

    result = simulate.run(
        report, since=date(2021, 6, 1), use_exits=False, rebalance=rebalance
    )
    out = set()
    for trade in result.trades:
        out.add((trade.ticker, str(trade.opened), 1))
        if trade.closed:
            out.add((trade.ticker, str(trade.closed), -1))
    return out


# Score every schedule on the desk's orders only, each on its own side.
def _desk_table(
    orders: Orders, test, schedules, desk: set, cost: float, title: str
) -> None:
    keys = [
        (t, str(d), s)
        for t, d in zip(orders.tickers[test], orders.days[test], strict=True)
        for s in (1, -1)
    ]
    side = np.array([k[2] for k in keys], dtype=float)
    keep = np.array([k in desk for k in keys])
    if keep.sum() < 20:
        print(f"\n{title}: {int(keep.sum())} matched, too few to score")
        return
    rows = np.repeat(np.arange(int(test.sum())), 2)[keep]
    side = side[keep]
    rel = orders.rel[test][rows]
    days = orders.days[test][rows]
    matched, sessions = int(keep.sum()), len(np.unique(days))
    print(f"\n{title}: {matched:,} over {sessions:,} sessions")
    print(
        f"{'schedule':26} {'all bps':>9} {'t':>7} {'buys bps':>9} {'t':>7} "
        f"{'sells bps':>10} {'t':>7}"
    )
    for name, (f_buy, f_sell) in schedules.items():
        f = np.where(side[:, None] > 0, f_buy[rows], f_sell[rows])
        values = shortfall(f, rel, side, cost)
        mean, t_all = _stat(values, days)
        buys, tb = _stat(values[side > 0], days[side > 0])
        sells, ts = _stat(values[side < 0], days[side < 0])
        print(
            f"{name:26} {mean:+9.2f} {t_all:+7.2f} {buys:+9.2f} {tb:+7.2f} "
            f"{sells:+10.2f} {ts:+7.2f}"
        )


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    root = intraday.partition()
    tickers = sorted(book_sides(build_universe()))
    orders = _orders(root, tickers)
    years = orders.days.astype("datetime64[Y]").astype(int) + 1970
    print(
        f"{len(orders.rel):,} order-sessions, {len(set(orders.tickers))} names, "
        f"{orders.days.min()} to {orders.days.max()}, device {DEVICE}"
    )
    desks = {}
    if not args.skip_desk:
        from backend.agents.trading.desk import desk as trading_desk
        from backend.market.store import MarketStore

        report = trading_desk.run(MarketStore(args.data_dir))
        desks["the desk's own orders"] = _desk_orders(report, 20)
        desks["the desk re-decided every session"] = _desk_orders(report, 1)
    x_all = torch.tensor(orders.x, device=DEVICE)
    rel_all = torch.tensor(orders.rel, device=DEVICE)
    fixed = _fixed(orders)
    pooled: dict[str, list] = {}
    pooled_days, pooled_rel, pooled_test = [], [], []
    for year in args.years:
        train, test = years < year, years == year
        if train.sum() < 5_000 or test.sum() == 0:
            continue
        idx = torch.tensor(np.flatnonzero(train), device=DEVICE)
        direct = [
            _train_direct(x_all[idx], rel_all[idx], args.cost, s)
            for s in range(args.seeds)
        ]
        ppo = (
            []
            if args.skip_ppo
            else [
                _train_ppo(x_all[idx], rel_all[idx], args.cost, s)
                for s in range(args.seeds)
            ]
        )
        x_test = x_all[torch.tensor(np.flatnonzero(test), device=DEVICE)]
        schedules = {name: (f[test], f[test]) for name, f in fixed.items()}
        schedules["direct policy"] = (
            _schedule(direct, x_test, 1.0),
            _schedule(direct, x_test, -1.0),
        )
        if ppo:
            schedules["PPO"] = (
                _schedule(ppo, x_test, 1.0),
                _schedule(ppo, x_test, -1.0),
            )
        _table(
            f"=== {year}, trained on {int(train.sum()):,} earlier order-sessions",
            schedules,
            orders.rel[test],
            orders.days[test],
            args.cost,
        )
        for title, desk in desks.items():
            _desk_table(orders, test, schedules, desk, args.cost, title)
        for name, pair in schedules.items():
            pooled.setdefault(name, []).append(pair)
        pooled_days.append(orders.days[test])
        pooled_rel.append(orders.rel[test])
        pooled_test.append(test)
    if len(pooled_days) > 1:
        joined = {
            name: (
                np.concatenate([p[0] for p in pairs]),
                np.concatenate([p[1] for p in pairs]),
            )
            for name, pairs in pooled.items()
        }
        _table(
            "=== every test year pooled",
            joined,
            np.concatenate(pooled_rel),
            np.concatenate(pooled_days),
            args.cost,
        )
        for title, desk in desks.items():
            _desk_table(
                orders, np.any(pooled_test, axis=0), joined, desk, args.cost, title
            )


if __name__ == "__main__":
    main()
