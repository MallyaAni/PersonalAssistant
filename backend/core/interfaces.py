from abc import ABC, abstractmethod
from typing import Any

from backend.artifacts.types import (
    DiagramSpecification,
    GeneratedImage,
    ImageGenerationRequest,
    StoredBinary,
    VisionAnalysis,
)


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
    ) -> list[dict[str, Any]]: ...


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
