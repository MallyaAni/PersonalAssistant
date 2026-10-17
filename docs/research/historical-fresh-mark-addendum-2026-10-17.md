# Conditional fresh-mark addendum1 — unused pure selector

This explicit addendum leaves original contract033934aa, its query windows,
AAPL primitive/resolver, models and economics unchanged. It adds an unused
candidate-mark selector; no broker observation/account call or connected runner
is authorized by this component. Original results and failures remain immutable.

At each completed boundary T, the proposed post-venue observation is
**T+33.101s**: fixed quote-window end T+33s, plus declared1ms event uncertainty,
plus the already declared100ms hypothetical quote receipt delay. This is an
assumed observation clock, not actual historical publication or receipt evidence.

The **previous observation** is taken from the exact ReplayBroker
`_observed_at` and its detached native ledger. Its conservative upper bound is
that clock plus a separately named **declared1ms previous-observation clock
uncertainty**. This addendum explicitly applies the same numerical tolerance to
this additional clock domain; it is not measured accuracy or a relabelled actual
receipt. WAIT may retain T+31.100; sender state may retain T+31.200. The resolver's
new `_now=T+33` is not the previous observation and cannot replace that cutoff.
The proposed mark-observation clock must strictly advance `_now`.

Use the already sealed, demand-bound generic packet. For every actual positive
holding, including fractional split residues, first consider only events whose
reported event minus1ms is strictly after previous-observation upper, and whose
reported event plus1ms plus100ms is no later than T+33.101. Select the latest
such event before testing its book. Conflicting equal-time rows, an invalid book,
nonpositive sizes or spread above the unchanged25bp guard make that name missing;
do not choose an older favorable quote. A qualified mark is the bid/ask midpoint,
not a fill price or inferred executable size. Raw event text, event bounds,
assumed receive bound, native clocks and proposed observation remain separate.

Bind the independently supplied full current-state digest to an exact
ReplayBroker instance. Derive holdings and observation from that instance,
authenticate source bytes/mapping/manifest, require actual holdings within frozen
request coverage, and verify no state mutation. This does not independently prove
prior account chronology or issuer identity. Unresolved/request-name-only registry
entries remain inadmissible. Conditional mappings retain their explicit status.

Every remaining holding needs a candidate: no-fill and partial orders do not
remove that requirement. Full exits require no held mark. An empty required set
returns an empty candidate dictionary, never fabricated cash equity. Any missing
name withholds the whole candidate observation. **NAV always remains null** until
a separate future native `observe` and `account` admission; stale marks, unknown
cash claims, reservations and all other native accounting guards are unchanged.

A selected quote need not occur after batch-finalization33. It must be fresh
after the prior observation and hypothetically received by the proposed later
observation. Reusing the same raw event that separately supplied a fill reference
is allowed only if it independently wins this latest-qualified midpoint rule.
No claim of historically observed clocks, liquidity, execution or publication is
made. Existing final-archive correction and SIP-versus-current-IEX limits persist.

Future coordinator, bounded streaming state/packet storage, independent ledger
audit, generic reference resolver and full-run admission remain separate work.
Full-state hashing and in-memory packet validation have only bounded fixture
resource evidence; they are not full-horizon feasibility proof.

Diagram impact: NONE — unused pure selector, no service/store/runner connection.
