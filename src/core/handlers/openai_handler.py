"""OpenAI news and research article handler for protected pages."""

from __future__ import annotations

from src.core.handlers.article_extraction import ArticleExtraction
from src.core.handlers.official_browser_handler import get_official_browser_article, is_official_publication_url

SUPPORTED_HOSTS = {"openai.com", "www.openai.com"}
ARTICLE_PATH_PREFIXES = ("/index/", "/news/", "/research/", "/blog/")


def is_openai_article_url(url: str) -> bool:
    """Return True only for supported official OpenAI publication paths."""
    return is_official_publication_url(
        url,
        hosts=SUPPORTED_HOSTS,
        article_path_prefixes=ARTICLE_PATH_PREFIXES,
    )


async def get_openai_article_content(url: str) -> ArticleExtraction:
    """Render and extract an official OpenAI article in a bounded browser process."""
    return await get_official_browser_article(url)
