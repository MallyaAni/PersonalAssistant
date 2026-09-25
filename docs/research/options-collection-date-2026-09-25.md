# Options collection uses the New York calendar date

## Scope and first failing boundary

The options CLI previously selected the UTC date, while `technical_detail`
supplies the New York date to its bounded options reader. Between UTC midnight
and New York midnight, a first collection could therefore be stored in a
partition the reader considered tomorrow. Real synthetic CLI/Parquet diagnosis
reproduced this in 17 cases and controls; those passing diagnostic assertions
established the defect, not a fix.

The storage reader correctly enforces its as-of bound. The targeted correction
is in `backend/cli/market_options.py`: choose New York's calendar date once at
CLI batch start unless `--asof` explicitly supplies a date. That selected date
continues to govern all three existing uses: partition name, chain retention
through 180 calendar days, and printed expiry selection. It is not rolled back
to a previous trading session on weekends or outside regular trading hours.

## Preserved meaning and behavior

- `source_time` remains each file's actual aware UTC collection timestamp,
  not the batch date or an OI effective timestamp. A long batch can cross
  midnight without changing its already selected partition date.
- An explicit `--asof` is preserved, including past or future dates. It labels
  a current retrieval and controls expiry filtering; it does not request
  historical provider data or prove historical availability.
- A frame already stored for the selected date is kept byte-for-byte, with
  no transport call or sleep for that name. This is not an intraday refresh.
- Existing UTC-labelled partitions are not renamed, overwritten or migrated.
  A legacy tomorrow partition remains hidden from the bounded reader until
  that date is reached. The fix cannot repair existing saved live snapshots.
- Query-only `--walls` and `--walls-book` still read the unbounded latest frame,
  without provider calls or writes. Their expiry-selection date now defaults
  to New York's date; this does not make their source lookup date-bounded.
- No options formula, grading, trading rule, account, order, provider schedule,
  quote-collector setting or dashboard component changes.

## Acceptance

Starting clean main: `a10c38fac2d10653e2f1a6e51fef05d14b8357a7`; initial pull
current. The new `backend/tests/test_market_options_date.py` invokes actual
CLI parsing/main, refresh, chain parsing, book filtering, real Parquet storage
and the bounded options reader. Only the clock, tiny synthetic universe,
transport and sleep are controlled. Networking is disabled and guarded.

**FAILED original / VERIFIED candidate:** the same 32-case regression matrix
has 13 failures and 19 passes against the preserved original collector, then
32 passes against the candidate. Coverage includes UTC/NY midnight, both DST
transitions, month/year boundaries, immutable reruns, explicit dates, legacy
partitions, retention endpoints and query-only expiry selection.

**VERIFIED regression:** 267 relevant backend tests pass, zero skips, with
16 existing empty-slice warnings in neighboring level tests, in 2.56 seconds.
The collector and test hashes are unchanged before and after the run. Scoped
Ruff/format and all 33 unchanged architecture diagrams plus the published page
pass. The initial diagram harness referenced an absent browser executable;
that setup failure is retained separately from application results.

**UNVERIFIED:** deployed scheduler behavior, provider data/coverage, OI effective
time, current AAOI/Barchart agreement and economic edge. The direct reader's
visibility is not browser acceptance or proof that a cached dashboard refreshes
at midnight. No frontend change or new UI verification is claimed. Full deploy
gates and postchecks have not run; no service was deployed or restarted.

Diagnosis receipt: `/private/tmp/anios-options-date-boundary.hZJb4v/RECEIPT.md`,
SHA256 `f337845a12ad9473849c5fe8e7403986babb311187a3fa3dd330cda8bb572a92`.
Implementation evidence: `/private/tmp/anios-options-ny-date-fix.QV6WnI/`.
Root evidence: `/private/tmp/anios-options-ny-date-root.urxLB8/ROOT_RECEIPT.md`.
Wider JUnit SHA256:
`33ae14e7549dc2da762250eff9465b5fabe2603a60f5db8a3ff916549898a041`.

**Diagram impact: NONE — internal default calendar correction within the
existing collector, store and reader boundaries.**
