from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from backend.artifacts.types import (
    DiagramSpecification,
    GeneratedImage,
    ImageGenerationRequest,
    StoredBinary,
    VisionAnalysis,
)
from backend.search.types import SearchResults


class MemoryService(ABC):
    @abstractmethod
    async def get_user_profile(self, user_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def get_episodic_memory(
        self,
        user_id: str,
        query: str,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_semantic_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]: ...

    # Embed one retrieval query so a turn can reuse the vector across stores.
    @abstractmethod
    async def embed_query(self, query: str) -> list[float]: ...


class ConversationRepository(ABC):
    @abstractmethod
    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def save_turn(
        self,
        conversation_id: str,
        turn: dict[str, Any],
    ) -> None: ...

    # Count persisted turns for a user-owned conversation.
    @abstractmethod
    async def count_turns(
        self,
        conversation_id: str,
        user_id: str,
    ) -> int: ...


class ConversationTracer(ABC):
    @abstractmethod
    def start_trace(self, user_id: str) -> str: ...

    @abstractmethod
    def log_step(
        self,
        trace_id: str,
        step_name: str,
        metadata: dict[str, Any],
    ) -> None: ...


class DiagramProvider(ABC):
    # Generate one bounded editable diagram specification from a user request.
    @abstractmethod
    async def generate(self, query: str) -> DiagramSpecification: ...


class ArtifactRepository(ABC):
    # Persist a pending visual artifact before provider work begins.
    @abstractmethod
    async def create_pending(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        provider: str,
        model: str | None,
    ) -> dict[str, Any]: ...

    # Mark a pending artifact ready with validated editable source.
    @abstractmethod
    async def mark_ready(
        self,
        artifact_id: str,
        user_id: str,
        specification: DiagramSpecification,
    ) -> dict[str, Any]: ...

    # Mark a pending artifact failed without storing provider internals.
    @abstractmethod
    async def mark_failed(
        self,
        artifact_id: str,
        user_id: str,
        error_code: str,
    ) -> dict[str, Any]: ...

    # List artifacts owned by one user conversation in creation order.
    @abstractmethod
    async def list_for_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> list[dict[str, Any]]: ...

    # List recent artifacts owned by one user across conversations.
    @abstractmethod
    async def list_for_user(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    # Delete one user-owned artifact and report whether it existed.
    @abstractmethod
    async def delete(self, user_id: str, artifact_id: str) -> bool: ...


class BinaryArtifactRepository(ArtifactRepository):
    # Persist a pending generated or uploaded image before binary work begins.
    @abstractmethod
    async def create_binary_pending(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        kind: str,
        provider: str,
        model: str | None,
        title: str | None,
    ) -> dict[str, Any]: ...

    # Mark a pending image ready with opaque storage and integrity metadata.
    @abstractmethod
    async def mark_binary_ready(
        self,
        artifact_id: str,
        user_id: str,
        stored: StoredBinary,
        mime_type: str,
        width: int,
        height: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]: ...

    # Return one artifact only when it belongs to the requested user.
    @abstractmethod
    async def get_owned(
        self,
        user_id: str,
        artifact_id: str,
    ) -> dict[str, Any] | None: ...

    # Merge bounded analysis metadata into one owned artifact.
    @abstractmethod
    async def update_metadata(
        self,
        artifact_id: str,
        user_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]: ...


class BinaryArtifactStore(ABC):
    # Store bytes under an opaque key derived from ownership and artifact identity.
    @abstractmethod
    async def write(
        self,
        user_id: str,
        artifact_id: str,
        extension: str,
        content: bytes,
    ) -> StoredBinary: ...

    # Read bytes only from a previously issued opaque storage key.
    @abstractmethod
    async def read(self, storage_key: str) -> bytes: ...

    # Delete bytes idempotently for a previously issued opaque storage key.
    @abstractmethod
    async def delete(self, storage_key: str) -> None: ...


class ImageProvider(ABC):
    # Generate one image through a replaceable local inference runtime.
    @abstractmethod
    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage: ...


class VisionProvider(ABC):
    # Analyze one validated image without receiving storage or permission authority.
    @abstractmethod
    async def analyze(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> VisionAnalysis: ...

    # Answer a new question about one image given prior question/answer context.
    @abstractmethod
    async def analyze_thread(
        self,
        content: bytes,
        mime_type: str,
        history: list[dict[str, str]],
        prompt: str,
    ) -> VisionAnalysis: ...


class SearchProvider(ABC):
    """Replaceable web-search backend returning untrusted third-party results."""

    # Report whether the provider is configured; callers must skip search if not.
    @abstractmethod
    def is_enabled(self) -> bool: ...

    # Execute one bounded query and return ranked, truncated results.
    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults: ...


class SemanticMemoryWriter(ABC):
    """Write side of semantic memory, segregated from the read-only contract.

    Kept separate so read-only consumers are not forced to implement writes, and
    so a derived-index writer cannot be mistaken for the approval-gated path
    that persists user-stated facts.
    """

    # Persist one embedded semantic memory under an explicit purpose.
    @abstractmethod
    async def save_semantic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]: ...


class VisionEmbeddingProvider(ABC):
    """Embeds images into the same latent space as the text embedder.

    Alignment is the contract: a text query embedded by the text provider must
    be directly comparable to an image embedded here, so both can share one
    vector column, one index, and one distance threshold.
    """

    # Report whether local weights are present; callers must skip indexing if not.
    @abstractmethod
    def is_enabled(self) -> bool: ...

    # Embed one validated image into a unit-length vector.
    @abstractmethod
    def embed_image(self, content: bytes) -> list[float]: ...


class ArtifactEmbeddingStore(ABC):
    """Persistence and search for aligned image vectors.

    Segregated from the artifact repository contract so existing consumers are
    unaffected, and so image search keeps its own threshold: cross-modal cosine
    scores are not comparable to text-text scores.
    """

    # Attach one aligned vector to an owned artifact.
    @abstractmethod
    async def set_embedding(
        self,
        artifact_id: str,
        user_id: str,
        embedding: list[float],
        model: str,
    ) -> None: ...

    # Rank one user's embedded images against a query vector by cosine distance.
    @abstractmethod
    async def search_by_embedding(
        self,
        user_id: str,
        embedding: list[float],
        limit: int,
        max_distance: float,
    ) -> list[dict[str, Any]]: ...
