from abc import ABC, abstractmethod
from typing import List, Dict, Any

class Retriever(ABC):
    """Abstract base class for all retrieval mechanisms."""

    @abstractmethod
    def retrieve(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the most relevant documents based on a vector."""
        pass

    @abstractmethod
    def search_semantic(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve using a semantic search (handles embedding internally if needed)."""
        pass