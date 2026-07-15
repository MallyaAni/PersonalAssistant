from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

class MemoryProvider(ABC):
    """Abstract base class for all memory systems (Long-term, Episodic, Semantic)."""

    @abstractmethod
    def store(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Store a memory unit."""
        pass

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve relevant memories based on a query."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a specific memory unit."""
        pass

class SemanticMemoryProvider(MemoryProvider):
    """Specialized provider for semantic (vector-based) memory."""
    pass

class EpisodicMemoryProvider(MemoryProvider):
    """Specialized provider for episodic (event-based) memory."""
    pass