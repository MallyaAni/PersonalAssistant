from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DiagramSpecification:
    """Validated editable source returned by a diagram provider."""

    title: str
    diagram_type: str
    source: str


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    """Validated prompt and sampling controls sent to an image provider."""

    prompt: str
    width: int
    height: int
    seed: int


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    """Validated binary image returned by a replaceable local provider."""

    content: bytes
    mime_type: str
    width: int
    height: int
    provider_job_id: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredBinary:
    """Opaque storage reference and integrity metadata for one binary artifact."""

    storage_key: str
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    """Decoded image facts accepted by AniOS binary validation."""

    mime_type: str
    extension: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class VisionAnalysis:
    """Grounded text returned by a replaceable vision-language provider."""

    content: str
    model: str
    metadata: dict[str, Any]
