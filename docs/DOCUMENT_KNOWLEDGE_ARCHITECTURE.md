# Document knowledge for AniOS

Status: LIVE (deployed f3dca29, then 61435af for room shares, 2026-09-02). Phases 1-4 VERIFIED in the deployed
image, including a live acceptance through the real API; the operator's own
iMessage run in the Groupie room is the last confirmation. This describes the
capability as built. Sections marked EXISTS are already built and VERIFIED; sections marked
NEW are the work. Written in the memory-overview shape: numbered stages, the
stores each touches, and where the person stays in control.

## What it is

A person hands AniOS a document — an itinerary PDF in the Groupie room, a lease
on the web chat, a scanned contract by iMessage — and it becomes durable,
retrievable knowledge: parsed, embedded, stored against them, and drawn on
whenever the assistant answers, with a citation back to the page it came from.
Not a separate "search your files" mode; the same memory the assistant already
reasons with, extended to what a document says.

The design principle that makes it fit an always-on assistant:

> **Parsing is bursty and lives where the GPU is (the desktop, sometimes off).
> Retrieval is always-on and lives where the assistant runs (the Spark).**

A document is parsed once, when the desktop is reachable; from then on it is
answered from the Spark whether the desktop is awake or not. Ingestion tolerates
the desktop being off (a durable queue); answering never depends on it.

## The five stages

1. **Arrive.** A document attaches on any channel — iMessage one-to-one, an
   allowlisted room, or deep-matter. In a room the document is read whether or not the
   assistant is named - it is context, like observed chatter - and the
   confirmation is sent only when it is addressed. The share is observed into
   the thread by name so it is what the next question means, and the sharer
   keeps their own copy (sharing is their own act) - never another member's.com. Today the iMessage bridge accepts
   images only (`INBOUND_IMAGE_TYPES`); NEW: extend the allowlist to PDF, DOCX,
   PPTX, ODT, RTF, and common image scans, each gated by a magic-byte check the
   same way images are, with a per-type size cap. The turn is routed to a
   document path rather than the photo path.

2. **Parse.** NEW: a Docling service (desktop GPU) converts the document to
   clean Markdown with page/slide anchors; Gotenberg renders Office formats to
   PDF first. Because the desktop is not always on, parsing is a durable job:
   the raw bytes are stored on the Spark on arrival, a parse job is enqueued,
   and it runs when Docling is reachable. The person is told "got it - I'll have
   it ready shortly" and is followed up when it is indexed. Docling is the one
   component kept from the Specialized-Services drop; the rest of that stack
   (RAGFlow, its Elasticsearch/MySQL/MinIO) is retired to an optional appliance.

3. **Embed and store.** EXISTS: the Markdown is chunked, embedded with Nomic
   (`text-embedding-nomic-embed-text-v1.5`, Spark:8004, dimension 768), and
   written to the native `KnowledgeStore` (pgvector, HNSW) - the same store and
   embedding the assistant's memory already uses (Milestone 3). Scoped to the
   owner: a `user_id` for a person, a `group:` id for a room. Content-hash
   dedupe means re-uploading the same bytes is free.

   What the document *says* that is worth remembering goes to memory as well
   (`backend/services/document_facts.py`, after the upload, in the background):
   a structured digest reads the document into one plain headline sentence,
   the sharer's own declarative words plus that headline are given to the same
   memory classifier a spoken turn gets, and the same attribution rule decides
   the owners - the sharer's store and the room's, never another member's on
   the sharer's word. The classifier keeps a plan stated short and plain and
   refuses a paragraph of detail, which is why the digest is one sentence.

4. **Retrieve.** NEW: when a turn asks something the documents cover, the reply
   consults `KnowledgeStore.search` and grounds its answer in the chunks it
   finds, citing the document and page. Today the reply recalls past turns,
   semantic memory, and images - not documents; this wiring is the highest-
   leverage piece, because it is what makes an ingested document actually change
   an answer. Retrieval runs on the always-on Spark, so a document parsed last
   week is answerable now even with the desktop asleep. Insufficient evidence
   abstains rather than inventing - the same discipline the reply already holds.

5. **Control.** NEW: replying to a document scopes retrieval to it, the way a
   reply to an image pins that image today. "Forget that document" deletes it
   and its chunks. Re-uploading replaces. A person can see what AniOS holds for
   them and remove any of it - documents are their memory, on the same terms as
   the rest.

### Stage 6 - Writing (2026-09-02)

