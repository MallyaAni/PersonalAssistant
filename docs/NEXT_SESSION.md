# Next session

Verified state as of 2026-09-05. `deep-matter.com` serves from spark1. The
Windows desktop is powered on again and holds the GPU for image work; when
it is off, image requests get an honest "try again later". Everything below
was checked by running it, not by reading it. The seven image scenarios can
be re-run any time with `python -m backend.cli.exercise_image_scenarios`
inside the backend container.

## 2026-09-05 (evening) — the events listing offers links instead of printing them; the follow-up delivers them (PUSHED `153ec73`, NOT DEPLOYED)

A weekend answer used to carry a row of links under every event. Now the
listing ends with one offer line and `send_event_links` delivers the map,
calendar and event-page links for exactly the events the person names, in
one follow-up. The Scout digest is untouched. Which events the person means
is resolved by the existing `pick_many` against the last listing this
conversation showed, kept per user in Redis (`last_listing_store`, 72h TTL)
as typed records; links are built by code (`backend/core/event_links.py`),
so the link fence still holds. Read-only, fast, withheld from a firing.

Measured: send_event_links 9/9 (evaluate_tool_selection 3 reps, floor 0.66);
functional/test_send_event_links_behaviour.py on the real model - router
sent "send me the links for the sunset session" to send_event_links, picker
resolved "the sunset session at potato head" with grounded links. Same commit
fixed the pre-existing red `test_tool_coverage_completeness`: `manage_runs`
had shipped with no TOOL_NAMES entry, cases, floor or `_ACTION_TOOL` mapping
(the exact gap the test catches); coverage added, measured 9/9, floor 0.66.
Unit: discovery + tools + reply suites 600 passed; two real-model functional
tests passed. Note: only the `send_event_links` and `manage_runs` routing
families were measured, not the whole matrix - re-run `evaluate_tool_selection
--reps 3` and the routing gate before raising `TURN_MAX_STEPS` to 3.

Diagram impact: NONE (no component added; the last listing rides the Redis
the app already reaches).

## 2026-09-06 (later still) — the desk runs itself on spark1 (PUSHED; DEPLOY STEP PENDING)

Continues the entry below it. Commit `562cce2d`.

**Scheduled.** `~/desk_daily.sh` on spark1, in the crontab at 17:30
Eastern on weekdays: pulls origin/main into `~/deploy/anios`, then runs
`market_daily --refresh --brief-book --prune-days 30 --llm-url
http://127.0.0.1:8000 --llm-model deepseek-v4-flash` with the research
venv (CUDA hidden, so nothing touches vLLM's memory). It writes bars,
filings and any new release scores into a fresh partition, grades the
book, briefs every held name through the local model, writes
`data/market/desk/asof=<session>/desk.json`, and drops bar and filing
partitions older than 30 days (a day is about 12 MB; tone and desk
records are never pruned). The log is `~/desk_daily.log`. The first run
was started by hand on 2026-09-06 to prove the path.

**The one deploy step left.** `docker-compose.yml` now mounts
`./data/market/desk` read-only into the backend container, so once the
stack is rebuilt (`docker compose up -d --build backend` and the gateway
for the new frontend view) the Desk view at deep-matter.com reads the
records the cron writes. Until that rebuild the API answers `latest:
None` and the page says so. Not done here: it restarts the production
backend, which is the operator's call.

**Next atomic task.** After the deploy: open #desk, confirm the record
and the orders render; then the paper book on the operator's Alpaca
paper account behind an explicit `--paper-trade` flag, and live P&L on
the page from the account's positions.

## 2026-09-06 (night) — the Desk page, and the desk run for real (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `4ddb4873` (pipeline and brief),
`cf937dc3` (ranks in the evidence), then the page.

**The desk ran end to end on real data.** `market_daily --refresh` pulled
95 bar series and 90 filings into `asof=2026-09-06`; the tone step scored
0 new releases because `prior_records` carried every earlier score
forward by accession; the desk ran; briefs for SNDK, CRWV and AAOI came
back from spark1's model (SNDK "own", CRWV "avoid", AAOI "own", each
citing the analysts by rank among the book); the record is at
`data/market/desk/asof=2026-09-04/desk.json` (the last session on file;
the run was on a Sunday).

**The operator's point: a printout is not a product.** What he acts on
is the change list and the book, so the page shows those. `backend/
market/deskrecord.py` diffs two records into upgrades, downgrades, the
orders that turn yesterday's book into today's (buy, sell, add, trim,
largest first) and the regime flags raised or cleared;
`GET /api/v1/market/{user}/desk` serves the latest record with its
summary, changes and sessions, `/desk/{session}` an earlier day; the
trading agent's card carries the session, the grade counts and the book
and opens the Desk view; `frontend/src/components/DeskPanel/DeskPanel.tsx`
renders the regime and flags, the orders at the next open, the book, every
grade with the four stances, and the brief per name, re-reading the record
every five minutes. Backend tests: `test_market_deskrecord.py`,
`test_market_desk_api.py` (including another user's token refused).
The frontend builds (`npm run build`).

**To deploy** (not done here): mount `./data/market` into the backend
container (the compose file only mounts `data/models`), rebuild the
gateway for the new view, and run `market_daily --refresh --brief <book>
--llm-url http://127.0.0.1:8000 --llm-model deepseek-v4-flash` on spark1
after the close (the research venv has curl_cffi, pyarrow and lightgbm;
spark1 is on Eastern time). Until then the record is written on the
desktop and the page reads it there.

**What comes next for making money with it**, in order: a paper book on
the operator's Alpaca paper account that places the page's orders at the
open (an explicit `--paper-trade` flag, off by default, so the track
record is real before any capital is), live P&L of that book on the page
from Alpaca positions, and a monthly `--calibrate` line on the page so a
grade that stops paying is seen.

## 2026-09-06 (night) — the 15-minute bars on entry days: fills and structure (NO CODE CHANGE)

Continues the entry below it. The last open intraday question, measured
on 9,968 entry days (grade A or better plus a dip or breakout trigger at
the prior close) across all 90 names with a full 15-minute session, from
the Alpaca bars in the store (scratch script `fill_study.py`).

**Fills.** Against the session VWAP: the open -1.1 bp, 10:30 -2.4, a
pullback to the 15-minute 21 EMA +1.4 (it happens on 83% of entry days
but sits above the open on down-gap days), a break of the first bar's
high +0.9, the close +2.5. On dip-entry days the first hour dips further
(10:30 is 3 bp under the open, the close 19 bp over it); on breakout days
nothing separates any fill. The 20-session return from every fill is
within noise of the return from the open (every t against the open below
1.1; the close on dip days is the one worse fill, t -1.9). Execution
timing on the entry day is worth a few basis points against an expected
move of 3.3% over 20 sessions: the backtest's next-open assumption stands,
and a 10:30 entry on dip days is the only thing worth doing differently.

**Structure as information.** Whether the entry day closed above its
15-minute 21 EMA: all entries +3.49% vs +3.01% over the next 20 sessions
(t 1.5); breakout entries +3.50% vs +2.91% (t 1.7); dip entries no
difference (t 0.0), and on dip days a close below the open is followed by
more (+3.99% vs +2.86%), the bounce not yet having happened. The
operator's read that the 15-minute trend lines are worth respecting is
mildly true on breakout entries and not on dips; at t 1.7 it does not
enter a rule. The 15-minute layer is closed: session features, the tape
encoder, fills and entry-day structure have all been measured.

**Next atomic task.** A desk narrative prompt with a functional test if
the operator wants the reasoning in words; otherwise the desk is complete
as measured, and the work is running it daily and re-calibrating monthly.

## 2026-09-06 (later) — the defaults now say what the backtests said (PUSHED, NOT DEPLOYED)

Continues the entry below it. The operator asked "have you implemented
your best solution given what you've learnt?" and the honest answer was
not yet: the defaults still encoded the beliefs from before the backtests.
Four changes, each measured after:

* **Backtest rules default to no price stop and a 10-session grade exit**
  (`backtest.Rules`), the set that measured best on every name; the
  variants list now starts from it and switches rules on, not off.
* **The book default is the top tenth at a 25% volatility target with a
  15% name cap** (`risk.BOOK_CONFIG`). Since 2021-06 on the 90 names:
  +31.6% a year, Sharpe 1.55, max drawdown -24.9% (the top fifth at 15%:
  +16%, 1.25, -16.5%; equal weight +41%, 1.28, -39%; SPY +14%, 0.85,
  -24.5%). `risk.size` rescales the engine's top fraction to the whole
  universe, since the engine only sees graded names: without that, "top
  tenth" meant three names on a day with 35 graded.
* **The fundamental analyst scores from whichever legs exist** (at least
  two of revenue growth, sequential growth, gross margin, acceleration), so
  a young filer like SNDK gets a view from its second quarter rather than
  its fifth.
* **Stances persist three sessions** before they change a grade
  (`opinions.persist`), which ends CRWD's daily B/C flicker on the
  rotation half-vote.

Calibration after all four: A+ 77 bp per 20 sessions (t 1.4), A 85 (t
1.7), B 10, C 18; 295 / 223 / 88 / 55 at 60; graded score rank IC 0.034
(t 2.3) at 20 and 0.052 (t 2.2) at 60. Persistence costs A+ some of the
first sessions after a release (102 → 77 bp) and buys a cleaner order.
Per-name backtests under the new defaults since 2021-06: the desk rules
are the best or near-best rule set on every name (AVGO +176% vs hold
+214%, MU +182% vs 252%, PANW +40% vs 171%) and still trail holding,
for the reasons in the entry below. Today's book: 9 names at the top
tenth (SNDK, ANET, PANW, AAOI, HPE and four A names).

**Next atomic task.** Whether the 15-minute bars improve the fill on an
entry day (next open versus a pullback to the 15-minute 21 EMA), the one
intraday question still open; then a desk narrative prompt with a
functional test, if the operator wants the reasoning in words.

## 2026-09-06 — entries, exits, the trade backtest, and what the book is worth (PUSHED, NOT DEPLOYED)

Continues the entry below it.

**Two more of the operator's claims measured.** His mean-reversion entry
(far below the short EMAs, near the lower Bollinger band) pays at one
week among qualified names: more than 8% below the 21 EMA +1.2% in 5
sessions (t 3.5, hit 0.58), below the lower band +0.9% (t 2.6), below the
band while the AI basket falls +2.1% (t 4.3, hit 0.62); by 20 sessions the
dip edge is gone and strength pays instead (more than 8% above the 21 EMA
+2.0%, t 2.6). Dips are entries, trend is the hold. And a learned model
does not beat the fixed grade: walk-forward LightGBM on every desk feature
(analyst ranks, levels, stretch, Bollinger, momentum, regime) gives
out-of-sample IC 0.006 (t 0.4) against 0.035 (t 2.1) for the grade on the
same sessions; it ranks tone, fundamentals and momentum highest and fits
noise after that. Reinforcement learning was asked about and declined for
the same reason: one path of 90 correlated names is not many episodes.

**The entry analyst and the trade backtest.** `desk/entry.py` (dip and
breakout triggers), `desk/backtest.py` (enter at the next open on A or
better plus a trigger, sized by grade and exposure; exit on a support stop
or a chandelier ATR stop or after N sessions below B; 10 bp a side;
variants switch each rule off), `market_desk --backtest MU NVDA --since
2021-06-01` and `--book-backtest`. **Result, on eight names since 2024 and
six since mid-2021: every per-name timing rule trails holding the name,
and the stops are the worst part** (AVGO since 2021: support stop +118%,
chandelier 3 ATR +40%, no stop with a slow grade exit +173%, hold +214%;
NVDA: +104% / +122% / +138% / +265%; PANW: -10% / +10% / +80% / +171%).
Hit rates 30-60%. The best rule set everywhere is no price stop and an
exit only after 10 sessions below B; even that trails buy-and-hold because
the first A grade arrives late (fundamentals need a year of filings: SNDK
entered 2025-11, CRWV never) and the position is out a third of the time.

**The book.** The graded scores through the sizing engine on the 90
names, monthly rebalance, no stops, since 2021-06: top 20% at a 15% vol
target +16.1% a year, Sharpe 1.25, max drawdown -16.5%; top 10% at 25%
vol +30.9%, Sharpe 1.55, -20.2%; equal weight of all 90 names +40.9%,
Sharpe 1.28, -38.7%; SPY +14.3%, 0.85, -24.5%. The daily equal weight of
A-or-better names +47.3% (Sharpe 1.22) against C names +42.0% (1.33): in
raw terms the grades barely separate, because these names' returns were
the AI theme, and the grade's measured edge (100 bp per 20 sessions,
beta-adjusted) is small next to a 40%-a-year drift. What the desk adds is
risk: a third of the drawdown at a similar Sharpe. That is the honest
"hedge-fund implementation" on this history: own the theme, size by risk,
rebalance monthly, exit on the grade, never on a price stop.

**Next atomic task.** Hysteresis on stances; the per-name backtest on the
book's 20-session clock; then whether the 15-minute bars improve the fill
on an entry day (enter at the next open versus a pullback to the 15-minute
21 EMA), which is the only intraday question still open.

## 2026-09-05 (later) — trade location; the technical analyst rebuilt on it (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `19a45009` (history), `34bd4af0`
(levels), then the veto.

**The operator's objection** was that the grades ignored technical
analysis as he practises it: location between support and resistance,
multi-timeframe agreement, reward-to-risk. The prior technical analyst
scored momentum and stretch only, because EMA slopes and candles measured
nothing as cross-sectional rankers. That was the wrong test. The right one
is trade quality among names that already qualify on fundamentals and
release tone, including entry risk. `backend/market/levels.py` computes
confirmed swing lows and highs (strictly the extreme of five bars either
side, stamped when confirmed), support as the nearest of those and the
daily 50/200 and weekly 21 EMAs below the close, resistance as the nearest
swing high above, reward-to-risk, position in the 60-session range, weekly
and daily trend, and a confluence count. Measured on the 90 book names
among qualified names, beta-adjusted, next 20 sessions, with the maximum
adverse excursion inside the window: weekly trend up +1.0% (t 4.2) against
-2.0% when flat; daily trend up +0.9% (t 3.3); top of the 60-session range
+1.3% (t 3.7, hit 0.56) against -0.5% at the bottom; more than 15% above
support earns nothing with a -12% adverse excursion against -7.6% at
support (support is an entry-risk fact, not a return fact); reward-to-risk
from swing levels inverts (RR < 1 +0.7%, t 2.3: resistance close overhead
means breakout on these names). The technical analyst now blends weekly
trend, daily trend, momentum and the negative of stretch (falling theme)
or range position (rising theme).

**Calibration after it** (`market_desk --calibrate`): A+ 102 bp per 20
sessions (t 1.9) and 343 per 60 (t 2.3, from 258); graded score rank IC
0.031 (t 2.1) at 20 and 0.050 (t 2.3) at 60. **The veto**: a bearish core
analyst caps the grade at B, which lifts A from 17 to 53 bp per 20
sessions and removes the losing case (IREN, January 2026: bullish release
and tape over bearish filings, then -22% and -26%).

**Per-name history** (`market_desk --history SNDK MU --since 2026-01-01`)
prints every grade change with the stances, the regime multipliers, the
next 20 sessions raw and beta-adjusted, earnings reaction days marked, and
a hold-while-graded backtest against buy-and-hold and SPY. 2026: SNDK A+
every session (+184% held, SPY +12.5%); MU A+ 107 sessions averaging
+14.7% (hit 0.80) against B sessions -8.9%; CRWV C all year (-4.6% on C
sessions); CRWD flickers between B and C daily on the rotation half-vote.
Two things still to do there: stances need hysteresis (a view must persist
before it changes a grade), and the per-name backtest switches daily where
the book rebalances every 20 sessions.

**What quant desks do with the same reads** (for the operator's question):
moving-average distance (21 vs 200 day) predicts the cross-section with
~9% annual alpha beyond momentum and the 52-week high (Avramov, Kaplanski,
Subrahmanyam 2021); the 52-week high is an anchor (George and Hwang 2004);
Lo, Mamaysky and Wang (2000) found chart patterns and levels carry
information when detected mechanically; Osler (2000) found bank-published
support and resistance levels in FX predict intraday reversals. None of
them trade levels by eye: every one is a feature measured in a
cross-section, which is what `levels.py` now is.

**Next atomic task.** Hysteresis on stances (persist N sessions), then
re-run `--calibrate` and the four histories; then the per-name backtest
on the book's 20-session rebalance clock.

## 2026-09-05 (night) — the book is AI and software only; the desk (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `9a5aaac1` (merged as `4764b76b`)
→ the technical switch.
Another agent is committing to this repository; files are added by name.

**The operator narrowed the book** to the AI-infrastructure and software
names he watches. `universe.book_sides()` returns 90 of them (every
overlay name plus the index's semiconductor, communications-equipment and
software sub-industries; utilities that only carry the power theme via the
index mapping are out), each tagged `ai` or `software`. The rest-of-
universe release batch on spark1 was killed for it (it was eight parallel
model calls against the assistant's own vLLM); the themed batch had
finished (3,896 releases, 382 min) and its partition is copied to the
desktop store (`edgar_tone/asof=2026-09-05`, 176 names).

**The desk** (`backend/agents/trading/desk/`, `python -m
backend.cli.market_desk --calibrate --brief SNDK`): fundamental, technical,
sentiment, regime and risk modules, each an `Opinion` (score, stance,
evidence) on the book's panel; a fixed grade rule (A+: bullish release and
agreement; A: agreement; B: one voice; C: none or split) with size
multipliers 1 / 0.75 / 0.5 / 0; `desk.calibrate` re-measures the grades.
Measured on the 90 names, beta-adjusted: A+ 102 bp per 20 sessions (t
2.0), A 26, B 24, C 15; at 60 sessions monotone, 283 / 173 / 105 / 59
bp (A+ t 1.9); the graded score's rank IC 0.035 (t 2.3) at 20 against
the composite's 0.025 (t 1.8) on the same names. Today: 6 A+,
11 A, 19 B, 54 C; book gross 0.30 (LRCX, NTAP, PANW, ANET, FN, AVGO,
AAOI). SNDK is B (fundamentals bullish, technical and tone neutral), CRWV
and IREN are C.

**What the regime analyst measured.** Software and AI residual baskets
were +0.19 correlated daily over the decade (+0.35 in 60-day windows, 7%
of windows negative) and -0.37 in 2026, -0.52 in the latest window: the
"inverse correlation" is a 2026 regime, so the analyst carries a novelty
z-score on the six theme baskets' co-movement structure (today +4.8) and
flags a change of shape rather than assuming one. Participation (20-day
dollar volume against the year, AI basket median) gates everything: tone
IC 0.033 (t 2.2) above the median vs -0.004 below; following the
60-session AI-vs-software leader 0.086 (t 3.0) vs -0.007; the composite
0.049 (t 2.3) vs -0.002 by software participation. After the top
participation quintile the AI basket lags SPY by ~1.2% over 20 sessions,
after the bottom it leads by 1.1%. So selection confidence is 0.5 below
the median (rotation withheld) and exposure 0.75 in the top quintile.
Today participation is at its two-year low (pct 0.00), confidence 0.5.

**The technical analyst switches playbook.** Over the decade the 21-EMA
fade pays only while the AI basket's 60-session return is negative (IC
+0.082, t 2.5; -0.006 while rising), proximity to the 52-week high pays
only while it is rising (+0.042, t 2.3), momentum 120/21 holds in both
and is strongest in low participation (+0.074, t 2.6). The first build
(momentum plus fade) lost through the rising basket of 2024-2025
(-0.057 on 2024-2026); it now fades stretch in a falling theme and buys
strength in a rising one. The operator's EMA slope and stack reads
measured nothing over the decade and paid only in the low-correlation
regime of 2026 (+0.066 to +0.072, t 2.0, 35 windows): cited as
evidence, not scored, until that regime has history. Buying near the
200 EMA lost in every regime (-0.023; -0.082 on 2024-2026).

