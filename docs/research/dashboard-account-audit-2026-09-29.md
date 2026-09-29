# Dashboard and paper-account reconciliation

## Findings from the running system

The user acts on **Stock rankings** in a real brokerage account. It must not
present a missing decision, unknown funding or a delayed setup as a genuine
instruction to hold. The paper account is a separate account, not its trade
confirmation source.

On September 29 the broker reported 16 fills across eight paper purchases
(AAOI, COHR, HPE, LITE, MDB, MU, STX and SWKS), from 09:30:18 through
09:33:31 ET. The prior evening had submitted those buys. This was verified
with the existing read-only `fill_activity` request, not inferred from an
order acknowledgement or a backtest.

The current manual board and paper executor **do not follow identical rules**:

- The manual `/4` board applies `dip_or_close`: a completed 15-minute price
  trigger or the close window. The paper executor queues buys for the next
  open; ordinary sells use the following close, subject to its green-open
  cancellation rule. Event/risk orders have their own explicit treatment.
- The personal planner uses its own target-gap and fractional buy sizing.
  It does not reproduce the paper planner's complete rotation, deferred-buy,
  idle-cash redeployment and whole-share behavior.
- The personal board uses live breakout readings, whereas the paper planner
  receives the nightly decision's close-based entry map.

This is not justified by a proven timing improvement. The registered timing
study recorded every alternative without promotion: `dip_or_close` was
−0.1 bp/session (t −0.2) on the choosing window and +1.0 bp/session
(t 2.2) on 2024–2026. See
[execution-timing-2026-09-27.md](execution-timing-2026-09-27.md).

At 10:56 ET today's price/trigger files were current; HPE, MDB, MU and STX
already had buy triggers. Therefore waiting for a trigger was not the sole
reason all rows could read Hold. A read-only reproduction with the page's
default $100,000 sizing and unconfirmed cash returned Buy intentions for
the eight names, suppressed by unknown cash in seven and an expired quote
in one. These were reproduction inputs, not verified real-account balances.

Backend image `3ebbba089c87` and gateway image `fa02be0391bf` were running.
The deployed `live_policy.py`, `paper.py`, `decision_view.py` and API module
matched the inspected Fable main `60b3ac3` byte-for-byte. Deployment status
recorded `e8fafc6e`, September 29 01:35 UTC; the public gateway asset was
`index-DAhHtA19.js`. A checkout SHA alone was not treated as runtime proof.

## Display corrections

- Separate Wait, Cash needed, Blocked and Unavailable from genuine Hold.
  None of these display states creates an executable order or a trade size.
- Keep the original current-decision checks, data expiry and account
  isolation. A paper fill cannot overwrite a personal action.
- Show actual paper balances, account-value changes, holdings and fills in
  the account section. Put historical simulations in a separate collapsed
  section, with their own source/funding qualifications.
- Compute planned cash from the recorded active allocation targets, not the
  legacy `/3` book still retained on a `/4` record. Invalid targets stay
  unavailable; a legacy fallback is explicitly named.
- Add read-only `/desk/paper/history` and an account-value chart/table.
  Values are actual saved broker observations; missing marks, missing
  sessions and unknown/reversed recording order remain explicit.

There are 16 saved observations for September 4–28, but they are not a
certified closing-return series. For example, the September 14 record was
captured September 15 at 10:17 ET. Neither this history nor the existing
equity-minus-last-equity headline has a verified cash-flow adjustment.
The interface calls these **account-value changes**, not strategy returns.

One additional bounded read confirmed Alpaca's `1D` portfolio-history API
is available. It was not substituted here: the documented timestamp labels
the beginning of a window, not the equity valuation instant, and the
returned values differ from the saved observations. Do not silently date
them as 16:00 ET closes or claim verified flow-adjusted strategy returns.

## Shared strategy: authorized, not yet implemented

The user requested one consistent strategy for personal guidance and paper
execution. The adopted `/4` planner is the evidence-backed baseline; do not
promote a failed timing alternative just to make the labels match.

Full alignment needs independent personal execution state, not another
account's last rebalance, holdings, pending orders or cash. The initial
personal state is not on file. The user was asked whether to enroll from
confirmed holdings/cash at the next eligible session or supply the existing
rebalance context. Do not invent this choice or claim parity in the meantime.

The next implementation should:

1. Pass the same frozen nightly grades, prices, targets, entry map, buy
   blockers and event policy to `paper.plan` for both accounts.
2. Give each invocation its own account state, positions and cash. A preview
   or browser history acknowledgement is not a fill and must not advance
   the execution clock.
3. Advance personal state only from explicit confirmed executions, including
   partial, rejected, pending and missed orders. No real-broker submission.
4. Apply the same execution schedule and green-open sell convention. A
   missed opening trade is not automatically a new intraday buy instruction.
5. Prove identical inputs/state produce identical order baskets, while
   changing the paper account cannot change personal holdings or funding.

The display patch does **not** implement this shared planner, change the
paper strategy, or establish that `/4` is the best possible future strategy.

## Validation of the display/history checkpoint

- **VERIFIED:** 134 offline backend tests passed for paper history, desk API,
  paper planning, fill activity, personal isolation and the level gate.
- **VERIFIED:** 141 browser tests passed across `desk.spec.ts`, paper history,
  level gate, point-in-time line and candidate line. These use controlled API
  fixtures, not the deployed backend. Required-request and console-error
  assertions remain enabled; phone layouts and recording failures are covered.
- **VERIFIED:** TypeScript and the Vite production build passed. Existing CSS
  selector and bundle-size warnings remain. `git diff --check` passed.
- Five separate quote-display failures in `desk-execution-evidence.spec.ts`
  reproduce on unchanged Fable main `60b3ac3`; they are not included in the
  141-pass count and are not claimed fixed.
- **UNVERIFIED:** deployed behavior and shared-strategy parity. No deployment
  or personal-account initialization was performed.

Local test evidence: `/private/tmp/anios-paper-ui.iwGNMH/`; final browser output
under `verified-suite`, final production assets under `root-final-dist`
(`index-DbT9KV5o.js`).

Diagram impact: NONE — the display patch reads the existing account journal
through the existing desk API; no account, storage or execution boundary changes.