The mirror of stage 1. When the person asks for what the assistant just wrote
as a file - "put that in a PDF", "make that a Word document", "create a pdf
of the revised itinerary so I can send it to Jen" - the router picks
`create_document` (title, format, and the body, or empty for "what you just
wrote", which resolves to the previous reply of at least a sentence or two).
The body is the Markdown subset the assistant writes anyway: headings,
paragraphs, bullets, bold.

- **PDF**: the Word file below, printed by Gotenberg's LibreOffice route
  (`GOTENBERG_BASE_URL`, on the desktop beside Docling) - one source for both
  formats. Gotenberg's Chromium route cannot start on the desktop's Docker
  (crashpad, measured 2026-09-02), so it is not used. The renderer is probed
  first; when it is away the person gets the Word file and is told the PDF
  comes back with the desktop.
- **Word**: built here from the standard library (a .docx is three XML parts
  in a zip); headings are sized bold paragraphs, bullets hang, bold survives.
  No renderer, so it never waits on anything.
- **Kept as an artifact** of kind `document` in the visual-artifact store:
  bytes under an opaque key (the store's extension allowlist admits `pdf` and
  `docx`; a new kind has to be admitted there as well as in the repository),
  hash and size on the row, served by the owned-artifact content route. The web shows a card with the file to save;
  the iMessage worker attaches it under its title (`Amalfi itinerary.pdf`),
  and the bridge lets a PDF or a Word file out, proven by its first bytes,
  under the same size cap as a picture.
- **Round trip**: a file the assistant wrote can be shared back to it and
  read through stage 1, which is how the functional test proves the PDF
  says what was asked - Docling reads it and the day-by-day is there.

Not Microsoft 365. A Graph or Office MCP would put the file in someone's
OneDrive and needs a tenant, consent, and tokens the household does not have;
the person asked for a file they can send, which this is. An MCP that edits
an existing .docx in place is the later step, if it is wanted.

## What exists versus what is new

| Piece | State |
| --- | --- |
| Nomic embedding, pgvector `KnowledgeStore`, ingest + search, per-user/group scoping, content-hash dedupe, chunking | EXISTS (Milestone 3, VERIFIED) |
| Document attachment acceptance on each channel (bridge allowlist, worker document turn, web upload) | NEW |
| Docling parse service + durable, desktop-off-tolerant parse queue; Gotenberg for Office | NEW (Docling reused from the drop) |
| Wiring `KnowledgeStore.search` into the per-turn reply, with citations and abstention | NEW - the load-bearing piece |
| Reply-to-document scoping, "forget that document", lifecycle | NEW |

| Writing a PDF or Word file from the reply | NEW: `document_writer` (Gotenberg + docx builder), `create_document` tool, artifact kind `document`, worker attachment, bridge rule |

## Build order (each phase ends in something the assistant can do)

1. **Retrieval wiring.** VERIFIED 2026-09-01 (9/9 across three container runs, `test_document_knowledge_behaviour.py`). Make the reply consult the existing `KnowledgeStore`
   per turn. Anything already ingested becomes answerable, cited. No desktop
   dependency, no new infrastructure - it proves the "documents feed the answer"
   half against knowledge that is already there. Smallest change, most value.
2. **Ingest one PDF end to end.** VERIFIED 2026-09-02 (3/3 across three runs through the real Docling: `test_document_upload_behaviour.py` parses the operator's itinerary into two page-anchored pages, stores it, retrieves it, and answers about Day 1's evening with attribution). Accept a PDF in chat, parse via Docling,
   ingest, answer. The Amalfi itinerary in the Groupie room is the acceptance
   case: "what is included the evening of Day 1" -> the Salerno dinner, cited.
3. **Format breadth and the queue.** VERIFIED 2026-09-02 for Word (a stdlib-built .docx through the same parser and store, seeded fact retrieved, 3/3) and for the queue's schema (migration 20260901_0015 builds from an empty schema); the queue's behaviour is unit-tested against the real table after it ships. Word, PowerPoint, scanned PDFs via
   Gotenberg + Docling; the durable queue so a document sent while the desktop
   is off is parsed when it wakes. The drop's test matrix (DOCX with tables and
   tracked changes, legacy DOC, ODT, RTF, PPTX with notes, scanned OCR, 100+
   page) is the breadth check.
