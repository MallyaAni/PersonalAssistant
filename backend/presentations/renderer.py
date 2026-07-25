import base64
from typing import Any

import httpx

from backend.presentations.types import DeckSpec, RenderedPresentation


class PresentationRenderError(RuntimeError):
    """Sanitized failure raised when the isolated renderer cannot compile a deck."""


class PptxGenJSRenderer:
    """Compile validated deck specifications through the stateless Node worker."""

    # Reuse one bounded HTTP client configuration for renderer calls.
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 60.0,
        max_output_bytes: int = 50 * 1024 * 1024,
        require_office_validation: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.require_office_validation = require_office_validation
        self.client = client

    # Send only validated JSON and decode the bounded PowerPoint result.
    async def render(
        self,
        specification: DeckSpec,
        images: dict[str, tuple[str, bytes]] | None = None,
    ) -> RenderedPresentation:
        payload: dict[str, Any] = {
            "specification": specification.model_dump(mode="json")
        }
        if images:
            payload["images"] = {
                artifact_id: {
                    "mime_type": mime_type,
                    "base64": base64.b64encode(content).decode("ascii"),
                }
                for artifact_id, (mime_type, content) in images.items()
            }
        try:
            if self.client is not None:
                response = await self.client.post("/v1/render", json=payload)
            else:
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                ) as client:
                    response = await client.post("/v1/render", json=payload)
            response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            raise PresentationRenderError("Unable to compile the presentation") from exc
        if len(response.content) > self.max_output_bytes:
            raise PresentationRenderError(
                "Compiled presentation exceeds the output limit"
            )
        if not response.content.startswith(b"PK"):
            raise PresentationRenderError("Renderer did not return an OOXML package")
        try:
            slide_count = int(response.headers["x-presentation-slide-count"])
            renderer_version = response.headers["x-presentation-renderer-version"]
        except (KeyError, ValueError) as exc:
            raise PresentationRenderError(
                "Renderer response omitted structural metadata"
            ) from exc
        if slide_count != len(specification.slides):
            raise PresentationRenderError("Renderer returned the wrong slide count")
        office_validation = response.headers.get(
            "x-presentation-office-validation",
            "skipped",
        )
        if self.require_office_validation and office_validation != "passed":
            raise PresentationRenderError(
                "Renderer did not pass independent office validation"
            )
        return RenderedPresentation(
            content=response.content,
            slide_count=slide_count,
            renderer=(
                "pptxgenjs+libreoffice"
                if office_validation == "passed"
                else "pptxgenjs"
            ),
            renderer_version=renderer_version,
        )
