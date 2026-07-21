"""Tests for Scrapling response extraction compatibility."""

from __future__ import annotations

import asyncio

import pytest

from src.core.crawlers import scrapling_crawler


class _FakePage:
    text = ""

    def get_all_text(self) -> str:
        return "Readable article body"

    def css(self, _selector: str) -> list[object]:
        return []


class _FakeFetcher:
    @staticmethod
    def get(*_args: object, **_kwargs: object) -> _FakePage:
        return _FakePage()


def test_crawl_article_uses_full_response_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scrapling_crawler, "SCRAPLING_AVAILABLE", True)
    monkeypatch.setattr(scrapling_crawler, "Fetcher", _FakeFetcher, raising=False)

    content, images = asyncio.run(
        scrapling_crawler.ScraplingCrawler().crawl_article("https://example.com/article")
    )

    assert content == "Readable article body"
    assert images == []
