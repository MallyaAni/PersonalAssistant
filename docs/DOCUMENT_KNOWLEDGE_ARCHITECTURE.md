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

## What exists versus what is new

| Piece | State |
| --- | --- |
| Nomic embedding, pgvector `KnowledgeStore`, ingest + search, per-user/group scoping, content-hash dedupe, chunking | EXISTS (Milestone 3, VERIFIED) |
| Document attachment acceptance on each channel (bridge allowlist, worker document turn, web upload) | NEW |
| Docling parse service + durable, desktop-off-tolerant parse queue; Gotenberg for Office | NEW (Docling reused from the drop) |
| Wiring `KnowledgeStore.search` into the per-turn reply, with citations and abstention | NEW - the load-bearing piece |
| Reply-to-document scoping, "forget that document", lifecycle | NEW |

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

## Hosting and availability

Docling parsing stays on the desktop (its GPU is the one heavy part; the queue
tolerates the desktop being off). Embedding, storage, and retrieval run on the
always-on Spark. This is the split that lets a personal assistant answer about a
document at any hour while doing the expensive parsing only when the parsing
machine is awake.
