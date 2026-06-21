"""Gemini API provider (Google) with load balancing and quota management."""

import logging
import random
import re
import time

from src.llm.providers.base import LLMProvider
from src.security.content_sanitizer import redact_secrets

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Google Gemini API provider with load balancing, rate limiting,
    daily quota management, and automatic model switching."""

    name = "gemini"

    def _load_config(self):
        from src.llm.llm_utils import load_llm_config

        return load_llm_config()["gemini"]

    # -- Error helpers ---------------------------------------------------

    @staticmethod
    def _extract_retry_delay(error_msg: str, attempt: int) -> float:
        """Parse retry hint from error message or compute exponential backoff."""
        for pat in (
            r'["\']retryDelay["\']\s*:\s*["\'](\d+)s["\']',
            r"retry in ([\d.]+)s",
            r"retry_delay\s*\{\s*seconds:\s*(\d+)",
        ):
            m = re.search(pat, error_msg)
            if m:
                return float(m.group(1)) + random.uniform(1.0, 3.0)
        lower = error_msg.lower()
        if "503" in error_msg or "unavailable" in lower:
            return min(60, 3**attempt + random.uniform(2, 5))
        return min(90, 10 * (2**attempt)) + random.uniform(1.0, 3.0)

    @staticmethod
    def _is_retryable(error_msg: str) -> bool:
        lower = error_msg.lower()
        codes = ("503", "429", "500", "502", "504")
        keywords = ("quota", "rate limit", "service unavailable", "unavailable", "overloaded", "resource_exhausted")
        return any(c in error_msg for c in codes) or any(k in lower for k in keywords)

    def _process_error(self, error, model, attempt, max_retries):
        """Classify error.  Returns 'retry', 'switch', or 'fail'."""
        from src.llm.llm_utils import (
            GEMINI_FALLBACK_MODEL,
            disable_model_for_today,
            gemini_balancer,
            is_gemini_quota_exceeded_error,
        )

        error_msg = redact_secrets(str(error))
        if is_gemini_quota_exceeded_error(error_msg):
            logger.info("model %s quota exhausted, disabling for today", model)
            disable_model_for_today("gemini", model, "quota_exhausted", error_msg)
            gemini_balancer.report_failure(model)
            return "switch" if model != GEMINI_FALLBACK_MODEL else "fail"
        if self._is_retryable(error_msg) and attempt < max_retries - 1:
            delay = self._extract_retry_delay(error_msg, attempt)
            logger.warning(
                "Gemini error (attempt %d/%d): %.200s — retry in %.1fs", attempt + 1, max_retries, error_msg, delay
            )
            time.sleep(delay)
            return "retry"
        logger.error("Gemini unrecoverable: %.200s", error_msg)
        return "fail"

    # -- Single-attempt helpers ------------------------------------------

    @staticmethod
    def _try_genai_sdk(api_key, model, contents, temperature, max_tokens):
        """One attempt via google-genai SDK.  Returns text or raises."""
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        if hasattr(response, "text") and response.text:
            return response.text.strip()
        return ""

    @staticmethod
    def _try_requests(api_url, api_key, prompt, image_data, temperature, max_tokens):
        """One attempt via plain HTTP requests.  Returns text or raises."""
        from src.llm.llm_utils import _http_session

        headers = {"Content-Type": "application/json"}
        params = {"key": api_key}
        if image_data:
            parts = [{"text": prompt}, {"inline_data": {"mime_type": "image/png", "data": image_data}}]
        else:
            parts = [{"text": prompt}]
        data = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        resp = _http_session.post(api_url, headers=headers, params=params, json=data, timeout=60)
        resp.raise_for_status()
        rj = resp.json()
        if "candidates" in rj and rj["candidates"]:
            return rj["candidates"][0]["content"]["parts"][0]["text"].strip()
        return ""

    # -- Main entry point ------------------------------------------------

    def call(
        self,
        prompt: str,
        system_content: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        image_data: str | None = None,
        max_retries: int = 5,
    ) -> str:
        from src.llm.llm_utils import (
            GEMINI_FALLBACK_MODEL,
            GEMINI_STRICT_LIMIT_PER_DAY,
            GEMINI_STRICT_LIMIT_PER_MINUTE,
            _is_forbidden_gemini_model,
            _is_strict_capped_gemini_model,
            _reserve_daily_request_slot,
            disable_model_for_today,
            gemini_balancer,
            rate_limiter,
        )

        config = self._load_config()
        api_key = config["api_key"]
        fallback = GEMINI_FALLBACK_MODEL

        # Model selection via balancer
        preferred = model if model is not None else config.get("model")
        model = gemini_balancer.get_next_model(preferred_model=preferred)
        if _is_forbidden_gemini_model(model):
            logger.info("[policy] %s forbidden -> %s", model, fallback)
            disable_model_for_today(
                "gemini", model, "policy_forbidden_model", "Gemini 2.5 family is disabled by policy"
            )
            gemini_balancer.report_failure(model)
            model = gemini_balancer.get_next_model(preferred_model=fallback)
        if not model:
            logger.warning("Gemini: all models unavailable today")
            return ""

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        # Rate limiting
        if _is_strict_capped_gemini_model(model):
            rpm, window = GEMINI_STRICT_LIMIT_PER_MINUTE, 60
            logger.info("%s rate-limit: %d/min, %d/day", model, rpm, GEMINI_STRICT_LIMIT_PER_DAY)
        elif "3.1-flash-lite-preview" in (model or ""):
            rpm, window = 15, 60
        else:
            rpm, window = 8, 60
        rate_limiter.wait_if_needed(f"gemini-{model}", max_requests=rpm, window_seconds=window)

        # Daily quota reservation (strict-capped models)
        if _is_strict_capped_gemini_model(model):
            if not _reserve_daily_request_slot("gemini", model, GEMINI_STRICT_LIMIT_PER_DAY):
                logger.info("%s daily limit (%d) reached -> %s", model, GEMINI_STRICT_LIMIT_PER_DAY, fallback)
                disable_model_for_today(
                    "gemini",
                    model,
                    "daily_limit_reached_local",
                    f"Local daily limit: {GEMINI_STRICT_LIMIT_PER_DAY}/day",
                )
                gemini_balancer.report_failure(model)
                if model != fallback:
                    return self.call(
                        prompt,
                        system_content,
                        fallback,
                        temperature,
                        max_tokens,
                        response_format,
                        max_retries=max_retries,
                        image_data=image_data,
                    )
                return ""

        temperature = temperature if temperature is not None else config.get("temperature", 0.7)
        max_tokens = max_tokens or config.get("max_tokens", 800)
        logger.info("[Gemini] model=%s prompt=%d chars", model, len(prompt))

        contents = (
            [{"text": prompt}, {"inline_data": {"mime_type": "image/png", "data": image_data}}]
            if image_data
            else prompt
        )

        # Retry loop — SDK first, then requests fallback per attempt
        for attempt in range(max_retries):
            # SDK
            try:
                result = self._try_genai_sdk(api_key, model, contents, temperature, max_tokens)
                if result:
                    gemini_balancer.report_success(model)
                    return result
                logger.warning("[Gemini] SDK returned empty")
                return ""
            except ImportError:
                logger.error("google-genai not installed: pip install google-genai")
                return ""
            except Exception as e:
                action = self._process_error(e, model, attempt, max_retries)
                if action == "switch":
                    return self.call(
                        prompt,
                        system_content,
                        fallback,
                        temperature,
                        max_tokens,
                        response_format,
                        max_retries=max_retries,
                        image_data=image_data,
                    )
                if action == "retry":
                    continue

            # Requests fallback
            try:
                result = self._try_requests(api_url, api_key, prompt, image_data, temperature, max_tokens)
                if result:
                    gemini_balancer.report_success(model)
                    return result
                logger.warning("[Gemini] requests returned empty")
                return ""
            except Exception as e:
                action = self._process_error(e, model, attempt, max_retries)
                if action == "switch":
                    return self.call(
                        prompt,
                        system_content,
                        fallback,
                        temperature,
                        max_tokens,
                        response_format,
                        max_retries=max_retries,
                        image_data=image_data,
                    )
                if action == "retry":
                    continue
                break

        logger.warning("Gemini API failed after %d attempts", max_retries)
        return ""
