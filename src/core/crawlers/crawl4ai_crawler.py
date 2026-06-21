"""Content crawler backed by Crawl4AI's AsyncWebCrawler."""

import logging
import re

from src.security.url_validator import SecurityError, validate_url

logger = logging.getLogger(__name__)


class Crawl4AICrawler:
    """Crawl web pages using Crawl4AI's ``AsyncWebCrawler``.

    Implements the ``ContentCrawler`` protocol.
    """

    def __init__(self, max_images: int = 5) -> None:
        from crawl4ai import AsyncWebCrawler

        self._crawler = AsyncWebCrawler()
        self._max_images = max_images

    async def crawl_article(self, url: str) -> tuple[str, list[str]]:
        """Fetch *url* and return (text_content, image_urls).

        Uses ``AsyncWebCrawler.arun`` under the hood, then parses the
        returned HTML with BeautifulSoup to extract text and images.
        """
        logger.info("[CRAWL4AI] Crawling: %s", url[:80])

        # SSRF protection
        try:
            validate_url(url)
        except (SecurityError, ValueError) as e:
            logger.warning("[CRAWL4AI] URL validation failed: %s | url=%s", e, url[:80])
            return "", []

        try:
            result = await self._crawler.arun(url=url)
        except Exception as exc:
            logger.error("[CRAWL4AI] Fetch failed for %s: %s", url[:60], exc)
            return "", []

        if not result.success:
            error_msg = getattr(result, "error", "unknown error")
            logger.warning("[CRAWL4AI] Failed for %s: %s", url[:60], error_msg)
            return "", []

        # --- parse HTML ------------------------------------------------------
        images: list[str] = []
        content = ""

        html = getattr(result, "html", None)
        if html:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # images
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if src and src.startswith("http"):
                    images.append(src)

            # text
            content = self._extract_main_content(soup)

        # --- clean up text ---------------------------------------------------
        content = re.sub(r"\s{2,}", " ", content)
        content = re.sub(r"(\n\s*){2,}", "\n\n", content)
        content = "".join(ch for ch in content if ch.isprintable() or ch.isspace())

        logger.info(
            "[CRAWL4AI] Done | chars=%d | images=%d",
            len(content),
            len(images),
        )
        return content.strip(), images[: self._max_images]

    async def close(self) -> None:
        """Release the underlying Crawl4AI crawler if it exposes a close method."""
        close_fn = getattr(self._crawler, "close", None)
        if close_fn is not None:
            await close_fn()

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_main_content(soup) -> str:
        """Heuristically pull the main readable text from *soup*."""
        # Remove boilerplate tags
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "menu"]):
            tag.decompose()

        # Remove common non-content selectors
        for selector in [
            ".nav",
            ".navigation",
            ".menu",
            ".sidebar",
            ".ad",
            ".advertisement",
            ".header",
            ".footer",
            ".breadcrumb",
            ".pagination",
            ".social-share",
            '[class*="nav"]',
            '[class*="menu"]',
            '[class*="sidebar"]',
            '[class*="ad"]',
            '[id*="nav"]',
            '[id*="menu"]',
            '[id*="sidebar"]',
            '[id*="ad"]',
        ]:
            for tag in soup.select(selector):
                tag.decompose()

        # Try content-area selectors in priority order
        for selector in [
            "article",
            "main",
            ".content",
            ".post-content",
            ".article-content",
            ".entry-content",
            ".post-body",
            ".article-body",
            ".story-content",
            '[role="main"]',
            '[role="article"]',
            ".main-content",
            ".primary-content",
        ]:
            main_content = soup.select_one(selector)
            if main_content:
                for tag in main_content.find_all(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                return main_content.get_text(separator=" ", strip=True)

        # Fallback: pick the element with the most text
        text_elements = soup.find_all(["p", "div", "section"])
        if text_elements:
            best = max(text_elements, key=lambda el: len(el.get_text()))
            return best.get_text(separator=" ", strip=True)

        # Last resort: full body text
        body = soup.find("body")
        if body:
            return body.get_text(separator=" ", strip=True)

        return ""
