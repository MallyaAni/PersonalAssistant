# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-27, America/New_York

Verified source state: uncommitted working tree based on
`3ecbe45091f2e49246333e31c8578c1f9f5bc767`. No commit, tag, branch, stash,
reset, restore, clean, push, or recovery operation was performed.

## Current boundary

Generated-image refinement is now real source-aware editing. The API re-reads
the owned parent through the byte-size and SHA-256 integrity boundary, sends
those source pixels plus the exact bounded feedback and preservation
constraints to `ComfyUIImageEditProvider`, and runs an official-style
FLUX.2 Klein 4B Distilled FP8 workflow through ComfyUI. The workflow uses
`qwen_3_4b.safetensors`, `flux2-vae.safetensors`, four distilled steps, and the
existing one-job concurrency gate.

The ready child is immutable and records parent ID, source SHA-256, exact
feedback, provider/model, seed, steps, and provider latency. The browser shows
`Refining...`, replaces the active image card in place, and retains both
database revisions. Prompt-only HiDream refinement, the unqualified
Qwen-Image-Edit path, and the experimental SAM recolor branch are not active
fallbacks.

HiDream-O1 Dev FP8 remains the text-to-image generator. Gemma remains the
vision and presentation model; Qwen 3.5 9B remains the main, native-MCP, and
diagram model. Automatic generated-image observations, user-labelled visual
references, semantic pre/post-edit verification, bounded corrective retry, and
application-owned model-residency preflight remain planned.

## Runtime and Git identity

- Branch: `main`.
- Base `HEAD`: `3ecbe45091f2e49246333e31c8578c1f9f5bc767`.
- The working tree was already dirty and contains the user's broader visual
  memory/editing work plus this task. Preserve it; no Git mutation was made.
- Rebuilt backend image exercised:
  `sha256:6105903b4d38d5a8ac5e5d6d7fd8fa8aa7560a2b1eccedacf3e4afe396ab77bf`.
- Rebuilt local-capabilities image exercised:
  `sha256:f8bafee12f02609fb3c91c9515d4f5e36af7c8cb4fc54a93e71722bbdf6aa96d`.
- Frontend image serving the bind-mounted source:
  `sha256:c520af97cd2ed7604563e6bcb6463197f3b3df1dfb316b593bb574fc23f80537`.
- ComfyUI 0.28.0 is running on host port 8188. The Compose backend, frontend,
  database, Redis, local-capabilities, presentation worker, and presentation
  renderer are running.

## VERIFIED

- The installed edit assets and SHA-256 values are:
  - `flux-2-klein-4b-fp8.safetensors`:
    `97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6`;
  - `qwen_3_4b.safetensors`:
    `6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a`;
  - `flux2-vae.safetensors`:
    `d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5`.
- Direct `POST /api/v1/images/a4596a7d-3d93-4334-8a8e-b6db5521af3a/refine`
  with `make this car red` returned HTTP 201 in 5.628 seconds. Provider time was
  4.203 seconds. The 1024x1024 child had FLUX model/four-step provenance,
  parent ID `a4596a7d-3d93-4334-8a8e-b6db5521af3a`, source SHA-256
  `700abec8439a063b61bbf6e9d7f8102bc0acd5e11da7c683a2764334f505503f`,
  and persisted/fetched child SHA-256
  `9d97c75d0269a96b46edfd24f2b76781a46ad0dc0fab391ae5d6465985605f04`.
  Visual inspection confirmed the same coupe, plate, wheels, road, cliffs,
  ocean, camera position, and composition with a red body.
- Three source-edit classes passed the actual API path on the same car:
  localized color/material, addition of one small yellow balloon, and changing
  only the plate text to `ANIOS`. Provider times were 4.2 to 10.9 seconds.
  Visual inspection confirmed the requested deltas and preservation.
- Real Playwright Chromium completed live HiDream generation, visible FLUX
  refinement, in-place replacement with exactly one image card, reload
  persistence, private-content fetch, Gemma analysis, terminal loading cleanup,
  and scoped deletion in 1.3 minutes. The captured edit retained the blue
  seahorse and scene while changing only the copper sphere to polished gold.
  Required requests succeeded and the successful run recorded no Console
  errors or page exceptions.
- Focused backend tests: 17 passed.
- Deterministic browser suite: 35 passed.
- TypeScript/Vite production build passed with only the existing chunk-size
  advisory.
- Qwen and Gemma were restored as `qwen/qwen3.5-9b` and
  `google/gemma-4-12b`, each at 8,192 context and parallelism one, after image
  qualification.
- Canonical full-system, runtime-deployment, visual-artifact, and visual
  memory/editing Mermaid views describe HiDream generation, FLUX editing, and
  the remaining planned semantic stages.
- The three unused Qwen-Image-Edit model assets and all scoped qualification
  artifacts/caches/logs were removed. Model cleanup reclaimed 30,172,239,743
  bytes while retaining the Qwen 3 4B encoder required by FLUX. The original
  user car remains ready with its original SHA-256.

## FAILED

- The prior Qwen-Image-Edit workflow required 40 steps and took 304.165 and
  567.668 provider seconds on persisted edits. It was not retained.
- The experimental native SAM recolor path took roughly the same time as FLUX
  but tinted windows, grille, wheels, and the plate. Its code, interfaces,
  configuration, dependency wiring, and tests were removed.
- A full backend test collection does not run in either available local test
  environment: the system Python lacks Google ADK and OpenTelemetry, the
  repository `.venv` additionally lacks Redis, and the production backend image
  intentionally lacks pytest. This is an environment/dependency failure before
  test execution, not a failing test assertion.
- The first live browser attempt used an exact mojibake ellipsis in its
  progress-button locator. The screenshot showed the product correctly in
  `Refining...`; the stable locator was corrected and the complete rerun passed.

## UNVERIFIED

- Semantic pre/post-edit verification, rejection of a bad candidate, and one
  bounded corrective retry are not implemented.
- Automatic VLM observation of every generated/edit revision, structured OCR
  and object semantics, user aliases, and memory resolution of prior pictures
  are not implemented.
- Edit cancellation, process-crash reconciliation, sustained concurrent load,
  long-duration quality drift, and DGX Spark performance were not qualified in
  this task.
- AniOS still does not own LM Studio/ComfyUI role residency. A later VLM call
  can auto-load Gemma with an unsafe default context unless the operator or a
  future preflight supplies the bounded profile.
- Full backend regression remains unverified until the declared development
  dependencies are installed in one reproducible test environment.

## Next atomic task

Implement durable, idempotent generated-image observation as the shared
foundation for visual memory and semantic edit verification. A ready generated
or edited revision must remain immediately visible, enqueue one observation
keyed by artifact/source hash plus schema/model, re-read owned
integrity-checked bytes, obtain a bounded typed Gemma observation, persist
append-only provenance/status, and expose visible failure/retry without making
the image unavailable. Validate direct API/job state, restart recovery,
generated and edited images, scoped deletion, real browser status, relevant
tests, build, and the affected diagrams before continuing to visual aliases or
post-edit promotion checks.
