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


def test_github_crawl_uses_social_card_and_readme_images_not_page_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Element:
        def __init__(self, **attributes: str) -> None:
            self.attrib = attributes

    class GithubPage(_FakePage):
        def css(self, selector: str) -> list[object]:
            if selector.startswith("meta["):
                return [Element(content="https://opengraph.githubassets.com/hash/owner/repo")]
            if selector == ".markdown-body img":
                return [Element(src="https://raw.githubusercontent.com/owner/repo/main/demo.png")]
            if selector == "img":
                raise AssertionError("GitHub page-chrome images must not be scanned")
            return []

    class GithubFetcher:
        @staticmethod
        def get(*_args: object, **_kwargs: object) -> GithubPage:
            return GithubPage()

    monkeypatch.setattr(scrapling_crawler, "SCRAPLING_AVAILABLE", True)
    monkeypatch.setattr(scrapling_crawler, "Fetcher", GithubFetcher, raising=False)

    _, images = asyncio.run(scrapling_crawler.ScraplingCrawler().crawl_article("https://github.com/owner/repo"))

    assert images == [
        "https://opengraph.githubassets.com/hash/owner/repo",
        "https://raw.githubusercontent.com/owner/repo/main/demo.png",
    ]
