"""Shared routing for first-party publication pages that need browser rendering."""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from urllib.parse import urlparse

from src.core.handlers.browser_article_handler import ArticleExtraction, get_browser_article_content


def is_official_publication_url(
    url: str,
    *,
    hosts: Collection[str],
    article_path_prefixes: Collection[str],
) -> bool:
    """Return True only for an HTTPS URL under an approved publication path."""
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() in hosts
        and parsed.path.startswith(tuple(article_path_prefixes))
    )


async def get_official_browser_article(url: str) -> ArticleExtraction:
    """Extract an approved first-party publication page within the browser budget."""
    return await asyncio.to_thread(get_browser_article_content, url)
