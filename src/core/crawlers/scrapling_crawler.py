"""Content crawler backed by Scrapling's Fetcher."""

import logging
import re
from urllib.parse import urljoin

from src.security.url_validator import SecurityError, validate_url

logger = logging.getLogger(__name__)

try:
    from scrapling.fetchers import Fetcher

    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False
    logger.warning("Scrapling not installed. Install with: pip install scrapling")


class ScraplingCrawler:
    """Crawl web pages using Scrapling's Fetcher with stealthy headers.

    Implements the ``ContentCrawler`` protocol.
    """

    def __init__(self, max_images: int = 5) -> None:
        if not SCRAPLING_AVAILABLE:
            raise ImportError("Scrapling is not installed. Run: pip install scrapling")
        self._max_images = max_images

    async def crawl_article(self, url: str) -> tuple[str, list[str]]:
        """Fetch *url* and return (text_content, image_urls).

        Uses Scrapling's ``Fetcher`` with ``stealthy_headers=True`` to
        bypass basic anti-bot protections.
        """
        logger.info("[SCRAPLING] Crawling: %s", url[:80])

        # SSRF protection
        try:
            validate_url(url)
        except (SecurityError, ValueError) as e:
            logger.warning("[SCRAPLING] URL validation failed: %s | url=%s", e, url[:80])
            return "", []

        try:
            Fetcher.configure(adaptive=True)
            page = Fetcher.get(url, stealthy_headers=True)
        except Exception as exc:
            logger.error("[SCRAPLING] Fetch failed for %s: %s", url[:60], exc)
            return "", []

        # --- text content ---------------------------------------------------
        content: str = page.get_all_text()

        # --- image URLs ------------------------------------------------------
        images: list[str] = []
        try:
            for img in page.css("img")[:10]:
                src = img.attrib.get("src") or img.attrib.get("data-src")
                if not src:
                    continue
                src = self._resolve_url(url, src)
                if src.startswith("http"):
                    images.append(src)
        except Exception as exc:
            logger.warning("[SCRAPLING] Image extraction failed: %s", exc)

        # --- clean up text ---------------------------------------------------
        content = re.sub(r"\s{2,}", " ", content)
        content = re.sub(r"(\n\s*){2,}", "\n\n", content)
        content = "".join(ch for ch in content if ch.isprintable() or ch.isspace())

        logger.info(
            "[SCRAPLING] Done | chars=%d | images=%d",
            len(content),
            len(images),
        )
        return content.strip(), images[: self._max_images]

    async def close(self) -> None:
        """No persistent resources to release."""

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_url(base: str, src: str) -> str:
        """Resolve *src* relative to *base*, handling ``//`` and ``/`` prefixes."""
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/") or not src.startswith("http"):
            return urljoin(base, src)
        return src
