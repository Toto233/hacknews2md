"""Moonshot API provider (OpenAI-compatible interface).

Models:
  - moonshot-v1-8k  (8k context)
  - moonshot-v1-32k (32k context)
  - moonshot-v1-128k (128k context)
"""

import logging

from src.llm.providers.base import LLMProvider
from src.llm.retry import with_retry

logger = logging.getLogger(__name__)


class MoonshotProvider(LLMProvider):
    """Moonshot (Kimi) API provider using the OpenAI-compatible chat endpoint."""

    name = "moonshot"

    def _load_config(self):
        """Load Moonshot-specific config from the shared LLM config."""
        from src.llm.llm_utils import load_llm_config

        return load_llm_config()["moonshot"]

    @with_retry(max_retries=2, backoff_base=2.0, backoff_max=30.0)
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
        """Call the Moonshot chat completions API.

        Moonshot does not support image input.  If *image_data* is provided it
        is silently ignored (the caller should route image requests to Gemini
        or Grok instead).
        """
        from src.llm.llm_utils import _http_session

        config = self._load_config()
        api_key = config["api_key"]
        api_url = config["api_url"]
        model = model or config["model"]
        temperature = temperature if temperature is not None else config["temperature"]
        max_tokens = max_tokens or config["max_tokens"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "messages": [
                {
                    "role": "system",
                    "content": system_content or "你是 Kimi，由 Moonshot AI 提供的人工智能助手",
                },
                {"role": "user", "content": prompt},
            ],
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            data["response_format"] = response_format

        response = _http_session.post(api_url, headers=headers, json=data, timeout=60, verify=True)
        response.raise_for_status()
        response_json = response.json()

        if "choices" in response_json:
            return response_json["choices"][0]["message"]["content"].strip()
        return ""