4. **Control and citation.** VERIFIED LIVE 2026-09-02 (`live_document_acceptance`: the deployed API cited the itinerary by name and page, answered a pinned question from the document alone, and removed it on "forget that document"; queue tests 12/12 x3 against the real table). Unit-verified (a document pin scopes retrieval; the confirming iMessage bubble pins the document; `forget that` deletes a stored document via the undo ledger; every chunk carries its page and the citation names it). Live acceptance in the Groupie chat pending. Reply-to-document scoping, forget, and citations
   surfaced in the reply so a person can see which page an answer came from.

6. **Writing** - `create_document` → Word file built here, PDF printed by
   Gotenberg's LibreOffice route, kept as an artifact, attached in iMessage /
   a card on the web. VERIFIED 2026-09-02: routing 12/12 (three phrasings and
   one non-ask, three reps); the PDF and the Word file read back through
   Docling with every day present (2/2); worker, bridge, and writer unit
   tests; sweep journey "plan as a pdf" walks it after every deploy.

## Edge cases, as built (2026-09-02)

- **Same bytes again** - one row; the content hash returns the existing
  document.
- **A new version of the same document** (same source, different bytes) - the
  older active copy is marked `superseded`; retrieval reads active rows only,
  so two versions of one itinerary never mix. Nothing is deleted.
- **Parser off when a document arrives** - the upload is kept in
  `document_parse_jobs`; each queue pass probes the parser's health first and
  leaves every job untouched while it is down (an overnight desktop burns no
  attempts). A reachable parser that fails on a file three times fails that
  job with the parser's own sentence.
- **Parser off, and how long the sharer waits to hear it** - the parser's
  host drops connection attempts while the container is stopped (it does not
  refuse them), so an upload handed straight to the parser waited out the
  kernel's retries, about two minutes, before "queued" came back (measured
  live 2026-09-02). The route now asks `/health` first, eight seconds at
  worst, and the parser client connects in ten seconds or gives up while
  still reading for the configured minutes. Plain text never asks.
- **"Forget that document"** - routes to undo (the affordance names a
  document it was given), and the undo targets the newest *document* receipt
  when the words name one - a share is followed seconds later by the memory
  receipt its facts pass writes, and "newest change" alone would have removed
  the fact and kept the document.
- **One statement, one fact** - two candidates from one turn with the same
  predicate (subject normalised away) are saved once; the embedder cannot make
  this call (measured), so it is deterministic.
- **The share is the referent everywhere** - rooms observe the share line into
  the thread; web and API uploads record the same line in their conversation;
  with it in history the router answers document questions from what is on
  hand rather than the web (measured 3/3).
- **Not built, on purpose** - a document that lands from the queue gets no
  facts pass (its facts come when someone next talks about it); on the web,
  "forget that document" works in the conversation the upload named.

## Retention (built 2026-09-02)

A document has three lives, and each is treated on its own:

1. **The file is never deleted on a date.** "What hotel did we stay at in
   Amalfi" is a real question two years later. Deletion stays a human act:
   "forget that document", or the memory page.
2. **Its weight in retrieval retires after the event.** The digest step that
   already reads a shared document also reports `about_until`, the last date
   it is about (an itinerary's final day, a ticket's date; empty for a lease,
   a recipe, a manual). `KNOWLEDGE_ARCHIVE_GRACE_DAYS` (30) after that date
   an hourly pass (`document_retention.py`, beside the parse queue) marks the
   document `archived` and records when. Retrieval reads active documents
   first; an archived one answers only when nothing current does, or when the
   person pinned it by replying to its bubble - so last year's plan stops
   competing with this week's without becoming unreachable. The reply is told
   a passage is archived and its last date, and answers about it as past.
3. **Its facts split into durable and dated.** The digest marks each
   supporting statement `dated` (a departure time, a meeting point, a day's
   schedule) or not (where they stayed, who went). The headline and durable
   statements are saved as before; dated statements are classified as the
   sharer's own words and saved with `expires_at` on the last date plus the
   grace period, so they leave through memory's existing purge.

Edge cases: an undated document never archives; a superseded document keeps
the status it had; a document that lands from the queue is not digested (no
speaker to attribute to) and so carries no date until someone talks about
it; a document shared in a room is dated once and the sharer's copy shares
the row. A deleted document takes its chunks; archiving deletes nothing.

## Hosting and availability

Docling parsing stays on the desktop (its GPU is the one heavy part; the queue
tolerates the desktop being off). Embedding, storage, and retrieval run on the
always-on Spark. This is the split that lets a personal assistant answer about a
document at any hour while doing the expensive parsing only when the parsing
machine is awake.
