# Legacy allocation policy-gradient qualification

September 25, 2026. This is a defect diagnosis and permanent regression, not a
corrected learner, a new training run, or a strategy-performance result.

## Finding and scope

At source checkpoint `8ca4f14f64f333de2c672192b73d68e46cbb84ab`,
`backend/cli/market_allocation_rl.py` uses the current softmax allocation itself
as the detached target of a log-softmax loss. For explored logits `z`,
`p = softmax(z)`, gross exposure `G`, weights `w = G*p` and scalar detached
advantage `A`, the implemented loss is:

`L = -A * sum_i(w_i.detach() * log(p_i))`

Its autograd derivative is `dL/dz_j = -A * (w_j - p_j * sum_i(w_i)) = 0`.
The loss value can change with reward without supplying the intended
reward-directed gradient. Gaussian noise added before both softmax operations
does not remove that cancellation. A naive finite difference that recomputes
the detached target would differentiate a different function.

**VERIFIED current-source defect:** exact source-extracted expressions were
executed with real Torch 2.9.0+cpu / Python 3.11.14, fixed synthetic inputs,
and no optimization or historical data. Twelve cases cover float32/float64,
uniform/asymmetric explored logits and rewards -2/0/+2. Uniform cases produce
exactly zero gradients; asymmetric maximum absolute residuals are
`3.217648014697261e-08` and `8.244829464602653e-17`, respectively.

A separately stated Gaussian score-function reference differentiates the log
likelihood of fixed sampled logits under their generating distribution. Its
gradient is `-A * noise / NOISE**2`, agrees with the independent analytical
expression, reaches magnitude 6 and reverses with reward. This reference is a
diagnostic control, not an implemented replacement or an expected-return claim.

Floating-point residuals can still move Adam because of its scaling. We have
not shown that any historical parameters stayed fixed. The complete original
training environment and saved-run/source attribution remain **UNVERIFIED**.

## What this changes about the research evidence

Only the legacy CLI's own `main` calls this `_policy_gradient` in the inspected
backend. `/3` does not use this trainer. The derivative-free cross-entropy
search arm does not use this loss. `market_offline_rl` imports shared helpers,
not this trainer, and uses a different objective. Later categorical growth and
intraday PPO experiments also use different objectives; this audit neither
validates nor rejects them.

Historical numbers in the legacy module, `desk/risk.py` and the changelog are
preserved. A run using the defective objective cannot support an interpretation
that a functioning REINFORCE learner was tested and found inferior. More
generally, those experiments do not establish that learned allocation is
worthless. The diagnosis also supplies no evidence that correcting the learner
would improve returns or drawdown. Existing rejected studies and their frozen
boundaries are unchanged.

The dated qualification lives here rather than changing `desk/risk.py` comments:
that file participates in policy source identities. No live policy, sizing,
grade, holdings, order or saved historical result is changed by this checkpoint.

## Permanent regression contract

`backend/tests/test_legacy_allocation_pg_gradient.py` executes only the actual
weight and inline objective AST, not the application entrypoint or trainer.
Ordinary tests validate extraction, reject objective mutations and check
zero-advantage/reference controls. Positive/negative-advantage numerical tests
are strict expected failures while the original defect remains. Extraction or
runtime errors must not be hidden as the expected numerical defect. Without
Torch, numerical skips are **UNVERIFIED**, not passes.

The permanent test is evidence preservation, not permission to retrain or
replace the retired experiment. Any future corrected learner needs its own
declared stochastic objective, gradient checks and separately authorized
leakage-safe economic evaluation.

**VERIFIED regression acceptance:** root independently ran the final test in
the cached Torch runtime: 23 passed / 8 strict expected failures, 0.79 seconds;
the separate `--runxfail` run produces 23 passed / exactly 8 numerical assertion
failures, also 0.79 seconds. There are no missing-runtime skips or warnings.
The implementing agent observed the same counts. Seven ordinary extraction
checks and sixteen zero-advantage/reference checks pass. The eight exposed
failures concern the intended reward gradient, not parsing or imports.

The image lacks pytest, so a narrow, checksum-matched copy of existing cached
pure-Python pytest dependencies was mounted read-only; nothing was installed
or downloaded. The agent's host-only run had 7 passes / 24 no-Torch skips and
is not numerical verification. Ruff/format and all 33 unchanged diagram/page
checks pass. Test SHA256
`bca4950cfcd618db33d269344a2f19d892b40a47fdc152cbe1eba3616c587259`.
Agent receipt `/private/tmp/anios-legacy-pg-regression.tSZptJ/RECEIPT.md`, SHA256
`d219daaeee52ee675a90c26bbf4e589a68e2dda43e1f34a03b5ce20689dcb0aa`.
Root evidence: `/private/tmp/anios-quote-rl-root.pM9CLO/rl-normal.xml`, SHA256
`f9afbc63eda6b0fee61be78382ce9a3d3a3249c3a2f768b092cb713fc1b5fe39`;
`rl-runxfail.xml`, SHA256
`6004baa2120a9cdb39287ccdd0b3eb646167b56ae18b90e34df280aff0827022`.

## Retained original proof

`/private/tmp/anios-legacy-pg-gradient.ZBn27B/RECEIPT.md`, SHA256
`1f3cc06208435904d1295febb3123048831443e268bc3a0272e27c998bca5116`.
The receipt records the exact isolated command and source extraction. Source
SHA256 `d12165e72432bfe4626d4b01ae63add622e5f5355a237947d7091de1696dd43b`;
result SHA256 `445a42b9cb84398fba35927437a389074792f3495a974616ceca6ae416090675`.
The cached Torch image is
`42b6e54382493d0b94b106063ce181bf04b67211cf4f8b6bcd75ff63c4ec5952`.
No model server, provider, account, optimizer, download or installation was used.

**Diagram impact: NONE — research qualification and isolated regression only.**
