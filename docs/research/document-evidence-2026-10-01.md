# Document evidence acceptance — 2026-10-01

Docling already supplies document extraction; no second parser was added.
The observed failure was malformed upstream output becoming readable evidence:
numeric or object-valued `md_content` was stringified, while invalid JSON and
top-level arrays escaped as unrelated exceptions. Four of six original checks
failed before the fix. Conversion now requires an object containing a document
object and string Markdown; malformed output raises `ParseError` rather than
entering the retry queue as an unreachable service or becoming searchable text.

**VERIFIED:** 20 tests passed across conversion evidence, existing parser,
knowledge paging and parse queue. Four existing integration cases skipped for
missing external fixtures/runtime; skips are not passes. The new real conversion
case called the configured Docling service at `172.16.8.6:5001` with a generated
public Word financial table. All quarter/revenue/margin cells survived actual
HTTP conversion and page-aware chunking, including the complete table despite
a smaller requested chunk size. Picture inference was disabled for that test;
there were no database writes, private uploads or model-service changes.

The separate page-two chunking case preserves the supplied page marker and
numbers. A Word document has no reliable physical pagination; the live Word
case does not claim PDF page-number accuracy or universal numeric extraction.
No source metadata or citation schema needed duplication: existing knowledge
ingestion retains its source/content hash and existing chunks retain page IDs.

Acceptance mounted the exact changed files read-only in the isolated Spark
checkout `/home/animallya96/scratch/open-source-source-20261001`, test mode,
image `anios-functional-tests` SHA256
`c8964e1233e1142b77e6ac2b24fda67ee110a0f8e4c95482c4799d8617e17fb0`.
The new test file passes Ruff; existing whole-parser lint findings remain and
were not waived. No prompts, trading policy or deployment changed.

**UNVERIFIED:** production release, arbitrary scanned PDFs and use of extracted
financial features in a profitable trading model. Extraction acceptance is not
a trading backtest.
