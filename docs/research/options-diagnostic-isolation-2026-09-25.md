# Raw option prices and optional diagnostic isolation

## Scope and contract

This fixes two reproduced boundaries in `live_technical`, not the options
strategy or the freshness of stored open interest. `technical_detail` now uses
the last raw `panel.close` only when comparing raw-dollar option strikes.
Adjusted technical features, scores and ranks are unchanged. A missing,
nonfinite or nonpositive raw price cannot fall back to an adjusted price.

The per-symbol optional-chain reader validates the stored frame before
calculating walls: required equal-length list columns, valid expiries and
call/put sides, positive finite strikes, finite nonnegative IV, finite gamma,
and integral nonnegative interest/volume. Boolean numeric values are rejected.
Absent stores, chains, empty frames and unusable reference prices still omit
walls. Supported filesystem/decoding/Arrow failures, malformed frame values
and overflowing gamma arithmetic instead return exactly:

```json
{"status": "unavailable", "reason": "options_data_unavailable"}
```

That marker contains no inferred levels. It preserves the symbol's other
technical evidence and the evidence for healthy symbols. Storage is not repaired
or rewritten. Generic storage `TypeError`, `KeyError`, `ValueError` and
`RuntimeError`, and unrelated computation defects, still propagate; this is not
a broader catch around the technical calculation or balancer.

The frontend models available versus unavailable walls explicitly and narrows
both displays before reading numbers. Valid presentation is unchanged. The old
JavaScript already omitted a status-only object because its numeric properties
were absent; no original browser crash is claimed. The real defect was the
producer losing technical evidence before it reached the browser.

## Acceptance

Starting main: `d12cfbec9ffad8f980306bc3706329351e2c4017`. All checks use the
mounted source or its identified production bundle, not a stale deployed image.

- **VERIFIED:** 147 relevant backend tests, zero skips, 16 existing empty-slice
  warnings, 2.35 seconds. The new 98-case contract covers price adjustments,
  missing data, 32 corruption variants, real Parquet readback, actual balancer
  and board calculation, JSON persistence and programming-error propagation.
  Opinion/provider/account inputs are synthetic; no model or broker runs.
- **VERIFIED:** three cases serve the actual produced snapshot through the
  authenticated ASGI `/desk/live` route. An unauthenticated request gets 401;
  bearer-token reads preserve prices, technical evidence and absent/valid/
  unavailable wall states. Snapshot/plan bytes remain unchanged. Only the
  unrelated search-metering account lookup is stubbed at the auth boundary;
  token verification and ownership checks remain real. This is not a deployed
  HTTP server or database-authentication acceptance claim.
- **VERIFIED:** 138 browser tests, zero skips/flaky/unexpected results, 60.228
  seconds; the new three cases cover both wall locations, technical evidence,
  navigation and reload. All 32 strict diagnostic attachments have six empty
  error categories. These are synthetic API responses, not live-provider data.
  TypeScript/production build, scoped Ruff/format, independent review and all
  33 unchanged diagram/page checks pass.

**FAILED before correction:** the expanded 95-case backend matrix produced
79 failures/16 passes against the original source. The initial 78-case matrix
and original reproduction remain retained. Independent review subsequently
found Boolean coercion and overbroad generic storage catches; nine permanent
regressions failed before their correction. The final 98-case original-source
replay includes the added HTTP acceptance; its result is retained separately.
It produced **80 failures/18 passes**, zero skips/warnings, 2.03 seconds.

Harness failures are not product failures. The first HTTP run passed its three
response assertions but its network guard caught three ancillary account-lookup
attempts; the final harness explicitly excludes that unrelated lookup. Frontend
evidence retains the initial wrong Chromium path, wall-text expectation and
read-only screenshot-directory errors. Introducing the accurate frontend union
before its guards produced 26 TypeScript errors; both original and final
production bundles pass the three final browser controls.

## What this does not establish

**UNVERIFIED:** current options freshness, provider OI effective time, AAOI's
actual chain or Barchart agreement, live prevalence, deployment, execution and
investment performance. A collection timestamp is not the OI effective time.
Already saved technical snapshots are not recomputed by this change.

The displayed walls remain **open-interest concentrations**, not measured
dealer gamma walls or guaranteed support/resistance. Their unchanged calculation
aggregates eligible expiries 1–60 calendar days ahead, excludes same-day expiry,
and uses the existing strike window and OI minimum. The separate unused gamma
proxy's assumptions/expired-contract treatment and the UI's OI wording and
duplicated `ET` remain separate known work. No options feature is promoted into
grading, sizing or `cash-bounded-breakout-rotation/3` by this fix.

No prompt, model, collector, account, holding or order changes. Full deployment
gates/postchecks have not run; not deployed. Deployment remains Spark-only using
`scripts/deploy.sh --wait-post`, subject to the unanswered collector activation
decision.

Evidence: `/private/tmp/anios-options-fix.RsXzen/RECEIPT.md`;
frontend `/private/tmp/anios-options-frontend.MoRRUI/RECEIPT.md`;
independent `/private/tmp/anios-options-independent.jyWfFz/RECEIPT.md`.

**Diagram impact: NONE — internal optional-data validation and field-level
rendering, without a new component, store, dependency or ownership flow.**
