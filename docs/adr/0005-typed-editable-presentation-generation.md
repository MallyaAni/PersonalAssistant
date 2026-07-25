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

The primary local Gemma model is shared with chat and other focused agents.
Presentation rendering therefore needs a narrow specification contract and a
replaceable worker that does not own application state.

## Decision

1. A focused `PresentationAgent` uses a replaceable provider. For deck
   creation, the model produces a compact semantic `DeckPlan`, and deterministic
   application code expands it into the strict `DeckSpec`, including layout,
   theme, editable objects, and stable identifiers. For selected-slide feedback,
   the model produces a strict `SlideSpec`. The model has no database,
   filesystem, authorization, promotion, or renderer-control authority.
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

## Consequences

Benefits:

- normal PowerPoint objects remain editable;
- slide-level feedback has deterministic scope;
- model/provider failures cannot corrupt the active revision;
- compact model output avoids repetitive coordinate/style generation and keeps
  normal local deck creation within one bounded planning call;
- renderer and model implementations remain independently replaceable;
- direct API, MCP, and browser paths reuse the same lifecycle service.

Costs and limitations:

- the browser preview approximates Office layout and is not a PowerPoint
  rendering engine;
- arbitrary existing-PPTX import and round-trip editing are not implemented;
- source-grounded citations, reusable master/template libraries, automatic
  visual-diff review, and durable distributed render jobs remain planned;
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
