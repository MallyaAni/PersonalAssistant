# Funded probabilistic timing — measured result

VERIFIED saved component evidence; live replacement remains UNVERIFIED.
The predeclared experiment completed once. Its independent saved-ledger audit
passed without refitting a model or resimulating an account.

The same 94-stock eligibility, grade-equal allocator, 20-session plans and
carried fractional-share book were used for both methods and the rule control.
Only the ordinary buy/sell act-versus-wait selector changed. Period:
2018-02-01 through 2026-09-30; initial NAV1; zero cash yield. Costs are per side.
Twenty overlapping planning phases are sensitivity checks, not independent
trials. Reused current-vintage grades/universe do not establish historical
point-in-time live-policy performance. Next-open prices are proxies, not fills.

## Incremental gain with allocation held constant

Median of within-phase candidate minus rule cumulative gain, in percentage
points of initial NAV; this is not annual return or a relative gain percentage.

| Timing model | 0bp | 10bp | 25bp | Positive phases at 10bp |
|---|---:|---:|---:|---:|
| Boosting empirical distribution | +1.18pp | +2.92pp | +5.16pp | 11/20 |
| Ridge empirical distribution | −0.04pp | +0.31pp | +0.80pp | 10/20 |

The small full-period median gains are not a reliable replacement signal.
At 10bp, Boosting lost 0.95pp against the rule in 2018–20 and 1.07pp in the
reused recent window; Ridge lost 3.93pp and 0.68pp respectively. Boosting gained
4.11pp in 2021–26; Ridge lost 0.66pp. No model, cost, phase or window was selected
or retuned after these outcomes.

| Full-period median at 10bp | Gain | CAGR | Drawdown loss | Sharpe |
|---|---:|---:|---:|---:|
| Boosting | 738.56% | 27.91% | 37.87% | 1.073 |
| Ridge | 709.19% | 27.38% | 37.79% | 1.056 |

Both arms exceeded SPY and QQQ in all twenty full-period phases. That mostly
reflects the shared stock selection/allocation: Boosting's median paired gains
against SPY/QQQ were 529.03pp/373.73pp, while its incremental gain against the
same allocation's rule was only 2.92pp. Beating ETFs does not isolate timing
skill. The full raw report retains all four fixed windows, rolling comparisons,
costs, phases, stock contributions, counters and unmatched opportunities.

## Proof and limits

Source: `2e49b234caf3ac286f2d00f90972bfb1a6908aa1`.
Whole-tree manifest: `ab6ff0d766c0449b36494f7c5f0443984633fd2cd2a97ffab9016521b8f51441`.
Pinned image: `sha256:5c6c560537b3e7c70202edd6dfc872d299e2a268aa302ec23c3f48a3f49d099d`.
Report: `9a367843ab2f529ba5123997967e435ae41481be5692314501e71f3aaad7be29`.
Independent proof: `1ab0a70e12592e8f85f2bd48e23dc60ca620a5e38c1fba396e2d5197d1876c69`.
Verifier: `98cf0683fb60abe762b9bf8750dbe14d77c0de898c3986dff12b323f189915c5`.
Verifier acceptance: 47 native and 47 pinned-image cases PASS, no skips.
Actual saved proof: exit0/no OOM; 120 new accounts, 103,844 intents,
1,111,840 decisions and 95,598 fills reconciled. Sixty completed controls and
six ETF accounts were authenticated and reused. Missing/partial/expired
opportunities and fixed-quantity attribution were retained. Attribution is
not investable compounded wealth.

Original artifacts on Spark1:
`/home/animallya96/scratch/probabilistic-funded-results-20261004-2e49b234/study`;
proof and immutable helper files:
`/home/animallya96/scratch/probabilistic-funded-verification-20261004-2e49b234`.

The component engine uses fractional shares and a locked first attempt. The
actual live planner uses whole shares, pending/rejected-order mechanics,
daily grade exits, deferred funding and FOMC handling. Those are material
differences. Shared nightly dispatch was extracted at `426a945f`, with 100
pinned-image integration/planner checks passing. It changes neither strategy
nor production and is a foundation for the next full-policy replay, not that
replay itself.

Next: preserve those actual planning/execution mechanics in the comparator,
identify where timing loses opportunity value, and evaluate buy timing and
sell timing separately before testing sizing. Improve the decision forecast
against its economically matched horizon rather than promote weak direction
accuracy or increase exposure to make this result appear better. Holding/profit
exits require a separate carried-position decision test; the source's 9.1%
example is an allocation, not a fixed profit-taking threshold. Live remains
unchanged. No promotion or deployment is justified by this experiment alone.