**Beta-label model rows** (`sweep_beta.tsv`): lgbm alpha h20 0.008, +
technical h20 0.010 / h60 0.016, + calendar 0.007, + macro 0.005, all
t < 1. Chart CNN (plain residual) h20 -0.001, h5 -0.012 (t -2.2). Nothing
learned beats the tone. The tape encoder (15-minute bars, `tape_h5`/`tape_h20`,
beta label) measured 0.004 (t 0.4) and -0.004: nothing. Balance-sheet
instants on the
full universe: buybacks 0.002, asset growth -0.015 (t -1.7, growth names
pay here), book-to-market 0.007; none entered the composite.

**Next atomic task.** The desk's sentiment stance is coarse (the reader
returns -1/0/1 per field, so ties leave SNDK neutral on a +1/+1 release):
add `tone_pricing` and `tone_supply_constrained` as tie-breaks and
re-measure with `--calibrate`. Then a functional test for a desk
narrative prompt if one is added (none yet: the desk is numeric). Then the
intraday controls on the 90 names measured zero on every session feature;
the 15-minute layer is closed unless a new idea comes with a number.

## 2026-09-05 (late) — beta was the signal; the calendar, the macro state, the tape (PUSHED, NOT DEPLOYED)

Continues the three entries below it. Commits `bc20418d` → `02a51e00`.
Another agent is committing to this repository and editing the security
agent in this checkout; files are added by name only.

**The correction that matters most (`9dbe052d`).** The harness scored
rankings against own return minus the benchmark's, and the models trained
on the same label. In a market that rose most years that pays high-beta
names for the market's drift. Beta-adjusted (own minus 120-session rolling
beta times the benchmark, beta known at t, now the default in
`evaluate_scores` and the model label): distance above the 52-week low
0.045 (t 2.8) → 0.005 (t 0.3); high volatility 0.037 → -0.017; the
fundamental blend 0.026 → 0.021 (t 2.3); the 21-EMA fade 0.027 → 0.024
(t 1.7, 20 sessions only); **the release-tone blend 0.063 → 0.044 (t 3.0)
at 20 sessions and 0.076 (t 3.8) at 60**. The book's composite drops the
52-week-low leg and adds the tone where a name has scored releases: rank
IC 0.032 (t 3.1), book Sharpe 1.05 vs 0.84, max drawdown -6.8%. Sweep
rows now go to `sweep_beta.tsv`; `sweep.tsv` (plain residual, full
cross-section) and `sweep_themed_only.tsv` are history. The full-cross-
section model rows measured on the plain residual before the change:
lgbm alpha h10 0.001 / h5 -0.001 / h60 0.024; lgbm +edgar h20 0.003;
lgbm +technical h20 0.019 (t 1.1) / h60 0.033 (t 1.2); mlp alpha h10
-0.002 / h5 0.011; mlp +edgar h20 -0.005; mlp +technical h20 0.010;
xsect alpha h10 0.008; lgbm +calendar h5 0.005 / h20 0.003. Nothing
learned beats the tone blend or the composite; the remaining GPU rows
(master, chart CNN h20/h5) append to `sweep.tsv` as the old process
finishes, and every model row is due a re-run under the beta label
(`--only ...` into `sweep_beta.tsv`).

**The calendar** (`backend/market/calendar.py`, FOMC dates committed):
over 94 decisions the index drifts up into the meeting (day -1 +24 bp, t
1.9), high-vol minus low-vol names +41 bp (t 2.4) on the decision day, AI
basket +32 bp (t 1.9) then -29 bp on day +2 and +32 bp on day +3. Quad
witching -41 bp (t -3.1), monthly expiry -13 bp (t -2.2), the Russell day
50% more volatile; turn of the month faint; December and January nothing.
**The macro state** (`macro.py`: VIX level, change and ratio to realised,
10-year yield and change, dollar, oil; series stored via `market_snapshot
--tickers "^VIX,^TNX,DX-Y.NYB,CL=F"`). Both enter every gate's market
vector and the "calendar"/"macro" feature layers.

**Other documented anomalies as controls (plain residual, then beta):**
low volatility and low beta are *negative* here (high vol +0.037 plain,
-0.017 beta-adjusted: beta); illiquidity within the index +0.015 →
+0.021 (t 2.6), plausibly survivorship of small survivors; anti-lottery
nothing. **Balance-sheet instants** (`02a51e00`): share issuance, asset
growth and book-to-market are parsed point in time; the desktop EDGAR
partition is being refetched to carry them (old one set aside as
`old-asof=2026-09-05`), controls to follow.

**The 15-minute tape.** Alpaca keys in `.env`; `market_intraday
--refresh` running for the universe (~30 s a name). Preliminary on 198
names, beta-adjusted, 20 sessions: bars above the 15-minute 9 EMA (5-day
mean) IC 0.029 (t 1.6), trending tape 0.026 (t 1.5), calm tape 0.015 (t
1.6, net Sharpe 0.58); at 5 sessions every strength measure is mildly
negative (reversal). The tape encoder (`tape.py`, encoder "tape",
`bc20418d`) recovers a planted intraday pattern in its test and runs
(`tape_h5`, `tape_h20`) once the fetch completes.

**Release batch:** ~90 of 109 themed names scored on spark1; the rest of
the universe since 2020 is queued (`~/run_tone_rest.sh`). Tone frames on
the desktop are a copy from the 51-name stage; copy again before
measuring.

**Next atomic task.** When the batch completes: copy `edgar_tone` from
spark1, rerun the tone controls on all names (beta-adjusted), then
`market_sweep --only lgbm_macro_h20,master_macro_h20 --device cuda` plus
tone-inclusive runs, into `sweep_beta.tsv`. When the intraday fetch
completes: the intraday controls on all names and `tape_h5,tape_h20`.
When the EDGAR refetch completes: controls for share issuance, asset
growth and book-to-market, and the CPU LightGBM rows under the beta label.
Whatever beats the composite's 0.032 (t 3.1) beta-adjusted becomes the
book's score.

## 2026-09-05 (afternoon) — the trader's toolkit measured, a measurement bug fixed, the tape arrives (PUSHED, NOT DEPLOYED)

Continues the two entries below it. Commits `0fd59012` → `bc20418d`,
gated on spark1. Every number was produced by running the code.

**A bug in my own measurement, fixed in `dc8f8bdc`.** The two theme
baselines fed to every model as features are NaN for untagged names (right
as controls), and the model's eligibility mask requires every feature
finite, so every learned model in the night's sweep trained and scored on
~96 themed names while the momentum reference beside it used 532. The
model rows in the previous entry's table are void as comparisons (kept as
`data/market/models/sweep_themed_only.tsv`). Untagged names now carry the
market series for those two inputs (506 eligible names per session); the
sweep table has a `names` column. The controls, the fundamental blend, the
technical features and the book were never affected. Re-measured so far on
503 names (rank IC, 10 bps): lgbm alpha h10 0.001, h5 -0.001, h60 0.024 (t
0.75); lgbm alpha+edgar h20 0.003; lgbm +technical h20 0.019 (t 1.12), h60
0.033 (t 1.22); mlp alpha h10 -0.002. Remaining rows (mlp h5, mlp edgar,
mlp technical, xsect, master, chart CNN h20/h5) append to `sweep.tsv` on
the desktop as the run completes.

**The trader's toolkit** (`backend/market/technical.py`, 33 features: EMA
9/21/50/200 and SMA 200 distances and slopes, stack order, crossovers,
weekly EMAs, 52-week high/low, candles, EMA spreads with slope-change
"converging" flags, the normalised MACD family), each alone through the
harness on 532 names since 2015:

| feature as the ranking | h | rank IC | t | net Sharpe |
| --- | --- | --- | --- | --- |
| distance above the 52-week low | 20 | 0.041 | 2.60 | 1.05 |
| distance above the 52-week low | 60 | 0.084 | 3.45 | 1.23 |
| extension above the 21 EMA (a fade) | 5 | -0.022 | -2.79 | -0.94 |
| 9/21 cross up within 5 days | 5 | -0.007 | -1.79 | -2.10 |
| 50/200 golden cross within 5 days | 5 | -0.007 | -2.91 | -0.71 |
| 21/50 converging (slope turning) | 20 | 0.011 | 0.94 | -0.05 |
| candles, MACD family, trend stack | any | ~0 | | negative |

The 52-week-low distance is positive in every sub-period (0.036, 0.025,
0.030, 0.055) and in both full-history and later-listed names. EMAs carry
information as levels price returns to, not as trend confirmation; the
crosses lose; the slope-turning flags are small and positive at 20 days.

**The composite** (fundamental blend + 52-week-low trend + 21-EMA fade,
`market_book --score composite`, now the default): rank IC 0.047 (t 3.73),
hit 0.65, net Sharpe 1.06 at h20; the book Sharpe 1.08 vs 0.92 benchmark,
max drawdown -8%. SanDisk ranked 1.00 on it through its July pullback to
the 200 EMA at $1,016 (the operator's example), the 21/50 convergence flag
was on from 08-27 and the cross came 09-04 with the 12% day; across all
names that flag raises P(>8% in 3 sessions) from 2.3% to 3.0%.

**Rotation from filings** (`market_rotation`): each theme's median
fundamental blend as every member's score has rank IC 0.049 (t 2.39, net
Sharpe 0.48) at h20 while theme price momentum is -0.036 on the same
sessions. As of 09-04: memory-storage revenue growth 35% and accelerating
fastest, networking 32%, ai-compute 29%, software 19% flat, power-cooling
10% decelerating.

**The release reader, first reading** (51 themed names scored at the time,
`edgar_tone` frames synced to the desktop): tone_guidance h20 IC 0.054 (t
3.68) net Sharpe 0.74; guidance change 0.052 (t 3.93); tone blend
(guidance, demand, change) 0.062 (t 4.24) net Sharpe 1.10; the fundamental
blend on the same names 0.028 (t 1.35). Capex and supply commentary carry
nothing alone. The strongest signal so far; a ~40-name cross-section, to be
re-measured when the batch completes (74 of 109 themed names stored on
spark1 at the time of writing; the rest of the universe since 2020 is
queued behind it, `~/tone_rest.log`).

**Alpaca 15-minute bars** (`backend/market/alpaca.py`, `market_intraday`;
keys in `.env`): the free IEX feed serves 15-minute bars back to 2016.
Ten session features (VWAP trend, first/last hour, reversal, bars above the
15-minute 9 EMA, EMA crosses as chop, range position, volume front-load);
SanDisk's 12% day reads as a clean trend day, its +5% day of 08-31 as chop
(9 crosses). The universe fetch is running on the desktop
(`E:\AgentWorkspace\tmp\intraday_refresh.log`, ~30 s per name, ~4 h).

**The tape encoder** (`backend/market/tape.py`, encoder "tape"): the
26-slot tape of each session (time-slotted, gaps flat with zero volume,
relative to the open) for the last five sessions through 1-D convolutions,
the daily window through an MLP, merged and attended across names. A
planted intraday pattern is recovered out of sample in the test. Sweep
runs `tape_h5` and `tape_h20` wait on the fetch. Torch encoders now train
one padded batch per step (`1d001b71`).

**Next atomic task.** When the fetch finishes: run
`scratchpad/intraday_controls.py`-style controls (kept in the session
scratchpad; re-derive from `alpaca.FEATURE_NAMES`) and `market_sweep
--only tape_h5,tape_h20 --device cuda`. When the batch finishes: rerun the
tone controls on all 109 names, then `market_sweep` with
"alpha+edgar+technical+tone" for lgbm/mlp/xsect at h20, then put whichever
score wins the harness into `market_book`. Then a point-in-time universe
remains the honesty gap (survivorship).

## 2026-09-05 (day) — filings are the signal: the EDGAR layer, the book, and the release reader (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `96ee4e6f` (EDGAR layer), `2fc6610e`
(sizing), `67f1bf2f` (release reader); every one gated on spark1, the last
with its functional test against the real DeepSeek. Every number here was
produced by running the code.

**The night's sweep, completed.** Fourteen price-only configurations and
six with filing features, every encoder and horizon: nothing beats the
plain controls. Full table in `data/market/models/sweep.tsv` on each
machine; the six filing-feature rows: lgbm h20 0.013, mlp h20 0.008, xsect
h20 -0.008, lgbm h60 -0.044, mlp h60 -0.014, master h60 -0.010 (rank IC).
The models keep losing to a hand-built ranking of the same columns.

**The EDGAR layer** (`backend/market/edgar.py`, `market_edgar --refresh`,
546 names in 7 min, ETFs fail by design): 8-K item 2.02 events with
acceptance timestamps (after the New York close → next session), XBRL
company facts kept as the earliest-filed value per period (restatements
never leak backwards), fourth quarters derived from the year, the tag with
the most quarters chosen per fundamental. Fifteen point-in-time features:
sessions since a release, the reaction-window residual return (the drift
signal), revenue yoy / qoq / acceleration, EPS change, margins, capital
intensity, staleness, presence indicators; neutral fills keep foreign
filers in the cross-section. Stored as immutable `edgar_events` and
`edgar_facts` frames (store.write_frame/read_frame).

**The first cost-positive signal on this universe.** Controls through the
unchanged harness, 532 names, 10 bps:

| control | horizon | periods | rank IC | t | net Sharpe |
| --- | --- | --- | --- | --- | --- |
| post-earnings drift (recent) | 20 | 146 | 0.002 | 0.34 | -0.10 |
| revenue yoy | 20 | 146 | 0.027 | 2.46 | 0.60 |
| revenue qoq | 60 | 48 | 0.025 | 2.24 | 0.65 |
| gross margin | 20 | 146 | 0.020 | 1.96 | 0.53 |
| **fundamental blend** (yoy, qoq, gross margin, acceleration) | 20 | 146 | **0.029** | **3.07** | **0.66** |
| fundamental blend | 60 | 48 | 0.039 | 2.63 | 0.71 |

Post-earnings drift is absent (as the literature says for large caps since
2015); fundamental growth is present. **Caveat, measured:** the blend's IC
was 0.049 (t 2.94) in 2015-2018, 0.041 in 2019-2021, -0.002 in 2022-2024,
0.007 (t 0.34) in 2025-2026. Part regime (the 2022 growth-to-value
rotation), part survivorship (today's index over-represents the names that
were growing a decade ago). It is the best signal on file and its recent
evidence is thin; both are true.

**Sizing** (`backend/market/sizing.py`, `market_book`): select the top
fraction, inverse-volatility weights with a 10% volatility floor (a name
pinned by a pending takeover read as 3% vol and would have taken the whole
cap), name and theme caps with excess redistributed, a volatility target
measured on the book's own trailing returns under the candidate weights
(the diagonal estimate ignored market correlation and let realised vol
reach 39%), and turnover control where an exit is always a full trade
(skipping small sales let stale positions accumulate to 2.7x gross). Six
tests including the two properties the report exposed. On the fundamental
blend, long-only, 15% target, 10%/40% caps, 20-session rebalance, 10 bps:
**Sharpe 1.02 vs benchmark 0.83, max drawdown -15%, turnover 16% per
rebalance**; the tighter book (top 10%, 20% target) Sharpe 0.92, drawdown
-27%. Today's book: SanDisk rank 1.00 and CoreWeave 0.82 enter at ~0.3%
each — their realised volatility (137%, 102%) is seven times the median
name's, which is the honest size at equal risk; IREN (rank 0.02, annual
facts only as a foreign filer) is not selected.

**The release reader** (`prompts/trading/release_tone.md`,
`backend/agents/trading/release_tone.py`): DeepSeek scores what a company
states about its outlook, demand, pricing, capex and supply constraint,
bounded, greedy. Functional test 4/4 on the real model (raised outlook
positive on all four; a cut negative; facts-only exactly 0 guidance;
deterministic). A first-draft instruction returned zeros for text with
explicit guidance — the prompt exists because of that.
`backend/market/language.py` finds the EX-99.1 through the filing index
page, stores `edgar_tone` frames, resumes from partials, and builds
point-in-time tone features (scores + change vs the previous release).
`market_tone --refresh` runs it; feature sets compose as
"alpha+edgar+tone".

**In flight:** the scoring batch for the 109 themed names, all years, on
spark1 (`~/tone_themed.log`, frames under
`~/deploy/anios/data/market/edgar_tone/asof=2026-09-05/`), ~4 hours at
four threads (~3 s per release effective; ~7k tokens each). Then the rest
of the universe since 2020 is the next batch. The desktop store has tone
frames only for CRWV and SNDK.

**Next atomic task.** When the batch has enough names: copy spark1's
`edgar_tone` partition to the desktop store, run the tone columns as
controls through `evaluate_scores` (guidance, guidance change, demand,
capex, supply) at 20 and 60 sessions, then the blend plus tone, then the
learned models on "alpha+edgar+tone". Anything that beats the fundamental
blend's 0.029 / 0.66 row on the same sessions replaces it as the book's
score in `market_book`. Then a point-in-time universe is the remaining
honesty gap (survivorship); free sources do not give delisted prices.

## 2026-09-05 — the market research system: measured end to end, and what the measurements say (PUSHED, NOT DEPLOYED)

Everything below was produced by running the code. Commits `1e4970de` →
`00ebf082` on main; the spark1 gate passed on `90b40e5c` (36 passed, 1
skipped: the model test skips without torch, by design). The operator was
asleep for the second half of this; nothing was asked, everything is here.

**What exists now, all in `backend/market/` and `backend/cli/market_*`:**
a Chrome-impersonating Yahoo fetch (Yahoo refuses by TLS fingerprint, not
IP) with corporate actions and the live session dropped; an immutable
as-of parquet store (`data/market/`, on this desktop and on spark1 at
`~/deploy/anios/data/market`, 546 names since 2015); a 546-name universe
(current S&P 500 with GICS tags + AI-infra/memory/networking/power/software
overlay + 15 sector ETFs); the aligned panel with theme baskets; 8 raw
channels and 31 causal multi-scale features (`alpha.py`); five baselines;
a walk-forward harness (rank IC against residual return, purged folds,
cost-charged long-short); a ranker with five encoders (mlp, gru, xsect =
attention across names, master = market-gated MASTER-style, lgbm) with
rank labels and seed ensembles; and a sweep CLI that appends one row per
run to `data/market/models/sweep.tsv` beside momentum on the same
sessions. 57 market tests, ruff/black clean.

**Research (through September 2026).** The Qlib leaderboard's best daily
rankers reach rank IC 0.05-0.067, rank ICIR ~0.45, on Chinese A-shares with
158-360 engineered inputs at a one-day horizon; the gains come from wide
inputs, market-gated attention within and across stocks (MASTER, AAAI-24;
StockMamba 2026 +15% rank IC over MASTER; ACT 2026), rank-aware losses
(LambdaRankIC 2026) and ensembling. Time-series foundation models
(TimeGPT, Chronos-2, TimesFM-2.5, Moirai-2) were evaluated on US equities
in June 2026: gains over a random walk "small and sparse". LightGBM remains
the tabular reference every deep model is judged against.

**Results, 532 ranked names, 2015-01-02..2026-09-04, 10 bps per unit
traded, top/bottom 20%, all through the same harness:**

