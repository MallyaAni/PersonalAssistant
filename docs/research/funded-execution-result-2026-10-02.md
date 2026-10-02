# October 2 funded execution diagnostic

Recorded with `93c63ab6`; evaluated with `6b9ddfa8`. The original protocol and
all source observations are unchanged. Five fixed opportunities (four entries,
one full exit) were observed 233 times from 15:00:15 to 15:59:45 New York.
The closing supplement uses matched paper-broker receipts and delayed SIP
endpoint labels, not assumed auction prices. The first-hour/morning decisions
are outside this cohort.

| Cost per side | Incumbent fills / expired | Candidate fills / not attempted | Candidate gain versus incumbent | Incumbent fees | Candidate fees |
|---|---:|---:|---:|---:|---:|
| 10 bp | 2 / 3 | 1 / 4 | −$7.81 | $4.85 | $3.72 |
| 25 bp | 2 / 3 | 1 / 4 | −$6.11 | $12.13 | $9.30 |

Incumbent trade notional was $4,853.62; candidate notional was $3,720.60.
Closing exposure was approximately 70.05% versus 68.99%. Candidate execution
remains a conditional IEX displayed-quote proxy; actual broker fills are known
only for the incumbent's closing orders. Stress-cost quantities are funded
counterfactuals, not a claim about broker commissions or candidate executions.

The candidate avoided buying outside its bounds but did not improve the closing
paired gain. Repeated wide single-venue quotes and prices outside the bound
prevented its four entries. This sample does not determine which restriction
should change, and no thresholds, windows or feed assumptions were retuned.
Keep the candidate experimental and the live strategy unchanged.

## Evidence and limits

Start SIP evidence: one complete page, 8,533 rows; end evidence: six complete
pages, 55,039 rows. Raw bytes, request/token chains, source timestamps and
receipt clocks were retained. The original latest NTAP starting quote exceeded
the registered 25-bp spread budget. Its identical held quantity cancels from
the paired difference; it cannot supply a valid initial total NAV. Total gain,
percentage return, turnover fraction and same-capital SPY/QQQ excess gain stay
unavailable. Endpoint evidence cannot establish drawdown or annualized metrics.

The original replay had a terminal-state defect: an unsupported closing auction
could become a fabricated later market fill. The failure was reproduced and
fixed in both replay engines before scoring. All five control opportunities
remain unsupported in the original proxy report. The separately named observed
closing supplement resolves only matched receipts: two filled, three expired.
Expired orders never become later simulated fills. No order or live holdings
were written and no policy was activated.

Exact-tree validation: 192 source-image tests pass (17 optional native cases
skip there); all 82 relevant native-environment tests pass without skips.
Ruff and formatting pass. A separate artifact verifier checks the full receipt
chain, matched broker IDs, original/evaluation implementation hashes, both
endpoint byte chains, nonnegative cash/shares, missing metrics and terminal
outcomes without rerunning or tuning the economic comparison.

Private Spark evidence:
`/home/animallya96/scratch/execution-forward-20261002/cohort-20261002-consolidated.json`.
Report SHA256:
`de51edbd77d9acfd45de6f9986f74abbb9d46d8b15ac5306487cfd69784e0a41`.
Proof: same directory, `cohort-20261002-proof.json`.
Logs: `/tmp/codex-funded-forward-{record,value,closing-tests,native-closing-tests}-20261002.log`.

Next evidence must come from prospective earlier-session cohorts with the same
fixed candidate and explicit excluded opportunities, retaining independent
funded books, actual receipt outcomes, missing marks and SPY/QQQ references.
Do not concatenate reset daily accounts into a compounded return. A broader
live-policy comparison requires carried selection, funding and corporate-action
state across sessions; this component diagnostic does not supply that evidence.
