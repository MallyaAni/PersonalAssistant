# Candidate: restore the FOMC cut at the decision-day close

Status: IMPLEMENTED on branch `fomc-decision-close`, tested, NOT merged, NOT
installed. Owner's word: "yes donit" / "do it" (2026-10-23, in session) in
reply to "Say go on the Fed timing". To be installed after the 2026-10-23
close so the 2026-10-27 nightly (the eve of the 2026-10-28 decision) runs
under it.

## The change

1. On the eve of the decision, once the cut has filled, `event_execution`
   plans the restoration with `decision_close` timing; the nightly holds it
   for the balancer and writes the decision session as its `execute_on`.
2. The balancer (`market_balancer`) sends it through
   `desk/decision_close.py` as a market order on the decision session's last
   candle (3:45 PM ET), after the statement and the press conference; never
   earlier, never on a price level. It reuses `intraday_orders._send_one`
   unchanged, under the same paper lock; `intraday_orders.py` keeps its
   bytes because the original live-model history audit pins them.
3. On the decision night, a cycle that finished hands the account back to
   the ordinary planner the same night (`nightly_plan.released`,
   `handed_back`: tonight's clock step counted once), so the plan's buys go
   in at the next open.
4. A cut not filled by the eve restores at the next open as before;
   reconciliation waits for the session close before settling an unsent
   decision-close row; the board says "3:45 PM, after the FOMC statement".

## The evidence

`docs/research/fomc-lead-in-2026-10-22.md`, section "Where the post-decision
move happens". Since the June 2026 guidance change the overnight gap after
the decision was +2.0%, +4.3% and +2.2% on the book; over 2016-2025 it
averaged +0.05%.

## Install sequence (after 16:00 ET)

Merge `fomc-decision-close` to main, push, verify the identity equals
`release.proposed.json`, `install_leader_release.py --revision <merge commit>`
with the owner's authorization, deploy, ADMITTED host==container. The
publication of 2026-10-22 expires at 16:00 regardless; tonight's 19:30
nightly publishes under the release, so no `publish_now.py`.
