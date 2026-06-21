"""Abstract base class for LLM providers."""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base for LLM providers.

    Each provider implements the call() method which handles:
    - API key and endpoint resolution
    - Request construction
    - Response parsing
    - Error handling with redaction
    """

    name: str  # e.g., "grok", "gemini", "moonshot"

    @abstractmethod
    def call(
        self,
        prompt: str,
        system_content: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        image_data: str | None = None,
        max_retries: int = 2,
    ) -> str:
        """Call the LLM API.

        Args:
            prompt: User prompt text.
            system_content: System prompt (if supported).
            model: Specific model name (overrides config default).
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            response_format: Response format hint (e.g., JSON).
            image_data: Base64-encoded image (if supported).
            max_retries: Maximum retry attempts.

        Returns:
            Response text, or '' on failure.
        """
        ...

    def health_check(self) -> bool:
        """Quick health check. Default: try a trivial call."""
        try:
            result = self.call("ping", max_tokens=5, max_retries=0)
            return bool(result)
        except Exception:
            return False
