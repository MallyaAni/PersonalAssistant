# Kronos candle-path timing research

`kronos-path-timing/1-research` implements the candle-timing method frozen in
`specialist-contributions/1` before outcomes. It has no production imports,
broker requests, portfolio writes, fitted thresholds or live activation.

## Fixed method

One original prior-night allocation intent may receive a permission after the
first regular fifteen-minute candle completes, at 09:45 New York. The input
is exactly 252 consecutive completed regular RAW candles ending at the current
session's 09:30 candle. Missing bars, duplicates, late assumed publication,
invalid OHLCV, unknown calendar coverage, or a split inside that prefix refuse
permission. Dated corporate-action evidence is required; no price-ratio fitting
or eventual same-day official-close scale is used in the forecaster.

The pinned Kronos-small checkpoint is
`NeoQuasar/Kronos-small@901c26c1332695a2a8f243eb2f37243a37bea320`, tokenizer
`NeoQuasar/Kronos-Tokenizer-base@0e0117387f39004a9016484a186a908917e22426`,
and official code `67b630e67f6a18c9e9be918d9b4337c960db1e9a`. The existing
loader verifies those identities. Model loading and inference are CPU only.
The native public interface internally averages `sample_count`; this adapter
instead makes eight independent calls with `sample_count=1`, seeds 0–7,
temperature 1, top-k 0, top-p 0.9 and maximum context 512. It forecasts the
remaining regular slots: 25 on a full day, 13 on a published early close.
The official predictor derives amount from volume times mean OHLC.
[Pinned official inference implementation](https://github.com/shiyu-coder/Kronos/blob/67b630e67f6a18c9e9be918d9b4337c960db1e9a/model/kronos.py).

The buy cap is the 25th percentile of the eight sampled path low minima;
the sell floor is the 75th percentile of their high maxima. Bounds round
inward to the existing equity price increment. A buy cap above the observed
close or sell floor below it is unavailable. All eight paths must have valid
OHLCV; malformed samples are retained and refused, never removed, repaired
or redrawn. The same captured paths can support either side of an existing
allocation intent; the forecaster does not invent a sell, size or eligibility.

A permission expires at that session's reviewed close. A price opportunity
requires a consecutive regular candle OPEN strictly after actual observation
and favorable to the bound. Therefore the 09:45 open is excluded for a
09:45-observed permission; the first possible open is 10:00. Intrabar touches
count as ambiguity, not fills. There is no closing-price fallback. Missing
consecutive evidence and immature labels remain unavailable/immature rather
than being replaced with a later favorable candle. Future candle defects
cannot rewrite an already resolved opportunity.

## Artifact interface

`prepare(payload)` takes `symbol`, `session`, `observed_at`, `price_basis:raw`,
source SHA256, `availability_mode:recorded|bar_close_assumed`, `bars`, and a
`split_audit`. Each bar supplies aware `start`/`available_at` and OHLCV. The
audit supplies `basis:dated-actions`, source hash, availability time/mode,
coverage start/end and dated split ratios. `assumed_research` audit availability
is explicitly an assumption about later-vintage evidence, not attested original
publication. Future bars are not inference inputs. Prepared context and calendar
hashes, sample hashes, and immutable intent/permission hashes bind the artifacts.

`KronosPaths.predict(prepared)` returns `[8, remaining_slots, 5]`, ordered
open/high/low/close/volume; its `provenance()` records actual runtime and pins.
`permission(prepared, intent, paths)` binds symbol, side, session, positive
whole-share probe quantity, original client identity and creation before open.
The probe quantity is unrelated to normalized portfolio sizing.

`price_opportunity(order, future_bars, data_as_of=...)` returns a price/time,
status and ambiguous-touch count, with no funded quantity or cash claim. The
shared normalized portfolio ledger owns actual adjusted units, cash, sell
proceeds, cost accounting and grade eligibility. The separate `proxy_fill`
wrapper applies explicit cash/whole-share holdings/fees to the same price
loop for engineering acceptance; it cannot oversell or borrow and suppresses
already completed identities. No bid/ask, IOC, midpoint or exact live execution
fill proof follows from either interface.

## Captured evidence

The read-only export retained the fixed twelve symbols for all eighteen
September 4–30 exchange sessions: 216 opportunities, 198 complete causal
prefixes, 18 unavailable TSLA cases with absent raw partitions. No other case
was substituted. Original partition hashes, raw SIP metadata and actual
`fetched_at` values are preserved. Bar-close availability and effective-date
split availability are research assumptions; original publication is unknown.
The source is later-vintage. Frozen caches were not rewritten and no provider
request was made.

Inputs on Spark:

- `scratch/specialist-runtime-20261001/timing-inputs/manifest.json`, SHA256
  `15dc623d12afe58ad28936bd17658ac1a5edd1cc307804da5ab3259ac0e3749d`.
- Separate `execution-basis.json`, SHA256
  `faed9eb90c19c36e868ec85f6e929217156e69a41a4a7c7a845346e8b9cfed29`:
  198 actual auction-first-print closes, 18 missing. This is label-only economic
  unit evidence, never an input to a permission. A same-session factor based
  on this later close is unavailable at the earlier decision.

Three predeclared native CPU cases ran once, each producing eight complete
25-slot OHLCV paths. NVDA September 4 completed in 28.20 seconds and produced
a resting synthetic one-share buy permission. AAOI September 21 took 23.73
seconds and MSFT September 21 took 27.12 seconds; both contain inconsistent
sampled OHLC and are retained as unavailable. No redraw or alternative case
was used. The paths and exact native-adapter source identity are captured in
`scratch/specialist-runtime-20261001/timing-proof.json`, SHA256
`53d67507db89a8a0c969abc6eb79d69b15f522c0b5c8da6d89acd22abbfb3880`.
These are runtime proofs using synthetic intents, not actual account orders or
return results. Subsequent kernel guards and price-only ledger interface were
added without repeating inference; the recorded source hash identifies the
exact adapter used for those captured paths.

The complete fixed reset capture covers September 4 and September 21 for all
twelve original symbols: 24 opportunities. The three proof cases were reused;
nineteen new native calls produced the remaining available-prefix samples,
without any redraw. Six cases have coherent forecast paths; sixteen retain
all eight paths but are unavailable because sampled OHLC is inconsistent.
The two TSLA cases retain missing-prefix status and null context/samples.
There are zero inference errors and 4,400 retained sampled candles. Valid
forecast cases are AAPL/NVDA/AAOI/SPY/QQQ on September 4 and GOOGL on
September 21. This sparse availability is a material limitation of the fixed
method, not a basis for removing failures or retuning its quantiles.

The shared interface artifact is
`scratch/specialist-runtime-20261001/paths-artifact-v2.json`, SHA256
`994669305e721c2476f072320b11a1c6cfed98dc0ada8f9d60744f9180a9e7d9`.
It binds the original internal artifact
`a815d869d916ec7ce3f0fe0d9437f0c8ce9a2c688aaea9838cec6bc87cf3a93e`,
source manifest and additive `execution-basis-v2.json`, SHA256
`db86f5ad465ac99e08bf0cc778d2bbb480d53e790014e1cbaaae171fcbbb0d6a`.
The latter explicitly supplies `official_close` following the existing
`session_scale` auction-first-print priority and separately preserves the
last regular candle close. Original evidence files remain unchanged.

The native inference adapter is archived as `timing-inference-source.py`,
SHA256 `09583f4f47851f71b70bd3ee39359b719df92506021fcc76a61b64ec9245e505`.
A final boundary test reproduced acceptance of a caller-rehashed future
context. The final guard now reruns canonical prefix preparation rather than
trusting the supplied hash alone; genuine frozen inputs and all sampling
parameters are unchanged. No model inference was repeated after that fix.

Twenty-seven synthetic cases pass locally and on the exact isolated Spark source
(27 passed, no skips, 0.21 seconds); Ruff is clean. Reviewed implementation SHA256
is `444b0a0d7a6745afc12ca71b5fe116a0d1cfd70ff320c28a1436d3b948ad0fb7`.
They cover completed-bar/publication causality, future-prefix invariance,
split/basis gates, early closes, fixed quantiles, all-path validation, original
intent identity, rehashed future-context refusal, strict observation-before-execution,
opening gaps, partial
funding, no overselling, repeat suppression, expiration, missing/immature
outcomes and distinct price-only versus funded interfaces. Economic evaluation
belongs to the parent's fixed common funded study. No improvement, superiority
or adoption claim is established by these engineering checks.
