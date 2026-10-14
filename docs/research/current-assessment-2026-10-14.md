# Current stock assessment

The ordinary Stocks view previously showed live prices and charts but only
received combined intraday grades after the personal-account panel opened.
The grade detail also hid the existing live technical read in Stocks mode.
This failed the user's current-price assessment workflow on CRWV.

The existing owner-only live endpoint now projects the shared grade calculation
from fresh, matching candle evidence and returns per-stock expiry deadlines.
The Stocks list and ticker detail consume those assessments without a personal
account preview. The detail leads with the candle price, actual evidence time,
entry eligibility, and the existing live chart read. Technical and available
price-derived valuation votes refresh; stored fundamental and earnings votes
retain their declared scope. Saved signals, allocation weights, order shares,
execution timing and historical records are not recomputed by this GET.
Missing, expired or mismatched evidence explicitly makes the current assessment
unavailable, while the saved grade remains dated.

Private validation: 79 backend checks passed, zero skips, in 3.21 seconds at
scratch/fresh-assessment-tests-20261014-v2; owner 200/private-no-store,
foreign 403, anonymous 401, expired/mismatched/missing reads rejected,
original source records unchanged. The preserved v1 run had 77 passes and two
failures because old tests froze the freshness clock but not the request clock;
both clocks are now explicitly pinned, without relaxing evidence deadlines.
TypeScript and the production build passed. Nine compiled controlled browser
workflows passed in 20.0 seconds, including current grade changes, stale
assessment removal, dated saved targets, no personal preview or other writes,
chart reads and separate paper/research history. Those fixtures are not live
delivery proof. Canonical source352d915c is now deployed:10654 unit passes,
93 skips,6 xfails;100 real routing passes/0skip and cheap post green. The first
guarded attempt failed one unchanged declined-offer routing case and did not
deploy; preserve it. The identical case passed three isolated real-model runs
before the complete canonical retry passed with one worker.

Actual deployed gateway verification at17:22:33Z returned94 fresh assessments,
owner200/private-no-store, foreign403/anonymous401. Actual authenticated public
compiled browser exercised CRWV list/detail/chart with personal guidance closed,
current C at66.10 for the17:00Z candle,17:15Z assessment, dated saved signal and
target, live technical read, automatic expiry and next-candle recovery; zero
captured console errors/warnings. The exact API and serving bundle hashes and
private evidence are in current-assessment-delivery-proof-2026-10-14.json.
This applies to tracked names with valid evidence; it is not a validated dip
profitability ranking or a newly inferred funded target/timing decision.

This urgent patch starts from production 42b11a76, separately from the pending
historical-sizing and parity-checker candidate. The one full historical account
and its frozen source are untouched. No model, configuration, economics, paper
order or saved history changes. Diagram impact: none; existing live endpoint,
readers and UI dependencies remain, with additional freshness-qualified fields.
