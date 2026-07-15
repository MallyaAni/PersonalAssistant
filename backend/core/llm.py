from abc import ABC, abstractmethod
from typing import List, Dict, Any

class LLMClient(ABC):
    """Abstract base class for all LLM providers."""
    
    @abstractmethod
    def generate_text(self, prompt: str, max_tokens: int = 512) -> str:
        pass

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 512) -> Dict[str, Any]:
        pass

# Example of a concrete implementation for LM Studio / OpenAI compatible APIs
class OpenAICompatibleLLM(LLMClient):
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        # In a real implementation, we would initialize the LangChain/OpenAI client here

    def generate_text(self, prompt: str, max_tokens: int = 512) -> str:
        # Implementation using actual LLM library
        pass

    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 512) -> Dict[str, Any]:
        # Implementation using actual LLM library
        pass