"""Anthropic news and research article handler for rendered pages."""

from __future__ import annotations

from src.core.handlers.article_extraction import ArticleExtraction
from src.core.handlers.official_browser_handler import get_official_browser_article, is_official_publication_url

SUPPORTED_HOSTS = {"anthropic.com", "www.anthropic.com"}
ARTICLE_PATH_PREFIXES = ("/news/", "/research/", "/engineering/", "/index/")


def is_anthropic_article_url(url: str) -> bool:
    """Return True only for supported official Anthropic publication paths."""
    return is_official_publication_url(
        url,
        hosts=SUPPORTED_HOSTS,
        article_path_prefixes=ARTICLE_PATH_PREFIXES,
    )


async def get_anthropic_article_content(url: str) -> ArticleExtraction:
    """Render and extract an official Anthropic article in a bounded browser process."""
    return await get_official_browser_article(url)
