"""Intraday agents on fifteen-minute bars, scored once on a year they never saw.

    python -m backend.cli.market_intraday_rl build          # episodes to TMP
    python -m backend.cli.market_intraday_rl run            # both agents
    python -m backend.cli.market_intraday_rl run sharpe     # one of them

What was asked
--------------
Whether a reinforcement-learning agent on the book's 15-minute bars could
find an edge the daily desk cannot. The daily book has few independent
periods to learn from; the fifteen-minute store has 20.8 million bars
across 529 names, closer to the regime where RL has worked in finance. So
it was tested rather than argued, on the 93 book names, with 2026 held out
and never seen by anything until one final table.

Four defects in the first version, and what they changed
--------------------------------------------------------
The first run reported every strategy negative at realistic cost and
called intraday trading "ruled out". A review found four reproducible
defects in that run. Each is fixed below; the conclusion is restated in
the results section from a rerun, not carried over.

* The session filter fixed the open at 13:30 UTC all year. New York opens
  at 14:30 UTC in winter, so from November to March the window kept four
  pre-market bars, dropped the last hour, and mis-slotted every bar in
  between. Winter days either failed the completeness check or passed it
  with the wrong bars in the wrong slots - including the first quarter of
  the held-out year. Sessions are now selected on the New York clock.

* The twenty-day volatility feature filled its warm-up rows with the
  median over the name's whole history, which reads the future for the
  first twenty sessions of every name. Those rows are dropped now rather
  than filled, so every feature is causal, as the first version claimed
  and was not.

* The "published momentum" baseline was not the published strategy. Gao,
  Han, Li and Zhou's signal is the return from the previous close to
  10:00 - the overnight gap included - and the position is held through
  the whole last half hour. The first version used the first fifteen
  minutes without the gap and held fifteen minutes. Its failure said
  nothing about the published effect. The gap is now a signal (known at
  10:00, causal) even though it is never earned (the agent is flat at the
  close), and the position covers both last-half-hour bars. "Long the
  session" now runs from the first bar's open rather than its close.

* The direct-Sharpe policy was trained on the Sharpe across stock-days in
  a batch and scored on the Sharpe of daily portfolio returns. Those are
  different objectives and can prefer different policies. Training
  batches are now whole days, and the loss is the Sharpe across days of
  the equal-weighted daily P&L - the same number the table reports.

Results, from the corrected run
-------------------------------
Selecting sessions on the New York clock brought back every winter day:
67,454 training sessions where the defective run had 45,308, and 15,151
held-out sessions where it had 11,312. Sharpe by one-way cost, then annual
return and worst drawdown at 3 bps:

  strategy                          turn   1bp    3bp    5bp   10bp    ann    maxDD
  long the session (open to close)  2.00  0.12  -0.27  -0.67  -1.64   -7.1%  -23.8%
  first-half-hour momentum (Gao)    2.00 -2.38  -4.86  -7.34 -13.55  -19.7%  -12.7%
  hourly reversal (Heston)         11.49 -3.23  -8.48 -13.95 -28.74  -95.0%  -47.4%
  direct Sharpe GRU, best seed      0.84 -0.24  -0.89  -1.54  -3.16   -5.8%   -8.0%
  direct Sharpe GRU, seed average   0.61 -0.19  -0.98  -1.76  -3.73   -3.8%   -4.6%
  PPO, positional context           2.65 -1.01  -1.52  -2.02  -3.24  -39.5%  -28.4%

Nothing is positive at a realistic cost, and the shape of the failure is
the same after the corrections as before them. Holding these names open
to close earns a few basis points a session and a round trip costs six.
The direct-Sharpe policy, now trained on the same portfolio Sharpe the
table reports, put its validation Sharpe at -0.06, -0.03 and -0.01 across
seeds and cut its turnover to 0.6-0.8 a session: a policy that learned
there was nothing worth paying for and traded less. PPO found +0.55 on
2025 with one seed and -0.85 and -1.20 with the other two, and the best
of them lost on 2026. Gao et al.'s rule, implemented as published - the
overnight gap in the signal, the whole last half hour held - loses at
every cost, so its earlier failure was not the fault of the earlier
mis-implementation.

These implementations did not demonstrate an advantage. That is the
claim, and the only one the evidence supports; the section below says why
it is not a larger one.

What a result here can and cannot say
-------------------------------------
Two agents, two published rules, seven years and roughly eleven thousand
held-out sessions is a fair test of *these implementations*. It is not a
proof about intraday trading in general: an average session return below
the round-trip cost rules out buying every session, not a conditional
strategy with a different return distribution, and a profitable long-short
sleeve is a different objective from improving the fill on a purchase the
desk was going to make anyway. Neither is tested by the other. The honest
form of a negative result here is "these implementations did not
demonstrate an advantage", and that is the form used.

The protocol
------------
Regular session only, 09:30 to 16:00 New York by the New York clock, 26
bars, and only days with every bar present. Returns are earned within the
day only, so overnight gaps, unadjusted splits and re-listings - which all
happen between sessions - never reach an agent that is flat at the close.
Any day with a bar move beyond 30% is dropped as a vendor error (NuScale
was recorded rising 68x in fifteen minutes). The first twenty sessions of
every name are dropped rather than back-filled. Features are causal and
standardised on training rows. Train 2020-2024, choose epochs and seeds on
2025, score 2026 exactly once. Every position is forced flat at the close
and bounded to [-1, 1], so nothing wins by leverage or by holding
overnight. Cost is charged on every unit of turnover including the first
entry and the final exit. The headline cost is 3 basis points one way,
which is what spread plus slippage costs on liquid US large caps; 1, 5 and
10 are reported beside it.

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
import torch
from torch import nn

from backend.market.intraday import BARS
from backend.market.intraday import episodes as _episodes
from backend.market.intraday import partition as _partition
from backend.market.universe import book_sides, build_universe

OUT = Path(os.environ.get("TMP", "/tmp")) / "intraday"
VOL_DAYS = 20
COSTS_BPS = (1.0, 3.0, 5.0, 10.0)
HEADLINE_BPS = 3.0
SEEDS = 3
EPOCHS = 40
DAYS_PER_BATCH = 32
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
    "gap",  # previous close to this bar, in logs; the Gao signal at 10:00
)


# --- the dataset --------------------------------------------------------------


# Causal features for every bar of every session, what each bar paid, and
# which sessions have a full warm-up behind them.
def _features(close, high, low, volume, prev):
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
    x[:, :, 4] = np.where(np.isfinite(vol20), vol20, 0.0)[:, None]
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
    with np.errstate(all="ignore"):
        gap = logc - np.log(prev)[:, None]
    x[:, :, 10] = np.where(np.isfinite(gap), gap, 0.0)
    # The first VOL_DAYS sessions have no honest twenty-day history and
    # are dropped, not back-filled from the future.
    valid = np.arange(n) >= VOL_DAYS
    return x, nxt, valid


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
        days, close, high, low, volume, open0, prev = got
        x, nxt, valid = _features(close, high, low, volume, prev)
        session = np.log(close[:, -1]) - np.log(open0)
        per_name[ticker] = (days[valid], x[valid], nxt[valid], session[valid])
        print(f"  {ticker:6} {int(valid.sum()):5d} full sessions", flush=True)
    # The book's own average as the market, aligned by date.
    all_days = sorted({d for days, *_ in per_name.values() for d in days.tolist()})
    index = {d: i for i, d in enumerate(all_days)}
    sums = np.zeros((2, len(all_days), BARS))
    count = np.zeros(len(all_days))
    for days, x, _, _ in per_name.values():
        rows = [index[d] for d in days.tolist()]
        sums[0, rows] += x[:, :, 1]
        sums[1, rows] += x[:, :, 2]
        count[rows] += 1
    market = sums / np.maximum(count, 1)[None, :, None]
    xs, rs, names, dates, sessions = [], [], [], [], []
    for k, (days, x, nxt, session) in enumerate(
        v for _t, v in sorted(per_name.items())
    ):
        rows = np.array([index[d] for d in days.tolist()])
        x[:, :, 8] = market[0, rows]
        x[:, :, 9] = market[1, rows]
        xs.append(x)
        rs.append(nxt)
        names.append(np.full(len(days), k))
        dates.append(days)
        sessions.append(session)
    np.save(OUT / "X.npy", np.concatenate(xs).astype(np.float32))
    np.save(OUT / "R.npy", np.concatenate(rs).astype(np.float32))
    np.save(OUT / "NAME.npy", np.concatenate(names))
    np.save(OUT / "SESSION.npy", np.concatenate(sessions).astype(np.float32))
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


# Daily P&L across the names traded each day, equal-weighted.
def daily_of(episode_pnl: np.ndarray, dates: np.ndarray) -> np.ndarray:
    days, inverse = np.unique(dates, return_inverse=True)
    daily = np.zeros(len(days))
    count = np.zeros(len(days))
    np.add.at(daily, inverse, episode_pnl)
    np.add.at(count, inverse, 1)
    return daily / np.maximum(count, 1)


# The usual numbers from a daily series.
def score(episode_pnl: np.ndarray, dates: np.ndarray) -> dict:
    daily = daily_of(episode_pnl, dates)
    annual = daily.mean() * SESSIONS_PER_YEAR
    vol = daily.std() * np.sqrt(SESSIONS_PER_YEAR)
    curve = np.cumprod(1 + daily)
    return {
        "annual": float(annual),
        "sharpe": float(annual / vol) if vol > 0 else float("nan"),
        "drawdown": float((curve / np.maximum.accumulate(curve) - 1).min()),
        "hit": float((daily > 0).mean()),
        "days": int(len(daily)),
    }


# Units of position changed per session; a round trip is 2.
def turnover_of(positions: np.ndarray) -> float:
    pos = positions.copy()
    pos[:, -1] = 0.0
    prev = np.concatenate([np.zeros((len(pos), 1)), pos[:, :-1]], axis=1)
    return float(np.abs(pos - prev).sum(axis=1).mean())


# The rules nothing is fitted for, as positions on the bar grid: the two
# published intraday effects, and flat. "Long the session" is not a grid
# position - it runs from the first bar's open - and is scored separately.
def baselines(x: np.ndarray) -> dict[str, np.ndarray]:
    n = len(x)
    out = {}
    # Gao et al.: the return from the previous close to 10:00, gap included,
    # predicts the last half hour; hold its sign through both closing bars.
    p = np.zeros((n, BARS))
    signal = x[:, 1, 10]  # gap to the close of bar 1, i.e. through 10:00
    p[:, 23] = np.sign(signal)
    p[:, 24] = np.sign(signal)
    out["first-half-hour momentum (Gao)"] = p
    # Heston et al.: fade the last hour's move, re-decided every bar.
    p = np.zeros((n, BARS))
    p[:, 4:] = -np.sign(x[:, 4:, 1])
    out["hourly reversal (Heston)"] = p
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


# Minus the Sharpe across DAYS of the equal-weighted daily P&L - the same
# quantity the table reports - with cost inside and flat at the close.
# `day` maps each episode in the batch to a day index in [0, days).
def sharpe_loss(pos, ret, cost, day, days: int):
    pos = torch.cat([pos[:, :-1], torch.zeros_like(pos[:, -1:])], dim=1)
    prev = torch.cat([torch.zeros_like(pos[:, :1]), pos[:, :-1]], dim=1)
    pnl = (pos * ret).sum(dim=1) - cost * (pos - prev).abs().sum(dim=1)
    total = torch.zeros(days, device=pnl.device).index_add(0, day, pnl)
    count = torch.zeros(days, device=pnl.device).index_add(0, day, torch.ones_like(pnl))
    daily = total / count.clamp(min=1)
    return -(daily.mean() / (daily.std() + 1e-6))


# Fit the direct-Sharpe policy on whole-day batches; the epoch is chosen
# on the validation days' portfolio Sharpe.
def train_sharpe(split, seed: int, cost: float):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    policy = SharpePolicy(split.width).to(DEVICE)
    opt = torch.optim.Adam(policy.parameters(), lr=1e-3)
    best, state = -1e9, None
    n_train_days = len(split.train_days)
    for _epoch in range(EPOCHS):
        policy.train()
        order = rng.permutation(n_train_days)
        for i in range(0, n_train_days, DAYS_PER_BATCH):
            picked = order[i : i + DAYS_PER_BATCH]
            rows = np.concatenate([split.train_days[j] for j in picked])
            day = np.concatenate(
                [np.full(len(split.train_days[j]), k) for k, j in enumerate(picked)]
            )
            b = torch.tensor(rows, device=DEVICE)
            opt.zero_grad()
            loss = sharpe_loss(
                policy(split.z_train[b]),
                split.r_train[b],
                cost,
                torch.tensor(day, device=DEVICE),
                len(picked),
            )
            loss.backward()
            nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
            opt.step()
        policy.eval()
        with torch.no_grad():
            v = -sharpe_loss(
                policy(split.z_valid),
                split.r_valid,
                cost,
                split.valid_day,
                split.valid_day_count,
            ).item()
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
def ppo_update(model, opt, trail, clip: float = 0.2) -> None:
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


# Fit PPO; the epoch is chosen on validation portfolio Sharpe.
def train_ppo(split, seed: int, cost: float):
    torch.manual_seed(seed)
    model = ActorCritic(split.width).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=3e-4)
    best, state = -1e9, None
    idx = torch.arange(len(split.z_train), device=DEVICE)
    batch = DAYS_PER_BATCH * 64
    for _epoch in range(EPOCHS // 2):
        perm = idx[torch.randperm(len(idx), device=DEVICE)]
        for i in range(0, len(perm), batch):
            b = perm[i : i + batch]
            model.eval()
            with torch.no_grad():
                _p, trail = rollout(
                    model, split.z_train[b], split.r_train[b], cost, True
                )
            ppo_update(model, opt, trail)
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
        session = np.load(OUT / "SESSION.npy")
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
        self.session_test = session[test]
        # Whole-day batching for the direct-Sharpe objective.
        train_dates = dates[train]
        _u, inverse = np.unique(train_dates, return_inverse=True)
        self.train_days = [
            np.flatnonzero(inverse == k) for k in range(inverse.max() + 1)
        ]
        _u, valid_inverse = np.unique(self.dates_valid, return_inverse=True)
        self.valid_day = torch.tensor(valid_inverse, device=DEVICE)
        self.valid_day_count = int(valid_inverse.max()) + 1
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


# "Long the session" from the first bar's open to the last bar's close,
# one round trip, which the bar grid cannot express.
def _long_session_row(split: Split) -> tuple[dict, float]:
    scores = {
        c: score(split.session_test - 2.0 * c / 1e4, split.dates_test)
        for c in COSTS_BPS
    }
    return scores, 2.0


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
    results: dict[str, tuple[dict, float]] = {
        "long the session (open to close)": _long_session_row(split)
    }
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
