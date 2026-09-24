# Fixed price-only neural ranking study — 2026-09-24

Declared before training or portfolio outcomes. This answers whether a small
price-only neural ranker improves scheduled selection inside the current rule.
It does not evaluate the existing frozen nightly neural model or establish a
new live strategy. All fundamental inputs remain missing because retained
frames discarded the currency/share-class evidence needed to verify them.

- Input: existing trusted corrected-exposure desk report, SHA256
  `d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26`.
  Preserve all 95 report symbols and its 2015-01-02..2026-09-18 calendar.
  Current survivor membership and reconstructed historical grades are explicit
  limitations. This differs from the frozen nightly model's 94-symbol cohort.
- Verify source OHLC/adjusted close/volume against stored snapshots no later
  than 2026-09-18, and calendar against XNYS. Missing prices are not filled.
  Held-mark gaps must fail accounting. Keep source file hashes with results.
- Eight existing growth-pilot price/volume features; append ten missing
  fundamentals and their usual missingness indicators. Training-only medians
  and scales, clipping at five standard deviations, 36→32→16→1 tanh network.
- Training decisions: 2018–2023, every fifth eligible session. Labels are
  twenty-session log total return from next close to close t+21; label endpoint
  must be before 2024-01-01. Seed0, AdamW lr0.001, weight decay0.001, batch2048,
  ten epochs, CPU two threads. No architecture/epoch/window search. Architecture
  and epoch count were previously examined; this is not a fresh discovery test.
- Evaluate 2025-01-02..2026-09-18; configuration boundary 2024-12-31. This period
  has already been examined in other studies. No 2016–20 or 2021–24 OOS claim.
  Report full period and calendar-year slices without restarting accounts.
- Compare ranking substitution against unchanged `simulate.LIVE_POLICY`, live
  reset cadence, FOMC lifecycle and funding. Preserve incumbent score coverage.
  This hybrid keeps the rule's midcycle entry/exit gates and can buy a negative
  neural forecast when the unchanged rules require it.
- NAV1, zero cash yield, costs at 10 and 25 bp one way. Live-rule buys next open;
  live sell timing/green-open guards remain unchanged. Midpoint fills unproven.
- SPY/QQQ controls use the existing funded constant-exposure next-open ledger.
  Equal weight uses the simulator, every21 sessions, causal complete eight-feature
  eligibility, no grade/FOMC/entry overlay. Label these execution differences.
- Report CAGR, negative drawdown, Sharpe, turnover with its denominator, rolling
  63/252-session wins against SPY/QQQ and incumbent. No promotion from this study.
  Preserve model, normalization, predictions, curves, input/source hashes and
  missingness. A source error stops the run; do not trim windows after outcomes.
