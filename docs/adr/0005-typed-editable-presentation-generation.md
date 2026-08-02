# ADR 0005: Typed Editable Presentation Generation

## Status

Accepted and runtime verified for local development.

## Context

AniOS needs to create presentation files that remain editable in PowerPoint and
support AI feedback on one selected slide without regenerating unrelated
slides. Directly asking a model to emit PPTX bytes, JavaScript, or arbitrary
layout instructions would mix probabilistic generation with file execution,
persistence, permissions, and revision authority. Rasterizing complete slides
would also prevent normal editing.

The configured local generation model is shared with chat and other focused agents.
Long presentation generations must not bind an HTTP request or prevent the
foreground assistant from answering. Presentation generation and rendering
therefore need narrow specification contracts, durable application-owned job
state, and replaceable workers that do not own authorization or promotion.

## Decision

1. A focused `PresentationAgent` LangGraph uses a replaceable provider. For
   deck creation, the model produces a compact `DeckOutline` followed by one
   bounded `PlannedSlide` microtask at a time; deterministic application code
   expands each partial plan into the strict `DeckSpec`, including layout,
   theme, editable objects, and stable identifiers. For selected-slide
   feedback, the model produces a strict `SlideEdit`. The model has no database,
   filesystem, authorization, job, promotion, or renderer-control authority.
2. Stable presentation, revision, slide, and element identifiers are
   application contracts. Slide feedback gives the model only the selected
   slide and replaces only that slide; every sibling specification is
   preserved by application code.
3. Presentations and append-only revisions are user-scoped in PostgreSQL. A
   revision records its parent and expected base. Stale-base edits fail rather
   than silently overwriting newer work.
4. A separate bounded HTTP worker uses pinned PptxGenJS to create native text,
   shape, chart, table, image, and notes objects. Raster images are replaceable
   objects but their pixels are not decomposed into editable drawing primitives.
5. Python inspects the returned OOXML package for its declared slides and
   required native object kinds. Compose additionally requires the worker to
   open the file with headless LibreOffice Impress and export a valid PDF.
6. PPTX bytes are written through the existing opaque binary store. The
   application promotes a pending revision to current only after generation,
   structural inspection, Office validation, and storage all succeed. A failed
   revision remains terminal and the prior current revision stays available.
7. The React view renders a typed specification preview and provides explicit
   deck creation, slide selection, slide feedback, revision history, download,
   and deletion. The local FastMCP facade exposes only bounded presentation
   metadata; it never returns PPTX bytes or private storage keys.
8. Creation is enqueued atomically in PostgreSQL and returns HTTP 202. A
   standalone worker claims jobs with recoverable leases and `SKIP LOCKED`,
   invokes the focused LangGraph, checkpoints each progressive draft, and
   records terminal state. The browser persists the active job handle and can
   reconnect after navigation, reload, or stream disconnection.
9. Backend chat and the presentation worker coordinate local inference access with
   an expiring Redis priority gate. Foreground chat holds the gate for its model
   lifecycle. Background creation holds it for only one outline or slide
   microtask and yields between calls while chat waits. Redis contains no
   prompt, draft, answer, identity, or artifact content.
10. A planned slide may declare one concrete image brief and priority, but it
    cannot invoke an image provider. After content planning, application code
    selects a configured maximum of the highest-priority applicable slides.
    The durable worker creates owned HiDream artifacts through the shared image
    service and checkpoints each enriched `DeckSpec` before final rendering.
    Image generation is best-effort: provider failure is visible in worker logs
    but cannot discard an otherwise valid editable text deck.

## Consequences

Benefits:

- normal PowerPoint objects remain editable;
- slide-level feedback has deterministic scope;
- model/provider failures cannot corrupt the active revision;
- compact model output avoids repetitive coordinate/style generation;
- presentation creation survives browser disconnection and no longer occupies
  the request process;
- microtask boundaries let foreground chat preempt a long deck without
  interrupting an in-flight local-model request;
- relevant slides receive bounded default imagery while progressive browser
  state remains reconnectable;
- renderer and model implementations remain independently replaceable;
- direct API, MCP, and browser paths reuse the same lifecycle service.

Costs and limitations:

- the browser preview approximates Office layout and is not a PowerPoint
  rendering engine;
- arbitrary existing-PPTX import and round-trip editing are not implemented;
- source-grounded citations, reusable master/template libraries, automatic
  visual-diff review, and distributed GPU-capacity scheduling remain planned;
- PostgreSQL and Redis are now required for durable background creation in the
  Compose runtime;
- cancellation is cooperative at draft checkpoints, not a forced model kill;
- LibreOffice validation proves the package can be opened/exported, not that
  every visual choice is manager-ready.

## Alternatives considered

- `python-pptx` was not selected as the primary renderer because PptxGenJS has
  a more ergonomic layout/chart API for a dedicated JavaScript worker. Python
  still owns validation and orchestration.
- Model-generated JavaScript was rejected because it would execute untrusted
  code and collapse the specification/renderer trust boundary.
- Full-slide image generation was rejected as the default because it sacrifices
  object-level editability and reliable slide-specific revision.
- A cloud presentation API was rejected because AniOS is local-first and the
  user requires a free path without sending private deck content externally.
