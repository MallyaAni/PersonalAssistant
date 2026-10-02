# Frozen pretrained entry challenger

Registered before any stock inference. Compare one pretrained challenger,
Amazon Chronos-2, rather than select among model outputs. The CPU adapter is
research only and has no order, production-data or inference-service writes.

Official sources checked on 2026-10-02:

- [Model card](https://huggingface.co/amazon/chronos-2): Apache-2.0, 120M
  parameters, CPU support, 8192 context and 1024 forecast observations.
- [Technical report](https://arxiv.org/abs/2510.15821): real and synthetic
  pretraining; forecasting accuracy is not demonstrated trading profitability.
- [Official implementation](https://github.com/amazon-science/chronos-forecasting):
  direct marginal quantiles, not sampled joint trajectories.

Pin the earliest uploaded weights/config revision
`95a9710e2596287d08352589f42634fa5abdf0a7`, uploaded 2025-10-30 at
14:58:57 UTC according to the publisher's commit API. Actual pretraining
observation cutoff is undocumented. Earlier backtests cannot claim a model
that existed at their dates. Only the frozen 2026-08-17..2026-09-30 holdout
is eligible for a post-artifact-date diagnostic; prior history is context.
Retrospective grade/universe and past inspection limitations still apply.

Input is a causal, synthetic log-price chain of alternating regular-session
bar opens/closes. Each session's raw prices are divided by that session's raw
prior close and joined to the preceding normalized close. This cancels raw
split units without inspecting the current session's future official close.
Only completed bars enter context, with at most 2048 observations (about 39
full sessions). Missing/nonpositive prices and irregular session geometry
are unavailable, never interpolated. The adapter cannot repair an incorrect
vendor prior-close basis; caller provenance must establish it.
Use the longest consecutive available suffix within the preceding 39 actual
panel sessions, requiring at least two full preceding sessions. A missing cube
session breaks context; it is not bridged or replaced with a selected day.

At completed bar k, forecast through the regular close ten sessions later:
`2*(26-k-1+10*26)` observations, at most 570. The first predicted open is
the immediate entry; waiting uses the following open, except k=24 uses the
next session's second bar open after its first completed-bar decision.
The terminal regular close is explicitly a proxy for the protocol's official
daily close/auction endpoint. This endpoint difference must remain visible.

Use the fixed marginal quantiles 0.1..0.9. Their nine equal-weight values form
a bounded quantile approximation, not an exact expected return or calibrated
distribution. Difference of marginal log-price means estimates entry-to-end
return; entry-versus-wait means estimate execution advantage. The risk proxy
combines marginal standard deviations with the conservative correlation-free
sum, and never falls below trailing observed log-increment variance times the
forecast span. This bound applies to the approximate marginal distributions;
unrepresented distribution tails remain unknown. Do not label it calibrated
variance or treat it as proof of risk control.

Before stock inference: verify split-unit invariance, future-prefix exclusion,
exact clock indices, crossing/invalid quantile refusal, explicit missing
dependency, deterministic output and a real pinned-weight synthetic inference.
Record source/weights/config SHA256, package versions, CPU-only settings,
wall time and memory. No remote-code trust, GPU or production model changes.

Bound historical computation before outcomes: all book tickers at completed
bar 9 on each available holdout session, one fixed clock, at most 94*33 rows.
Unknown cubes and missing endpoints remain in the common denominator. These
are component diagnostics; they cannot establish full 25-clock live parity or
replace the live policy. Root's funded replay and benchmarks remain necessary.

Common-clock supplementary portfolio comparison: reset one fresh NAV1 account
at the declared holdout start, and let pretrained, boosting and ridge decisions
act only at completed bar 9. Compare all three at 0/10/25 bp with all 20 fixed
control reset phases and SPY/QQQ over exactly that holdout. Do not select the
best phase, count each model's missing opportunities, and retain the
regular-close versus official-close label difference visibly. This does not
replace each learned model's broader all-clock walk-forward evaluation.

Verified adapter acceptance on 2026-10-02: 19 tests passed, including the real
pinned CPU model, zero skips. Isolated environment: chronos-forecasting 2.3.2,
torch 2.2.2, transformers 4.57.6, NumPy 1.26.4. Two repeated 552-observation
synthetic forecasts were exactly deterministic; initial load 7.512 s,
inference 0.325 s, repeat 0.201 s, peak RSS 758,697,984 bytes on Mac.
This is synthetic inference proof, not historical trading performance.
Private proof: `/tmp/codex-chronos-entry-real-proof-20261002.json`; acceptance
log `/tmp/codex-chronos-entry-acceptance-20261002.log`. Downloaded model SHA256
`ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`
matches the publisher's pinned-revision LFS record; config SHA256
`ef1143bfdc9c0376d9a056eefca46cb4b1ec3d0ffacd541ff56feb40fb708031`.

Diagram impact: NONE — optional research adapter stays within the existing
market research model boundary; no runtime service or persistent store added.