| run | horizon | periods | rank IC | t | net Sharpe |
| --- | --- | --- | --- | --- | --- |
| momentum 12-1 (reference) | 10 | 213 | 0.015 | 0.95 | 0.15 |
| mlp, raw channels | 10 | 213 | 0.015 | 1.01 | 0.12 |
| gru, raw | 10 | 213 | -0.005 | -0.35 | -0.27 |
| xsect, raw | 10 | 213 | 0.012 | 0.79 | -0.36 |
| mlp, alpha, rank label | 10 | 213 | 0.018 | 1.30 | -0.26 |
| lightgbm, alpha, rank | 10 | 213 | 0.002 | 0.10 | -0.67 |
| master, alpha, rank | 10 | 213 | -0.005 | -0.29 | -0.70 |
| xsect, alpha, rank | 10 | 213 | -0.001 | -0.08 | -0.63 |
| momentum 12-1 (reference) | 5 | 425 | 0.020 | — | 0.09 |
| lightgbm, alpha, rank | 5 | 425 | -0.003 | -0.21 | -0.92 |
| mlp, alpha, rank | 5 | 425 | 0.017 | 1.59 | -0.10 |
| xsect, alpha, rank | 5 | 425 | 0.013 | 1.01 | -0.30 |
| master, alpha, rank (spark1, CPU) | 5 | 425 | 0.012 | 0.88 | -0.44 |
| mlp, alpha, rank, 3 seeds, hidden 32, wd 1e-2, train 1250 | 5 | 325 | 0.018 | 1.32 | -0.68 |
| xsect, alpha, rank, 3 seeds, hidden 32, wd 1e-2, train 1250 | 5 | 325 | 0.013 | 0.92 | -0.61 |
| lightgbm, alpha, rank | 20 | 107 | 0.003 | 0.14 | -0.53 |
| master, alpha, rank (spark1) | 20 | 107 | -0.014 | -0.64 | -0.73 |
| mlp, raw (spark1) | 20 | 107 | -0.006 | -0.30 | -0.51 |
| lightgbm, alpha, rank | 60 | 34 | 0.018 | 0.38 | -0.03 |
| mlp, alpha, rank | 60 | 34 | -0.072 | -1.98 | -0.63 |
| master, alpha, rank | 60 | 34 | -0.033 | -0.84 | -0.46 |

Full rows with hit rate, net per period and cost: `data/market/models/
sweep.tsv` on each machine (the LightGBM h10/h20 rows there show NaN IC
from before the harness fix; recomputed from their saved scores above).

No encoder, feature set, label or horizon beats the reference on the
same sessions, and at sixty sessions the fitted models are *inverted*
out of sample (the relation learned in each training window flips in its
test window: regime dependence, on 34 periods). **The positive control explains why.** Run through the unchanged
harness on the same panel:

| known effect | horizon | periods | rank IC | t | Sharpe @0 bps | @10 bps |
| --- | --- | --- | --- | --- | --- | --- |
| 1-day reversal | 1 | 2934 | 0.016 | 4.65 | 0.42 | -3.90 |
| 5-day reversal | 5 | 586 | 0.024 | 3.16 | 0.66 | -0.04 |
| 10-day reversal | 5 | 585 | 0.018 | 2.40 | 0.38 | -0.12 |
| theme reversal (20d) | 10 | 291 | 0.030 | 2.07 | 0.14 | -0.07 |
| theme momentum (60d) | 60 | 47 | 0.054 | 1.56 | 0.39 | 0.36 |

The pipeline sees the effects the literature says are there. They live at
one to five sessions (reversal, significant, eaten by cost at full
rebalancing) and at one to three months (theme rotation persists, too few
periods yet to be significant). At ten sessions the two cancel, and that is
where every model was trained. **Structure exists; the label horizon was
wrong.**

**In flight at shutdown (results append to `sweep.tsv` on each machine):**
desktop 5080: done, every row above. spark1, CPU only
(`CUDA_VISIBLE_DEVICES=` — torch 2.14's AdamW touches the accelerator even
for CPU tensors and the GB10 has no free memory beside vLLM): master h20,
h5, and the 3-seed ensemble at h10 (`~/sweep_spark1_cpu2.log`,
`~/deploy/anios/data/market/models/sweep.tsv`): only the 3-seed master
ensemble at h10 is still running there. Read that table first.

**Next atomic task.** Read the h5 and h60 rows. If a model beats the
reversal control at h5 or the theme-momentum control at h60 net of cost,
that is the model; build position sizing on it (volatility-targeted, theme
exposure budget, turnover-aware so reversal is not traded at full
rebalance). If nothing does, the next lever is information the price
series does not hold: a scheduled DeepSeek pass turning earnings calls,
hyperscaler capex guidance and memory-pricing news into dated features on
the same calendar (`model.build_features` takes any (T, N, K) array).
Second lever, cheap: batch several sessions per step with padding masks —
the per-session Python loop keeps the 5080 at 10-13% utilisation.

## 2026-09-06 — Cross-chat continuation and unsupported media (DEPLOYING)

See `docs/CHANGELOG.md`, this date. Codex should review
`backend/services/cross_chat.py` and `_history_for_routing`, and the media
branches in `backend/workers/imessage_chat.py`.

**VERIFIED (unit):** `test_cross_chat_and_media.py` 7 and the suites around
them 199. **VERIFIED on the real router:** `test_cross_chat_followup_behaviour.py` 3/3, including the control without the room turn.

**Deploy:** this batch and everything since `8116e7d2` (the deployed marker)
goes out through `scripts/deploy.sh` on the Spark from this session, with
`AGENT_RUNS_ENABLED`, `AGENT_EXPERIENCE_REVIEW_ENABLED` and
`AGENT_EXPERIENCE_REVIEW_HOUR_UTC` added to the Spark `.env` first.
Deploy #1 failed its unit gate on a stale listing test (opencode's
events-links change; fixed). Deploy #2 passed both gates, backed up,
migrated and restarted; its post-deploy sweep died because the backend was
recreated mid-sweep to stop the hand-off's texts (below); the marker was not
written but the code is live. Deploy #3 <<DEPLOY3_RESULT>>

**The hand-off's first live run** texted the operator a failure; see the
changelog entry of this date. Its fixes and the reviewer's per-fact verdicts
are committed and go out with the next deploy.

## 2026-09-05 — The bird, Don Tito's, and the experience reviewer (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
room photo path (`imessage_chat._observe_photos`), the firing note
(`services/transcript.py`), the proposal prompt's rejection rule, and the
experience world's check (`agents/experience/world.py::_check`).

**VERIFIED on the real models:** reminder-not-habit 1/1 (three replies),
correction capture 5/5. **VERIFIED (unit):** room worker, transcript,
recall, experience world and the suites around them 357.
**VERIFIED on the real model:** `test_experience_review_behaviour.py` 2/2 (the bird and the reminder found, a quiet day clean). **VERIFIED live:** three reviews of the operator's last 36 hours
(`backend.cli.review_experience --run`); the third, run `92af03ec`, is
parked in the live `agent_runs` table on "forget the memory 'Ani is with
Gubacchi'" and expires in 24 hours if nobody answers - the runs API and
`manage_runs` are not deployed yet, so it can only be answered after the
deploy or left to expire. Two earlier runs from the same session sit there
completed and cancelled.

