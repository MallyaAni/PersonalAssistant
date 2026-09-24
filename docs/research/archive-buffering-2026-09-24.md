# Nested-study archive buffering — 2026-09-24

## Scope and result

VERIFIED: the offline nested-study archive writer completes a controlled
1,131,163,836-byte evidence document under the same 3 GiB memory limit that
OOM-killed the old writer. This changes document/file buffering, not the
economic experiment, packing format, source guards, strategy or accounts.

The original historical `market-run-02` remains interrupted: its final root
manifest is absent and its original whole-evidence digest is unverified. The
[recovered economic result](nested-market-validation-2026-09-24.md) still
rejects the new allocation gate. No historical fit, account or parameter was
rerun or retuned for this fix. No live deployment or automatic promotion.

## Implementation contract

`backend/market/nested_market_study.py` now emits sorted, ASCII-escaped canonical
JSON, including its final newline, in buffers of at most 65,536 bytes. Hashes
are updated incrementally. JSON files are created exclusively; short writes,
interrupted writes and failed closes cannot register a successful manifest
entry. File receipts count and hash the bytes actually read in bounded chunks.
The final manifest is still written last and independently read back.

`_pack` is unchanged: array occurrence numbering, copies, traversal, scalar
sentinels, ownership and hash scopes retain their existing meaning. Temporary
verification maps, packed trees and copied arrays are released after their last
use. Source/evidence checks still run before and during publication; saved
arrays and every file are checked against their declared receipts.

This is **not globally constant-memory serialization**. `_pack` still copies
container trees and arrays, and the standard JSON encoder can allocate an
entire escaped scalar string. The bounded claim concerns emitted document
buffers and file readback, not all allocations or every possible payload.

## Acceptance and provenance

Starting branch: `main`, clean before this task, at
`ebc33159e6546dab066dcbe7f45d84218daee093`; the initial pull was current.
The old source is an immutable Git export of that revision. Only the archive
module changes among the source files consumed by the controlled experiment.

- Old archive-module SHA256:
  `9d0a602bd6d1cbbcc512c5b00a1b193504f6cacacfb5569545eb4d2899be89d7`.
- Accepted new archive-module SHA256:
  `6417dbd925f6ea9970911d5f49a0fbd1005273e6fdfe38b7268b7f9c609c1a5c`.
- New test-module SHA256:
  `7f7706960961fe8de5816d3af165029ad3a5b8f193a10e807158475ef73d0d02`.
