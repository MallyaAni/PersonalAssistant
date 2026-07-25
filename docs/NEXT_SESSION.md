# Next Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-24, America/New_York

## Current milestone

**Milestone 5: tools and specialized agents — `IN PROGRESS`.**

AniOS now has three focused LangGraph boundaries: the streaming assistant,
`DiagramAgent`, and `PresentationAgent`. Presentation generation is implemented
as a typed application-owned subsystem and is available in its dedicated UI/API
plus the local capability MCP facade. This remains narrower than general
multi-agent scheduling or A2A.

## Current presentation boundary

- `PresentationAgent` and `LLMPresentationProvider` ask local Gemma for a
  compact semantic `DeckPlan` during creation or a selected-slide `SlideSpec`
  during feedback. A deterministic compiler owns creation layout, theme,
  editable objects, and stable IDs. The model cannot persist, authorize,
  render, choose storage keys, promote revisions, or edit siblings.
- `PresentationService` creates pending append-only revisions, preserves every
  sibling during slide feedback, renders, validates, stores, and promotes only
  a fully successful revision. Reusing a stale base revision returns HTTP 409.
- The port-8002 worker uses pinned PptxGenJS 4.0.1 for native text, shapes,
  charts, tables, images, and notes. Python inspects OOXML, and Compose requires
  a successful headless LibreOffice Impress open/PDF-export check.
- PostgreSQL stores user-scoped presentations and revision lineage. Encrypted
  title/spec fields use the existing optional `EncryptedText`; PPTX files use
  the opaque binary store, optional binary encryption, SHA-256 metadata, and
  owned deletion.
- The Presentations UI supports persisted deck lists, typed previews and
  thumbnails, slide selection, independent per-slide feedback conversations,
  revision history, navigation restoration, named `.pptx` downloads, deletion,
  loading, and visible pending/ready/failed outcomes. Each feedback revision
  carries its stable target slide ID.
- The local capability FastMCP facade exposes seven metadata-only tools,
  including `create_presentation`, `revise_presentation_slide`, and
  `get_presentation`. The server remains `untrusted`, so explicit calls require
  confirmation and ordinary chat cannot yet autonomously resume them.

## Git and runtime state

- Starting state: branch `main`, `HEAD`
  `b3d35bddaa615133f317287045b633f00755217e`, clean worktree.
- Current presentation and documentation changes are uncommitted. No commit,
  tag, branch, stash, reset, restore, checkout, push, or recovery operation was
  created.
- Compose currently runs backend, frontend, local capabilities,
  presentation-renderer, PostgreSQL, and Redis. The renderer is healthy and
  backend/local capabilities were rebuilt from this source tree.
- Alembic reports `20260724_0014 (head)`.
- Temporary direct/browser diagnostic decks were removed through their owned
  DELETE APIs. The original verified revision deck remains
  `7be08e63-c065-46dc-8801-25c20e9e8ba6`; the retained six-slide browser
  acceptance deck is `a8bfcc5e-a85a-44a2-babe-6e028dc5b2cc`.

## VERIFIED

### Direct API and persisted output

- The exact reported slow request, `create a presentation on horses, 6 slides`,
  now returned HTTP 201 in 28.67 seconds after one Gemma completion and one
  renderer call. The resulting revision was `ready`, used
  `pptxgenjs+libreoffice`, and contained exactly six stable slide
  specifications.
- The retained browser-created horse deck revision
  `aa8d093c-424b-4933-8835-b4cc37e93bf5` is 116,620 bytes with SHA-256
  `fbdb3c5a7e91be76c7de4b083e3d502730dad02b9764dbdd39318f36fde07c77`.
  Direct download plus current-source OOXML inspection found six slides, 42
  native text bodies, 72 native shapes, and six notes slides.
- The documented `POST /api/v1/presentations` body for user `ani.mallya`, a
  UUID conversation, and a three-slide AniOS brief returned HTTP 201 after
  local Gemma generation.
- The initial ready revision contained three slides, native text, shapes, one
  chart, one table, and three notes. Direct download and OOXML inspection
  confirmed those objects.
- A direct selected-slide request produced a parent-linked ready revision while
  exact application-level comparison proved slides 1 and 3 unchanged and slide
  2 changed. Reusing an older base revision returned HTTP 409 before model use.
- Direct per-slide follow-up acceptance created ready revision 8,
  `24fc1a29-a2c9-42fc-82b6-c6db4d8763a6`, with
  `target_slide_id=slide_001`, its unique marker in the specification, and one
  persisted slide-1 conversation entry.
- The final current revision is number 10,
  `96c270c8-dc7a-4d79-bd98-f3c7b8b7e0d8`, status `ready`, and targets
  `slide_002`. The deck currently exposes three threaded revisions: revision 8
  belongs only to slide 1, while revisions 9 and 10 belong only to slide 2.
- Backend logs show Gemma HTTP 200, renderer HTTP 200, presentation revision
  HTTP 201, deck/history HTTP 200, and content HTTP 200 with no traceback in
  the acceptance window.

### Real browser

