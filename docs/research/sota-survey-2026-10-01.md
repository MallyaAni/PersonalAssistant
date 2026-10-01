# What would make this a better system: a survey of the state of the art against what this desk has measured (2026-10-01)

**Research only. Nothing here changes the live book.** The operator asked
two questions on the night of 09-30: what would continue to make the
system better, and whether the state of the art had been surveyed. The
honest answer to the second was no: a handful of models had been checked
(Kronos, the LLM trading agents, chart-reading VLMs) and the repo holds two
literature memos (text signals, market structure). This note is the
survey, organised by the four decisions the desk makes, with each
candidate judged on three things: the quality of the published evidence,
whether it applies to *this* book (long-only, 94 US large caps, daily
grades, a 25% cap, a manual operator), and what this desk has already
measured on its own data. The last column is the proposed registered
study and a prior, so the next sessions have a ranked queue instead of a
reading list.

## What the desk already knows about itself (the baseline every idea must beat)

- **Selection is where the edge is.** The five analysts carry rank ICs of
  0.03-0.05 on the book; the tone analyst's 0.037 survived a leak test
  (`tone-validity-results-2026-09-30.md`). The simulator's graded book at
  25 bp costs: CAGR 28.5% on 2016-2023, 46.8% on 2024-2026, worst drawdown
  −43% / −25% (`structure-rules-results-2026-09-30.md` control).
- **Timing is closed, five ways.** Hand rules (stages 3-5, adaptive entry,
  seven structure rules), learned intraday models (ridge, CNN, PatchTST,
  Chronos), a K-line foundation model (Kronos), stops (seven variants) and
  volatility sizing all RECORD against `dip_or_close` on ten years at 20
  offsets. The oracle shows why: even the session's low captures only a
  few bp a buy. 467 registered trials.
- **Drawdown is the number that has not moved.** Nothing tried so far
  lowers the −43% / −25% worst drawdown; the universe study made it 9
  points shallower at the cost of 13-28 CAGR points.

So "better" means, in order: (1) a higher IC on *what* to hold, (2) a
lower drawdown at the same return, (3) fewer ways the live loop can be
wrong. Faster fills are not on the list.

## A. Selection: what to hold

