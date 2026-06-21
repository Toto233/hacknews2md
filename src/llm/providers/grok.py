"""Grok API provider (xAI).

Uses the OpenAI-compatible chat completions endpoint.
Supports text and multimodal (image) input via Grok 4.1+.
Prefers httpx for SSL compatibility; falls back to curl-cffi.
"""

import logging

from src.llm.providers.base import LLMProvider
from src.llm.retry import with_retry
from src.security.content_sanitizer import redact_secrets

logger = logging.getLogger(__name__)


class GrokProvider(LLMProvider):
    """xAI Grok API provider.

    Calls the Grok chat completions endpoint (OpenAI-compatible).
    Image input is supported on Grok 4.1+ models.
    """

    name = "grok"

    def _load_config(self):
        """Load Grok-specific config from the shared LLM config."""
        from src.llm.llm_utils import load_llm_config

        return load_llm_config()["grok"]

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
        """Call Grok API for a single attempt.

        Retries are handled by the ``@with_retry`` decorator.  On final
        failure the exception propagates to the caller.
        """
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

        # -- Build messages --
        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})

        if image_data:
            user_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_data}"},
                },
            ]
        else:
            user_content = prompt
        messages.append({"role": "user", "content": user_content})

        data = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            data["response_format"] = response_format

        total_len = sum(len(str(m)) for m in messages)
        logger.info(
            "[Grok] prompt=%d chars, total=%d chars, ~%d tokens",
            len(prompt),
            total_len,
            total_len // 4,
        )

        # -- Send request (httpx preferred, curl-cffi fallback) --
        import certifi

        try:
            import httpx

            logger.info("[Grok] using httpx")
            with httpx.Client(
                verify=certifi.where(),
                timeout=120.0,
                follow_redirects=True,
            ) as client:
                response = client.post(api_url, headers=headers, json=data)
                response.raise_for_status()
        except ImportError:
            from curl_cffi import requests as curl_requests

            logger.info("[Grok] httpx unavailable, using curl-cffi")
            response = curl_requests.post(
                api_url,
                headers=headers,
                json=data,
                timeout=120,
                verify=certifi.where(),
            )
            response.raise_for_status()

        # -- Parse response --
        response_json = response.json()
        if "choices" in response_json:
            result = response_json["choices"][0]["message"]["content"].strip()
            logger.info("[Grok] success, %d chars", len(result))
            return result

        logger.warning(
            "[Grok] no 'choices' in response: %s",
            redact_secrets(str(response_json)[:500]),
        )
        return ""
