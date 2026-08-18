"""Run one real edit and write the result to disk, for looking at.

The edit that prompted this - "make the image look like it came in its original
packaging" - came back as the same photograph. Every edit was sent with "do not
add, remove, or move anything" appended, and that edit cannot be carried out
without adding something, so the model obeyed the more specific prohibition.

This runs the real provider against the real source so the fix can be judged by
looking rather than by reasoning about it. Run inside the backend container,
which is what can reach ComfyUI. One edit per invocation: three back-to-back
runs exhausted ComfyUI's memory and restarted it.
"""

import asyncio
import sys
import time
from pathlib import Path

from backend.artifacts.image import ComfyUIImageEditProvider
from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.artifacts.types import ImageEditRequest
from backend.config.settings import settings
from backend.services.image_refinement_service import _KEEP_THE_SCENE

# Read through the store, not off the disk. Artifacts are sealed at rest
# (`enc:1:` marker), so reading the file directly hands ComfyUI ciphertext and
# it answers "cannot identify image file" - which is what the first run of this
# script did, and it looked exactly like a pipeline failure.
STORAGE_KEY = "29784a95d7e9a37980de259a/94d47108-f153-4443-8c0a-ce74e654fa49.png"
FEEDBACK = "Make the image look like it came in its original packaging"
SEED = 873598876526131574


def _provider(steps: int) -> ComfyUIImageEditProvider:
    return ComfyUIImageEditProvider(
        base_url=settings.IMAGE_PROVIDER_BASE_URL,
        model=settings.IMAGE_MODEL,
        text_encoder=settings.IMAGE_TEXT_ENCODER,
        vae=settings.IMAGE_VAE,
        timeout_seconds=max(settings.IMAGE_PROVIDER_TIMEOUT_SECONDS, 600),
        poll_seconds=settings.IMAGE_PROVIDER_POLL_SECONDS,
        max_concurrency=settings.IMAGE_MAX_CONCURRENCY,
        max_output_bytes=settings.IMAGE_MAX_OUTPUT_BYTES,
        max_pixels=settings.IMAGE_MAX_PIXELS,
        steps=steps,
        megapixels=settings.IMAGE_EDIT_MEGAPIXELS,
        scale_method=settings.IMAGE_EDIT_SCALE_METHOD,
    )


async def main(label: str, steps: int, restages: bool) -> None:
    source = await LocalBinaryArtifactStore(settings.ARTIFACT_STORAGE_ROOT).read(
        STORAGE_KEY
    )
    out = Path("/app/data/step_comparison")
    out.mkdir(parents=True, exist_ok=True)

    # Assembled exactly as ImageRefinementService assembles it, so what is
    # measured here is what the product sends.
    # The permissive wording this measured, kept verbatim rather than imported:
    # it was removed from the service once measurement showed the editor will
    # not restage a scene however it is asked, and this records that finding.
    permissive = (
        "Keep the identity of the subjects exactly as they are. Everything "
        "else serving the instruction may change, and you may add whatever "
        "the instruction requires."
    )
    if restages:
        instruction = f"Edit image 1 as follows: {FEEDBACK}. {permissive}"
    else:
        instruction = f"Apply only this edit to image 1: {FEEDBACK}. {_KEEP_THE_SCENE}"

    began = time.monotonic()
    result = await _provider(steps).edit(
        ImageEditRequest(
            instruction=instruction,
            source_content=source,
            source_mime_type="image/png",
            seed=SEED,
        )
    )
    target = out / f"{label}.png"
    target.write_bytes(result.content)
    print(
        f"{label}: {time.monotonic() - began:.1f}s  "
        f"{len(result.content) / 1_000_000:.1f} MB -> {target}",
        flush=True,
    )


if __name__ == "__main__":
    name = sys.argv[1]
    step_count = int(sys.argv[2])
    restaging = sys.argv[3].lower() == "true"
    asyncio.run(main(name, step_count, restaging))
