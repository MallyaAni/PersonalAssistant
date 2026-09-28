# Profit-taking and dip-buying on the `/4` book: pre-registration (2026-09-27)

Written before the run. The operator's reading of the live policy - graded
equal weight (`policy_v4`: every A/A+ name at equal weight, capped at 20%),
exits on a downgrade, and since tonight the redeploy of idle cash between
resets - is that it is bad at *taking profits* and at *buying dips*, and
that a top-tier book should lead the market rather than wait for its own
20-session reset. This trial prices that reading as a fixed set of rules
that trim a held name between resets (never exit it, except in one
model-guided stop) and let the executor's own redeploy put the proceeds
back to work, plus one rule that adds to a name on a dip. It changes
nothing on the executor.

## The operator's question, made testable

"Take profits" and "buy dips" are instincts about the path a name takes
inside a cycle. The reset already does both, coarsely, once every twenty
sessions: a name that ran up is trimmed back to equal weight and a name
that fell is bought back to it. The question is whether doing it *between*
resets, on a signal, earns anything after cost on this book - or whether
the reset's slow version is the right one because the names the desk grades
A keep going.

Every variant is the live executor as it runs tonight -
`market_pit_scorecard._live_options` plus `midcycle_redeploy=True`
(`profit_taking.control_options`; the control is "ew-redeploy") - with one
rule added through two hooks of `simulate.run`: the allocator wrapper (the
policy's targets with the rule's state applied) and `weight_filter` with
the new `midcycle_trims=True`, which sells a held name down to the rule's
weight between resets (before it, the hook could only act on rebalance
sessions under `live_midcycle`, because the live plan replaces its target;
`midcycle_trims=False` is byte-identical). The sale fills as every live
sell does - at the close, held back on a green open and retried the next
session while the rule's state holds. The restore is the executor's: once
a trimmed name's state clears, its full target is back in the allocator and
the redeploy (from cash beyond the 2% buffer) or the next reset buys it
back.

## The variants (fixed here, seven trials)

| name | rule | trigger | restore | size |
|---|---|---|---|---|
| `ew-redeploy` | control | - | - | - |
| `trim-runup-20` | run-up | held weight >= 1.5 x target | (stateless) | back to target |
| `trim-rsi` | RSI(14) | > 80 | < 60 | target x 0.5 |
| `trim-band` | Bollinger, 20 sessions | close > mean + 3 sigma (one sigma above the upper band) | < mean + 2 sigma (back inside) | target x 0.5 |
| `dip-add` | 21-session EMA | close < EMA x 0.92 (8% under) | the next reset; re-armed once back within 8% | target x 1.5, capped at the 20% hold limit |
| `trim-dd-forecast` | CNN drawdown20 forecast | worst decile of the day's A/A+ book (by rank, at least one name) | out of the decile | target x 0.5 |
| `trim-dd-forecast-stop` | the same | the same, plus a full exit when the close is 15% below the trim close | the stop lifts at the next reset | 0 |

