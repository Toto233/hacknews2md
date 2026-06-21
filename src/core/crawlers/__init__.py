"""Crawler abstraction layer.

Provides a uniform ``ContentCrawler`` protocol and two concrete
implementations that are interchangeable:

* ``ScraplingCrawler`` -- lightweight HTTP fetch via Scrapling's Fetcher
* ``Crawl4AICrawler``  -- full-page fetch via Crawl4AI's AsyncWebCrawler
"""

from src.core.crawlers.base import ContentCrawler
from src.core.crawlers.crawl4ai_crawler import Crawl4AICrawler
from src.core.crawlers.scrapling_crawler import ScraplingCrawler

__all__ = [
    "ContentCrawler",
    "ScraplingCrawler",
    "Crawl4AICrawler",
]
