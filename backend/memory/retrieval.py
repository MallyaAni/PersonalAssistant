from dataclasses import dataclass
from typing import Any

from backend.models.memory import SemanticMemory


@dataclass(frozen=True)
class SemanticRetrievalPolicy:
    max_cosine_distance: float = 0.35
    max_results: int = 5
    max_content_chars: int = 4_000

    def select(
        self,
        matches: list[tuple[SemanticMemory, float]],
        requested_results: int,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        used_chars = 0
        result_limit = min(requested_results, self.max_results)

        for memory, distance in matches:
            if len(selected) >= result_limit:
                break
            if distance > self.max_cosine_distance:
                continue
            content_size = len(memory.content)
            if used_chars + content_size > self.max_content_chars:
                continue
            item = memory.to_dict()
            item["retrieval"] = {
                "cosine_distance": round(distance, 6),
                "relevance_score": round(max(0.0, 1.0 - distance), 6),
            }
            selected.append(item)
            used_chars += content_size

        return selected
