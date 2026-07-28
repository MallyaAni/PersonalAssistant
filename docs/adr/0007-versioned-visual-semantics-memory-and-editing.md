# ADR 0007: Versioned Visual Semantics, Memory References, and Editing

## Status

Accepted and partially implemented. Pixel embedding, owned artifacts, VLM
question-answering, and stage 3 source-aware immutable editing are implemented.
Automatic generated-image observation, durable visual jobs, structured visual
observations, user-labelled visual references, reference resolution, and
semantic post-edit verification remain `PLANNED`.

## Context

AniOS can generate and upload images, store them privately, embed their pixels,
retrieve them by aligned text-to-image similarity, ask Gemma questions about
owned image bytes, and pass an owned generated image to a source-conditioned
local editor. Semantic observation and post-edit verification are not yet part
of the promotion boundary.

The user needs two related future capabilities:

1. modify the image that was actually produced rather than merely regenerate
   its prompt; and
2. reference prior pictures from memory by meaning, user label, conversation,
   or recency.

A caption alone is not sufficient. It can omit details, become stale after an
edit, or ambiguously describe several pictures. Storing image bytes inside a
text-memory record would duplicate private data and bypass the artifact
ownership, integrity, retention, and deletion boundary.

Current local image-editing systems support the required separation. ComfyUI
documents both [image-to-image](https://docs.comfy.org/tutorials/basic/image-to-image)
and [FLUX.2 Klein](https://docs.comfy.org/tutorials/flux/flux-2-klein)
workflows. AniOS qualified
[FLUX.2 Klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
on the configured RTX 5080 and selected its Apache-2.0 distilled
single-reference path only after local quality, latency, lineage, API, and
browser acceptance. Model selection remains replaceable and evidence-driven.

## Decision

1. **Pixels remain artifacts, not memories.** The opaque binary store owns one
   copy of each image revision. Memory stores an immutable artifact/revision
   handle, bounded derived semantics, user labels, and provenance. Every use
   re-resolves the handle and re-checks owner, ready status, deletion state,
   byte size, and SHA-256 before pixels are read.

2. **Image identity and revision identity are distinct.** An image family is a
   lineage DAG whose immutable revisions retain parent ID, source byte hash,
   instruction, provider/model/workflow version, seed, and verification result.
   A failed candidate never replaces its ready parent.

3. **Grounded observations are append-only and versioned.** A
   `VisualObservation` is keyed by artifact revision, plaintext byte hash,
   observation schema version, and VLM model version. It contains a bounded
   caption, objects, attributes, relationships, OCR text, confidence, status,
   and provenance. Re-analysis creates a new observation rather than silently
   rewriting history. User corrections are separate provenance-bearing
   assertions and outrank model observations without altering the pixels.

4. **Generation is not blocked by understanding.** Successful pixels become
   visible immediately. A durable observation job runs afterward and exposes a
   separate `pending`, `ready`, or `failed` understanding state. An observation
   failure does not hide or delete a valid image. A semantic edit can wait for,
   retry, or explicitly proceed without an observation according to visible
   application policy.

5. **Visual recall combines independent signals.** `VisualReferenceResolver`
   fuses exact user aliases and collections, semantic-description vectors,
   aligned pixel-vector search, conversation/recency, and lineage state. Each
   signal keeps its own calibrated scale. A minimum score and best-to-runner-up
   margin are required; close candidates cause a visible clarification instead
   of silent selection.

6. **The editor receives the source pixels.** A typed `ImageEditRequest`
   contains the resolved source revision, user instruction, optional
   mask/region, requested semantic delta, and preservation constraints. A
   replaceable `ImageEditProvider` may use image-to-image, inpainting, or a
   qualified instruction editor. Text-to-image prompt regeneration is not an
   editing fallback and is not the definition of editing.

7. **Understanding does not authorize editing.** A focused `VisualAgent`
   LangGraph may turn the instruction and observation into a typed edit plan.
   Application code owns ownership checks, limits, provider selection, resource
   leases, job state, retries, storage, and promotion. The VLM, editor, and
   agent receive no database, permission, or lifecycle authority.

8. **Every candidate is observed and verified before promotion.** The
   verification boundary compares the requested delta and explicit preservation
   constraints against pre-edit and post-edit observations. Deterministic
   integrity and dimension checks always run. Policy permits at most one
   bounded corrective retry; otherwise the candidate is visibly failed and the
   parent stays current. Verification is evidence, not a mathematical guarantee
   of pixel identity.

9. **Jobs are durable and idempotent.** Observation and editing work uses
   application-owned jobs with leases, cancellation, retry budgets, terminal
   state, and idempotency keys. Observation jobs deduplicate by source hash,
   schema, and model. GPU residency and prioritization belong to the planned
   resource coordinator rather than a model or ComfyUI workflow.

10. **Agent tools exchange handles, not bytes.** Future MCP tools may expose
    `find_images`, `describe_image`, and `edit_image`. Results contain bounded
    metadata and opaque owned handles. Application-owned identity remains
    outside model-visible arguments, and consequential editing follows the
    confirmation policy.

11. **Deletion follows the lineage and derived-data graph.** Owned deletion
    removes or tombstones the selected scope, binary revisions, observations,
    aliases, semantic vectors, pixel vectors, and pending jobs consistently.
    Export lists the same provenance. Derived observations and embeddings share
    the source artifact's retention classification.

12. **Implementation proceeds in independently verifiable stages.**
    Stage 1 adds durable generated-image observations. Stage 2 adds visual
    aliases and reference resolution. Stage 3 adds a qualified source-aware
    editor and is now implemented with FLUX.2 Klein 4B Distilled. Stage 4 adds
    post-edit verification and bounded retry. Stage 5 adds
    agent/MCP exposure and production resource scheduling. No stage is called
    complete from interfaces, diagrams, or mocked providers alone.

## Consequences

Benefits:

- the assistant can reason about actual pixels rather than only the generation
  prompt;
- references such as “the red car from yesterday” resolve to an owned artifact
  without copying private image bytes into text memory;
- edits preserve lineage and can use image-to-image or masked workflows;
- model observations can be refreshed, corrected, audited, and deleted;
- VLM, embedding, editing, storage, memory, and hardware providers remain
  independently replaceable;
- the same typed workflow can run locally now and behind future workers or
  subagents without transferring authority to a model.

Costs and risks:

- automatic observation adds GPU work, storage, and a new durable lifecycle;
- captions and structured observations can be wrong, omit details, or contain
  sensitive OCR and therefore require provenance and user control;
- rank fusion needs a labelled retrieval evaluation as the image library grows;
- high-fidelity editing may require a larger model or different residency
  profile than text-to-image generation;
- VLM-based verification can agree with a bad edit, so user-visible comparison
  and retention of the parent revision remain mandatory;
- cascading deletion and export become more complex because derived records
  must follow artifact lineage.

## Alternatives considered

- **Use only the original generation prompt.** Rejected because prompts describe
  intent, not necessarily rendered pixels.
- **Store only a VLM caption.** Rejected because captions are lossy and do not
  provide appearance conditioning for editing.
- **Put image bytes into semantic memory.** Rejected because it duplicates
  sensitive data and bypasses artifact ownership and lifecycle controls.
- **Let the VLM choose and execute an editor directly.** Rejected because model
  understanding is not authorization, resource policy, or promotion evidence.
- **Overwrite an image in place.** Rejected because it destroys provenance,
  rollback, comparison, and reference stability.
- **Require analysis before showing a generated image.** Rejected because it
  adds avoidable perceived latency and couples valid artifact availability to a
  derived-model enhancement.
