# Phone evidence visibility: correct the acceptance position

September 25, 2026. Test-only correction; no production layout change.

## Objective and first failing boundary

Keep the two original full-visibility assertions, 390 × 844 viewport,
fixtures, content, controls, horizontal-overflow and browser-diagnostic checks
in `frontend/e2e/desk-evidence-timing.spec.ts`. Correct only the native scroll
position chosen before checking both grade regions together.

**FAILED original:** scrolling Evening alone places the scrollport at 793,
with Latest's top at −43.125 px and visibility ratio 0.8955811262130737.
This reproduces on both the original and accepted f108 frontend bundles.
The two closed sections occupy 798 px and fit the 844 px scrollport; all
controls are reachable. This is a test-placement defect, not evidence of
inaccessible dashboard content.

**FAILED diagnostic attempt:** aligning the first region with `block: 'start'`
still clips 0.125 px (ratio 0.9996973276138306). That attempt was not adopted.
The retained diagnosis is
`/private/tmp/anios-phone-reachability.No5YGt/RECEIPT.md`, SHA256
`7f87d1b9ab08cca8faad99bdb562e9daae17c89c224b0deb2fd21a26623c2925`.

## Targeted correction and proof

One commented helper finds the real vertical scrollport, measures the union
of the two regions, rejects a union taller than the scrollport and centers it
using native scrolling. Both original ratio=1 assertions remain. The correction
contains no fixed pixel offset, style change, viewport change, skip or xfail.
Removing just the helper and its call restores every original test-file byte.

**VERIFIED:** the full nine-case file passes on each immutable bundle, plus
one focused phone run on each: 9 + 9 + 1 + 1 passes, zero skips, flaky or
unexpected results; all 20 six-category diagnostic records are clean.
Root independently runs all nine cases on the accepted f108 bundle: 9 pass,
8.402 s, zero skips/flaky/unexpected results, nine clean diagnostic records.
Root visually inspects the resulting phone screenshot. Independent source
review finds no assertion weakening. TypeScript and diff checks pass.

Final test SHA256:
`02ef37ad9083a9f174c463ef1c62e6037c3a3be6cb2825ba6a5a1458a9dcf279`.
The original frontend asset has SHA256
`8cb5034ec179fd3b0ea6a0a1e88438586362a15f4f21fa82522f27cf78d44c2a`;
the accepted f108 asset `index-CD-q3LR7.js` has SHA256
`d557371561b3616e4d5e84810a0fb4954714835ab5b68307cf915e219a65ad5e`.
At starting HEAD `a5de878f62c54d2d6713d783c4312b012272c0bf`, the frontend
tree is identical to f108; only handoff documentation changed between them.

Agent receipt: `/private/tmp/anios-phone-test-alignment.BqJV8j/RECEIPT.md`,
SHA256 `c6ace420dcfa60a15161d08d5c245f2271ca969bee99c9df46d6b1b87fa24d74`.
Root report: `/private/tmp/anios-display-root.4tLv17/phone-report.json`, SHA256
`30ee2ade8d064fd80311c2528c4ed9d0d8b656f7704f48611e738ae0cc66a370`.
Commands, source snapshots, prior failures and screenshots remain in those
directories. Cached headless Chromium runs the real browser workflow with
synthetic API data, no network, read-only source and immutable built assets.

## Limits

This corrects the earlier 263-pass / one-failure acceptance result; the
original result stays recorded. Combined regression of the separate pending
display-wording change is reported in its own checkpoint. No claim is made
about other viewports, physical devices, live data or deployment. No account,
provider, model, trading policy, production CSS or application source changed.

**Diagram impact: NONE — test-only native scroll alignment.**