| Candidate | Published evidence | Fit to this book | Registered study | Prior |
|---|---|---|---|---|
| **A1. Earnings-call and release *text surprise* (PEAD.txt)** — a regularised model of which words move the one-day reaction, used as the surprise measure | Meursault, Liang, Ross, Zhu (Philadelphia Fed WP 21-07): the text spread portfolio earns 8.0% cumulative abnormal return at one year against 4.6% for classic SUE drift, 3.9 bp a day of six-factor alpha, and it decays less than SUE in the second half of 2010-2019 | **Strong fit.** The desk already fetches the releases, has 3,451 scored, and the harness measures rank IC per window; the transcripts (memo study 3) are the missing text. Long-only large caps will show less than the paper's long-short | Arm 1: the desk's own tone fields as a *surprise* (tone minus the previous release's tone) at 20 and 60 sessions; Arm 2: call transcripts through the same reader; Arm 3: a learned word-surprise model, point-in-time (fit on 2015-2017, walk forward). Gate: IC ≥ 0.02 at t ≥ 2 beside the existing analysts and the T-S1 book gate | 35% that one arm earns a seat |
| **A2. LLM financial-statement analysis** — the model reads anonymised statements and predicts the earnings direction | Kim, Muhn, Nikolaev (2024): GPT-4 60.4% direction accuracy vs 52.7% for analysts, equal to a tuned ANN; the ANN fed GPT's narrative reaches 63.2%; "higher Sharpe and alpha" than other models, numbers not in the brief; anonymised to blunt memorisation | **Good fit, and partly built.** The fundamental and value analysts already read the XBRL facts; what is new is the *narrative* step producing a direction call. Look-ahead applies (the reader was trained on these years), so the post-cutoff window decides, as with Kronos | Arm: DeepSeek reads each name's last eight quarters of standardised facts (no names, no dates) and emits a direction and a rationale; scored as a stance. Gate as A1 | 20% |
| **A3. "Lazy prices": changes in 10-K/10-Q language** | Cohen, Malloy, Nguyen (JF 2020): firms that change their filings underperform; long-short 5-6% a year, concentrated in small caps and decaying | Weak fit: large caps, long-only; the effect is mostly in the short leg | Reported only, inside A1's transcript fetch (same EDGAR path): a change score on consecutive 10-Qs | 10% |
| **A4. Analyst revisions and insider trades** | Revisions: a well-known cross-sectional factor, strongest at one to three months; insiders: Cohen, Malloy, Pomorski (2012) opportunistic trades predict returns | Fit depends on data: revisions need a paid feed; Form 4 insider filings are free on EDGAR | Form 4 arm only: net opportunistic insider buying over 90 sessions as a stance. Gate as A1 | 15% |
| **A5. Options-market signals** (IV skew, IV spread, option/stock volume) | Muravyev, Pearson, Pollet (2022): the predictability is the omitted stock-borrow fee; after fees the strategies keep a third or less and the O/S strategy is unprofitable; 2006-2015 | **Poor fit**: the signal is about shorting costs, which a long-only book cannot earn | Closed on the literature | — |
| **A6. Cross-sectional ML on hundreds of characteristics** (Gu, Kelly, Xiu 2020 and the global edition) | Monthly OOS R² under 1% but economically large long-short portfolios, dominated by small and illiquid names | **Poor fit** at 94 large caps: stage 1-4 are this desk's version and found IC 0.01; the wide universe lost 13-28 points | Closed on own evidence; revisit only with a wider, shortable book | — |
| **A7. Foundation / price models** (Kronos, Chronos, TimesFM, Moirai; FinRL) | Kronos's own best is RankIC 0.025 on A-shares; the RL literature rarely survives costs and point-in-time evaluation | Measured here: Kronos IC −0.057 post-cutoff; Chronos 0.011 | Closed on own evidence | — |

## B. Risk and sizing: how much to hold

| Candidate | Published evidence | Fit | Registered study | Prior |
|---|---|---|---|---|
| **B1. Volatility targeting of the book** (scale gross exposure to a fixed volatility, 12% a year, not to the variance ratio) | Moreira & Muir (2017) in-sample; Cederburg et al. (2020) showed the plain real-time version does not help; **Xu (2024, CFR forthcoming)**: a constant 12% target plus two conditional switches raises Sharpe by 0.20 on ten factors out of sample (plain: 0.09), works best on momentum and market, survives 40 bp costs | **Good fit.** The book is a concentrated momentum-tilted long book; vol targeting cuts exposure in the storms that make the −43%. It trades CAGR for drawdown, which is the trade the operator has not yet been offered | Arm: gross = min(1, 12% ÷ realised 20-session book vol) (variants 15%, 20%); measured on CAGR, worst drawdown and the ratio; the drawdown criterion from S1g (−3 points on both windows at ±1 CAGR point) | 40% on drawdown, 10% on return |
| **B2. Regime gross** (the day-type model's tail probability gates exposure) | Regime-switching allocation (Shu, Yu, Mulvey 2024, sparse jump model, 2007-2024 with a one-day lag): information ratio 0.4-0.5 against equal weight, better drawdowns; caveat: regimes flip twice as often in real time | Fit: `day_type.json` already exists with these features; untested as a gate | S3 in the catalogue; run after B1, against B1 as the control, because a simple vol target may already capture most of it | 20% |
| **B3. Trend filter on the index** (out of the book when SPY < 200-day) | Faber (2007) and the trend-following literature: lower drawdown, similar return, whipsaw costs in sideways markets | Fit: trivial to build; the risk is turnover and missing the V-shaped recoveries this book lives on | Arm reported beside B1 | 15% |
| **B4. Position-level stops, vol sizing** | — | Measured here: every stop lost; vol sizing lost | Closed | — |

## C. Timing and execution: when to fill

| Candidate | Evidence | Fit | Status |
|---|---|---|---|
| **C1. Meta-labelling / triple-barrier** (Lopez de Prado) | A labelling scheme, not a signal; the public tests are on crypto and single assets; Hudson & Thames' own write-up finds it adds precision only when the primary model has skill | The desk's primary timing models have no skill to filter | Closed unless a primary model appears |
| **C2. Everything else** | Stages 3-5, adaptive entry, S1 ×7, Kronos K2 | — | Closed on own evidence (467 trials) |

## D. Reliability: fewer ways to be wrong live

Not models, but they move the real account more than any of the above:

- **D1. The 6-K classifier** refuses NBIS entirely and one ASML and SIMO
  release a year (`NEXT_SESSION.md` 10-01). A data fix with a measurable
  coverage target (4 a year per filer).
- **D2. The intraday leg's feed lag** (15-minute bars, 10-15 minutes
  behind a live screen): now shown as the price's age; the board should
  refuse to call a stale print "now" anywhere else it appears.
- **D3. The grade-parity drift banners** after a data-vintage change
  (tonight's backfill) need a plain explanation on the board, not only in
  the log.
- **D4. Test rot**: a date-pinned fixture broke the deploy gate tonight;
  fixtures that reference calendar dates should be relative.

## The ranked queue

1. **A1 text surprise** (three arms; transcripts are the new data; the
   harness exists). The one line with both strong published evidence and a
   measured foothold on this desk.
2. **B1 volatility targeting** of the book, the first candidate aimed at
   the drawdown rather than the return, with real-time-honest evidence
   behind it.
3. **A2 LLM statement reading** as a sixth stance, post-cutoff decides.
4. **B2 regime gross** against B1.
5. **A4 insider (Form 4)** as a stance.
6. **D1-D4** in parallel, as data and board work.

Closed, and why: options signals (borrow-fee artefact), wide-universe ML
(measured), price foundation models (measured), meta-labelling (no primary
skill to filter), stops and vol sizing at the name level (measured),
intraday timing in every tested form (measured).

## Disclosed

- The sources were read on 2026-09-30/10-01 through the research proxy;
  the Trading-R1 PDF could not be fetched (rate-limited) and its numbers
  come from a secondary review. Xu (2024) was read from the CFR
  forthcoming PDF; Kim-Muhn-Nikolaev from the SUERF policy brief (the
  Sharpe is stated there without a number).
- Priors are the author's and are recorded so that the outcomes can be
  scored against them.
