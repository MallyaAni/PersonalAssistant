# Settlement quantity persistence candidate

This atomic candidate starts from production N2
`ad44d536a70d5c037cb931836a3c9f48b014d84a` on
`codex/settlement-quantity-retention-20261017`. The initial tree was clean.
It changes only `paper.py`, a new targeted regression file, the changelog and
these proof documents. It is not deployed and does not renew source approval.

## Verified behavior and source boundary

Native synthetic regression: **15 test functions passed, zero skipped, 0.005 s**.
The exact runtime proof is
[`settlement-quantity-native-proof-2026-10-17.json`](settlement-quantity-native-proof-2026-10-17.json),
SHA256 `d40a024a58e6cb626c466d2fd4448c19b9d8596c09ea0312ffdab28cb995ad94`.
Root inspected both retained containers and isolation/source/log hashes.

- Candidate `paper.py`: `8db1777c9b15d6cc09613efa15530ae637f7968d0afda47ae733b5ce5eb7c045`.
- Test source: `3ab6d27427e1b591feb9e2d3854aaf7d489167200963209afd63df068d21c329`.
- Runtime image: `sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237`.
- Green container: `0429263d80c6cbe27b8ac7eed4a2b42c2868fc939da8704e580e72b945750d14`.
- The candidate source is an explicit read-only overlay, not claimed baked image
  content. Network is none; root filesystem is read-only; limits are one CPU
  and 512 MiB. No model, provider or actual broker calls occur.

The journal now retains independently observed broker `submitted_qty` and native
`sender_qty` after terminal pending removal. Desired eight, sender five, broker
five and fill five remain **terminal partial** relative to the desired eight.
Missing metadata stays unknown; old unannotated journal rows are not backfilled.
Fractional/adjusted broker observations are not floored. Disagreements and
malformed metadata retain raw non-diagnostic evidence. They add no execution
clamps, equality exceptions, inferred corporate action or altered control rules.

Tests cover durable readback, terminal and working partials, zero-fill expiry,
pending replacement, unknown domains, malformed/unrepresentable quantities,
adjustment/disagreement evidence, idempotence and explicit rebalance rollback.
Old positional `Settled` construction remains supported.

Source-only AST comparison against exact N2 confirms the only changed original
nodes are `Settled`, `settle` and `apply_settlements`; only two private readers
are added. Every other original class/function, including `PaperState`,
`PaperOrder`, planner and state-save functions, is AST-identical. Compilation,
diff whitespace and the explicit dataclass schema check passed locally.

## Preserved failures

The original regression against unchanged baked N2 ran ten functions in 0.007 s
with 15 subtest errors, proving absent quantity fields. Red container
`92f7b67c7db4ab73a671d5c159786fa986b19218aae7d75a7fb42ccdab252719`,
test SHA256 `cef393e52daf608bba7d9134bc43f92bfe805df897acff777591595dc0ca136a`,
and full logs remain under `scratch/settlement-quantity-red-20261017-v1`.
The green uses `scratch/settlement-quantity-green-20261017-v1`; red was not
overwritten or restarted.

Root review caught a pre-run draft that had appended the new fields to the wrong
dataclass (`PaperOrder` rather than `Settled`). It was never run natively or
deployed. Its complete source is preserved at
`/tmp/settlement-quantity-draft-failure-20261017-v1/paper.py`, captured at actual
2026-10-17T13:36:17Z, SHA256
`85fa58dc4db0cf43cfbabfe34699499bee09628c6434018234267e0bd05b788f`.
The corrected structural regression checks the original `PaperOrder` field list
and actual `Settled` keyword/positional construction.

## Remaining boundaries

The original immutable joined/reconciliation fixtures and old terminal journals
remain original. Existing OPG/day queue and `pending_replace` logic remain
unchanged; split accounting does not establish broker/sender equality.
Synthetic verification does not prove fresh operational acceptance, historical
quantity delivery or a complete model-funded execution account.

Source-approval renewal, config binding, broader canonical gates and deployment
remain unverified for this candidate. The guarded map still has 31 members, but
`paper.py` has a new digest and must receive exact reviewed admission. The root
agent owns that separate admission change. Diagram impact: none; this adds
metadata to the existing settlement boundary, no new flow/service/store.