- Runtime image: `anios-functional-tests`, image ID
  `sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.
  The regression suite used `PYTHONPATH=/deps:/app` with OpenBLAS, OMP and
  MKL each set to one thread. The controlled memory runs instead used
  `PYTHONPATH=/code:/deps` and `OPENBLAS_NUM_THREADS=1`; OMP/MKL thread
  variables were unset. Source snapshots were mounted read-only. Both memory
  runs had separate memory and combined memory-plus-swap caps of
  3,221,225,472 bytes each, with no additional swap allowance.

VERIFIED: **1,096 passed, one deliberately deselected, five existing warnings**
in 37.65 seconds across journal, producer, allocation, nested-fitting,
source/input/study and serialization tests. The cached historical experiment
was deliberately excluded. The **33 new serialization tests** pass, including
the reproduced old `arrays.npz.read_bytes()` boundary, canonical-byte/hash
parity, Unicode/surrogates/floats, dataclass and array packing, bounded reads,
short/interrupted writes, failed close, corruption and source/evidence mutation
guards. An 8 MiB multi-scalar payload uses less than 2 MiB additional encoder
allocation. Scoped Ruff lint/format and diff checks pass.

A separate 90-case helper probe exercised the actual helper source at buffer
sizes 1, 2, 7, 127 and 65,536; all byte/hash and buffer-bound checks passed.

Published implementation checkpoint:
`5040fdf0eebc28a432975a5ea1f2b4f9cbe54222`, pushed to Spark, then to GitHub
from Spark. The exact clean tree repeated the same **1,096 passed, one
deselected, five existing warnings in 36.76 seconds**. The command, tree ID,
source hashes and final JUnit are retained at
`/private/tmp/anios-archive-committed.p0nzs4/`; JUnit SHA256
`aa166b8372c939cae0aeebf3cc5ea886aa7702b000263fd74615a85934950fb7`.

## Full-size controlled experiment

The fixture reconstructs a previously completed **synthetic** archive. It adds
13,388 references to an existing training-input receipt as explicitly labelled
metadata pressure, not independent observations or new fits. Account and fit
values are unchanged. A 128-repeat calibration separately verifies identical
old/new serializer inputs before the full-size source-bound comparison.

The old fixture predates the `currency_scale_checks` diagnostic. Its initial
observer comparison failed solely on that new verification field; every older
field was identical and the CLI succeeded. Both controlled fixtures received
the same newly verified diagnostic receipts after all 20 ledgers passed. The
failed observer attempt and this adjustment remain in `OBSERVER-NOTES.md`.

- **FAILED old writer:** exit 137, Docker OOM event and `OOMKilled=true`,
  118.57 seconds. The full evidence JSON, arrays, sources and journals exist;
  the final root manifest does not. Its saved evidence JSON matches its
  independently calculated oracle. The sampled cgroup peak is at least
  3,162,771,456 bytes; exact process maximum RSS after SIGKILL is unavailable.
  The precise statement at the kill is not established.
- **VERIFIED new writer:** exit 0, no OOM or timeout, 181.54 seconds for the
  observer (184.08 seconds including orchestration). Maximum process RSS is
  866,692 KiB (846 MiB); exact cgroup peak is 2,027,298,816 bytes (1.89 GiB).
  All **218 final manifest entries**, **146 arrays**, **80 old/new journal JSON
  files** and **20 standalone CLI replays / 544 closing marks** reconcile.

The same-input calibration digest is
`1f1025f14377bdb7ddc0a95dd8839ef76d00270683d40a030858185aa80042cc`.
Full-size economic/metadata content excluding source identities has the same
hash in both runs:
`d6708835c90a69731502a2c099cc5453b6e782add3e9dc30cd32dd0c4da95af1`.
Complete evidence hashes legitimately differ because they bind different source
versions; source checks were not removed or monkeypatched to force equality.

Accepted new evidence digest:
`45329d74fdafd43cba2172bcde5612df456e7e1415fd45f353ed852d4051d74b`.
New final manifest SHA256:
`bb8ac7bd9644c060abb0e2755e423678536efaa8ffb3e1cf387335a88fb200f9`.
New full-size proof SHA256:
`35d6e49a23613db2451d0bb774e7e1b8feb937aa1d7c7eba0a90021eeecfc96b`.

## Retained evidence and remaining work

Local evidence roots:

- `/private/tmp/anios-archive-buffering.5HrHog/`: full-suite JUnit and synthetic
  fixtures, actual helper source/probe, and an independent unchanged rehash of
  all **634 original historical files / 1,688,236,289 bytes**.
- `/private/tmp/anios-nested-market-acceptance.teTufe/archive-memory-acceptance.doHMXX/`:
  frozen old/new source snapshots, `fixture_driver.py`, `run_experiment.py`,
  startup commands, runtime identity, execution/memory logs, both old failure
  and new complete archive, calibrations and all standalone CLI receipts.
  `acceptance-summary.json` SHA256:
  `b4b219ee1edf54b2c3f0a7d953eef74bc9d5116598b9c6f64f6210a82597f090`.
- Parent acceptance directory: `serialization-baseline-01.xml` preserves the
  old boundary failure; `serialization-focused-01.xml` preserves the 33-test
  acceptance. These are distinct from the controlled fixture-age mismatch.

The original historical failure is already retained at
`/home/animallya96/anios/data/market/research/nested-market-20260924.xEBPm7/`.
It must not be overwritten or given a fabricated completion manifest.

The fresh archive-buffering retention directory is
`/home/animallya96/anios/data/market/research/archive-buffering-20260924.uw4mdckq/`.
The main payload now passes remote readback: **5,491 files / 2,378,027,323 bytes**,
zero missing, changed or unexpected files. The 52 duplicate symlink aliases
were explicitly excluded; all unique evidence and source files were retained.
All 4,451 files in the earlier historical archive also match before/after.
Retention receipt `retention/retention-readback.json` SHA256:
`04bea694267ea8a9cf060af168e08f22b4d0ca8f04ce5f20e4893ea3488983ca`.

The exact-commit supplement at `committed-5040fdf-n3zunsqw/` also passes complete
readback: **2,275 payload files / 67,134,707 bytes**. Its separate retention
receipt SHA256 is
`dee86f187aaf0991a6ee72e08f3f263491048333a4a18e289208166154fe4e53`.
Both verifications preserve the original main payload and the earlier market
archive. No transfer remains running. See the [handoff](../NEXT_SESSION.md) for
the separately retained dashboard diagnosis and subsequent work.

Full deployment gates and deployed behavior remain UNVERIFIED. This task adds
no model prompt, API, UI, datastore or trading-policy change. Diagram impact:
**NONE — internal archive buffering; unchanged data flow**. Historical input
causality, membership and financial-quality coverage still need independent
audit before the incumbent's reconstructed returns are treated as investable.
