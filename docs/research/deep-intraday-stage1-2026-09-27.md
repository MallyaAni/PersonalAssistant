# Deep sequence models on the fifteen-minute bars, stage 1: results (2026-09-27)

Pre-registration: [deep-intraday-plan-2026-09-27.md](deep-intraday-plan-2026-09-27.md)
(hypotheses, kill criteria, and the two model families added before the run:
PatchTST and a frozen Chronos-Bolt encoder with a ridge head; eight trials
in all). Runs on spark1 from `448b7535`, store `~/deploy/anios/data/market`,
payloads in `docs/research/scorecards/deep_intraday_{ridge,cnn,patchtst,chronos}.json`.
Dataset: 81,612 rows (name, session) with five complete prior sessions and
a complete next session, 94 names, 2016-02-01 to 2026-09-24; 54,804 rows in
the choosing window 2016-2023, 26,808 in 2024-2026; 15,727 rows with an
A/A+ grade. Walk-forward: 33 refits every 63 sessions on an expanding
window with a 5-session purge, first test 2018-02-21. Inputs: the last five
sessions' 26 bars x (bar return, volume share, range) plus the gap and the
trailing 20-session return and volatility; nothing after the close of t.

## The table

Return head (`rank`: next session's open-to-close return, rank-normalized
within the date). IC is the daily cross-sectional Spearman correlation, t is
Newey-West at lag 20 over dates. "Top" is the equal-weight top quintile by
forecast, next session open to close, 10 bp one way on entries and exits,
against equal weight of every eligible name that date (the hurdle every arm
faces). "A only" restricts both sides to names the desk graded A/A+.
"Ctrl t" is the residual IC after regressing the return forecast on the
volatility forecast per date. Volatility head: out-of-sample R² against the
trailing 20-session realized volatility.

| window | model | IC | IC t | top vs hurdle bp/d (t) | A-only bp/d (t) | ctrl t | vol R² |
|---|---|---|---|---|---|---|---|
| 2016-2023 | ridge | +0.0132 | 2.11 | -13.1 (-10.2) | -8.4 (-3.1) | 1.53 | 0.131 |
| 2016-2023 | temporal CNN (13k params, GPU) | +0.0125 | 2.30 | -6.8 (-4.8) | -4.0 (-1.4) | 1.56 | **0.268** |
| 2016-2023 | PatchTST (71k params, GPU) | +0.0107 | 1.71 | -6.3 (-4.2) | -10.0 (-3.6) | 0.42 | 0.193 |
| 2016-2023 | Chronos-Bolt-small frozen + ridge | +0.0113 | 1.99 | -13.3 (-10.3) | -8.7 (-4.0) | 1.79 | 0.134 |
| 2024-2026 | ridge | +0.0061 | 0.89 | -12.5 (-4.9) | -16.6 (-2.8) | 0.75 | 0.211 |
| 2024-2026 | temporal CNN | -0.0073 | -0.89 | -9.6 (-3.5) | -10.5 (-2.1) | -1.40 | 0.266 |
| 2024-2026 | PatchTST | -0.0032 | -0.39 | -7.4 (-2.5) | -11.0 (-1.8) | -0.19 | 0.236 |
| 2024-2026 | Chronos frozen + ridge | +0.0023 | 0.28 | -15.7 (-6.6) | -17.5 (-3.1) | 0.02 | 0.118 |

**Verdict, every family: INSUFFICIENT EVIDENCE for the return signal.**
No family clears both floors on the choosing window (IC t >= 2 *and*
portfolio t >= 2). Two clear the IC floor by a hair (ridge 2.11, CNN 2.30)
and the third and fourth sit at it (1.71, 1.99): a real but tiny
cross-sectional signal, IC about 0.011-0.013, that costs more to trade than
it earns - the top-quintile book loses 6-13 bp a day to the hurdle at 10 bp
costs because a daily quintile turns over most of itself. It adds nothing
to the grade (A-only lines all negative). On 2024-2026 the IC is zero or
negative for three of four. After the volatility control the residual t is
0.4-1.8: a good part of what the return head learned was volatility.

**The volatility head works, as the literature said it would.** Every
family beats trailing volatility out of sample; the CNN doubles ridge's R²
(0.27 against 0.13) and holds it on 2024-2026 (0.27). This is the one
result in the study that a deep model earns over a linear one.

## Reading it

1. Eight trials, one configuration each, no search, kill criteria fixed
   before the run. The best IC t is 2.30 on the choosing window with eight
   trials counted; the expected maximum of eight null t-statistics is about
   1.4, so 2.3 is mild evidence of a signal of size 0.012 - which is what
   the portfolio test says is worth nothing after costs. The ceiling clause
   in the plan (IC > 0.05, t > 4) is nowhere in sight.
2. Transfer learning did not help. The frozen Chronos-Bolt encoder's
   embedding plus ridge reproduced ridge on the raw bars almost exactly
   (0.0113 against 0.0132; volatility 0.134 against 0.131): a forecaster
   pre-trained on point forecasts of generic series carries no information
   about this cross-section that the raw bars do not.
3. Capacity did not help either. The 71k-parameter PatchTST is the weakest
   return head of the four. This is the same lesson as the gradient-boosted
   rankers on daily data: the information is not in the model class.
4. Stage 2 (reinforcement learning as the sizing layer on top of these
   forecasts) does not start: there is no return forecast to size.
5. What is worth keeping is the volatility head. A next-session volatility
   forecast with R² 0.27 against trailing volatility is directly useful to
   a sizing rule that already pays attention to volatility - and to the
   question the session-anatomy study left open, whether "red days" are
   foreseeable inside the day. Registered as the next trial: the CNN's
   volatility forecast as the sizing input for the graded equal-weight
   book (the arm that scored 27.5-29.9%), against the arm without it, on
   the point-in-time scorecard. A volatility-scaled book is a different
   claim from a return forecast and gets its own kill criterion.

## Compute notes

The ridge and Chronos runs took minutes on CPU; the CNN and PatchTST took
14 and 32 minutes on the Spark's GB10 (the GPU the model server shares).
Two torch trainers at once overflow the memory the server leaves free
(PatchTST died with CUDA out of memory alongside the CNN; the Chronos
weights would not even load on the GPU afterwards and ran on CPU), so GPU
jobs on the Sparks are one at a time. The Hugging Face cache under
`~/.cache/huggingface/hub` is root-owned on spark1; `HF_HOME=~/scratch/hf`
works. A week-long run belongs on the desktop's RTX 5080, which needs an
SSH server on the desktop before this session can reach it.
