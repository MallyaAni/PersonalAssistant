"""Intraday agents on fifteen-minute bars, scored once on a year they never saw.

    python -m backend.cli.market_intraday_rl build          # episodes to TMP
    python -m backend.cli.market_intraday_rl run            # both agents
    python -m backend.cli.market_intraday_rl run sharpe     # one of them

What was asked, and the answer
------------------------------
Whether a reinforcement-learning agent on the book's 15-minute bars could
find an edge the daily desk cannot. The daily book has about 65
independent twenty-session periods to learn from, which is why every
network tried on it fit one price path. The fifteen-minute store has 20.8
million bars across 529 names - a data regime where RL has genuinely
worked in finance - so the question deserved a real test rather than an
argument.

It does not work here, and the reason is arithmetic that no algorithm can
change. Scored once on 2026, which nothing saw until the final table, at
the 3 basis points one-way that spread plus slippage costs on liquid US
large caps. Sharpe by one-way cost, then annual return and worst drawdown
at 3 bps:

  strategy                          turn   1bp    3bp    5bp   10bp    ann    maxDD
  long the session                  2.00  0.06  -0.27  -0.61  -1.44   -8.3%  -25.1%
  first-half-hour momentum (Gao)    1.99 -2.56  -5.01  -7.46 -13.56  -20.4%  -11.9%
  hourly reversal (Heston et al.)  11.51 -1.10  -3.82  -6.62 -13.92  -81.7%  -45.5%
  direct Sharpe GRU, best seed      1.20 -1.10  -2.65  -4.18  -7.87  -10.7%   -8.4%
  direct Sharpe GRU, seed average   0.90 -0.39  -1.44  -2.47  -5.03   -6.5%   -5.9%
  PPO, positional context           3.53 -1.28  -1.97  -2.64  -4.23  -54.4%  -28.4%

Nothing is positive at a realistic cost. The mechanism is visible in the
first row: holding these names open to close earned +3.6 bp per name-day
in 2026 (the daily panel, built from a different source, says +2.9), and
a round trip at 3 bps costs 6. The best thing an intraday agent could do
is not trade, and the direct-Sharpe policy nearly learned that: its
validation Sharpe was +0.02 to +0.04 across seeds, which is a policy that
found nothing worth paying for. PPO found something on 2025 - validation
Sharpe +1.10, +1.69, -0.29 across seeds - and lost it entirely on 2026,
which is what fitting noise looks like when the year changes.

The two published intraday effects fail too, and not because 2026 is
odd. Gao, Han, Li and Zhou's first-half-hour momentum and Heston,
Korajczyk and Sadka's hourly reversal lose in every year from 2020 to
2026 in these names at 3 bps, and so do their inverses: the fade rule
earns -1.2 bp/day at 1 bp of cost across the training years, so the
underlying effect is about a basis point and the round trip is six. Those
papers measured an index ETF from 1993-2013 and a broad cross-section in
the post-decimalisation years, at institutional costs. Single-name AI and
software stocks in 2020-2026 are not that population, and the low hit
rates - 27% of days positive for the rules - are the cost exceeding the
signal on most days, not the signal pointing the wrong way.

What this rules out and what it does not
----------------------------------------
It rules out an intraday sleeve on these names at retail-realistic costs,
and it rules out intraday execution timing as a place to combine an agent
with the desk: the desk trades about nine names a month with no market
impact at its size, and there is no intraday edge to time into. Two
agents, two published rules and their inverses, seven years, eleven
thousand held-out sessions - the answer is consistent enough to stop.

It does not rule out the fifteen-minute data being useful to the daily
desk as features - realised variance, volume profile, close-to-close
microstructure - which is a different question with a different test.
And it does not say anything about names outside this book or about
costs below a basis point, where "long the session" is the one row that
turns faintly positive.

The protocol
------------
Regular session only, 09:30 to 16:00 New York, 26 bars, and only days with
every bar present. Returns are within the day only, so overnight gaps,
unadjusted splits and re-listings - which all happen between sessions -
never reach an agent that is flat at the close. Any day with a bar move
beyond 30% is dropped as a vendor error (NuScale was recorded rising 68x in
fifteen minutes). Features are causal and standardised on training rows.
Train 2020-2024, choose epochs and seeds on 2025, score 2026 exactly once.
Every position is forced flat at the close and bounded to [-1, 1], so
nothing wins by leverage or by holding overnight. Cost is charged on every
unit of turnover including the first entry and the final exit.

The agents are from the literature rather than invented. The direct-Sharpe
policy is Lim, Zohren and Roberts (2019): a recurrent policy trained by
gradient ascent on the Sharpe ratio of its own P&L with the cost inside the
objective; the environment is fully known and has no impact at this size,
so the gradient is exact. PPO with positional context is the method and
state of arXiv 2406.08013 - current position, return since entry, time
left, day return - the one intraday DRL paper with concrete numbers, which
assumed 0.08 bps of cost, roughly forty times too low for equities.
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch
from torch import nn

from backend.market.universe import book_sides, build_universe

ROOT = Path("data/market/bars_15m")
OUT = Path(os.environ.get("TMP", "/tmp")) / "intraday"
BARS = 26
OPEN_MINUTE = 13 * 60 + 30
BAD_BAR = 0.30
VOL_DAYS = 20
COSTS_BPS = (1.0, 3.0, 5.0, 10.0)
HEADLINE_BPS = 3.0
SEEDS = 3
EPOCHS = 40
BATCH = 512
SESSIONS_PER_YEAR = 252.0
POSITIONAL = 4
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
FEATURES = (
    "r1",
    "r4",
    "r_day",
    "vol_today",
    "vol_20d",
    "volume_ratio",
    "time",
    "range_pos",
    "mkt_r4",
    "mkt_r_day",
)


# --- the dataset --------------------------------------------------------------


# The newest partition of fifteen-minute bars.
def _partition() -> Path:
    parts = sorted(p for p in ROOT.glob("asof=*") if p.is_dir())
    if not parts:
        raise SystemExit("no bars_15m partition; run market_intraday --refresh")
    return parts[-1]


# One name's regular-session bars, with the slot each one occupies.
def _load(root: Path, ticker: str):
    d = pq.read_table(root / f"{ticker}.parquet").to_pydict()
    start = np.array(d["start"], dtype="datetime64[m]")
    day = start.astype("datetime64[D]")
    minute = (start - day).astype(int)
    keep = (minute >= OPEN_MINUTE) & (minute < OPEN_MINUTE + BARS * 15)
    fields = {
        k: np.array(d[k], dtype=float)[keep] for k in ("close", "high", "low", "volume")
    }
    return day[keep], ((minute[keep] - OPEN_MINUTE) // 15).astype(int), fields


# The full, clean sessions of one name as aligned arrays.
def _episodes(root: Path, ticker: str):
    day, slot, f = _load(root, ticker)
    kept: dict[str, list] = {k: [] for k in ("days", "close", "high", "low", "volume")}
    for d in np.unique(day):
        m = day == d
        if m.sum() != BARS or not np.array_equal(np.sort(slot[m]), np.arange(BARS)):
            continue
        order = np.argsort(slot[m])
        c = f["close"][m][order]
        if not np.all(np.isfinite(c)) or np.any(c <= 0):
            continue
        if np.abs(np.diff(np.log(c))).max() > BAD_BAR:
            continue
        kept["days"].append(d)
        kept["close"].append(c)
        for k in ("high", "low", "volume"):
            kept[k].append(f[k][m][order])
    if not kept["days"]:
        return None
    stacked = [np.stack(kept[k]) for k in ("close", "high", "low", "volume")]
    return np.array(kept["days"]), *stacked


# Causal features for every bar of every session, and what each bar paid.
def _features(close, high, low, volume):
    n = len(close)
    logc = np.log(close)
    r = np.zeros((n, BARS))
    r[:, 1:] = np.diff(logc, axis=1)
    nxt = np.zeros((n, BARS))
    nxt[:, :-1] = r[:, 1:]
    x = np.zeros((n, BARS, len(FEATURES)))
    x[:, :, 0] = r
    for i in range(BARS):
        x[:, i, 1] = logc[:, i] - logc[:, max(0, i - 4)]
    x[:, :, 2] = logc - logc[:, :1]
    x[:, :, 3] = np.sqrt(np.cumsum(r**2, axis=1) / np.arange(1, BARS + 1))
    daily = logc[:, -1] - logc[:, 0]
    vol20 = np.full(n, np.nan)
    for d in range(VOL_DAYS, n):
        vol20[d] = daily[d - VOL_DAYS : d].std()
    fill = np.nanmedian(vol20) if np.isfinite(vol20).any() else 0.0
    x[:, :, 4] = np.where(np.isfinite(vol20), vol20, fill)[:, None]
    ratio = np.ones((n, BARS))
    for d in range(VOL_DAYS, n):
        med = np.median(volume[d - VOL_DAYS : d], axis=0)
        with np.errstate(all="ignore"):
            ratio[d] = np.where(med > 0, volume[d] / med, 1.0)
    x[:, :, 5] = np.log(np.clip(ratio, 0.05, 20.0))
    x[:, :, 6] = np.tile(np.arange(BARS) / (BARS - 1), (n, 1))
    run_high = np.maximum.accumulate(high, axis=1)
    run_low = np.minimum.accumulate(low, axis=1)
    with np.errstate(all="ignore"):
        pos = (close - run_low) / (run_high - run_low)
    x[:, :, 7] = np.where(np.isfinite(pos), pos, 0.5)
    return x, nxt


# Build the episode arrays for the book and write them to TMP.
def build() -> None:
    """Turn the fifteen-minute store into (episodes, bars, features) arrays."""
    root = _partition()
    OUT.mkdir(parents=True, exist_ok=True)
    per_name = {}
    for ticker in sorted(book_sides(build_universe())):
        if not (root / f"{ticker}.parquet").exists():
            continue
        got = _episodes(root, ticker)
        if got is None:
            continue
        days, close, high, low, volume = got
        per_name[ticker] = (days, *_features(close, high, low, volume))
        print(f"  {ticker:6} {len(days):5d} full sessions", flush=True)
    # The book's own average as the market, aligned by date.
    all_days = sorted({d for days, _, _ in per_name.values() for d in days.tolist()})
    index = {d: i for i, d in enumerate(all_days)}
    sums = np.zeros((2, len(all_days), BARS))
    count = np.zeros(len(all_days))
    for days, x, _ in per_name.values():
        rows = [index[d] for d in days.tolist()]
        sums[0, rows] += x[:, :, 1]
        sums[1, rows] += x[:, :, 2]
        count[rows] += 1
    market = sums / np.maximum(count, 1)[None, :, None]
    xs, rs, names, dates = [], [], [], []
    for k, (days, x, nxt) in enumerate(v for _t, v in sorted(per_name.items())):
        rows = np.array([index[d] for d in days.tolist()])
        x[:, :, 8] = market[0, rows]
        x[:, :, 9] = market[1, rows]
        xs.append(x)
        rs.append(nxt)
        names.append(np.full(len(days), k))
        dates.append(days)
    np.save(OUT / "X.npy", np.concatenate(xs).astype(np.float32))
    np.save(OUT / "R.npy", np.concatenate(rs).astype(np.float32))
    np.save(OUT / "NAME.npy", np.concatenate(names))
    stamp = np.concatenate(dates).astype("datetime64[D]").astype(np.int64)
    np.save(OUT / "DATE.npy", stamp)
    (OUT / "meta.json").write_text(
        json.dumps({"names": sorted(per_name), "features": FEATURES})
    )
    print(f"wrote {len(stamp):,} episodes to {OUT}")


# --- the accounting every contender is scored by --------------------------


# P&L per session: the position held into each bar times what the bar
# paid, less the cost of every change. The last bar is forced flat, so
# nothing earns an overnight move.
def pnl_of(positions: np.ndarray, returns: np.ndarray, cost: float) -> np.ndarray:
    pos = positions.copy()
    pos[:, -1] = 0.0
    prev = np.concatenate([np.zeros((len(pos), 1)), pos[:, :-1]], axis=1)
    return (pos * returns).sum(axis=1) - cost * np.abs(pos - prev).sum(axis=1)


# Daily P&L across the names traded each day, equal-weighted, then the
# usual numbers.
def score(episode_pnl: np.ndarray, dates: np.ndarray) -> dict:
    days, inverse = np.unique(dates, return_inverse=True)
    daily = np.zeros(len(days))
    count = np.zeros(len(days))
    np.add.at(daily, inverse, episode_pnl)
    np.add.at(count, inverse, 1)
    daily = daily / np.maximum(count, 1)
    annual = daily.mean() * SESSIONS_PER_YEAR
    vol = daily.std() * np.sqrt(SESSIONS_PER_YEAR)
    curve = np.cumprod(1 + daily)
    return {
        "annual": float(annual),
        "sharpe": float(annual / vol) if vol > 0 else float("nan"),
        "drawdown": float((curve / np.maximum.accumulate(curve) - 1).min()),
        "hit": float((daily > 0).mean()),
        "days": int(len(days)),
    }


# Units of position changed per session; a round trip is 2.
def turnover_of(positions: np.ndarray) -> float:
    pos = positions.copy()
    pos[:, -1] = 0.0
    prev = np.concatenate([np.zeros((len(pos), 1)), pos[:, :-1]], axis=1)
    return float(np.abs(pos - prev).sum(axis=1).mean())


# The rules nothing is fitted for: buy-and-hold the session, the two
# published intraday effects, and flat.
def baselines(x: np.ndarray) -> dict[str, np.ndarray]:
    n = len(x)
    out = {"long the session": np.ones((n, BARS))}
    p = np.zeros((n, BARS))
    p[:, 24] = np.sign(x[:, 1, 2])
    out["first-half-hour momentum"] = p
    p = np.zeros((n, BARS))
    p[:, 4:] = -np.sign(x[:, 4:, 1])
    out["hourly reversal"] = p
    out["flat"] = np.zeros((n, BARS))
    return out


# --- the direct-Sharpe policy -------------------------------------------------


class SharpePolicy(nn.Module):
    """A GRU reads the session; a tanh head emits a position per bar."""

    def __init__(self, width: int) -> None:
        super().__init__()
        self.gru = nn.GRU(width, 32, batch_first=True)
        self.head = nn.Sequential(nn.Linear(32, 16), nn.Tanh(), nn.Linear(16, 1))

    # Positions in [-1, 1] for every bar of every session in the batch.
    def forward(self, x):
        h, _ = self.gru(x)
        return torch.tanh(self.head(h).squeeze(-1))


# Minus the Sharpe of the batch's P&L, cost inside, flat at the close.
def sharpe_loss(pos, ret, cost):
    pos = torch.cat([pos[:, :-1], torch.zeros_like(pos[:, -1:])], dim=1)
    prev = torch.cat([torch.zeros_like(pos[:, :1]), pos[:, :-1]], dim=1)
    pnl = (pos * ret).sum(dim=1) - cost * (pos - prev).abs().sum(dim=1)
    return -(pnl.mean() / (pnl.std() + 1e-6))


# Fit the direct-Sharpe policy; the epoch is chosen on validation.
def train_sharpe(split, seed: int, cost: float):
    torch.manual_seed(seed)
    policy = SharpePolicy(split.width).to(DEVICE)
    opt = torch.optim.Adam(policy.parameters(), lr=1e-3)
    best, state = -1e9, None
    idx = torch.arange(len(split.z_train), device=DEVICE)
    for _epoch in range(EPOCHS):
        policy.train()
        perm = idx[torch.randperm(len(idx), device=DEVICE)]
        for i in range(0, len(perm), BATCH):
            b = perm[i : i + BATCH]
            opt.zero_grad()
            sharpe_loss(policy(split.z_train[b]), split.r_train[b], cost).backward()
            nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
            opt.step()
        policy.eval()
        with torch.no_grad():
            v = -sharpe_loss(policy(split.z_valid), split.r_valid, cost).item()
        if v > best:
            best, state = v, {k: t.clone() for k, t in policy.state_dict().items()}
    policy.load_state_dict(state)
    policy.eval()
    return policy, best


# --- PPO with positional context ----------------------------------------------


class ActorCritic(nn.Module):
    """Features plus positional context in; action logits and a value out."""

    def __init__(self, width: int) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(width + POSITIONAL, 128),
            nn.Tanh(),
            nn.Linear(128, 64),
            nn.Tanh(),
        )
        self.actor = nn.Linear(64, 3)
        self.critic = nn.Linear(64, 1)

    # Logits over {short, flat, long} and the state value.
    def forward(self, s):
        h = self.body(s)
        return self.actor(h), self.critic(h).squeeze(-1)


# Run whole sessions in parallel, bar by bar, carrying the positional
# context forward; sampling for training, greedy for scoring.
def rollout(model, x, r, cost, sample: bool):
    n = x.shape[0]
    pos = torch.zeros(n, device=DEVICE)
    entry_ret = torch.zeros(n, device=DEVICE)
    day_ret = torch.zeros(n, device=DEVICE)
    trail: dict[str, list] = {k: [] for k in ("states", "acts", "logs", "vals", "rews")}
    positions = torch.zeros(n, BARS, device=DEVICE)
    for i in range(BARS):
        time_left = torch.full((n,), (BARS - 1 - i) / (BARS - 1), device=DEVICE)
        context = torch.stack([pos, entry_ret, time_left, day_ret], 1)
        s = torch.cat([x[:, i], context], 1)
        logits, value = model(s)
        dist = torch.distributions.Categorical(logits=logits)
        a = dist.sample() if sample else logits.argmax(-1)
        new_pos = a.float() - 1.0
        if i == BARS - 1:
            new_pos = torch.zeros_like(new_pos)
        reward = new_pos * r[:, i] - cost * (new_pos - pos).abs()
        changed = new_pos != pos
        entry_ret = torch.where(
            changed, torch.zeros_like(entry_ret), entry_ret + pos * r[:, i]
        )
        day_ret = day_ret + r[:, i]
        for key, value_ in (
            ("states", s),
            ("acts", a),
            ("logs", dist.log_prob(a)),
            ("vals", value),
            ("rews", reward),
        ):
            trail[key].append(value_)
        positions[:, i] = new_pos
        pos = new_pos
    return positions, trail


# Generalised advantage estimation over a batch of whole sessions.
def advantages(rews, vals, gamma: float = 0.99, lam: float = 0.95):
    adv = torch.zeros_like(rews)
    last = torch.zeros(rews.shape[0], device=DEVICE)
    for t in reversed(range(BARS)):
        nxt = vals[:, t + 1] if t + 1 < BARS else torch.zeros_like(last)
        last = rews[:, t] + gamma * nxt - vals[:, t] + gamma * lam * last
        adv[:, t] = last
    ret = adv + vals
    return (adv - adv.mean()) / (adv.std() + 1e-8), ret


# One PPO update from one batch of rolled-out sessions.
def ppo_update(model, opt, trail, cost, clip: float = 0.2) -> None:
    rews, vals = torch.stack(trail["rews"], 1), torch.stack(trail["vals"], 1)
    adv, ret = advantages(rews, vals)
    states, acts = torch.cat(trail["states"], 0), torch.cat(trail["acts"], 0)
    logs = torch.cat(trail["logs"], 0)
    flat_adv, flat_ret = adv.T.reshape(-1), ret.T.reshape(-1)
    model.train()
    for _ in range(4):
        logits, value = model(states)
        dist = torch.distributions.Categorical(logits=logits)
        ratio = torch.exp(dist.log_prob(acts) - logs)
        clipped = torch.clamp(ratio, 1 - clip, 1 + clip) * flat_adv
        pg = -torch.min(ratio * flat_adv, clipped).mean()
        loss = (
            pg + 0.5 * (value - flat_ret).pow(2).mean() - 0.01 * dist.entropy().mean()
        )
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 0.5)
        opt.step()


# Fit PPO; the epoch is chosen on validation Sharpe.
def train_ppo(split, seed: int, cost: float):
    torch.manual_seed(seed)
    model = ActorCritic(split.width).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=3e-4)
    best, state = -1e9, None
    idx = torch.arange(len(split.z_train), device=DEVICE)
    for _epoch in range(EPOCHS // 2):
        perm = idx[torch.randperm(len(idx), device=DEVICE)]
        for i in range(0, len(perm), BATCH * 4):
            b = perm[i : i + BATCH * 4]
            model.eval()
            with torch.no_grad():
                _p, trail = rollout(
                    model, split.z_train[b], split.r_train[b], cost, True
                )
            ppo_update(model, opt, trail, cost)
        model.eval()
        with torch.no_grad():
            pv, _ = rollout(model, split.z_valid, split.r_valid, cost, False)
        v = score(pnl_of(pv.cpu().numpy(), split.r_valid_np, cost), split.dates_valid)[
            "sharpe"
        ]
        if v > best:
            best, state = v, {k: t.clone() for k, t in model.state_dict().items()}
    model.load_state_dict(state)
    model.eval()
    return model, best


# --- the run ------------------------------------------------------------------


class Split:
    """The arrays each agent trains, validates and is scored on."""

    def __init__(self) -> None:
        x_all = np.load(OUT / "X.npy")
        r_all = np.load(OUT / "R.npy")
        dates = np.load(OUT / "DATE.npy").astype("datetime64[D]")
        year = dates.astype("datetime64[Y]").astype(int) + 1970
        train, valid, test = year <= 2024, year == 2025, year == 2026
        self.width = x_all.shape[-1]
        # Standardised on training rows only.
        flat = x_all[train].reshape(-1, self.width)
        z_all = ((x_all - flat.mean(axis=0)) / (flat.std(axis=0) + 1e-8)).astype(
            np.float32
        )
        self.z_train, self.r_train = _dev(z_all[train]), _dev(r_all[train])
        self.z_valid, self.r_valid = _dev(z_all[valid]), _dev(r_all[valid])
        self.z_test, self.r_test = _dev(z_all[test]), _dev(r_all[test])
        self.r_valid_np, self.dates_valid = r_all[valid], dates[valid]
        self.x_test, self.r_test_np, self.dates_test = (
            x_all[test],
            r_all[test],
            dates[test],
        )
        self.counts = (int(train.sum()), int(valid.sum()), int(test.sum()))


# A tensor on the device.
def _dev(a, dtype=torch.float32):
    return torch.tensor(a, dtype=dtype, device=DEVICE)


# Score a set of test positions at every cost, with its turnover.
def _row(split: Split, positions: np.ndarray) -> tuple[dict, float]:
    scores = {
        c: score(pnl_of(positions, split.r_test_np, c / 1e4), split.dates_test)
        for c in COSTS_BPS
    }
    return scores, turnover_of(positions)


# Train the direct-Sharpe policy over the seeds and score the held-out year.
# The seed is chosen on validation, never on the held-out year.
def _sharpe_rows(split: Split, results: dict) -> None:
    print("training the direct-Sharpe policy", flush=True)
    seeds = []
    for seed in range(SEEDS):
        policy, v = train_sharpe(split, seed, HEADLINE_BPS / 1e4)
        with torch.no_grad():
            seeds.append((v, policy(split.z_test).cpu().numpy()))
        print(f"  seed {seed}: validation Sharpe {v:+.3f}", flush=True)
    _v, best = max(seeds, key=lambda s: s[0])
    results["direct Sharpe (GRU), best seed"] = _row(split, best)
    results["direct Sharpe (GRU), seed average"] = _row(
        split, np.mean([s[1] for s in seeds], axis=0)
    )


# Train PPO over the seeds and score the held-out year.
def _ppo_rows(split: Split, results: dict) -> None:
    print("training PPO with positional context", flush=True)
    seeds = []
    for seed in range(SEEDS):
        model, v = train_ppo(split, seed, HEADLINE_BPS / 1e4)
        with torch.no_grad():
            p, _ = rollout(model, split.z_test, split.r_test, HEADLINE_BPS / 1e4, False)
        seeds.append((v, p.cpu().numpy()))
        print(f"  seed {seed}: validation Sharpe {v:+.3f}", flush=True)
    _v, best = max(seeds, key=lambda s: s[0])
    results["PPO, positional context, best seed"] = _row(split, best)


# Print the held-out table.
def _report(split: Split, results: dict) -> None:
    print(f"\nHELD-OUT 2026, {split.counts[2]:,} name-sessions")
    head = "".join(f"{f'Sharpe@{c:g}bp':>12}" for c in COSTS_BPS)
    print(
        f"{'strategy':38} {'turnover':>8} {head}{'ann@3bp':>9} {'maxDD':>8} {'hit':>6}"
    )
    for name, (row, turn) in results.items():
        h = row[HEADLINE_BPS]
        cells = "".join(f"{row[c]['sharpe']:12.2f}" for c in COSTS_BPS)
        print(
            f"{name:38} {turn:8.2f} {cells}"
            f"{h['annual']:+9.1%} {h['drawdown']:8.1%} {h['hit']:6.1%}"
        )


# Train the agents on 2020-2024, pick on 2025, score 2026 once.
def run(which: list[str]) -> None:
    """Train whichever agents were asked for and print the held-out table."""
    split = Split()
    print(
        f"train {split.counts[0]:,} valid {split.counts[1]:,} "
        f"test {split.counts[2]:,}; {DEVICE}"
    )
    results: dict[str, tuple[dict, float]] = {}
    for name, pos in baselines(split.x_test).items():
        results[name] = _row(split, pos)
    if "sharpe" in which:
        _sharpe_rows(split, results)
    if "ppo" in which:
        _ppo_rows(split, results)
    _report(split, results)


# Command line.
def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Intraday agents on 15-minute bars.")
    parser.add_argument("command", choices=("build", "run"))
    parser.add_argument("agents", nargs="*", default=["sharpe", "ppo"])
    args = parser.parse_args()
    if args.command == "build":
        build()
    else:
        run(args.agents)


if __name__ == "__main__":
    main()
