"""Tencent Hunyuan blog handler.

The public Hunyuan article pages are rendered as a JavaScript shell, but
the page data is exposed through a stable public detail API.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from src.security.url_validator import SecurityError, validate_url
from src.core.handlers.article_extraction import ArticleExtraction

logger = logging.getLogger(__name__)

API_URL = "https://api.hunyuan.tencent.com/api/blog/publicDetail"
SUPPORTED_HOSTS = {"hy.tencent.com"}


def is_hunyuan_blog_url(url: str) -> bool:
    """Return True for public Hunyuan article URLs."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    if host not in SUPPORTED_HOSTS:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 2 and parts[0] in {"research", "blog"}


def _custom_url_from_page_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    return parts[-1]


def _strip_hunyuan_markdown(value: str) -> str:
    """Remove Hunyuan custom cards and image-only markdown noise."""
    text = re.sub(r"@@@[\s\S]*?@@@", "\n", value or "")
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", "\n", text)
    text = re.sub(r"<img\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_public_detail_content(data: dict[str, Any]) -> str:
    """Extract publishable article text from Hunyuan publicDetail JSON."""
    detail = data.get("data", {}).get("detail", {})
    if not isinstance(detail, dict):
        return ""

    title = detail.get("title")
    content = detail.get("content")
    parts: list[str] = []
    if isinstance(title, str) and title.strip():
        parts.append(title.strip())
    if isinstance(content, str) and content.strip():
        parts.append(_strip_hunyuan_markdown(content))
    return "\n\n".join(part for part in parts if part).strip()


async def _post_public_detail(custom_url: str, language: str = "en") -> dict[str, Any] | None:
    import aiohttp

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": language,
        "Content-Type": "application/json",
        "Origin": "https://hy.tencent.com",
        "Referer": f"https://hy.tencent.com/research/{custom_url}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    payload = {"id": 0, "customUrl": custom_url}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as response:
            if response.status != 200:
                logger.warning("[HUNYUAN] publicDetail failed status=%s custom_url=%s", response.status, custom_url)
                return None
            data = await response.json(content_type=None)
            return data if isinstance(data, dict) else None


async def get_hunyuan_blog_content(url: str) -> str:
    """Fetch Hunyuan blog/research content from the public detail API."""
    if not url:
        return ""
    try:
        validate_url(url)
        validate_url(API_URL)
    except (SecurityError, ValueError) as exc:
        logger.warning("[HUNYUAN] URL validation failed error=%s url=%s", exc, url[:80])
        return ""

    custom_url = _custom_url_from_page_url(url)
    if not custom_url:
        return ""

    try:
        data = await _post_public_detail(custom_url)
    except Exception as exc:
        logger.warning("[HUNYUAN] publicDetail exception error=%s custom_url=%s", exc, custom_url)
        return ""

    if not data or data.get("code") != 0:
        logger.warning("[HUNYUAN] publicDetail returned non-success custom_url=%s", custom_url)
        return ""
    return extract_public_detail_content(data)


async def get_hunyuan_article(url: str) -> ArticleExtraction:
    """Adapt Hunyuan's public API response to the common article contract."""
    content = await get_hunyuan_blog_content(url)
    return ArticleExtraction(
        content=content,
        reason=None if content else "hunyuan_api_content_unavailable",
    )
