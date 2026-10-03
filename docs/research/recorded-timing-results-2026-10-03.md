# Recorded entry and exit timing results

The frozen learned timing model does not establish an advantage over the 1%
gate. It wins October 1 and loses more on October 2. The stricter execution-delay
case also favors the gate over these two dates. Keep this model experimental;
live policy remains unchanged. This does not establish that 1% is optimal.

[Fixed protocol](recorded-timing-plan-2026-10-03.md),
[equivalent batching validation](recorded-timing-batch-validation-2026-10-03.md)
and [all 36 account results](recorded-timing-results-2026-10-03.json).
No fitting, parameter selection or new provider requests occurred.

## Measured results

Each date independently starts from its genuine archived prior-night paper
cash and whole-share holdings. All 15 October 1 and 10 October 2 planned rows are
retained, including duplicate symbols and redeploy legs. These are price-proxy
account results conditioned on recorded selection/sizing, not actual broker
profits or a carried live-policy backtest.

Ideal next-regular-open proxy, 10 bp per side:

| Session | Learned gain | 1% gate gain | First available gain | Learned−gate |
|---|---:|---:|---:|---:|
|2026-10-01|$2,438.42|$2,282.20|$2,416.93|+$156.22|
|2026-10-02|$1,865.70|$2,288.28|$1,865.70|−$422.58|

Under the fixed delayed proxy, learned−gate is +$17.39/−$442.44 respectively
at 10 bp and −$0.63/−$453.33 at 25 bp. Seven/four gate intentions have no later
regular open; they remain unfilled in the strict case. Both learned books
fill all 15/10 intentions under these proxies. No partial fills occur at the
declared costs; the cash/coverage constraints remain active.

Gross SPY references are +0.206%/+0.736%; QQQ +0.297%/+1.012%. All three
conditioned books outperform these references on these dates. Much of each
book's gain comes from existing holdings; this is not evidence that learned
timing improves stock selection or continuously beats either ETF. Complete
net returns, benchmark excess, fees and turnover at 0/10/25 bp are in the JSON.
There are no valid CAGR, Sharpe or regime-win claims from two reset accounts.

## Verified evidence

Evaluated source beb79528ce80c246596de573df12f7ea8d97ca3d; pinned CPU image
sha256:5c6c560537b3e7c70202edd6dfc872d299e2a268aa302ec23c3f48a3f49d099d.
50 native and 50 source-image tests pass, including 28 unchanged independent
account cases and 25-clock exact synthetic feature parity/future invariance.

All 36 saved ledgers independently reconcile to original inputs: cash,
whole-share holdings, 25 intention identities, first attempts, funding, fees,
execution prices/times, terminal wealth and ETF references. Verifier does not
refit models or resimulate policies. Report SHA
4816cea5b3e53e143fdb92e49afd173214550728813a95deb044a006c3577880;
275-file input inventory SHA
804537a07ded30117051007efc4f1479fd945e5dcd202ded35aa0359efbe0547.
Independent verifier SHA
d1bba6757b725fccdf43c90eb9a414c347476125f68719d5adeb10b525eda877;
verification-log SHA
c8426383ec810749c47a704f2bbf41b8d5d7d042a7254f5f9c3697a515bc9135.
Source-image test-log SHA
f38023edf109b7eb262cdf5db92556e30ec033e0072964bc5f880a071188e8d1.

Artifacts on Spark: private results under
`/home/animallya96/scratch/recorded-timing-batched-output-20261003-beb79528/results`;
logs under `/home/animallya96/scratch/sequential-execution-supervision-20261002`.
The original a1404a72 reference run remains active in its immutable checkout;
full saved-prediction/account equivalence is still UNVERIFIED at publication.
Do not restart it or call this pending check completed. Batched causal features
already match the original bridge exactly in the synthetic acceptance path.
A single bounded read-only watcher compares the two saved session objects
when the original finishes; it performs no inference or account replay. Its
proof will be `recorded-timing-saved-equivalence-20261003.json` under supervision.

## Limits

Raw SIP last regular closes provide prior anchors and final marks; 16:00-start
rows are unused and not asserted to be official closes. This prior reference
differs from training's Yahoo official close. Original archived grades/current
membership also differ from training's reconstructed inputs. September heads
are carried into October without refitting. Historical bar receipts/model
completion times and actual fills are unavailable; next opens are hypothetical
execution proxies. No midpoint fill is proved. Corporate-action caches contain
no relevant dated event, but lack publication proof. Source vintages and all
these limitations are retained explicitly rather than repaired with price ratios.

No original research inputs, production state, policy, UI or model services
were changed. Model container IDs/start times remained identical. A 1%
replacement needs stronger evidence; these results reinforce the recent
32-session finding rather than supporting promotion.
