"""Base protocol for content crawlers."""

from typing import Protocol


class ContentCrawler(Protocol):
    """Protocol defining the interface all content crawlers must implement."""

    async def crawl_article(self, url: str) -> tuple[str, list[str]]:
        """Crawl a URL and extract article content and image URLs.

        Args:
            url: The URL to crawl.

        Returns:
            A tuple of (text_content, image_urls).
        """
        ...

    async def close(self) -> None:
        """Release any resources held by the crawler."""
        ...