Conventions that matter: the band z is in sigma units (the desk's
`entry.bollinger_z` is the same number halved; the upper band is 2, the
trigger 3). A trimmed name's half target is enforced on every mid-cycle
session while the state holds, so a name that runs on after the trim is
kept at its cut (the planner's 0.5% trade floor leaves dust alone). The
dip add is paid from cash beyond the buffer first and then pro rata from
the other held A/A+ names, and the buy itself is the redeploy's the
session after, toward the raised allocator target; the raise is cleared at
the next reset and the name cannot re-add until its close is back within
8% of the EMA, so a name in a long slide is added to once per cycle at
most. The forecast rules take the worst tenth by rank, ties broken by
column order, never by a threshold a tie could put the whole book under.
A name the policy no longer wants (downgraded, out of the book) loses its
state and the rotation sells it as before.

The two model rules need the CNN's out-of-sample ``drawdown20`` forecast
per (ticker, date), written by the stage-2 command on the RTX
(`market_deep_stage2 --export-forecasts`, `market/drawdown_forecast.py`;
row (name, t) is made from bars through t's close and aligned to panel
position t, and the alignment test asserts a one-session shift is a
different matrix). Without the file the two are skipped and the payload
and the verdict say so; the price rules run everywhere.

## Statistics

The other studies': twenty start offsets on the 20-session clock, 10 and 25
bp, the scorecard's windows (2016-2023 choosing, 2024-2026 reported, all),
median and worst CAGR, median worst drawdown and Sharpe across offsets, the
paired daily difference against the control at the median offset with its
Newey-West t at lag 20, offsets above the control, and the exposure reading
from a passive ledger (cash share; the control's CAGR scaled to the
variant's invested share). For the trims themselves: trims and adds a year,
the mean trim size (share of equity sold), the share of trims the name
kept rising after (its close 20 sessions later above the trim close -
"sold too early"), the share of adds the name kept falling after, the
median 20-session return after a trim, and what the sold slice would have
earned over those sessions in bp of equity (size x forward return). The
CAGR attributable to the trims is the whole gap to the control, since
nothing else differs.

## Verdict (fixed before the run)

ADOPT (registered) when a rule is >= +1.0 CAGR point over the control on
2016-2023 at 25 bp with paired t >= 2.0, not worse on 2024-2026 by paired
bp a day, and its median worst drawdown is within 3 points of the
control's on both windows; else RECORD. A RECORD above the control on at
least 90% of the offsets by >= 2 points is read as "CONSISTENT, floor not
cleared by daily t", the mid-cycle study's second reading, stated as a
reading and never as an adoption. A skipped model rule is SKIPPED.

## The prior, stated before the run

On a momentum-graded book, trimming winners has cost return in every
related test so far. Volatility sizing (the inverse-vol tilts and the vol
targets, with the CNN forecast and without) lost 0.3-0.5 points on
2016-2023 and 6-10 on 2024-2026 for 2-3 points of drawdown; the stage-2
decision test that *dropped* the names whose forecast drawdown was worst
lost 2 bp a session even with an IC of 0.12-0.15; the catastrophe stops
that fired were all false alarms; the `/3` exit overlay's band trims were
retired because the names resumed. The reason is the same each time: the
desk grades names for their trend, a name that is up 50% in a cycle or
three sigma above its band is exactly the name the grade selected for, and
the simulator's own partial-trim option on the retired exit overlay
(`simulate.run(trim=...)`) measured the same way: these names resume
after the pause. So I expect
every price-based trim to **cost 0.5-2 CAGR points on 2016-2023 and lower
the median worst drawdown by 1-3 points**, with the RSI and band trims
costing the most (they fire on the names running hardest and hold the cut
until the run is over) and the run-up trim the least (it fires rarely at
1.5x within twenty sessions). The forecast trims should do better than the
drop rule did - halving keeps most of the name - but the flicker of a
daily decile (a name in and out of the worst tenth from one day to the
next) will turn over more than the forecast's IC pays for; I expect them
RECORD with a small cost and a drawdown saving under 2 points, and the stop
variant to add nothing, as every stop has.

`dip-add` is the one rule with a plausible positive prior, and I want to
say what cuts against it before the run. For: the book buys back its
fallen names at the reset anyway, so buying earlier in a cycle is a timing
tilt on a purchase the policy already makes, and an A-graded name 8% under
its 21-session average is mostly a name in a market drawdown, where the
grade has not moved. Against: the session-anatomy study found that
intraday dips on these names *continue slightly* rather than reverse
(-2% by late morning, 3-10 bp less than unconditional to the close, the
same sign in both windows), the fill-timing study found nothing to buy
at the open after a dip, and at the 20-session scale a name 8% under its
EMA with its grade intact is the case the drawdown forecast flags. The add
is also paid by trimming the others, which is a second bet on the same
day. My expectation is **-0.5 to +1.0 points, not significant, on
2016-2023, and worse on 2024-2026**, where the fallen names fell further
(the mid-cycle study's downgrade exits earned their place there for that
reason).

What would make the prior wrong: a "sold too early" share well under
50% for a price trim (the names did not keep going, so the trim gave up
nothing) together with a positive `trim_forward_bp` reading turning
negative; a forecast trim whose trims cluster in the sessions before the
2022 and 2024-2025 drawdowns rather than flickering daily; a dip add
whose adds are followed by a positive median 20-session return on both
windows. Any of those with the registered floors cleared would be the
first evidence that this book's return is not all in letting its winners
run, and would be recorded as an ADOPT for the executor to take up as a
registered change after a reset, never before.

## Costs and runtime

Seven variants (five without the forecast file) x twenty offsets x two
costs = 280 (200) simulator runs of the live policy on the point-in-time
book, each about the mid-cycle study's per-run cost (240 runs took about
25 minutes there). Expect about 20 minutes on the Spark for the price
rules and 30 with the file, plus the desk run.

## Commands

    # Spark, price rules now (the model rules are skipped with a note):
    python -m backend.cli.market_profit_taking --root data/market --offsets 20 --costs 10 25
    # RTX, the forecast file from the stage-2 dataset:
    python -m backend.cli.market_deep_stage2 --root <dir> --dataset deep_stage2.npz \
        --models cnn --targets drawdown20 --device cuda \
        --export-forecasts drawdown_forecasts.npz --out deep_stage2_dd.json
    # Spark, every rule:
    python -m backend.cli.market_profit_taking --root data/market --offsets 20 --costs 10 25 \
        --drawdown-forecasts research/drawdown_forecasts.npz

Writes `data/market/desk/profit_taking.json`; the results note goes beside
this one as `profit-taking-2026-09-27.md`, with the payload copied to
`docs/research/scorecards/profit_taking.json`.