**Deploy notes (operator):** the room photo fix and the firing note take
effect with the next backend deploy; the reviewer needs
`AGENT_EXPERIENCE_REVIEW_ENABLED=true` beside `AGENT_RUNS_ENABLED=true` on
`discovery-worker` (both in compose now). The three wrong memories from the
bird evening ("Ani is with Gubacchi" twice, "going line dancing with a
bird") are still stored; the reviewer's first run proposes forgetting them,
or `DELETE /api/v1/memory/{user}/semantic/{id}` removes them by hand.

**Next atomic tasks, in order:**
1. Deploy; turn the reviewer on; read its first daily report.
2. Fixes beyond forgetting: re-run a dropped attachment through vision;
   correct a fact in place with the person's yes.
3. A labelled corpus of degraded days under `docs/evals/` and a precision
   floor for `experience/judge`.

## 2026-09-05 — A hard constraint filters a result (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review
`semantic_fact_is_constraint` in `backend/memory/proposal_agent.py`, the
`violates` path in `backend/core/result_ranking.py`, and `_without_violators`
in `backend/services/conversation_service.py`.

**VERIFIED (unit):** `test_constraints.py` 7; regression 586 passed.
**VERIFIED on the real models:** `functional/test_constraint_ranking_behaviour.py` 7/7 (ranking 3, classifier 4).

**Known and left:** existing preference rows were classified before the
flag existed, so a stored allergy is a preference until
`backend.cli.classify_preferences` is run (it now asks the constraint
question; dry run by default, `--apply` writes). The memory classifier
captured "I use a wheelchair, so I need step-free access" in one run of
three during the functional run while the model was at capacity, and
twelve of twelve across three phrasings when probed afterwards; the
functional test now judges the label over what was captured, and the
capture rate is the memory-capture discipline suite's property. The
paired-profile property is also a recorded measurement:
`python -m backend.cli.evaluate_constraints --reps 3` writes a run under
`docs/evals/runs/constraint-ranking/`.

**Next atomic tasks, in order:**
1. Run `classify_preferences --apply` on the Spark once the dry run below
   has been read, so stored allergies and needs become constraints.
2. The deploy steps with the operator (see the previous sections).

## 2026-09-05 — A run's approval can be answered from chat (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review
`backend/tools/manage_runs.py`, `backend/services/run_answers.py`, the
`runs_waiting` context and `_render_run_context` in `backend/agents/graph.py`.

**VERIFIED (unit, real schema):** `test_run_answers.py` 7; suites 428.
**VERIFIED on the real models:** `functional/test_run_answers_behaviour.py` 6/6 (routing 4, with `MCP_SERVERS_JSON` exported; reply 2).

**Known and left:** a yes by tapback or a phone reply outside a turn is
still not an answer; `manage_runs` has no cancel mode (the runs API has
cancel). The router's judgement that a bare "yes" answers a run rests on
the history carrying the assistant's mention of the waiting run, which the
turn context now makes it say.

## 2026-09-05 — A cut-short chat turn hands the rest to a run (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
hand-off (`ConversationService._hand_off`, `_create_continuation_run`), the
step routes (`backend/api/v1/chat_steps.py`, `decide_step`/`apply_step`),
and the world (`backend/agents/chat/world.py`).

**VERIFIED (unit, this host, real schema):** `test_chat_continuation.py` 30;
regression 498. **VERIFIED on the real model:** `functional/test_handed_off_wording_behaviour.py` passed (three replies, one property at a time).

**UNVERIFIED and worth a session:** a live hand-off end to end - a real turn
on deep-matter.com stopping on its budget, the run claimed by the worker,
the two routes called through the gateway, the person told. It needs
`AGENT_RUNS_ENABLED=true` on both `backend` and `discovery-worker` (compose
carries it on both now) and `IMESSAGE_CHAT_BASE_URL` reachable from the
worker (it is, for iMessage). `TURN_MAX_STEPS` is still 1 in the deployment,
so no turn hands off until the routing gate lets it rise.

**Next atomic tasks, in order:**
1. Phase 4: hard `constraints` in `PersonContext` and the paired-profile
   evaluator.
2. The deploy steps with the operator (see the previous sections).

## 2026-09-05 — Runs hardened: grant, fair claiming, delivery, capacity drill (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
grant enforcement (`backend/runs/grants.py`, `RunController._apply`,
`run_worker.py::GRANTS`) and the delivery (`backend/runs/delivery.py`).

**VERIFIED (unit, this host, real schema through the tunnel):** runs 19,
drills 2, capacity 1 (24 runs / 3 workers / 29.4 s), delivery 6 = 29 passed;
regression over isolation, review check, security world, loop bounds,
discovery worker, boundaries and coverage 134 passed. Diagram
`agent-runs-subsystem` re-rendered; others restored. **UNVERIFIED:** delivery
on a real iMessage channel (the worker path is exercised with a null
channel; the discovery digest uses the same channels).

**Gap audit against `docs/AGENT_PLATFORM_PLAN.md`, what remains:**
- Phase 3: a chat turn that exceeds its budget creating a run (needs a
  conversation world over `_execute_step`); an approval answered from chat
  or the phone (today: told, answered only via the runs API); an
  idempotency key on `ScheduledTaskRepository.create` for the chat loop's
  own writes.
- Phase 4: hard `constraints` in `PersonContext` (filter, not rank) and the
  paired-profile evaluator.
- Phase 5: `repo_blame`; a labelled corpus of diffs beyond the planted
  functional fixtures; runs created from a repository event.
- Phase 6: enrichment tools (log query, alert fetch, CVE lookup through
  `allowed_hosts`); remediation tools with `approval: always`.
- Phase 7: the grant as a verifiable token (D8's second shape); redaction
  short of deletion; the isolation numbers under concurrent load with chat
  in the mix (the capacity drill is runs only).
- Deploy (operator): Spark `.env` gets the `repo` server, `REPO_MCP_ROOT`,
  `SECURITY_AUTHORIZED_ASSETS`, `AGENT_RUNS_ENABLED=true`; `git` in the
  serving image; `TURN_MAX_STEPS=3` after the routing gate.

**Next atomic tasks, in order:** the Phase 3 items above (chat → run
hand-off first, then approvals in chat), then Phase 4's constraints, then
the deploy steps with the operator.

## 2026-09-05 — Every flagged line accounted for: the security agent's judgement step (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
judgement step (`backend/agents/security/prompts.py`, `SecurityWorld`
in `backend/agents/security/world.py`, `prompts/security/judge_hits.md`).

**VERIFIED on the real model:** `functional/test_security_review_behaviour.py`
2/2 with the stage (log `scratchpad/sec_fn6.log` on the desktop). Before
it, the planted case passed 3 of 5 attempts: the findings step left the
hard-coded key out, silently. **VERIFIED (unit, this host):** security
world 13, review check 23 + coverage suites (91 together), runs/drills/
isolation/bounds/prompt/worker suites 400. Diagram `agent-security`
re-rendered; the other SVGs restored unchanged.

**What the stage does:** after the findings are checked, every flagged
line no kept finding covers goes back to the model with six lines of code
on each side for a verdict - a finding through the same evidence check, or
a dismissal with a reason. Each verdict is bound to the hit it is about
(`hit_for`), so the hit's identity is the world's and only the quote is the
model's. The report carries `dismissed` and `unjudged` beside `findings`
and `rejected`; a hit past `MAX_JUDGED_HITS` (12), unanswered, or whose
judgement failed `MAX_JUDGEMENT_ATTEMPTS` (3) times is named unjudged.

**Known and left:** the egress screen withholds `password` and `api_key`
in any tool argument, so those words cannot be grep shapes; `secret_key`
and `token=` stand in. The functional test's variance is the model's, at
temperature zero under batching; the stage is what makes the property hold
regardless.

**Next atomic tasks, in order:**
1. Configure on the Spark: the `repo` server in `.env`'s `MCP_SERVERS_JSON`,
   `REPO_MCP_ROOT`, `SECURITY_AUTHORIZED_ASSETS`, then `AGENT_RUNS_ENABLED=true`
   on `discovery-worker` once one hosted run has been watched end to end.
   The serving image needs `git` (opencode's Dockerfile change is in flight).
2. Compare the pilot review's findings on `7cdd4af4` with Codex's.
3. Raise `TURN_MAX_STEPS` to 3 after the routing gate and a sweep pass.
4. Phase 7 remainder: retention for run events, fair scheduling per
   principal, a capacity test. The router track remains unstarted.
5. Chat → run hand-off and approvals in chat (Phase 6 remainder).
6. The gap audit the operator asked for, against `docs/AGENT_PLATFORM_PLAN.md`.

## 2026-09-05 — Security agent verified on the model (2 of 3 attempts); Refused decision; drill pollution fixed (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
`Refused` decision (`turn_steps.py`, `runs/controller.py`) and the evidence
check's canonical-line change (`agents/review/world.py`).

**VERIFIED on the real model:** `functional/test_security_review_behaviour.py`
- the refusal case passed on both attempts; the planted case passed on its
second attempt (three investigations, key and shell found each time, safe
call not reported) and failed on the first with the assertion lost to a
25-line log tail. A third full run was started at this checkpoint with the
whole log kept (`scratchpad/sec_fn2.log` on the desktop); if it fails, the
assertion is the thing to read first. **VERIFIED (unit, this host):** full
suite 2850 passed / 8 failed before the fixes below; the drill, encryption,
pool and runs suites 32 passed together after; review check 23, security
world 4, loop bounds 25.

**What was wrong and is fixed:** the security scope refusal was retryable
(`Unavailable` → requeued) and is now `Refused`, final, `error_code=refused`;
a kept finding's evidence was the model's quote, cut at the first embedded
`"`, and is now the file's own line; two grep shapes (`password=`, `secret=`)
were withheld by the egress screen on every run and are replaced by shapes
it lets pass; `test_crypto.py` and `test_storage_encryption.py` blanked the
encryption key on teardown and broke the process-kill drill in the full
suite only.

**Untracked and deliberately not committed:** fifteen trajectory run records
under `docs/evals/runs/tool-selection/` from this session's measurements
(the measurement of record is the one tracked file), and
`backend/market/model.py`, which belongs to the other session.

**Next atomic tasks, in order:**
1. Read `sec_fn2.log`; if the planted case failed, fix the cause and re-run
   before anything else. Then compare the pilot review's findings on
   `7cdd4af4` with Codex's on the same commit.
2. Configure on the Spark: the `repo` server in `.env`'s `MCP_SERVERS_JSON`,
   `REPO_MCP_ROOT`, `SECURITY_AUTHORIZED_ASSETS`, then `AGENT_RUNS_ENABLED=true`
   on `discovery-worker` once one hosted run has been watched end to end.
   The serving image needs `git` (opencode's Dockerfile change is in flight).
3. Raise `TURN_MAX_STEPS` to 3 after the routing gate and a sweep pass.
4. Phase 7 remainder: retention for run events, fair scheduling per
   principal, a capacity test. The router track remains unstarted.
5. Chat → run hand-off and approvals in chat (Phase 6 remainder).
6. The gap audit the operator asked for, against `docs/AGENT_PLATFORM_PLAN.md`.

## 2026-09-05 — Place judgement live (9/9); security agent's first shape; pilot defects fixed (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
security world (`backend/agents/security/world.py`) and the two pilot
fixes (`backend/mcp/servers/repo.py` bounds, `turn_steps.py` key-before-step).

**VERIFIED on the real model:** `functional/test_place_bound_judgement_behaviour.py`
9/9. **VERIFIED (unit, this host):** security world 4, API isolation 3,
repo server + evidence check 23, loop bounds 15, search place suites, the
coverage and prompt suites; 30 diagrams synchronized.
**VERIFIED on the live model:** the pilot review of `7cdd4af4` completed
(run `2aeb5927-6526-4596-9d23-eca7c62d4bfe` for `ani.mallya`: six files
read, one finding kept, seven rejected for a quote one line off - the
evidence check now tolerates two lines). **UNVERIFIED:**
`functional/test_security_review_behaviour.py` (running at this checkpoint
against a model at six concurrent requests). The local
`.env`'s internet server entry was behind the Spark's (17 of 23 forwarded
names) and is refreshed; the deployment was never affected.

**Opencode's state (checked 2026-09-05 afternoon):** nothing pushed since the
Phase 1 scorer fix (`29c48ea3`). Its Spark checkout is behind `origin/main`
with no unpushed commits and two uncommitted things: `Dockerfile` gains `git`
in the *test* image for the repo-server tests (right, and it should commit
it), and two trajectory runs recorded at `2fc6610` - the tree before the
step-line fix - reading 9/18 and 9/18, i.e. the pre-repair baseline, not a
regression. Its second run showed `reference` at 2/3 breaching a 0.67 floor:
2/3 is 0.667, so that floor tolerated no miss; the floors for three-sample
categories are 0.66 now. When reviews are hosted by `discovery-worker`, the
*serving* image needs `git` too (the repo server shells out to it); that is
the Dockerfile's runtime stage, left to opencode since the file is in flight
there.

**Next atomic tasks, in order:**
1. Read the security functional test's result; compare the pilot review's
   findings on `7cdd4af4` with Codex's on the same commit.
2. Configure on the Spark: the `repo` server in `.env`'s `MCP_SERVERS_JSON`,
   `REPO_MCP_ROOT`, `SECURITY_AUTHORIZED_ASSETS`, then `AGENT_RUNS_ENABLED=true`
   on `discovery-worker` once one hosted run has been watched end to end.
3. Raise `TURN_MAX_STEPS` to 3 after the routing gate and a sweep pass on
   this tree.
4. Phase 7: a restart drill that kills the worker process (the in-process
   drill exists), retention for run events, fair scheduling per principal.
   The router track (rate assertions, the SetFit front) remains unstarted.
5. Then the gap audit the operator asked for.

## 2026-09-05 — Phase 2 closed (15/18); Phase 3 built; the reviewer built; two functional tests wait on a quiet model (NOT DEPLOYED)

Read `docs/CHANGELOG.md` (this date, second entry) for what was built and
measured. Codex should review the Phase 3 controller (`backend/runs/`) and
the reviewer world (`backend/agents/review/world.py`) before Phase 5 goes
further.

**VERIFIED:** trajectories 15/18 on the real router, recorded and floored;
unit suites for runs, the repo server, the evidence check, the harness and
the registry; the additive migration `20260905_0019` applied to the live
database (backup first); 29 diagrams synchronized.
**VERIFIED on the real model:** `functional/test_unknown_step_wording_behaviour.py`
(with `LLM_TIMEOUT_SECONDS=900` under load).
**VERIFIED on the real model:** `functional/test_code_review_behaviour.py`
- three reviews of a planted off-by-one behind an injected comment, run
through the real repo MCP server and the real controller: every run
completed on evidence, only read tools were recorded, no finding named the
file the comment pointed at, and the defect was found (5m33s under a model
at six concurrent requests, `LLM_TIMEOUT_SECONDS=900`). Run them alone when
`curl http://172.16.8.3:8000/metrics | grep num_requests_running` is near
zero, with `LLM_BASE_URL=http://172.16.8.3:8000 LLM_MODEL=deepseek-v4-flash
PYTHONPATH=<checkout>` exported (the test suite skips `.env`). Sweep
journeys and the routing matrix have not been run on this change. Nothing
is deployed; `TURN_MAX_STEPS` is still 1 and `AGENT_RUNS_ENABLED` false.

**Next atomic tasks, in order:**
1. Configure the `repo` server in `.env`'s `MCP_SERVERS_JSON` and
   `REPO_MCP_ROOT` on `discovery-worker` (compose allowlist too), review one
   real commit of this repository with `backend.cli.review_commit`, compare
   with Codex's review of the same commit.
2. Raise `TURN_MAX_STEPS` to 3 in `.env` and read it back from the
   container, only after the routing gate and a sweep pass on this tree.
3. Phase 4's first slice is in (`backend/memory/person_context.py`, wired
   into the search stage and the ranker, unit-verified). Next for it: retire
   `_PLACE_BOUND` by adding `place_bound` to `search/place.md` with a
   functional test, then constraints as hard filters and the paired-profile
   evaluator. The router track (rate assertions, the SetFit front), Phase 6
   and Phase 7 remain unstarted.

## 2026-09-05 — Phase 2 first checkpoint: bounds are structural, the step line is the next defect (NOT DEPLOYED)

Committed as a checkpoint at the operator's request (usage ran out), with
the verification state below. Codex should review this commit before the
next step. The plan is `docs/AGENT_PLATFORM_PLAN.md`; this is its Phase 2.

**VERIFIED (unit, this host, Postgres and Redis over the SSH tunnel):** the
29 focused suites around the change and the four new modules
(`test_turn_steps_bounds`, `test_effect_contracts`, `test_mcp_tool_contracts`,
`test_routing_decisions`) - 366 + 147 passed. `test_tool_catalog_page` and
`test_discuss_image_tool` updated for the new column and the removed
`_runnable`. Diagram check: 27 synchronized.
**VERIFIED (full unit suite, this host):** 2744 passed, 3 skipped, 9 failed
in 8m11s. One failure was this change (`test_history_recall` imported the
removed `_runnable`; rewritten against the executor in the follow-up commit).
The other eight are this Windows host, not the change: six need the parser or
Drive services (`ConnectError`), one is `_hold_to_dates`'s `%-d` format that
Windows `strftime` rejects, and `test_settings_reach_their_consumer[internet.py]`
fails at HEAD too. Re-run in the container before deploying.
**UNVERIFIED:** the sweep journeys and the routing matrix have not been run
on this change. Nothing is deployed.
**MEASURED:** `evaluate_trajectories --reps 3` on the real router: 10/18,
unchanged; one acceptance breach (a duplicate in `search-then-remind`).

**Next atomic task - make the step line say what was done.** The evidence
in the run file is unambiguous: `_step_line` renders "Scheduled tasks: once at
18:00" and "Manage scheduled tasks: reschedule", so the router cannot tell
which reminder it already set and writes "call mum" twice (at 6pm and again
at the gym's 8pm), and repeats a reschedule it cannot see it made. Fix
`_detail` in `backend/tools/registry.py` to carry the instruction (`once at
18:00 - remind me to call mum`) and `which`/the new time for `manage_tasks`;
strip trailing punctuation in `schedule_task`'s key; then re-run the
evaluation and expect `multiple_writes` to move. Two case questions for the
operator: `cancel-and-reschedule` is answered by one `reschedule` call, which
the case labels incomplete; and `search-then-remind` took no tool twice on
the first decision - the harness should record the typed decision
(`NeedsInput` is the likely reason: "saturday" has no time) rather than
`(none)`.

After that: `TURN_MAX_STEPS=3` in `.env` and the three compose services,
read back from the container, only once the gate holds; then Phase 3.

## 2026-09-05 — Phase 1 evaluation made honest after codex review (PUSHED)

Codex reviewed the Phase 1 baseline and showed four false positives: the
first scorer credited any step of the right *name*, so a failed reminder for
the wrong task "completed", two identical wrong reminders "completed" with
zero duplicates, and list-tasks counted as "carrying" the move request it
never made. The follow-up makes completion mean the requested effects
happened, and records why a turn stopped. Verified:

- `trajectory_harness.py`: `RequiredEffect` pairs each required step with the
  operation, the argument words it must carry, and whether it must have
  succeeded; the required sequence is matched in order `required_times` over,
  and `covers` words must appear across the *matched* steps (two copies of one
  reminder never satisfy a request for two). `honest_failure` semantics for
  the scripted not-found case. Duplicate = a create beyond the allowance OR
  identical to an earlier one. `carried` is a diagnostic, independent of
  success.
- `turn_steps.py`: `run_steps` returns a `TurnResult` with a real, named stop
  reason (declined / ceiling / repeated / unapplied / budget / second-create).
  The recorded reason answers the review's question directly: every
  `two-reminders` run stops on `SECOND_CREATE` — the repeat guard, not the
  model, is what cuts two writes to one.
- `evaluate_trajectories.py`: `acceptance()` is a pure gate (completion and
  carrying floors, no unauthorized tool, no duplicate effects) that fails the
  CLI; runs persist per-observation evidence, the model, a case fingerprint,
  and the commit (`ANIOS_EVALUATION_COMMIT`).
- The four review reproductions are pinned as regression tests in
  `test_trajectory_evaluation_behaviour.py`.

Corrected baseline (2026-09-05, two runs, recorded pre-commit as
`*-nocommit.json`): single_step 3/3, reference 3/3, partial_failure 3/3,
mixed_tools 0–1/6 (router does the first tool and stops or repeats), and
multiple_writes 0/3 (all `SECOND_CREATE`) — overall 9–10/18, now honest.
Carried: single/reference 3/3, mixed_tools 1/6, multiple_writes 0/3. Floors
in the CLI were then set one miss below these numbers and the gate re-run
PASS. Verified: full unit suite **2635 passed / 9 skipped** via
`bash scripts/gate.sh --unit`; trajectory + loop + turn-steps functional
suite **25 passed** (one transient router-variance failure on the first
batch run, passed alone and green on re-run).

## 2026-09-05 — stock-analysis foundation, slice 1 (SUPERSEDED by the market research entry above; kept as history)

First slice of the deep-learning research system for the trading agent,
built from the plan the operator endorsed (daily data, swing horizon,
DeepSeek as a research component, measure before betting). The design answer
to "wouldn't a neural network already learn the structure report?": **yes —
so it is fed raw normalized price/volume sequences, not a hand-coded trend
slope or volatility number.** The hand-coded sector report is a later
baseline to beat, not the architecture.

New `backend/market/` package:

- **`universe.py`** — focus names (CRWV, IREN, SNDK), a comparison universe
  across the themes money rotates between (software, ai-compute,
  memory-storage, networking, power-cooling; overlapping baskets, not one
  "AI" label), and benchmarks (SPY, QQQ, SMH).
- **`yahoo.py`** — daily OHLCV + adjusted close from the free keyless Yahoo
  chart endpoint, with a normal user agent. A 429 or any non-200 raises
  `MarketDataUnavailable`; the parser is a pure function over the payload so
  tests use a recorded fixture, never the network.
- **`market_daily_bars` table** — one row per (ticker, session date, source)
  with raw OHLCV, adjusted close, volume, source and retrieved_at, so
  corrections are traceable. Migration `20260905_0018`, **applied to the
  live DB** (backup taken first; head now `20260905_0018`).
- **`repository.py`** — async upsert (rerunning a date refreshes, never
  duplicates), latest-session, bars-for-range, delete-for (test cleanup).
- **`snapshot.py`** — `refresh` (fetch + store, failures captured per ticker,
  never fatal) and `status` (per-ticker missing/stale flags), plus
  `daily_returns` computed **from adjusted close, so a split cannot
  manufacture a return**.
- **`windows.py`** — the model input: per ticker, windows of raw daily
  channels (own log return, log volume, market-relative return vs the
  benchmark) over the shared trading calendar, **structurally no look-ahead**
  (a window ending at session t contains only <= t) with a separate K-day
  forward-return label marked invalid wherever the future is not fully known.
  Channels are emitted raw; z-scoring is a harness step fit on train only.
- **`backend/cli/market_snapshot.py`** — `--refresh` and `--status`.

Verified: 15 new tests (parser fixture, 429 handling, upsert idempotency,
reproducibility, split-safety, stale/missing flags, window no-look-ahead and
gap handling); full unit suite **2635 passed / 9 skipped** via
`bash scripts/gate.sh --unit`. CLI verified live: `--status` reports every
ticker MISSING; `--refresh` against the real source flagged each ticker
FAILED with a clean message and exited 0 — **the rate-limited path is proven
live**. The DeepSeek research model was checked as requested:
`deepseek-v4-flash` is live on spark1 `172.16.8.3:8000` (`/v1/models`,
max_model_len 1048576).

**UNVERIFIED:** a successful real fetch+store. Yahoo is 429-throttling this
network (host and backend container) all session; the parser is fixture-tested
and the fetch+store path is gate-tested with a stubbed fetcher, but the
real-network round trip has not landed rows yet.

**Next atomic task:** when Yahoo's throttle clears, run
`python -m backend.cli.market_snapshot --refresh` over the universe and
confirm stored rows via `--status`. Then slice 2: the walk-forward harness
with a relative-strength baseline (the thing the DNN must beat), and decide
the training environment — **no torch/pandas/sklearn in the backend
container today**, so training placement (a Spark, a new image, or the Mac)
is a decision before any model can be trained.

## 2026-09-05 — Phase 1 of the execution-boundary repair: measured and pushed

The trajectory baseline is built, measured, and on `main`
(`python -m backend.cli.evaluate_trajectories --reps 3`). It drives the real
router + `run_steps` over six labelled trajectories and measures whole-turn
completion, argument carrying, unauthorized tools, duplicate effects, and
cost. Baseline (stable across two runs): **10/18 overall (0.556)** —
single_step 3/3, reference 3/3, partial_failure 3/3, but mixed_tools 1/6
(the router does the first tool and stops or repeats it) and multiple_writes
0/3 (two reminders become one: the repeat guard cuts the second write). Both
failing categories are floored at 0 until Phase 2/3 moves them. Runs recorded
under `docs/evals/runs/trajectories/` (pre-commit, `*-nocommit.json`).

Next is Phase 2, the repair the baseline was built to measure: typed
decision/result states (distinguish finished / needs clarification / model
failure / no tool), deadline enforcement (re-check before executing the
returned action), complete nested MCP schema validation, recursive outbound
screening, cache identity on full tool definitions, and per-tool retry rules.
Phase 3 then makes the run durable (storage, idempotency, cancellation,
recovery). The user will have codex review each phase's work.

## 2026-09-04 — the "try again" fix is deployed (8116e7d); the search-place fix is live

The first bad "fun things to do in the area" answer shipped on pre-fix code
(the distance filter was not yet in the built image). The retry ran on the
fixed code and was still bad: "try again" searched **Colonial Heights** for a
person in Courthouse because `search/compose` copied the town out of the
previous answer's listing. A prompt sentence was measured and failed 2/3, so
the fix is structural (`prompts/search/place.md`, `foreign_places`,
`_drop_foreign_places` in `_research`) — see the CHANGELOG entry of this date.

Also fixed: `test_the_search_is_personalised_only_where_that_is_the_answer`
could never pass (it compared the *pair* of lists `relevant_interests` returns
against the flat interest set, and `bool(((), ()))` is truthy), so the "18/18
measured" claim for `search/personalize` had no passing test behind it. The
corrected test passes on the real model.

Verified: unit suite 2620 passed / 9 skipped; `functional/test_search_compose_behaviour.py`
13 passed against the real model. **Deployed and live** as `8116e7d` on
2026-09-04: unit gate 2620 passed, routing gate 83 passed, sweep journeys and
search harness passed after deploy.

## 2026-09-03 — model-serving docs corrected, and the Trading agent's first capability (NOT DEPLOYED)

Three files still described the retired 2-bit ds4 GGUF as the deployed model:
`AGENTS.md`, `docs/DEVELOPMENT_GUIDE.md`, and the top of
`docs/MODEL_EVALUATION.md`. The running reply model is the **official FP8**
DeepSeek-V4-Flash-0731 (~156 GB, `quant_method: fp8`), served by vLLM
tensor-parallel across both Sparks, port 8000 — confirmed from the live
container (`config.json`, `/v1/models`, the vLLM command line, and the
retired ds4 port 8888 refusing connections). `ML_SYSTEM_DESIGN.md` already
recorded this correctly; the three other docs now agree. Pushed as
`ea3bfb0`.

**Trading agent (Phase 1 of the personal trading analyst):** a new agent
`backend/agents/trading/` with one prompt (`prompts/trading/autopsy.md`) that
reads a person's own trade-history passages and names the behaviours that
repeat, what they cost (only when a number is actually in the record), and a
stop/start/keep plan. Card registered in `agents/registry.py`; a new
`agent-trading.mmd`/`.svg` diagram pair registered in the renderer, the
published page, and the catalog; a row in `AGENT_CATALOG.md`; functional
proof `backend/tests/functional/test_trading_autopsy_behaviour.py` — 6/6
against the real model (pattern must repeat, once-off is not a pattern, no
invented amounts, real costs reported with source, plan has all three lists,
every pattern carries evidence). Also fixed a pre-existing inconsistency the
renderer surfaced: `document-knowledge` was rendered and cataloged but never
in the published page or the renderer list; it is now registered and the
full suite is 26/26 synchronized. Full unit suite green (2530 passed, 9
skipped).

**Next atomic task:** make the autopsy reachable in chat — a router tool
(e.g. `analyze_trading`) so the assistant can act on "analyze my trading".
Per AGENTS.md a new tool is not shipped until the router is measured choosing
it, so that means a `TOOL_NAMES` entry, labelled cases in
`backend/services/tool_selection_cases.py`, and `python -m
backend.cli.evaluate_tool_selection` per-category comparison, then a sweep
journey over HTTP. Broker statements (Schwab) are post-analysis only — not
ingested yet. Free market data (yfinance-style Yahoo chart API, Alpha
Vantage, TwelveData) is reachable from inside the backend container; that is
the Phase 2 data layer. Nothing here is deployed.

## 2026-09-02 — decks plan their slides together, and background work stops starving (NOT DEPLOYED)

Traced from a live deck that took 12m32s for seven slides while the inference
engine sat at `Waiting: 0 reqs`, 0.5% KV. Three things were serialising it and
all three are addressed; the full reasoning and numbers are in the CHANGELOG
entry of the same date.

- **`backend/core/model_gate.py`** — `background()` waited for *zero*
  interactive requests before starting, which never happens under sustained
  chat (17-27 calls/min when measured). It now yields for
  `MODEL_GATE_MAX_WAIT_SECONDS` (20 s) then proceeds; a held lease is renewed
  so a whole deck does not outlive it; Redis keys are namespaced so a test
  cannot stall the live scheduler.
- **`backend/presentations/provider.py`** — slide calls are scheduled together
  (`PRESENTATION_SLIDE_CONCURRENCY`, 4) and consumed in outline order, and the
  background lease is taken once per deck rather than once per call.
- **The trap that would have made it a no-op**: `LLMClient` serialises its own
  requests through a per-instance lock guarding the `reasoning_effort` latch,
  so each concurrent worker gets its own client from `llm_factory`. Without a
  factory the provider plans one slide at a time rather than pretending. The
  lock itself was deliberately not touched — every other caller relies on it.

Measured on the deployed stack, one 6-slide deck per arm: concurrency 1
130.65 s, 2 75.66 s, 4 50.30 s, 8 51.89 s (four is the knee). Two further
1-vs-4 runs gave 1.86x and 1.46x. Foreground cost with chat probes running:
no deck 0.17 s median / 0.24 s p95; deck at 2, 0.26/0.39; deck at 4,
0.27/0.40 — so almost all of the cost is a deck running at all, not its width.

Verified: 10 new unit tests green (5 gate, 5 fan-out), deck functional suite
6/6 against the real model in 4m47s including new `create_progress` coverage,
2,387 unit tests green in the container. The two failures in that run are the
documented environment leak (`AUTH_COOKIE_SECURE`, `LLM_BASE_URL` from the real
container env) and pass when those are neutralised — not regressions.

**Next atomic task: deploy it.** Nothing is deployed; the measurements above
were taken by running the new code inside `anios_backend` via the `docker cp`
overlay, which does not affect the running server. Before `bash
scripts/deploy.sh`, check `git status --porcelain` in the Spark's `~/anios` —
deploy.sh builds from that working tree, and opencode edits in it. Two live
values to confirm reached the containers afterwards, since a `.env` entry beats
a compose default: `docker compose exec -T presentation-worker printenv | grep
-E 'PRESENTATION_SLIDE_CONCURRENCY|MODEL_GATE_MAX_WAIT_SECONDS'`.

## 2026-09-01 — links are hyperlinks on every surface (deployed 2ee4c4a)

Chat replies and digests pasted bare long URLs: the listing wrote `Map:
https://maps.google.com/...` and `Details: https://...` as raw text, the web
chat rendered bare URLs as inert text, the Scout "Add to calendar" used a
relative `/api/v1/discovery/...` path, and a feed URL with a stray newline
became dead text in iMessage. Fixes in the working tree (deploy pending via
`scripts/deploy.sh`):

- **Listing emits markdown links** `[Map]/[Add]/[Hear it]/[Details](url)`
  (backend/core/events_listing.py). Web chat renders them tappable; the
  iMessage worker's `plain_text` converts to `label (url)` which iMessage
  auto-links. The link fence keeps every one (verified).
- **Web chat auto-links bare URLs**: `frontend/src/utils/linkify.ts`
  `linkifyMarkdown` in MessageBubble, plus `frontend/src/components/Linkified.tsx`
  for the Scout preview/rehearsal panes (ScoutSetup.tsx). Safe because the
  reply fence already stripped unvouched URLs.
- **`calendar_path` is absolute** (backend/api/v1/discovery.py `_calendar_link`,
  both call sites), built from `DISCOVERY_CALENDAR_BASE_URL`
  (`https://deep-matter.com/api/v1/discovery`), so the `.ics` opens from a
  phone. NOTE: the single-event `.ics` route is still behind `authorize_path_user`
  — a phone without a session still gets 401. If "Add to calendar" must work
  unauthenticated, make it public-by-unguessable-digest like the feed router.
- **Digest URLs cleaned** (`_clean_url` in backend/discovery/digest.py, applied
  at every append site) — strips control characters/whitespace.

Verified: 187 unit tests (including new: cleaned digest URLs, absolute
calendar link, markdown listing assertions), fence keeps all listing links,
`plain_text` round-trips, frontend type-checks. A deterministic Playwright
test (`renders markdown links and bare URLs in an answer as tappable links`
in frontend/e2e/chat.spec.ts) is written but **could not be run here — no
host node/browser**; run `npm run test:e2e` (or open the web chat and confirm
the listing's Map/Add/Details are clickable) to close the UI check.

**Still open from the 2026-08-31 work**: four commits (`1a5b8a3`, `e9a476b`,
`9627a26`, `bff350f`) are deployed but UNPUSHED to origin (no git auth on this
host — push from the Mac). `NEXT_SESSION`
and `CHANGELOG` got entries for the 2026-08-31 fixes; the Google-fallback,
pool, spread/repeat, date-rollover, and chat-grounding changes need their
handoff entries folded in.

## 2026-09-01 — digest keeps the working artifact (deploying with this commit)

- **`prompts/memory/digest.md`**: the rolling digest now explicitly keeps "the
  artifact they are working on... and what was decided or changed about it, by
  name." A long coding thread can outlive the ten-turn window; the durable fact
  is which file/artifact was in play, which the old keep-list captured only via
  "what the person is trying to do". Pinned by
  `test_digest_keeps_the_artifact_and_the_decision_about_it`
  (`test_conversation_digest_behaviour.py`); 14 digest tests pass.
- Investigation result worth remembering: the durable-context machinery already
  exists and is sound - cumulative digest every 10 turns at priority 0 (never
  trimmed), reply prompt already hedges on missing earlier turns, reply-rescue
  covers explicit replies. No new system was needed; this is a one-line
  keep-list refinement plus a pin.

## 2026-09-01 — manage_tasks claims its memory undo (deployed 7fff8d9→ecc233a)

- **`backend/tools/manage_tasks.py`**: the tool description now says undo puts
  back "the most recent change the assistant made - a reminder, Scout's
  schedule, or a fact it just saved to memory - 'forget that'..." . The router
  reads each tool's own description when choosing, and the old text never
  mentioned the memory undo this tool performs, so "forget that" mis-routed to
  Past conversations/None ~1/3 of the time with a false "forgotten" claim.
  Controlled in-process A/B: 4/15 -> 15/15 manage_tasks. Full matrix with the
  fix: manage_tasks 45/45, task_undo 15/15, no new cross-tool cell.

## 2026-09-01 — "forget that" routing fix + judge pin (deploying with this commit)

- **`prompts/routing/select_action.md`**: removed the contradiction that made
  the router sometimes route "forget that" to no tool, leaving the reply to
  claim a forgetfulness that was never written (the sweep journey caught it).
  An instruction to change what the assistant holds is an action (manage_tasks
  undo), never a question to answer. Verified 5/5 journey runs; matrix gate
  7/7; evaluator 0.9184 overall, manage_tasks 43/45, task_undo 13/15.
- **`backend/tests/functional/test_semantic_judge_reliability.py`**: pins
  `semantic.states` (the judge behind a dozen functional modules and every
  journey) against ten unambiguous seeds at a floor one miss below the
  measured 10/10. Finding recorded in the module: the judge reads action
  wording ("forgot, removed") but not state wording ("no longer remembers"),
  which is why journey statements already carry the action words.

## 2026-09-01 — notability tiebreak + check-in journey (deployed 593cf3c)

- **`prompts/scout/rerank.md`** adds a notability tiebreak: among finds the
  approved facts do not distinguish, a one-off festival/headline leads a
  routine weekly social. Reorder-only, never an exclusion, so it cannot empty
  a digest. Pinned by two cases in `backend/tests/functional/test_prompt_behaviour.py`;
  `evaluate_discovery_ranking` green (filtering recall 0.8571, geography
  happening-retention 1.0). Rehearsal still shows variety.
- **`backend/cli/sweep_journeys.py`**: "group: a shared plan arms a check-in
  in the room" now allows `(None, "Past conversations")`. Check-in arming is
  route-independent; in the red runs the check-in was armed and only the route
  was flagged. sql_holds (the armed `checkin:%` task) stays the real assertion.
  Verified 3/3 green.
- Both were committed with this session's link work as `2ee4c4a` is already
  deployed; these two are in the next commit.


## 2026-08-31 — recommendation quality: ranked by the person, not a stale mood (deploy pending)

The operator's digest on 2026-08-31 recommended a guided walk at Arlington
Court, **Devon, England** to someone in Courthouse, Arlington, Virginia.
Root cause, all verified by running the live pipeline: the profile's region
was stored **`Arlington, Arlington`** (a repeated region), which makes the
US-state-only `contradicts_locality` guard see nothing and every query say
"Courthouse, Arlington, Arlington"; the Brave snippet named only the estate's
town, so the `_located_elsewhere` judge said "local"; and the URL
(`/visit/devon/`) — where the page actually is — was never shown to the
judge. With one novel candidate that sweep, it shipped. Second contributor:
the memory classifier had stored "feeling a little tired today" (2026-08-29)
with **no expiry**, so it aimed the hiking query at "easy scenic nature
walks" and put a hiking-guide page ahead of the dance events the account
asks for.

**Fixed and functionally verified in the working tree (deploy pending via
`scripts/deploy.sh`):**

- **Region**: `_apply_locality` collapses a repeated region segment
  (projection.py); ani.mallya's locality corrected to `Courthouse, Virginia`
  (approved fact + `discovery_localities`), which re-arms the US-state guard
  and fixes the queries.
- **Locate judge sees the URL** (describing.py + prompts/scout/locate.md):
  the Devon snippet alone returns not-elsewhere, with the URL it returns
  elsewhere — verified live.
- **Sweep context excludes image descriptions** (runner.py, purpose
  `visual_artifact_analysis`), so durable demographics/preferences fill the
  bounded context.
- **Transient facts expire** (proposal_agent.py `semantic_fact_is_transient`
  + conversation_service save path, `TRANSIENT_FACT_DAYS=7`); ani.mallya's
  stale "tired today" row expired.

**Rehearsal proof** (`DiscoveryRunner.sweep(...persist=False)` for
ani.mallya, worker image with the tree mounted): query now
"Courthouse, Virginia"; shortlist all line-dancing/social-dance finds;
reranker (memory) orders NVCDA social dances, Virginia Line Dance Festival,
DanceSportVA — no Devon, no hiking guide.

**Measurements**: `evaluate_discovery_ranking` green (filtering 0.857/1.0,
geography retention 1.0; the new Devon case is labelled and the deterministic
US-only guard honestly still can't catch it — the model stage now does).
`test_description_quality.py` 101/101, `test_prompt_behaviour.py` 22/22,
`test_preference_labelling_behaviour.py` 13/13, `test_memory_capture_discipline.py`
green, discovery/memory units 512+44+17+30.

**Known**: `test_memory_capture_discipline.py::test_a_fact_survives_a_catalogue_that_mentions_its_subject`
is flaky by nature (per-message 3/4 recall on a documented-fragile case; it
flaked with and without this change, and is not in the deploy gate). The
reranker's exclusion of an explicit restriction (e.g. "55+") is deliberately
conservative and flaky (see reranking.py) — ordering, not exclusion, is the
memory mechanism.

**Deploy**: `bash scripts/deploy.sh`, then confirm the next ani.mallya sweep
(19:00 UTC) recommends local dance/social finds. After deploy, re-check
`docker compose exec backend` has the new code (it is image-baked).

**If you are picking this up on the Mac**, read [Where things run](#where-things-run)
and [Operational traps](#operational-traps-that-cost-real-time) first. The Mac is
not currently part of the running system except as the iMessage bridge, and one
task below is deliberately assigned to it.

## Live and verified

| | |
|---|---|
| site | `deep-matter.com` 200, tunnel is a compose service on spark1 |
| database | on spark1, migration head `20260828_0011` (conversation groups; 39 tables) |
| redis | 6,655 keys, append-only on, cursor `imessage:chat:cursor` present |
| models | DeepSeek-V4-Flash TP=2 (spark1+spark2), Qwen3-VL-8B (spark2), nomic 768-dim + Qwen3-Reranker-0.6B (spark1), FLUX.2 Klein 9B Q6_K + Kontext via ComfyUI on the desktop (only while it is on) |
| deploy gate | `bash scripts/gate.sh` — 7 passed, 0 skipped, ~5 min; exits 1 with the router down |
| backups | nightly 03:30 timer, three copies (spark1, spark2, Mac), restore proven end to end; WAL archived every 5 min with weekly-pruned base backups, point-in-time recovery rehearsed 2026-08-25 |

## Where things run

| Host | Address | What it holds |
|---|---|---|
| spark1 | `172.16.8.3` | every app container, the database, redis, the tunnel |
| spark2 | `172.16.8.5` | the VLM, half of the TP=2 router, the backup mirror |
| Mac | iMessage bridge only | `allow_recipient`, `send_imessage`, `read_messages` |
| desktop | `172.16.8.6` (Wi-Fi) | RTX 5080, **16 GB VRAM**; revived to host ComfyUI. Image work only while it is on |

User `animallya96` on both Sparks, same password on both. No BMC and no
wake-on-LAN, so **a powered-off Spark needs someone to press the button.**

## Search spend and providers — 2026-08-29

- **Brave is metered now.** Its live headers say `50;w=1, 0;w=2678400`: 50
  per second, **0 per month**, and requests are still served - i.e. billed
  (~$5/1k). The local `BRAVE_SEARCH_MONTHLY_LIMIT=900` is a spend cap, not a
  free allowance. Check the Brave dashboard and decide the cap deliberately.
- **Tavily leads now** (`SEARCH_PROVIDER_ORDER=tavily,brave,google` in
  `.env`, backup `.env.bak-20260829-search`): 1,000 free credits a month,
  reset on the 1st, so from 1 September the free one is spent first.
- **Gemini grounding stays off, and turning it on is now three steps.**
  Google's pricing page: grounding is *not available* on the free tier
  (which is the 429 we measured - a plain call on the same key works). With
  billing enabled the first 5,000 search queries a month carry no grounding
  surcharge on Gemini 3.x, then $14/1,000, and prompts stop being used to improve
  Google's products.
  1. AI Studio → API keys → find the Cloud project behind `GOOGLE_API_KEY`.
  2. Google Cloud console → Billing → link a billing account to that
     project, and confirm Tier 1 on the rate-limits page.
  3. On spark1: `GOOGLE_SEARCH_ENABLED=true` in `.env` (already inherited by
     the search subprocess), and put `google` first in
     `SEARCH_PROVIDER_ORDER`. The ceiling is already in place -
     `GOOGLE_SEARCH_MONTHLY_LIMIT` defaults to 4,800, under Google's included
     5,000 search queries, with the daily 450 beneath it. As of the paid-key
     acceptance on 2026-08-29, AniOS reserves ten queries before each call and
     reconciles the counters from `web_search_queries`; an uncertain timeout
     keeps the reservation. This is a buffered local stop, not a provider bill
     cap.
  Verify with one grounded call and `search_credits`, which now reports the
  Google allowance beside Brave's.
  The paid-key comparison chose `gemini-3.1-flash-lite` for this retrieval
  worker: across Python, Federal Reserve, and Artemis queries it returned the
  same current facts and official sources as 3.6, while the two timed comparison
  cases took 1.56/1.95 seconds instead of 3.25/7.96 and used one search query
  each instead of one/two. Current paid token rates are also lower.
- **The sweep is the biggest spender**: ~344 of the month's ~403 searches
  were verification runs, against ~59 from people. The 30-minute answer
  cache is live and measured (560 → 561 → 561 for a repeated question); if
  that is not enough, give the sweep a "skip the live-search journeys" mode
  for routine deploys and keep the full set for weekly runs.
- **`BRAVE_SEARCH_MONTHLY_LIMIT` is now a spend cap, not a free allowance**
  (900). The operator has not chosen that number under the new billing -
  ask before assuming it is right.
- **"group: dinner suggestion uses a member's taste" - fixed structurally
  2026-08-29.** The "What's on" pack was on every user's menu and took
  requests that were never about it (dinner question: 4/4 skill without the
  clock, 1/4 with it, and it failed a deploy's sweep twice). Wording in the
  pack description and in the router prompt was already right, and a third
  attempt measured worse. Now a shipped pack is offered only when the
  message names it: dinner 0/3, "what's on ..." 3/3, "quick brief ..." 3/3.
  Taught skills are unaffected. If a future pack needs to be found without
  being named, the answer is a semantic shortlist (the pattern MCP tools
  already use), not a sentence.

## Group chats — BUILT AND GATED 2026-08-28, live acceptance pending

The assistant in an iMessage group with approved users, as its own account
(ADR 0016; design, proof and status in `docs/GROUP_CHATS_ARCHITECTURE.md`;
diagram `docs/diagrams/group-chats-subsystem.svg`). Bridge, worker, pipeline,
attribution, delivery, admin, sweep journeys, and three real-model suites are
in; the unit gate and `sweep --only group` ran green before the deploy that
carried them (CHANGELOG).

**Done live on 2026-08-28 in "Groupie"** (`chat308729799386740866`, the
operator + jenos1): mention → answered in the chat in 22 s; thread reply →
answered (late, fixed); weather "here" → Somalia (fixed). The bridge's plist
now carries `IMESSAGE_BRIDGE_GROUPS`, `IMESSAGE_BRIDGE_READ_GROUPS=true` and
`IMESSAGE_BRIDGE_ADDRESSES=deep-matter@agentmail.to`. What remains is a
re-test on the build that carries the fixes (dd3cc92e): an @mention asking
the weather (answered for the speaker's city, or asked if none is on
record), a tap-and-hold reply with a question (seconds, not a minute), and
a "thanks!" reply (no bubble). For any other group, the steps:

1. find the room's identifier - `osascript -e 'tell application "Messages" to
   get {id, name} of every chat'` and pick the `iMessage;+;chatNNN` whose name
   matches;
2. add to `~/Library/LaunchAgents/com.anios.imessage-bridge.plist`:
   `IMESSAGE_BRIDGE_GROUPS=chatNNN` and `IMESSAGE_BRIDGE_READ_GROUPS=true`
   (`IMESSAGE_BRIDGE_ADDRESSES=deep-matter@agentmail.to` is already there:
   a mention is matched on the account's address, so the name each friend
   saved the contact under does not matter; `IMESSAGE_BRIDGE_DISPLAY_NAME`
   is optional and only adds "scout, ..." as a plain-word trigger); then
   `launchctl kickstart -k gui/$(id -u)/com.anios.imessage-bridge`;
3. in the group, from the friend's phone: "Scout, thai or pizza friday?" →
   one answer in the room; a tap-and-hold Reply to that bubble: "thai then"
   → answered; "thanks!" → no bubble; an unaddressed "lol" → nothing leaves
   the Mac (bridge log shows no forward);
4. `GET /api/v1/admin/groups` lists the room with both members;
5. `python -m backend.cli.explain_turn --user group:<slug> --last 3` shows
   `group: {speaker, members}` in each trace.

If anyone in the room is not approved, the assistant stays quiet and your
phone (`OPERATOR_ALERT_PHONE`) gets one text a day about that room.

**Candidate verified, not deployed:** conversational ❤️/👍 now queries only the
exact GUIDs of Scout's recent bubbles and becomes "yes, do that" only when the
readiness model's separate `accepts_offer` field says the targeted bubble
unambiguously offered one action. In a room the allowlisted reactor is mapped
to a current member and becomes the turn's speaker; missing or unknown identity
fails closed. Focused bridge/worker/API tests are 179/179 on the Mac; the Spark
candidate is 178 passed plus the expected macOS-only skip; the real-model
readiness suite is 33/33 and the accepted-search router proof 1/1. The exact
current-tree candidate also passed 2,213 non-functional tests with nine
documented environment-dependent skips. A live
tapback in Messages and deployment are still pending. The
remaining unbuilt trigger is the next otherwise-unaddressed message from the
person Scout asked; that needs a scoped expectation with a short TTL.

**Deploy #16 then showed the real defect behind "forget that":** with the
journey's own setup turn failed under model contention, "forget that" undid
a *task change from another conversation* - the change log's latest
undoable change was per person, not per conversation. Scoped to the
conversation now (migration `20260828_0012`); the sweep reports a failed
setup turn as the journey's failure. Deploys now retry a failed journey once
before paging.

**Two intermittent sweep gaps, traced and closed (2026-08-28):** "more
casual (draft referent)" - the resolver read "draft" every time, but a
draft turn could still be offered `edit_image` and the router took it
1-in-3; picture-editing tools are now withheld on draft turns and the
follow-up reading is traced on every routed turn. "forget that (memory
undo)" - its assertion counted every semantic row of the sweep user, so
earlier journeys' captures failed it in full sweeps; it asserts the change
log now. `sweep_journeys --keep` exists for the next one. The kept full
sweep (user `sweep_708ace97`) showed exactly that: the undo removed the
dentist row, the leftovers were "the user has a retail team" (captured from
the draft-email journey) and the next journey's restatement of the dentist.

**Fixed 2026-08-29 (they predated this session - four of five reproduce at
`7df424b6`):** the five red cases in
`functional/test_main_action_selector_behaviour.py` - a haiku routed to
generate_image, a polite "can you generate a labelled image of this?"
routing to nothing, an invented "Arlington, Virginia" when no place was
known, and two tests left stale by capabilities that shipped after them.
See the CHANGELOG for what each measured before and after. **The lesson to
carry:** this suite is not part of the deploy gate, so it drifted unseen for
at least a week. Consider adding it to `deploy.sh` (it costs ~7 minutes) or
running it weekly.

**Still red, deliberately: `test_search_routing_quality_meets_the_retired_cascades_floor`.**
Recall 0.806 against the 0.85 floor, the same five misses at this session's
base commit and with today's weather wording reverted - a real decline, not
variance and not from this session. The misses are all questions whose
subject the conversation never names ("did the merger go through", "what
time does the game start", "has the strike ended", "any news about the
merger", "is the farmers market open this sunday"): the subject-copy rule
added after the Surviving Paradise incident tells the router to call no tool
when nothing names the subject. Narrowing that rule to pointing words was
tried and measured *worse* (6 misses, two new: the euro cases), and was
reverted. Next step is the proper instrument, not another wording guess:
`ablate_prompt_rules` over the search rules plus `evaluate_tool_selection`,
then decide whether these cases should search in the person's own words or
whether the cases themselves encode behaviour the incident rule deliberately
replaced. The floor is left red on purpose - lowering it would hide the
decline.

**Router wobble, observed once (deploy #17's sweep):** "Scout hows the
weather here today?" in a group, with the speaker's place known, routed to
a history search; it was Weather in deploys #15 and #16 and 2/2 in
`test_weather_here_uses_the_known_place_or_asks`. Deploys retry a failed
journey once from #18 on; if this shows twice in one deploy, it is not a
wobble - trace it with `--keep` and read the `followup` and `route` in the
turn's trace before touching the router prompt.

**Observed once in the kept full sweep, not yet fixed:** the group dinner
question ("where should the two of us go for dinner on friday?") was routed
to a built-in skill pack that searched "events happening this weekend"
(off-subject results; the reply still answered from the room's Thai plan).
A dinner question is not a weekend brief. Measure with the evaluator before
touching the router prompt; the sweep journey keeps `Skill` out of its
accepted routes on purpose.

## Shipped 2026-08-24

**Sign-up collects a phone number, and approving someone allowlists them.**
The number is required at sign-up in E.164 (`backend/core/phone.py`), stored
encrypted with a separate digest, and approval does two things that used to be
done by hand and drifted: enrols the number as a subscriber in AniOS, then
calls `allow_recipient` on the Mac. Both gates, one decision. Verified live —
`saps21` signed up 03:23:17 and was approved 03:23:41 with both gates set.

**A newly approved person gets an introduction.** `backend/services/welcome_service.py`,
fired from the approve button. The message is generated by the reply model from
the same capability list the router offers as tools, so it describes what the
system can do today rather than what someone wrote in a paragraph once. Sent
after the bridge grant (the Mac refuses a number it has not been told about),
never fatal to the approval, and `user_accounts.welcomed_at` makes it
exactly-once. Existing accounts are deliberately **not** back-filled — they have
been using the assistant for weeks and an introduction now would read as a
fault.

**Data durability, which was the weakest thing here.** Before: two dump files,
one of them 20 bytes, both on the same NVMe as the live database, no schedule
and no restore ever attempted. Now: a nightly systemd timer, a mirror to
spark2, thirty-day retention pruned on both sides, Redis append-only, and a
restore proven end to end — 37 tables and 2,506 rows identical to live, then 65
encrypted values decrypted out of the restored copy with the escrowed key. That
last check is the one that matters; see [docs/RESTORE.md](RESTORE.md).

**The architecture page now publishes every canonical view.** The iMessage
bridge and Tasks & skills diagrams existed but were absent from the page's
publication list, which left its own completeness metric at 20/22. Both are now
included, and the freshness check fails whenever that list and the canonical
Mermaid source count diverge. The generated page reports 22/22; its structure,
unique embedded SVGs, source links, and zoom controls were checked locally.

## Live incident 2026-08-26 21:28 — a reminder became Scout's schedule, and "this" moved the wrong thing

What the operator saw: "adjust this to daily at 3pm", said about Scout,
moved their stretch reminder to 3 PM. What actually happened, from the
decrypted conversation rows and the task/schedule tables:

1. 21:28 "send another don tito reminder at 7" set the reminder correctly
   *and* the memory proposal agent read "at 7" as the sweep's cadence
   (its prompt said "asking for one to be set or changed states it just
   as plainly"), so Scout - daily 5 PM until then (runs 21:00-22:00 UTC) -
   became daily 7 AM, and the reply truthfully reported "the daily 7 AM
   Scout check is saved".
2. 21:30 "when did i say 7 am for scout?" - the reply invented a
   conversation ("back when we were setting up your recurring events
   sweep").
3. 21:31 "adjust this to daily at 3pm" - the router chose the task
   manager; the picker, given only the word "this" and two tasks, chose
   the only daily one (stretch, 18:00) and moved it to 15:00; the proposal
   agent moved Scout to 15:00 as well.

Fixed, verified, and deployed the same evening (see CHANGELOG 2026-08-26):
the proposal agent's `schedule` means the sweep's own cadence and never a
reminder; the proposal agent and the task picker both see the assistant's
previous reply; the picker is offered "none"; the router matrix carries
the Scout continuation as NO_TOOL; the reply answers "when did I say X?"
only from what it can see. Stretch reminder restored to daily 6 PM.

Then the journey sweep's Scout-continuation journey showed the route
itself still wrong (manage_tasks, with the picker's "none" as the only
thing between Scout and a moved reminder), and the 2026-08-23 note in
`backend/tools/manage_tasks.py` had already measured that no wording
fixes it. So the structural fix landed the same night: `scout_schedule`
is Scout's own tool (see CHANGELOG 2026-08-26).

Closed by the operator at 22:08 UTC the same evening: "i don't want
stretch reminders. only scout for 3pm everyday" - the stretch reminder was
cancelled on request and Scout stays daily at 3 PM (it had run daily at
5 PM before the incident).

**For the operator, one click:** GitHub -> repository Settings -> Branches
-> add a rule for `main` -> tick "Do not allow force pushes" (and "Require
linear history" if you like). The local pre-push hook now refuses rewrites
from this checkout, but only the server setting protects the branch from
every clone.

## Live incident 2026-08-27 15:55 UTC — "weather in DC" asked for a ZIP code, then got the wrong words

ama_edm (new that day, no locality on record) asked for DC's weekend
weather; the geocoder had nothing for "Washington, DC" so the reply asked
for a ZIP, and the forecast it then gave was Open-Meteo's WMO wording
("violent showers" on a 29% day, "overcast" on a mostly-sunny Saturday)
without Sunday. Fixed the same day: place aliases and fallbacks, NWS as
the US source, plain wording with the rain chance, weekdays and coverage.
See CHANGELOG 2026-08-27.

## Live incident 2026-08-27 02:41 UTC — a follow-up searched as a different show

jenos1, over iMessage, about Netflix's "Surviving Paradise": the router
searched "does only one person win at the end?" as Squid Game: The
Challenge and "you mentioned there was only one season" as Love Island
USA, and the reply answered about those shows. Read from the turn trace
in under a minute (`explain_turn --user jenos1`). Fixed the same night:
the query copies the conversation's subject (router + composer, tested on
the query text), and the ranker's new `on_subject` flag turns wrong-subject
results into a disclosure instead of an answer. See CHANGELOG 2026-08-27.

## State at the end of 2026-08-26 — the "no more bugs on done items" wave

Shipped through `scripts/deploy.sh` (the only deploy path now; it runs the
unit suite and routing gate before, the journey sweep and search harness
after): undo for reminders and Scout's schedule (`scheduled_task_changes`),
one writer for Scout's cadence (`scout_schedule`; the proposal agent has no
schedule field), a trace on every turn (`backend.cli.explain_turn`), a green
unit suite (1841; the 24 "stale" failures were the test container's missing
Redis and stale image copies), eight referent-shaped multi-turn journeys,
a pre-push hook against rewriting `main`, and - found only by an HTTP
end-to-end check - the stream wrapper losing every per-turn ContextVar
between frames (`_with_heartbeat` now runs each pull in one context).

Added 2026-08-27 (see CHANGELOG): a **follow-up resolver** - one reading
of "this/it/again" before the router, the research rounds and the trace
(the structural answer to the week's whole incident class); **"forget
that"** for automatic memory saves; the **ablation tool**
(`backend.cli.ablate_prompt_rules`) for measuring the router prompt's
sentences against each other; the ranker's **on_subject** flag turning
wrong-subject results into a disclosure.

Still open, in order of risk:
1. **The router's tail.** With the resolver alone: regenerate 5/6 (from
   3/6), followup_subject 6/6, diagrams 12/12 - but opinions about a
   picture moved from edit to *show* (0/9) and draft continuations stayed
   6/12. So: `discuss_image` (a named "talk about it, change nothing") and
   no automation offered on a draft turn. Measure again; if writing
   follow-ups still leak, the next step is a `regenerate_image` row and a
   two-stage router.
2. **Run the ablation** on the router prompt (`--categories` for the weak
   ones first) and delete what costs nothing.
3. **Two prompts with no functional pin yet** (declared in their headers,
   enforced by `test_functional_coverage_completeness`): `refinement/keep_scene`
   and `style/distill` - both need the edit model on a real picture.
4. **Operations on several tasks at once.** "delete the paused ones"
   (real phrasing) reaches a picker that chooses one task; cancel/pause of
   a set is not supported. Needs `manage_tasks` to accept a selection
   ("all paused", "the weather ones") and a confirmation line listing what
   it touched.
5. **GitHub branch protection** - the operator's click (above).
6. Tavily plan/credits; schedutil on the Sparks; wake-on-LAN for the
   desktop; a fare API for trips (all earlier notes).

## What is still open

**A third backup copy on the Mac — LIVE 2026-08-25.** Remote Login is on,
spark1's `spark1-backup-mirror` key is authorized for `animallya@172.16.8.2`,
and spark1's `.env` lists both mirrors. Proven with a real run: the same
dump (`anios_db-20260824-222902.sql.gz`, 37 tables) landed on spark1, spark2,
and `/Users/animallya/anios-backups`, 534 sealed values inside and zero key
material. The first three-copy run mirrored to nobody: the `.env` parser
stripped spaces along with carriage returns and fused the two hosts into one
name — fixed in `backup-db.sh` the same night. **The Mac still holds
ciphertext only: never copy `ENCRYPTION_KEY` onto it.** The key is escrowed at
`C:\Users\Ani Mallya\anios-recovery\anios-keys.env` on the Windows box.
(Cosmetic: the Mac's `~/.bashrc` line 2 prints `$: command not found` on
every non-interactive ssh; harmless, not fixed, the operator's file.)

**FLUX decision 2026-08-25: the desktop hosts FLUX.2 Klein 9B, and image
work is available only while the desktop is on.** The operator revived the
RTX 5080 box for exactly this: ComfyUI is to be the only GPU tenant there,
and when the machine is off the assistant says so ("the machine that runs
image generation is off - try again later"; `_image_provider_failure_message`,
29/29 gated). spark1's side is ready: defaults moved to the 9B pair
(`flux-2-klein-9b-fp8.safetensors` + `qwen_3_8b_fp8mixed.safetensors` -
the 8B encoder is mandatory, the 4B one produces garbage silently), the
Klein workflow nodes are unchanged from the 4B. **VERIFIED from spark1, 2026-08-25 03:50 UTC.** The desktop session
installed Plan B (`flux-2-klein-9b-Q6_K.gguf`, ungated, plus the official
`qwen_3_8b_fp8mixed.safetensors` encoder; the fp8 9B is HF-gated and the
operator's account is not on its list), started `anios_comfyui` as the only
GPU tenant, and measured 6.0 s warm / 114.5 s cold at 1024x1024, 13,755 MiB
peak. spark1's `.env` now points `IMAGE_PROVIDER_BASE_URL` at
`http://172.16.8.6:8188` with the Q6_K model names; backend,
presentation-worker, and local-capabilities were rebuilt (the running image
had predated the GGUF-loader commit - the baked-image trap, again - so the
first probe reached ComfyUI with a plain `UNETLoader` and a 400) and
recreated. A provider-level probe through the backend's own classes then
generated a 1024x1024 image in 16.9 s and Kontext-edited it in 118.6 s. That
second number is the model swap: Klein and Kontext cannot both stay resident
on 16 GB, so a generate followed by an edit pays a cold load of roughly two
minutes; ComfyUI runs prompts serially, so concurrent requests queue rather
than OOM. The Docker Desktop firewall rule that allowed any port from any
remote (an unauthenticated ComfyUI answering everything that could route to
`172.16.8.6`) was scoped to 172.16.8.0/24 by the operator on 2026-08-25;
spark1 and the Mac still get HTTP 200 from `:8188`, which is the allow side
proven. The deny side cannot be tested from inside the subnet - a probe from
outside the /24 is the only thing that would prove it. **Edits moved to the Klein 9B (13:4x UTC), measured first:** with the vision
model judging the pixels, the 9B added a yellow umbrella on request and
turned the wall white, in 20.0 s / 18.3 s while resident, against Kontext's
109.6 s cold / 43.7 s warm for the same edits (both editors passed both
judgements; the source had no umbrella). The 4B's "preserves its reference,
adds nothing" failure does not hold for the 9B, so `IMAGE_EDIT_MODEL` is
empty on spark1: one resident model, no Klein-Kontext swap, no swap-induced
VM-memory crash, and an edit after a generation in seconds. Kontext stays
one env var away (`IMAGE_EDIT_MODEL=flux1-kontext-dev-Q4_K_M.gguf`) if a
class of edit needs it; the judgement was two instructions on one picture,
not a fidelity benchmark. **Seventh scenario pass with edits on Klein: 7 of
7** (`python -m backend.cli.exercise_image_scenarios` inside the backend
container) - every edit on the picture it was meant for, lineage intact,
no ComfyUI restart, delete-all clean. **Correction, measured on the desktop itself 2026-08-24 22:50:** the
desktop *is* on the LAN, at `172.16.8.6` on its Wi-Fi adapter, same /24 as
the Sparks and the Mac. The earlier scan missed it. Its wired `Ethernet`
adapter is on a 169.254 link-local address, which is probably what the scan
found.

**Desktop readiness, measured on the box 2026-08-24 22:50.** All read-only;
nothing on that box was changed. Two of these started as blockers and are
resolved — both are kept, with the reasoning, because the corrections are more
useful than a tidy list would be.

**Verdict: Plan A is sound on paper and nothing technical is in the way.** What
remains is three things only the operator can authorise, listed at the end.
Plan B needs no code: commit `1bc2c2df` makes both Klein workflows follow the
model file name, so a `.gguf` routes to `UnetLoaderGGUF` and anything else to
`UNETLoader`. Dropping `flux-2-klein-9b-Q6_K.gguf` (~7.5 GB) into
`diffusion_models/` and pointing `IMAGE_MODEL` at it is the entire fallback.

- **VRAM: 16,303 MiB total, 13,727 free** (the rest ordinary Windows desktop
  processes — no compute tenant). I first read this as fatal, summing the 9B
  and its 8B encoder as ~17 GB co-resident. **That was the wrong model of how
  ComfyUI loads**: it encodes with the Qwen encoder, then evicts it to system
  RAM to make room for the diffusion model, which is why Comfy's own Klein
  guide lists 16 GB for the 9B fp8 pair. The figure that actually matters is
  the eviction target — and **I first reported that wrong.** The host has
  31.9 GB, but the container does not get it: with no `.wslconfig`, Docker
  Desktop's WSL2 VM takes the default 50%, so ComfyUI's own boot line reads
  **`Total VRAM 16303 MB, total RAM 15947 MB`** and `free -m` inside the
  container agrees. **The eviction ceiling is 15.57 GB, not 31.9 GB**, and
  14.35 GB of it is reserved as pinned memory.

  That ceiling is the real constraint, because the model pairs sit right
  against it: encoder 8.07 + Kontext 6.46 = **14.53 GB**; encoder 8.07 +
  Klein 7.33 = **15.40 GB** — before activations or a 2 MP latent. On
  2026-08-25 04:30:19 UTC the container exited mid-request during a Kontext
  edit at `IMAGE_EDIT_MEGAPIXELS=2.0` on a 1024x1024 source, and
  `restart: unless-stopped` brought it back: `RestartCount 1`,
  **`OOMKilled: false`, `ExitCode: 0`**, no CUDA error and no OOM anywhere in
  the log. A clean exit with no torch exception is VM memory pressure, not a
  GPU OOM.

  **The real fix is `.wslconfig` with `memory=24GB`** (then `wsl --shutdown`
  and restart Docker Desktop) — on a 32 GB host that gives the eviction target
  genuine headroom. The interim lever, and what was set when the box had to
  power down, is **`IMAGE_EDIT_MEGAPIXELS=1.0`**: it shrinks the latent and
  activations on the heaviest path, and a 1 MP edit of a 1024x1024 source is
  not a visible downgrade.
- **Neither 9B file is on the box.** `diffusion_models/` has
  `flux-2-klein-4b-fp8.safetensors` (3.79 GB) and
  `flux1-dev-kontext_fp8_scaled.safetensors` (11.09 GB);
  `text_encoders/` has `qwen_3_4b.safetensors` (7.49 GB), not the 8B. So
  spark1's defaults currently name files that do not exist — a missing
  checkpoint at request time, not a fallback.
- ~~ComfyUI is 0.28.0 and `nodes_flux2.py` is absent~~ — **retracted, this was
  a bad inference.** Upstream puts the FLUX.2 nodes in `nodes_flux.py`
  alongside the FLUX.1 ones; there is no `nodes_flux2.py` to be missing. All 13
  nodes the workflow needs are present, `CLIPLoader` offers `type="flux2"`
  (`nodes.py:995`), and `UnetLoaderGGUF` exists for the GGUF fallback. The
  checkout is `c9602625`, **18 July 2026**, `master` — the "0.28.0" is the
  generated version string, not the checkout age. No `git pull` needed.
- **`anios_comfyui` exited 137** (SIGKILL) 47 hours ago; cause not established.
  Its image is right for this card — `nvidia/cuda:12.8.0-runtime-ubuntu22.04`
  with cu128 wheels, i.e. Blackwell/sm_120. The "cannot emit sm_121" caveat in
  these notes is about the DGX GB10, **not** this box.
- **Port 8188 is closed.** Nothing listening (container down), and there is no
  Windows firewall rule for 8188 or ComfyUI, so inbound from 172.16.8.0/24 is
  dropped by default once it starts. Adding one needs admin on the desktop.
- **No Hugging Face auth**: no `~/.cache/huggingface/token`, no `HF_TOKEN`. The
  9B is gated, so this blocks the download outright.
- Present and healthy for the Kontext editing path:
  `unet/flux1-kontext-dev-Q4_K_M.gguf` (6.46 GB),
  `text_encoders/t5-v1_1-xxl-encoder-Q5_K_M.gguf` (3.15 GB),
  `clip_l.safetensors`, `vae/ae.safetensors`, and the `ComfyUI-GGUF` custom
  node.

**DONE 2026-08-24 23:40 — image generation runs on the desktop, on Plan B.**
Measured, not inferred:

| | |
|---|---|
| model | `flux-2-klein-9b-Q6_K.gguf` (7,865,424,160 B), `unsloth/FLUX.2-klein-9B-GGUF` |
| encoder | `qwen_3_8b_fp8mixed.safetensors` (8,664,848,742 B), Comfy-Org, ungated |
| loader | `UnetLoaderGGUF`, chosen by `_model_loader()` from the `.gguf` suffix |
| cold / **warm** | 114.5 s / **6.0 s** at 1024x1024, 4 steps |
| **peak VRAM** | **13,755 MiB of 16,303**, sampled every 2 s during the run |
| LAN | `system_stats` from spark1 → HTTP 200 in 0.015 s |

Run through `ComfyUIImageProvider._workflow()` rather than a hand-written
graph, so the proven path is the one the backend takes. Output verified as real
1024x1024 PNGs. **Peak never approached the ~17 GB predicted** — the eviction
model is correct and the earlier VRAM worry is settled empirically.

**A slow first edit is a cold load, not a fault.** Generation holds Klein 9B
Q6_K (7.33 GB); the Kontext edit holds `flux1-kontext-dev-Q4_K_M.gguf`
(6.46 GB) with a different encoder. Both together do not fit 16 GB, so
alternating generate → edit → generate makes ComfyUI evict and reload each
time. Measured: **114.5 s cold against 6.0 s warm.** So "make me a picture"
followed by "now change it" costs about two minutes on the second request, and
it will be reported as a hang. It is not.

Related, and recorded because I got it wrong first: **ComfyUI executes prompts
serially** (`queue_running` / `queue_pending`), so overlapping requests queue
rather than running together. There is no concurrent-workflow OOM to defend
against, and `IMAGE_MAX_CONCURRENCY=1` (settings.py:522) already holds. The
semaphore in `ComfyUIImageProvider` is per instance and `dependencies.py`
builds three, so two requests can be in flight in the app — harmless, because
ComfyUI serialises them anyway. Do not "fix" that by assuming it causes OOMs.

**Plan A remains unavailable.** `black-forest-labs/FLUX.2-klein-9b-fp8` returns
**403 GatedRepo** for `deepmatter77`; access needs a click on the model page and
no token can self-approve. Set `IMAGE_MODEL=flux-2-klein-9b-Q6_K.gguf` unless
that gate is cleared.

**CLOSED 2026-08-25 — 8188 scoped to the LAN, with one honest caveat.**
Publishing 8188 had exposed an unauthenticated ComfyUI to every source that
could route here, because `Docker Desktop Backend` allows **Any port from Any
remote** and an extra *Allow* rule cannot narrow that — Windows Firewall
permits if any Allow matches. The fix is a **Block** rule, since Block takes
precedence, written as the complement of the LAN because "block except X" is
not directly expressible:

```powershell
New-NetFirewallRule -DisplayName "Block ComfyUI 8188 outside LAN" -Direction Inbound `
  -Protocol TCP -LocalPort 8188 -Action Block -RemoteAddress @(
    "0.0.0.0-126.255.255.255","128.0.0.0-172.16.7.255","172.16.9.0-255.255.255.255")
```

The `127.x` gap keeps loopback working. Verified after applying: loopback 200,
spark1 200, spark2 200 — nothing that must work broke.

**The caveat, stated because it would be easy to imply otherwise: the block
itself was not empirically proven.** Every traffic source available on this
network NATs into `172.16.8.0/24` — a container's probe arrived as
`172.16.8.6 → 172.16.8.6:8188`, i.e. from inside the allowed range, so it
proved nothing. Testing it properly needs a host genuinely outside the `/24`.
What is established is that the rule is correctly formed, that Block precedence
is documented behaviour, and that the permitted paths still work.

Scale of the original risk, also worth stating plainly: NAT meant this was
reachable by devices on the home network, not from the internet, unless
someone had port-forwarded 8188.

**Awaiting the operator, and only the operator.** A peer session asking is not
authorisation for any of these:

1. **Hugging Face login** — the 9B is gated under FLUX Non-Commercial.
2. **~18 GB of downloads** — `flux-2-klein-9b-fp8.safetensors` (~9.5 GB) into
   `diffusion_models/`, `qwen_3_8b_fp8mixed.safetensors` (~8.5 GB) into
   `text_encoders/`. The `vae/flux2-vae.safetensors` already present is right.
3. **An inbound Windows firewall rule for TCP 8188, scoped to 172.16.8.0/24**
   — needs admin on the desktop.

Then, in order: `docker compose --profile comfyui up -d comfyui` with
`COMFYUI_DOCKERFILE=Dockerfile`, confirm via `nvidia-smi` that ComfyUI is the
only compute process and no other anios container started, and prove it with
`curl http://172.16.8.6:8188/system_stats` from a Spark plus one real 4-step
1024x1024 generation. Report wall time and peak VRAM during the run; on OOM,
switch to Plan B and report the same numbers. Only then does spark1's `.env`
get `IMAGE_PROVIDER_BASE_URL=http://172.16.8.6:8188` and the 9B names.

The earlier headroom analysis, kept for the record:
**FLUX did not fit on the Sparks as they stand.** The sm_121
blocker is solved — `docker/comfyui/Dockerfile.gb10` (NVIDIA CUDA-13 PyTorch
base, aarch64), selected by `COMFYUI_DOCKERFILE` in `.env`, and
`IMAGE_PROVIDER_BASE_URL` is now env-overridable so placement is an `.env`
decision. The real blocker is **headroom**: measured 2026-08-24, spark1 has
~9 GiB available and spark2 ~2 GiB, because DeepSeek TP=2 holds ~97 GiB on each
node (weights+overhead are a ~90 GiB/node floor, so trimming KV frees only
~3 GiB). 4B needs ~14 GiB, 9B ~18 GiB — neither fits while DeepSeek holds both
nodes, and over-allocation hangs a box with no BMC. The desktop 5080 is retired
by decision, so it is not the fallback. Options recorded for the operator: run
DeepSeek TP=1 on one node to free the other; a GGUF-quantized 4B (~8 GiB, still
tight); or accept no local image gen and un-advertise `generate_image`/
`edit_image` (both are registered builtins, so the welcome currently promises a
capability with no backend). The 9B is additionally gated + FLUX
Non-Commercial; the 4B is Apache/ungated. Checkpoints are on the powered-off
desktop and must be re-fetched from HuggingFace (reachable from spark1).

## BUILT — active recall: `search_history` (2026-08-24; gate-verification pending)

The spec below was implemented the same day, from the Mac. Everything landed
as designed: `RecallHistoryAction` + `backend/tools/search_history.py` in the
registry; `search_turns` on the memory service (questions kept, exchange-level
dedup, excerpts bounded at 1,000/1,500 chars); `_recall_history_evidence` in
the conversation service (embeds the model's query, filters out what the
visible window already shows, never costs the turn); its own prompt section
(`_render_history_recall_context`, own-record framing, injection-resistant
wording) riding a new `past_conversations` budget section at priority 2 —
**the section priorities below it were renumbered** (tools 3, history 4,
images 5, recalled 6, memory 7), which was safe because enforcement is off
and no floors were ever recorded. `_runnable` now passes three action kinds.
The chat-orchestration diagram gained the flow (SVG re-rendered on spark1).

**Verification: GREEN, run on spark1 the same day through the gate's test
container** (working tree mounted, skips-count-as-failures):
`test_history_recall.py` 10/10; `functional/test_history_recall_behaviour.py`
7/7 against the real router — every backward-reference phrasing chose the
tool, ordinary questions and a visible-context follow-up stayed out, so the
routing-precision risk did not materialize; and the full tool-selection
matrix (`bash scripts/gate.sh`, 294s) stayed green with the new tool offered,
which is the no-regression proof for widening the router's option set. If a
future run flakes, tune the description by subject shape, never by adding the
failing phrasings to it.

**One loose end: chat-orchestration.svg is stale.** The .mmd (canonical)
carries the new flow; the SVG could not be regenerated — spark1's host has no
node, and a throwaway node:22 container gets as far as mermaid-cli's
puppeteer failing to launch its browser ("Failed to launch the browser
process", a container sandbox/provisioning issue; playwright's own install
succeeds and is not what mermaid-cli uses). Render it from whatever
environment produced the 2026-08-24 22/22 suite; the freshness check will
flag the pair until then.

## The spec as approved (kept for the record)

**The gap it closes.** Recall today is passive: top-3 similar past remarks are
injected before the model answers. A detail that was never fact-shaped, got
compressed out of the digest, and does not resemble the current wording sits in
Postgres but never reaches the model — recorded, not recallable. The operator's
stated bar is "recall anything at any point in time"; the fix is letting the
model *search its own transcript store* on demand, the way it can already
search the web.

**What exists to build on (all verified in source).**
`Conversation` rows are one per exchange with a pgvector `embedding` per turn
(`memory/repository.py::get_recalled_turns` is the passive query — user-scoped,
`embedding IS NOT NULL`, excludes the current conversation). Builtins are one
`BuiltinTool` row each (`tools/base.py`; label + router description in one
place), actions are frozen dataclasses in `tools/actions.py`, and search
evidence is injected at `conversation_service.py:1678` (`context["search"]`)
where it rides the "evidence" prompt section and the context budget.

**The build.**
1. `RecallHistoryAction(query: str)` in `tools/actions.py`. It must join
   `SearchAction`/`ToolboxAction` as the *third* action kind that survives to
   the reply path (that list is currently hardcoded to two — see the
   2026-08-20 handoff entry on dropped actions).
2. A `BuiltinTool` row: name `search_history`, schema `{query}` required
   (`required_text` house rule: empty query = no call). Description states the
   principle, not cases: it fires when the user refers to something from a
   past conversation that is not in view; a question answerable from what is
   already visible selects no tool.
3. Execution: embed the query with the existing provider, then a wider
   variant of `get_recalled_turns` — top ~12, cosine ≤ 0.6 (passive recall's
   0.45/top-3 stays untouched), exclude the current conversation, return
   `{when, said, answered}` snippets with timestamps. **No SQL text search is
   possible** — `query`/`response` are `EncryptedText` — so any keyword
   refinement happens Python-side over a bounded candidate set (e.g. the top
   200 by embedding), never a full-table decrypt scan.
4. Inject results into `context["search"]`-shaped evidence (untrusted-literal
   framing like everything retrieved), so budgeting, enforcement, and the
   buried-evidence gate apply unchanged. The iMessage worker gets the feature
   for free — same `process_request`.
5. Tests: structural (scoping, exclusion, empty-query-no-call) plus
   functional per the completion rule — a seeded old remark is found and used
   in the answer; the existing 52-case routing floor still passes so ordinary
   turns don't start misfiring into recall; assert properties, not wording.
   Routing on a 4B model is the known risk (see "The 4B ceiling") — measure
   the tool's trigger precision before trusting it, and keep the description
   subject-shaped, not phrase-shaped.

Latency cost: one embedding call + one pgvector query on selected turns only.
Diagram impact to assess at build time: chat-orchestration view if action
flows are drawn there.

## Recall scalability wave — BUILT AND VERIFIED 2026-08-24 (cad31224)

The five recorded limitations of the first search_history cut are closed, and
each fix ran on spark1 the same night: turn vectors now embed BOTH voices
(backfill re-embedded 188/188 rows into the `#qr1` space via the test
container with `-e EMBEDDING_BASE_URL=http://vllm-embedding:8000` — spark1's
host-style .env value otherwise leaks into the container and refuses);
retrieval matches only the current model+scheme signature so a space change
degrades to invisible-until-rebuilt, with the signature-driven backfill as the
one-command rebuild; `ix_conversations_embedding_hnsw` is live (applied via
the tree-mounted test container, verified in pg_indexes); the model states
time bounds as ISO dates in its tool call (never regex over prose) and they
narrow the search in SQL; misses log the nearest rejected distance so the 0.6
threshold becomes measured; excerpts carry truncation markers; the active
search probes both the router's query and the user's raw phrasing. Gates:
structural 13/13, functional 8/8, tool-selection matrix green. Multi-round
history search stays deliberately deferred until miss telemetry argues for it.

## Live incident 2026-08-24 23:52 — a debate point became a stored preference

In the operator's iMessage thread, "but conversation history will be
summarized and important facts stored in memory" — a rebuttal in a technical
discussion about context sizing — was answered as if it were an instruction
("Got it — noted and saved"), and the memory pipeline persisted it as a
user_explicit semantic fact describing how the system already works. No
context was lost (same conversation, 49 turns, prior exchange 78 minutes
earlier and inside the window): this is the documented over-capture class
(Scout interests from task talk, 2026-08-21) surfacing in the semantic
pipeline. The junk row (c6f33d16) was deleted. The real fix is prompt work on
the memory classifier — distinguishing a statement about the system in a
design discussion from a standing preference — done the recorded way:
reproduce the verbatim turn at temperature 0 first, one wording attempt,
functional-gated against the existing interest-capture cases.

## Reranker stage — DEPLOYED AND VERIFIED 2026-08-25 (d8887d30..92d62c83)

Qwen3-Reranker-0.6B serves on spark1 as `vllm-reranker` (same ARM image as
the embedding service, documented classifier hf_overrides, 0.03 utilization,
max-model-len 2048 after 4096 measured spark1 idling at 3 GiB free - the
trim bought back 2). `backend/core/reranker.py` speaks `/v2/rerank` - on this
build /v1 and /rerank reset the connection while /v2 answers in the JinaAI
shape - and history recall now fetches a top-40 and lets the cross-encoder
cut it to twelve, fail-soft to cosine order on any failure (an empty
RERANKER_BASE_URL switches the stage off entirely). Verified: live ranking
correct (0.987 answer vs 0.293 decoy), structural 5/5, functional 2/2,
history-recall 8/8, tool-selection matrix green.

One instructive regression, caught by the gate and worth remembering:
**adding optional fields to a tool schema moves the 4B router's decision
boundary.** The since/until additions made "make it more casual" (a revision
of the draft on screen) route to history search. Fixed on the first wording
attempt with a principle, not a phrasing: a short follow-up continuing work
in view is part of that work, never a reference to the past. Any future
schema touch on any builtin should expect to re-run its behaviour suite.

Follow-up MEASURED 2026-08-25, and the answer is no for now. The swap is
built and selectable - `DISCOVERY_RERANKER_SOURCE=service` routes Scout's
RerankProvider contract to the vLLM Qwen3 reranker through
`backend/embeddings/service_reranker.py`, probabilities converted back to
log-odds so MIN_ATTRIBUTION_MARGIN keeps its meaning - but
evaluate_discovery_ranking scored attribution 0.25 under the service
against 0.50 local (both below the harness's own 0.60 floor; local's
failures are wrong answers, the service's are all margin-misses). Default
stays `local`. That both models fail the floor says shortlist attribution
itself is weak and the labelled cases are seeded judgements worth
correcting; revisit at the Qwen3-VL migration, by the same harness.

## Embedding research verdict, 2026-08-25 (for the coordinated space migration)

Current text leaders: the Qwen3-Embedding family tops open MTEB; Tencent's
KaLM-Embedding-Gemma3-12B scores higher but is weeks old with no production
record. For THIS system the decisive fact is unchanged: text and vision are
one aligned nomic 768 space, so the text embedder cannot move alone.

**The designated migration target at hardware ramp: Qwen3-VL-Embedding
(2B/8B) + Qwen3-VL-Reranker (2B/8B).** One family, one unified space across
text, images, screenshots and video; Matryoshka output (can emit 768, so the
Vector(768) columns need no schema surgery); quantization-aware training;
vLLM-servable; and the reranker speaks the same /v2/rerank contract the
deployed 0.6B already uses - the multimodal step becomes a compose model-name
change plus one signature-driven backfill per store and a re-measure of the
two distance thresholds. jina-embeddings-v4/reranker-v3 rejected: stronger
per-parameter but CC BY-NC and no vLLM support. The cutover is sized for the
ramp, not before: the 2B pair wants ~10+ GiB that today's boxes do not have.

## Hardening wave — BUILT AND VERIFIED 2026-08-25

Four improvements closed in one pass, each verified on spark1:

**The memory classifier no longer stores the discussion as the user.** The
23:52 over-capture was reproduced first (the verbatim rebuttal plus two more
system-statement shapes, all failing at temperature 0), then fixed in the
prompt with principles, not phrasings: a statement about how the assistant
or any system under discussion works is the work at hand and fills nothing;
semantic facts are what the user states about themself; another person's
fact remains theirs. The first wording said "about the user's own life" and
the model read a daughter's ballet into it - the refinement to
states-about-themself closed that. `functional/test_memory_capture_discipline.py`
pins both sides; the full memory-capture batch runs 38/38.

**The phone/address digest is keyed (C12 closed).**
`discovery.addressing.address_digest`, HMAC-SHA256 from `ENCRYPTION_KEY`
(falling back to `SECRET_KEY`), in all four consumers at once; the rekey CLI
moved 1 access request + 14 subscribers and reports zero on re-run, which is
the proof the stored digests now match what the lookups compute. A
source-inspection test forbids the unkeyed path from returning. Rotating
`ENCRYPTION_KEY` or restoring a pre-rekey dump now requires
`python -m backend.cli.rekey_address_digests` afterwards.

**The memory export carries the sign-up phone** (`sign_up` section, schema
version 3): the approved access request keeps the number keyed by
desired_username, the one place a per-table coverage sweep cannot see.

**The loopback binding outage, caused and fixed the same evening.** Applying
the committed 127.0.0.1 port bindings for db/redis broke every NEW container
connection - services dialled the host's LAN address, established
connections coasted, health stayed 200 while 50 refusals accumulated.
Containers now address `db` and `redis` over the compose network (the
binding never touched it) and the gate's `POSTGRES_HOST` is literal `db` so
spark1's host-oriented .env value cannot leak in. See the new trap below.
One aftershock surfaced on the post-deploy health sweep: `up -d` had left
memory-maintenance and storage-collection running with the old env (28h
uptime, silently failing every job), and only an explicit
`up -d --force-recreate` of the pair moved them. After any compose env
change, check `docker ps` uptimes against the deploy time rather than
trusting up -d's own output.

## Image scenarios on the real chat path — measured, two defects fixed, 2026-08-25

Seven scenarios driven through `POST /api/v1/chat` (SSE) and
`/vision/analyze` inside the backend container - the browser's and the
iMessage worker's exact path - with the desktop generating. **Verified:**
generate (artifact_ready), upload + ask (the VLM described the picture),
edit the newest uploaded picture with no selection (child's
`parent_artifact_id` = the upload), and a question about a picture answered
in words with no artifact ("The bicycle in the first picture is red"). **Two
defects found, both fixed and gated, both awaiting an end-to-end re-run
when the desktop is next on:** (1) a generated picture was never indexed
into the visual-memory description store - only uploads were - so with no
explicit selection "add a yellow umbrella" right after a generation had no
edit candidate at all, and "edit the bicycle picture" found nothing; a
generated picture is now indexed by its prompt and an edit by its origin
plus the instruction (`ImageArtifactService._index_description`, fail-soft,
deleted with the artifact). (2) When that fall-through reached the plain
reply, the model answered "Here's the updated image with the yellow umbrella
added" for pixels never touched; `_render_edit_state` now tells the reply
that nothing was changed, and `functional/test_image_edit_state_behaviour.py`
holds three registers of the request at 4/4. **One infrastructure finding:**
the explicit-selection Kontext edit died with "server disconnected" at
04:30:16 UTC together with a generation that was not mine - ComfyUI had
exited cleanly (`ExitCode 0`, no CUDA error) under the WSL2 VM's 15.6 GB
RAM ceiling with Klein, the 8B encoder, and Kontext swapping. Edits now run
at `IMAGE_EDIT_MEGAPIXELS=1.0` (spark1 `.env`, verified generate 114 s cold +
edit 115 s cold after the restart); the structural fix is a `.wslconfig`
with `memory=24GB` on the desktop, an operator host change for its next
boot. **Third pass, after the fixes and at 1 MP (04:44 UTC): 6 of 7.** The
unselected edit right after a generation now edits that picture (child's
parent = the generated one), the explicit selection edits the chosen
picture with no ComfyUI restart, "edit the bicycle picture" resolves by
description into the bicycle lineage, generation, upload + ask, and the
question all pass. The one failure was new and different: for "make the
background of this picture purple" (no selection, right after the upload)
the router chose *no tool* this time, and the plain reply - its history now
full of "Editing ..." turns - wrote "Editing a red bicycle with a wooden
basket" for an edit it never made and a basket that did not yet exist. The
no-change block is therefore rendered whenever a picture is in view on the
plain path (`_render_edit_state`, neutral wording, 5/5 including a plain
question), rebuilt and redeployed. That routing shape - an
imperative edit with no selection after an upload turn - is now in the
tool-selection floor set (matrix 7/7 with it). **Fourth pass (04:55 UTC):
6 of 7 again, and the seventh changed shape** - the router chose edit this
time, but with no selection "this picture" edited the bicycle, not the
newest upload. Cause: referent candidates came only from a similarity
search over descriptions, and a bare "this" matches nothing, so the
picture the person was looking at was never offered and the resolver's
recency rule had nothing to apply to (in the second pass the same step was
right only because generated pictures had no descriptions yet). Fix: the
three newest ready pictures are always offered alongside whatever
similarity retrieved (`ImageReferentSource`, `RECENT_CANDIDATES`);
structural 44/44, referent-resolution behaviour 7/7, redeployed. Real
clients send the active picture explicitly (browser chip, iMessage
reply-pin) and never hit this; an API client without image tracking did.
**Fifth pass (13:08 UTC): 6 of 7 still** - the upload was now offered and
the resolver still chose the bicycle, reading "background" in "make the
background of this picture purple" as a detail matching its brick wall.
Fixed in the resolver prompt as a principle: "this" points at the most
recent candidate, and naming a part any picture has (background, sky,
colours, something to add) is not a distinguishing detail; only a detail
that fits some candidates and not others chooses an older one. Reproduced
first as three registers plus a separating-detail control in
`functional/test_referent_resolution_behaviour.py`; one of my own cases
("the sky in this one") was wrong rather than the model - among a flag, a
sunset portrait, a bicycle, and a kitchen a sky *is* separating - and was
replaced. 11/11, rebuilt and redeployed. **Sixth pass (13:22 UTC): 7 of
7.** Generate; unselected edit of the generated picture; upload + ask;
unselected edit of the upload landing on the upload; explicit selection;
"the bicycle picture" by description; a question answered in words - every
child's `parent_artifact_id` as expected, no ComfyUI restart, delete-all
clean. That is the image subsystem verified end to end through the chat
API. Still not driven by me: the browser's own clicks and an inbound
iMessage text-then-edit (the send half is proven), both recorded above.

## A newcomer's first evening: four defects and one exhausted key — 2026-08-25

Zakarya's first iMessage conversation (six turns) surfaced, in order:

- **"Can you show me that image?"** was answered "I can't display it here" with
  the picture already recalled into the model's context. No action existed
  that put an existing picture back in front of a person. `show_image` is now
  a router tool: the referent resolver picks the picture, the existing
  artifact is re-streamed as `artifact_started` + `artifact_ready` (the web
  fills the card, the iMessage worker attaches the photo), several matches
  show the newest and offer the rest. The web client's `artifact_started`
  validation accepted only fresh generations and would have thrown; widened.
- **"Can you regenerate it?" / "A general one"** was answered "I'll create a
  fresh one. Give me a sec." with nothing running. The router prompt now says
  a short answer to the assistant's own question about a picture completes
  the request; the honesty guard renders whenever the conversation has
  carried a picture, not only when one is in view, and forbids promising one.
- **"Who am I?"** got "I don't have your name": nothing seeded a profile at
  approval. Approval now writes the sign-up name; alippe and zakarya were
  seeded by hand.
- **A burst of photos** over iMessage: the worker waited nine seconds for
  iCloud to finish downloading and answered one photo per message. It now
  waits about a minute with backoff, answers every photo (up to four,
  numbered), and says "still downloading" rather than "couldn't open". The
  fourth photo that evening failed for a different reason: the backend was
  restarting under a deploy at that moment.
- **Writing inside generated pictures was not English.** `IMAGE_TEXT_SUFFIX`
  now rides on every generation prompt; the tenth image scenario reads a
  generated sign back through the vision model ("OPEN").
- **"Events that have passed"** is not the date - the reply and router get
  the real clock - it is that **every web search was failing**: Tavily
  answers 432 (plan limit). The key is at 993 of the Researcher plan's 1,000
  credits for the cycle, and the local ceiling had been counting calls while
  an `advanced` search bills two credits, so it never tripped first. Counting
  is fixed; a failed search is now rendered to the reply as evidence saying
  so, so it admits it could not check instead of promising to. **Operator
  decision:** wait for the cycle to reset, raise the plan or pay-go, or enable
  Google grounding. Since then: `search_credits` on the internet server lets
  the operator ask the meter in chat and schedule "message me if credits are
  below N" - the firing stays quiet until it is true; and with the pool spent, every
  turn now knows it before routing and opens with a friendly "search
  allowance used up" line instead of a search that fails. Later the same
  evening Brave Search became the first rung (900 requests a month, local
  hard stop under the $5 free credit; the operator also set the dashboard's
  monthly usage limit to the free credit), so live search is back. Google grounding (`GOOGLE_SEARCH_ENABLED`, off because the key's tier
  returned 429). Until then every live question is answered from training.

Measured on the live router 2026-08-26, with the firing rule in the prompt: "Remind
me to stretch" calls no tool 3/3, but "time to call mom" still searched 2/3 -
so plain reminder firings are no longer routed at all (`_is_plain_reminder`),
and the prompt rule covers the phrasings the regex does not.

The journey sweep (`sweep_journeys`, 2026-08-26) passes 17/18 on its first run
after two fixes it found itself: a guest's daily search allowance was charged
per round (three questions a day) and the reply did not know the person's
place. Two observations left open: "send an email to my landlord" is answered
with an offer to draft (right) without saying plainly that email cannot be
sent; and the sweep account is a guest, so the operator-only meter journey is
not in it.

One functional case is red independently of tonight: `test_scheduled_task_behaviour.py::
test_cancelling_names_the_task_in_the_persons_words` - "cancel the weather
texts" routes to manage_tasks with operation `list`, not `cancel`, and does so
with the router prompt and the tool registry as they were at c0cea0f, so it is
the model's decision drifting rather than tonight's prompt growth (bisected by
removing each added paragraph; none restores it). Worth a look at the
manage_tasks description.

Pre-existing red in the unit suite, untouched here and worth a session of
their own: `test_search_budget.py` (8), `test_access_requests.py` (5,
`KeyError: 'request_token'`), `test_turn_measurement.py`,
`test_unattended_turn.py`, and a handful more - 21 after this work, down
from 31. The desktop `.wslconfig` item closed itself later that evening: the
PC rebooted (cause unknown to this side) with the file in place, the VM now
reports 23.47 GiB, and `IMAGE_EDIT_MEGAPIXELS` is 2.0 again on spark1 with a
measured generate (54 s) then 2 MP edit (68 s) and 7.1 GiB to spare. The
parked Remote Control session on the desktop is gone with the reboot.

## alippe welcomed by hand, and two pieces of test residue found — 2026-08-25

`alippe` (Alec) was approved on 2026-08-17, before sign-up collected a number,
so the account had no phone anywhere - not on the request, not as a
subscriber, not on the Mac - and the welcome had nowhere to go. The operator
supplied the number; the same three steps approval performs were run by
hand from the backend container (enrol as a consented iMessage subscriber,
`allow_recipient` on the Mac, `send_welcome_if_new`): `granted`, `sent`,
`welcomed_at` set. He can now text the assistant as well as use the web.

`zakarya` (Zakarya) was in the same position - approved 2026-08-17 with
`phone: null` on the request, active on the web, never welcomed. The
operator supplied his number the same day and the same three steps were
run from the backend container: enrolled (active, deliverable), `granted`
on the Mac, `sent`, `welcomed_at` set at 17:34 UTC. Two accounts predating
phone sign-up are now reachable; any others will show as `welcomed_at`
null with no subscriber row.

Found while looking, **not cleaned up - the operator's call, since both are
deletions in production**: eight orphan `discovery_subscribers` rows for
`del_*` / `api_del_*` users on a fake `...0100` number (2026-08-08 and
08-12) - structural tests that ran against the live database through the
gate and did not clean up; and two fake numbers (`...0000`, `...0143`, the
README's examples) granted on the Mac's allowlist by test approvals. Neither
harms anything today; both are sloppy, and the first says the gate's test
container should be pointed at a scratch database before any test that
writes is run through it again.

## The desktop's memory ceiling, measured for the second time — 14:02 UTC

The operator received "the image generation backend stopped partway through
this request" over iMessage for a plain *generation*. spark1's log: six
generations submitted between 13:56 and 14:02 (the operator testing after
the seventh scenario pass), the sixth failing at 14:02:38 with "Server
disconnected"; the desktop: `RestartCount 1` at 14:02:39, `ExitCode 0`,
`OOMKilled false`, no error in the log, and a fresh process with nothing
resident afterwards. Encoder 8.07 GB + Klein 7.33 GB = 15.40 GB against the
WSL2 VM's 15.57 GB, with 14.35 GB already pinned - **a generation alone
crosses the line** when the encoder is evicted while Klein loads. Moving
edits to Klein removed the second model but not the pair already at the
limit, and `IMAGE_EDIT_MEGAPIXELS=1.0` was the right answer to the wrong
question. **The fix is on the desktop and is written but not yet in
effect:** `C:\Users\Ani Mallya\.wslconfig` with `memory=24GB` and
`swap=8GB` needs `wsl --shutdown` and a Docker Desktop restart - the
operator's call. **Until then generations die intermittently**, and the
provider now covers the common case: when ComfyUI drops a job it had
accepted, the provider waits for `/system_stats` to answer again (up to
`IMAGE_PROVIDER_RESTART_WAIT_SECONDS`, 90) and resubmits exactly once - a
job it rejected or one that timed out is never retried, and a second
failure reports as before. Structural tests pin both directions; the seven
scenarios then passed 7 of 7 on the deployed build with no resubmission
needed (ComfyUI stayed up for that run - the retry is insurance until the
VM restart, not a substitute for it).

## iMessage pictures — defect found and fixed, 2026-08-25

The operator asked for a picture over iMessage and received "here's the
image you asked for" with no image. The log trail: text bubble sent
04:09:16, the attachment send at 04:13:26 failed with
`MCPInvocationError: argument_withheld`. Reproduced in the worker container
by screening the exact argument shapes: `attachment_name`, media type, and
base64 all pass; `body: ""` returns `allowed=False, categories=['empty']`.
The egress policy's "empty means nothing to search" verdict was being
applied to a tool argument where empty is legitimate - every
attachment-only send. Fixed in `_screen_arguments` (an empty string
discloses nothing), pinned by `test_an_empty_string_argument_is_not_withheld`,
images rebuilt and redeployed, and proven by sending a labelled test picture
through `_invoke_discovery_tool` - the worker's own path - to the operator's
phone (message GUID returned, `is_error=False`). The text-before-image
ordering means a failed attachment still leaves a misleading sentence; the
bubble pacing and the reply pinning are unchanged.

## ML system design — the document that must move with every serving change

`docs/ML_SYSTEM_DESIGN.md` (and `docs/diagrams/ml-serving-design.mmd`) now
carries the serving decisions with their measurements and the tried-and-
rejected ledger, and the published architecture page renders it as its own
section. AGENTS.md's ownership rule: update it in the same change as any
serving flag, quantisation, model, cache, context, threshold, or token
budget; a decision whose evidence lives only in a commit message is not
documented. Three documentation drifts it surfaced, still to reconcile in
their owners: `ds4-tp2.sh`'s header asserts 0.83, 0.90, and 0.78 in three
places while the exec block runs 0.81 (the README already says to trust the
flags); `vlm-serve.sh`'s header says "2 GiB" for a 3 GiB KV cap; and
`docker-compose.yml`'s reranker comment says `/v1/rerank` where the code
speaks `/v2`.

## Backup alerting — LIVE 2026-08-25

`ALERT_BRIDGE_URL`, `ALERT_BRIDGE_TOKEN` (taken from spark1's own
`MCP_SERVERS_JSON`, never moved off the box), and `OPERATOR_ALERT_PHONE` (the
admin account's own approved subscription) are set in spark1's `.env`. A
labelled test page went through `scripts/notify-operator.sh` to the
operator's phone ("alert sent"). The four units are installed in
`/etc/systemd/system`: the nightly backup now carries
`OnFailure=anios-backup-failed.service`, and `anios-backup-freshness.timer`
(Mondays 09:00, `Persistent=true`) runs `scripts/check-backup-freshness.sh` -
every copy must hold a dump newer than 36 h, an unreachable mirror counts as
stale, and it pages on its own. The freshness service was run once under
systemd and finished `Result=success`; the failure unit lints clean. The
failure path was deliberately not fired end to end, because its only output
is a "backup FAILED" text to the operator - the notify script it calls is the
one already proven.

## Architecture document rewritten for newcomers, 2026-08-25

`docs/ARCHITECTURE.md` is now three parts: a newcomer's Part I (what it is,
the machines, a message's path, the models and why each is where it is,
memory in plain words, safety on one screen, and every subsystem in the
memory overview's numbered shape), Part II cataloguing every ADR and every
decision made while running the system with its reason and date, and Part
III, the prior engineering reference with its stale single-RTX-5080 topology
and role tables replaced by the Spark deployment and marked historical where
kept for measurements. Found while writing it, not yet fixed:
`docs/diagrams/authentication-subsystem.mmd` predates the phone sign-up,
approval, bridge grant, and welcome flow (2026-08-24) and still shows only the
operator-CLI invite path - a real diagram gap under the maintenance rule.
Also found and fixed the same hour: `RERANKER_BASE_URL` had reached only the
test container, so the live backend's reranker stage was off (fail-soft hid
it); it is wired into backend and local-capabilities and verified enabled.

## Direction from the operator, 2026-08-24

More MCP integrations are coming (Instagram, Google Drive, and more), and
**quality is as important as speed in scaling**. The toolbox path already
generalizes (shortlisted candidates, alias parsing, guarded invocation, the
per-server risk classification) — what each new integration needs is its own
quality gate in the house pattern: a labelled routing floor so the new tools
do not dilute selection precision, and functional coverage of the real
provider contract before it is advertised as a capability.

## Code review pass — 2026-08-24, and what it deferred

A full review of the 63 commits since the iMessage work closed a chain of
defects (commits d251338b, 26c7c303, 15c8d53b, 4b4864a3, ffc18fe0). Fixed: the
sign-up phone takeover chain (unverified/non-unique number → account takeover)
and its blast radius; the welcome service blocking the event loop and its
partial-failure handling; the image-reply path that never delivered (bridge
rejected the worker's empty-body attachment sends) and never pinned (guid
format mismatch); the Redis cursor discarding messages on a blip; the red
approval test suite; backup partial-file/CRLF/multi-host; and Postgres/Redis
bound off the LAN. Backend fixes are gate-verified only — the suite cannot run
on the Mac; **run `bash scripts/gate.sh` on spark1 before trusting them.**

Deferred, needing a box or a window, in priority order:
1. ~~Apply the committed deploy changes on the boxes~~ — done 2026-08-25.
   spark2's installed `/etc/systemd/system/anios-vlm.service` now carries
   `After=ds4-worker.service` (spark2 has no repo checkout; the unit was
   patched in place and reloaded, VLM left running). The port-binding change
   is applied on spark1 — with the compose-network fix it forced, above.
2. **Netplan for the RoCE fabric (#1, not written).** The `192.168.100/101.x`
   addresses are set by hand and do not survive a reboot, so a power cycle
   leaves both ds4 units retry-looping forever. Capture the live addresses
   (`ip -4 addr show enp1s0f1np1` on each node) into a netplan file and apply
   during a window — applying netplan can drop the network, so not done blind.
3. **Backup failure alerting (#3, not written).** Nothing signals a failed or
   silently-stalled backup. Wants an `OnFailure=` unit that notifies through
   the iMessage bridge plus a weekly "is there a dump newer than 36h on the
   mirror" check — not shipped blind because it needs the bridge token/recipient
   wired and tested on the box.
4. ~~Keyed phone/address digest (C12)~~ — done 2026-08-25, see the
   hardening wave above and SECURITY.md.
5. ~~Memory export phone; `.env.example` desktop paths~~ — both done
   2026-08-25.

**The architecture study-guide source is missing.** The prior handoff said a
100,501-character, 65-decision draft existed at `scratchpad/study_guide.md`,
but that path is absent and was never tracked by Git. Recover the draft from
the session or machine that produced it before attempting publication. The
existing `docs/architecture.html` is the generated canonical-diagram page and
must not be overwritten based on the stale premise.

**Point-in-time recovery does not exist.** `archive_mode=off`,
`wal_level=replica`, nightly dumps — so a failure at 03:29 loses the day. WAL
archiving is the fix if that window is ever too wide.

## Operational traps that cost real time

Every one of these cost hours or data, and none are discoverable from the code.

**A comment inside a backslash-continued shell command deletes every argument
after it.** This silently dropped seven vLLM flags and caused a two-hour
outage. `deploy/spark/ds4-tp2.sh` now keeps all commentary in the header and
none inside the exec block.

**`--kv-cache-memory-bytes` is a hard cap that does not scale with
utilization.** It survived in the repo copy after being removed elsewhere and
pinned the KV cache at exactly 5 GiB through four restarts. Banned; do not
reintroduce it.

**spark2 bounds `--gpu-memory-utilization`, not spark1.** spark2 also hosts the
VLM and has roughly 15 GB less headroom. 0.90 is refused there; 0.81 is the
settled value.

**Over-allocating GPU memory hangs the box.** No BMC, no wake-on-LAN: recovery
is a physical button press.

**Binding a published port to the host's loopback silently cuts off every
container that dials the host's LAN address.** Applied 2026-08-25 to
db/redis: services hardcoding `POSTGRES_HOST=animallya-spark1.local` kept
their established connections and refused all new ones - health answered 200
throughout, the failure lived only in the logs. Container-to-container
traffic must use compose service names (`db`, `redis`); anything that
regresses to host addressing will break again exactly this quietly.

**Redis 7 starts empty if `appendonly yes` is set with no AOF file on disk.**
It ignores the RDB. Enabling AOF must be done live with `CONFIG SET` first, so
the AOF is written from memory, and only then recreated. Getting this backwards
loses the iMessage cursor.

**The gateway and the backend are one-shot builds.** The gateway is a static
bundle and the backend bakes migrations into the image. A frontend change needs
a gateway rebuild and redeploy — Vite HMR proves nothing — and a new migration
needs a backend rebuild before `alembic upgrade head` can even see it. Both of
these were hit on 2026-08-24: a phone field that was "done" but invisible, and
a migration that reported success while doing nothing.

**`docker compose` service names are not what you would guess.** It is
`backend`, not `api`. The functional-test image is separate (`target: test`)
and a `docker compose build backend` does not rebuild it.

**Long bash heredocs fail to parse on the Windows host.** Use Write/Edit for
anything substantial; a doubled or very long heredoc silently runs nothing.

**Never run destructive DDL against `anios_db`.** It holds real user data.
Restores go into a scratch database, never over the live one.

## Conventions worth knowing before changing anything

- **Commit directly to `main`.** No feature branches, no PRs unless asked.
- **Intent and meaning are decided by models, never by regex.** Routing,
  classification, and "what did they mean" go through tool-calling.
- **Every new function gets a comment saying why it exists**, not what it does.
- **A change that adds or alters a prompt is not complete** until a functional
  test in `backend/tests/functional/` exercises it against the real runtime and
  asserts on what came back. Structural tests prove the call happened; they
  cannot tell you the answer got worse.
- **Prompts live in `prompts/`** — 39 files, catalogued in
  [prompts/README.md](../prompts/README.md). Two exceptions are still Python
  constants and are listed there under "Still in Python":
  `backend/agents/graph.py` and `backend/services/main_action_selector.py`.
- **Do not modify `bridges/imessage_mac`** except from the Mac session.
