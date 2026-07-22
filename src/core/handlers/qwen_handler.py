"""Qwen blog handler backed by Qwen's public article API."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import structlog
from bs4 import BeautifulSoup

from src.core.handlers.article_extraction import ArticleExtraction
from src.security.url_validator import SecurityError, validate_url

logger = structlog.get_logger(__name__)

API_URL = "https://qwen.ai/api/v2/article/"
SUPPORTED_HOSTS = {"qwen.ai", "www.qwen.ai"}


def is_qwen_blog_url(url: str) -> bool:
    """Return True for a public Qwen blog URL with an article identifier."""
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() in SUPPORTED_HOSTS
        and parsed.path.rstrip("/") == "/blog"
        and bool(parse_qs(parsed.query).get("id"))
    )


def _article_slug(url: str) -> str:
    values = parse_qs(urlparse(url).query).get("id", [])
    return values[0].strip() if values else ""


def _article_image_urls(root: BeautifulSoup) -> tuple[str, ...]:
    """Return deduplicated, absolute image URLs from the article body."""
    image_urls: list[str] = []
    for image in root.select("img"):
        source = image.get("src") or image.get("data-src")
        if not isinstance(source, str) or not source.strip():
            continue
        resolved = urljoin("https://qwen.ai", source.strip())
        if resolved.startswith("http") and resolved not in image_urls:
            image_urls.append(resolved)
    return tuple(image_urls)


def extract_qwen_article_content(data: dict[str, Any]) -> ArticleExtraction:
    """Extract scoped readable text and article images from a Qwen API response."""
    article = data.get("data")
    if not isinstance(article, dict):
        return ArticleExtraction(reason="qwen_api_payload_invalid")
    title = article.get("title")
    html = article.get("content")
    if not isinstance(html, str) or not html.strip():
        return ArticleExtraction(reason="qwen_article_content_missing")
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("article") or soup.select_one("main") or soup
    for tag in root(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = root.get_text("\n", strip=True)
    parts = [part for part in (title, body) if isinstance(part, str) and part.strip()]
    return ArticleExtraction(content="\n\n".join(parts).strip(), image_urls=_article_image_urls(root))


async def _fetch_qwen_article(slug: str, language: str) -> dict[str, Any] | None:
    import aiohttp

    params = {"language": language, "path": slug, "type": "qwen_ai"}
    headers = {
        "Accept": "application/json",
        "Referer": f"https://qwen.ai/blog?id={slug}",
        "User-Agent": "hn2md/1.0 (+https://github.com/Toto233/hacknews2md)",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(API_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)) as response:
            if response.status != 200:
                logger.warning("qwen_article_response_failed", status=response.status, slug=slug)
                return None
            payload = await response.json(content_type=None)
            return payload if isinstance(payload, dict) else None


async def get_qwen_blog_content(url: str) -> ArticleExtraction:
    """Fetch Qwen blog text and images from its public structured article endpoint."""
    if not is_qwen_blog_url(url):
        return ArticleExtraction(reason="qwen_url_not_supported")
    try:
        validate_url(url)
        validate_url(API_URL)
    except (SecurityError, ValueError) as exc:
        logger.warning("qwen_url_validation_failed", error=str(exc), url=url[:80])
        return ArticleExtraction(reason="qwen_url_validation_failed")

    slug = _article_slug(url)
    for language in ("zh-CN", "en"):
        try:
            payload = await _fetch_qwen_article(slug, language)
        except Exception as exc:
            logger.warning("qwen_article_fetch_failed", error=str(exc), slug=slug, language=language)
            continue
        if payload and payload.get("success") is True:
            extraction = extract_qwen_article_content(payload)
            if extraction.content:
                return extraction
    return ArticleExtraction(reason="qwen_api_content_unavailable")
