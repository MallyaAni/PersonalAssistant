# Execution-quote wording and verification flags

September 25, 2026. Display-only correction; no execution eligibility, action,
amount, ranking, filter, account or strategy calculation changes.

## Meaning preserved and corrected

An eligible IEX quote can have an unverified spread. The backend already sends
`spread_verified=false`, but the UI type omitted it and the collapsed BUY/size
row hid that limitation. Both the collapsed action and shared decision displays
now show `IEX spread unverified`. An eligible legacy row without the field says
`Spread verification unrecorded`; absence never implies verification.

The explanation now says the available quote covers one venue and the
consolidated spread is unverified. It no longer claims only one venue is quoting.
Tight IEX/SIP cases retain their own source-specific check descriptions; wide
SIP still fails the unchanged execution filter. Quote evidence is not a fill.

The real decision producer lowercases its clock blocker. The previous exact
capitalized match misclassified it as unavailable quote evidence. A shared
display-only helper now handles both cases and the legacy fallback. Visible
readiness says `Regular-session execution blocked`, with a full title explaining
that the regular session is closed or its clock unavailable. Raw API reasons
remain unchanged. This neither declares all venues closed nor disables the
separate overnight/premarket/postmarket display path.

## Acceptance and retained failures

**VERIFIED:** root independently ran 19 browser cases (12 new quote cases and
seven existing action/ranking cases), all passing. The agent's focused suite
passes all 12 cases in 6.808 seconds, with all 12 strict six-category diagnostic
records empty. Eight synthetic fixtures are generated through the actual
`execution_quotes.describe` and `decision_view.build`; root regenerated and
matched them after the parallel backend changes. No provider or account was used.

Cases cover tight/wide IEX/SIP, absent/stale quotes, false/unknown regular clocks,
legacy missing flags, expanded/full-panel views, refresh, reload and expiry.
They assert unchanged strategy actions, executable sizes and source/deadline
timestamps. A synthetic fresh BOATS overnight midpoint remains visible beside
a blocked regular-session BUY and no executable size. Root inspected the final
wide-IEX and overnight-clock screenshots.

TypeScript and the production build pass, with existing CSS/large-chunk notices
retained. Producer Ruff/format and all 33 unchanged diagram/page checks pass.
All seven changed frontend/test file hashes plus the unchanged lockfile match
the source manifest used for the final build.

**FAILED broader acceptance:** 263 pass / one fails, no skips/flaky results,
163.435 seconds; all 67 strict diagnostic records are empty. The existing
390 × 844 phone test demands both entire grade sections simultaneously in the
viewport after scrolling Evening into view. Latest has viewport ratio
`0.8955811262130737` on both the original and candidate bundle. That assertion
was not edited or loosened. Its interpretation requires separate investigation;
the full suite is not reported green.

**FAILED original desired behavior:** seven failures / five passes. Independent
review found the first correction still exposed raw clock wording in visible
rows; stronger assertions reproduced two failures / ten passes before the
final correction. Original, intermediate and final bundles remain distinct.
Harness-only JSON-import/locator errors and the changed legacy wording
assertion's original failure are also retained, not counted as new defects.

**UNVERIFIED:** deployed behavior, provider availability, live account execution
and investment performance. A separate pre-existing phrase remains outside
this checkpoint: `No fresh quote from available feeds` describes only the
display snapshot, despite separate fresh execution evidence being possible.
It is a follow-up, not evidence that every dashboard word is now precise.

## Evidence and artifact identity

Agent receipt `/private/tmp/anios-execution-ui-fix.aV4oym/RECEIPT.md`, SHA256
`90c51a736449e59707aad02a840cfeb5ffa30992d0373779c49572d13a773542`.
The directory retains original/candidate/reviewed source and build states,
browser reports, diagnostics, screenshots and exact commands.
Final asset `index-CD-q3LR7.js`, SHA256
`d557371561b3616e4d5e84810a0fb4954714835ab5b68307cf915e219a65ad5e`.
Root report `/private/tmp/anios-quote-rl-root.pM9CLO/root-ui-report.json`, SHA256
`d146822402a86c933585c341625200b3c17cef058635c900087022966648fd6f`.

Browser runs serve that exact built artifact over isolated container loopback
using cached ARM Chromium, not the stale deployed frontend. Network, provider,
account and user-browser access are excluded. No dependency installation,
service restart, laptop permission change, fit or historical replay occurred.
Only agent-owned temporary browser containers were removed; evidence is retained.

**Diagram impact: NONE — existing display fields and wording only.**
