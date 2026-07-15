from abc import ABC, abstractmethod
from typing import List
import numpy as np

class EmbeddingProvider(ABC):
    """Abstract base class for generating vector embeddings."""

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Convert a string into a list of floats (vector)."""
        pass

    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """Convert a search query into a vector."""
        pass