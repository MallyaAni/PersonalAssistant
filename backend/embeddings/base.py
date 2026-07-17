from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base class for generating vector embeddings."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Convert a string into a list of floats (vector)."""
        ...

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Convert a search query into a vector."""
        ...