- A fresh Chromium submission against the final rebuilt source image returned
  HTTP 201 for the exact six-slide horse prompt in 37.98 seconds. The UI
  displayed its running PresentationAgent
  state, rendered six slide selectors and the created title/preview, replaced
  the loading control with the normal creation control, and reported no
  Console errors or page exceptions. Network inspection showed the required
  POST plus required list/detail GETs all succeed.
- The final live Playwright workflow passed in 32.6 seconds. It selected slide
  2, submitted unique AI feedback, observed the running PresentationAgent
  state, received HTTP 201, rendered the marker, compared both sibling slides
  unchanged, navigated to Memory and back, reselected slide 2, restored its
  exact suggestion and ready-revision response, and downloaded the exact ready
  revision with HTTP 200 and the revisioned filename.
- The workflow reported no page exceptions or blocking Console errors and
  cleared the loading state.
- The deterministic presentation browser workflow also passed; the live test
  is intentionally skipped unless its two environment gates are set.

### Regression and architecture evidence

- Full current-source backend suite: `452 passed`.
- PptxGenJS renderer suite: `1 passed`.
- Strict MyPy: no issues in 135 source files. Repository-wide Ruff and Black
  checks passed.
- Frontend TypeScript/Vite production build passed. Vite reports only its
  existing large-chunk advisory.
- The deterministic presentation Playwright workflow passed.
- `docker compose config --quiet` passed.
- Live MCP listing reports local utility, internet search, and all seven local
  capability tools with bounded schemas.
- All 11 Mermaid sources and SVGs plus the published architecture page are
  synchronized. The new presentation view was visually inspected after being
  changed from a narrow vertical layout to a numbered landscape flow.

## FAILED

- The reported six-slide prompt originally spent roughly 200 seconds across two
  oversized malformed full-`DeckSpec` model responses and returned HTTP 503
  before rendering. Replacing repetitive model-authored layout JSON with a
  2,048-token semantic plan and deterministic application compilation produced
  the unchanged prompt successfully in one model call.
- The first compact-plan retest reached a valid six-slide renderer response in
  27.69 seconds but was rejected because the Python OOXML inspector counted
  `a:txBody`; native PowerPoint slide text uses `p:txBody`. Correcting that
  namespace check and adding a native-text regression test made the unchanged
  direct and browser paths pass.
- The first real deck creation produced invalid model JSON twice. Returning the
  exact bounded validation reason on the correction request was the first
  targeted fix; the unchanged acceptance brief then created a ready deck.
- The first real slide revision returned a full `DeckSpec` where a `SlideSpec`
  was required. A dedicated single-slide grammar was the targeted fix; the
  unchanged revision acceptance then passed.
- The initial deterministic browser assertion matched both main and thumbnail
  previews. Scoping the assertion to the main visible result fixed the test.
- The first browser download exposed a real CORS issue: JavaScript could not
  read `Content-Disposition`, so it used `presentation.pptx`. Exposing only that
  response header fixed the real filename path.
- The first visual render of the presentation architecture diagram was too tall
  and narrow. A numbered landscape source was rendered, synchronized, and
  visually re-inspected.
- An initial strict MyPy command included untyped FastMCP decorators and reported
  all seven handlers. Narrow `untyped-decorator` ignores were placed only on
  that third-party decorator boundary; the rerun passed without weakening
  handler annotations.
- The first live per-slide browser assertion required the unique marker to be
  the entire suggestion, while the correctly restored UI displayed the full
  sentence containing it. Scoping the assertion to contained text fixed the
  test; the unchanged live workflow then passed.
- `alembic current` reports `20260724_0014 (head)`, but `alembic check` remains
  `FAILED` because the pre-existing visual-artifact HNSW index created by
  migration `0012` is absent from `VisualArtifact.__table_args__`; Alembic
  therefore proposes removing `ix_visual_artifacts_embedding_hnsw`. Source diff
  against the starting SHA confirms neither `0012` nor the artifact model was
  changed by this task. The real index still exists in PostgreSQL and was left
  untouched because visual-embedding metadata drift is outside this atomic
  slide-feedback task.

No hypothesis boundary failed three times.

## UNVERIFIED

- Creation latency for substantially larger decks, concurrent model workloads,
  and sustained repeated generation has not been benchmarked; the current
  single six-slide acceptance is verified, not a general latency SLA.
- Arbitrary existing-PPTX import and round-trip modification are not
  implemented.
- The browser preview is a typed layout approximation, not Office rendering.
  Automatic slide-image comparison or manager-quality visual scoring is not
  implemented.
- Source-grounded research/citations, reusable master/template libraries,
  first-class hydration of owned image/diagram artifacts into decks, durable
  distributed render queues, cancellation, crash reconciliation, retention,
  package malware scanning, and renderer sandboxing remain planned.
- Raster images are replaceable native image objects, but their pixels are not
  decomposed into editable PowerPoint shapes.
- General multi-agent scheduling, A2A, and durable agent sessions remain
  unimplemented.

## Next atomic task

Implement explicit chat confirmation and resume for the existing untrusted
`create_presentation` MCP tool. The acceptance path should make Gemma select a
semantically discovered presentation tool, show the pending tool card and safe
summary, require the user to confirm, invoke through the existing live
contract/privacy/risk gates, restore the same chat turn, and render a link to
the persisted deck in Presentations. It must not make other consequential MCP
tools autonomous or broaden the presentation agent's authority.
