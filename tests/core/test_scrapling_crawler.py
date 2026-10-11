"""Tests for Scrapling response extraction compatibility."""

from __future__ import annotations

import asyncio
import re

import pytest

from src.core.crawlers import scrapling_crawler


class _FakePage:
    text = ""

    def xpath(self, _selector: str) -> list[str]:
        return ["Readable article body"]

    def css(self, _selector: str) -> list[object]:
        return []


class _FakeFetcher:
    @staticmethod
    def get(*_args: object, **_kwargs: object) -> _FakePage:
        return _FakePage()


@pytest.fixture(autouse=True)
def offline_crawler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scrapling_crawler, "validate_url", lambda url: url)
    monkeypatch.setattr(scrapling_crawler, "SCRAPLING_AVAILABLE", True)
    monkeypatch.setattr(scrapling_crawler, "Fetcher", _FakeFetcher, raising=False)
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        lambda *args, **kwargs: pytest.fail("Crawler tests must not use live HTTP"),
    )


def test_crawl_article_uses_full_response_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scrapling_crawler, "SCRAPLING_AVAILABLE", True)
    monkeypatch.setattr(scrapling_crawler, "Fetcher", _FakeFetcher, raising=False)

    content, images = asyncio.run(
        scrapling_crawler.ScraplingCrawler().crawl_article("https://example.com/article")
    )

    assert content == "Readable article body"
    assert images == []


@pytest.mark.parametrize("byte_body", [False, True], ids=["text-html", "utf8-bytes"])
@pytest.mark.parametrize(
    ("article_html", "expected"),
    [
        (
            '<p>We will support the <a href="/runtime">Deno runtime</a> for another year '
            'with monthly releases containing bug fixes and security updates.</p>',
            "We will support the Deno runtime for another year with monthly releases "
            "containing bug fixes and security updates.",
        ),
        (
            '<p>The check only runs <strong>if the line is present</strong>, '
            'so leaving it out skips it. The destination is set only by '
            '<code>channel:</code>, and has to be a channel or a supergroup.</p>',
            "The check only runs if the line is present, so leaving it out skips it. "
            "The destination is set only by channel:, and has to be a channel or a supergroup.",
        ),
        (
            '<p>执行 <code>go clean -cache</code> 后再编译，保留模块缓存。</p>'
            '<pre><code>first_call();\nsecond_call();</code></pre><p>代码块之后的结论。</p>',
            "执行 go clean -cache 后再编译，保留模块缓存。 first_call(); second_call(); 代码块之后的结论。",
        ),
    ],
    ids=["deno-support-promise", "telegram-conditional", "inline-and-block-code"],
)
def test_crawl_preserves_complete_inline_sentences(
    monkeypatch: pytest.MonkeyPatch, article_html: str, expected: str, byte_body: bool,
) -> None:
    parser = pytest.importorskip("scrapling.parser")
    html = (
        '<html><head><script>tracking-script</script><style>hidden-style</style></head>'
        f'<body><article>{article_html}</article><!-- hidden-comment --></body></html>'
    )
    page = (
        parser.Adaptor(body=html.encode("utf-8"), encoding="utf-8")
        if byte_body else parser.Adaptor(text=html)
    )

    class FixtureFetcher:
        @staticmethod
        def get(*_args: object, **_kwargs: object) -> object:
            return page

    monkeypatch.setattr(scrapling_crawler, "Fetcher", FixtureFetcher)
    content, images = asyncio.run(
        scrapling_crawler.ScraplingCrawler().crawl_article("https://example.com/article")
    )

    readable_text = re.sub(r"\s+([,.])", r"\1", " ".join(content.split()))
    assert readable_text == expected
    assert images == []


def test_crawl_handles_missing_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_FakeFetcher, "get", lambda *_args, **_kwargs: None)
    assert asyncio.run(
        scrapling_crawler.ScraplingCrawler().crawl_article("https://example.com/article")
    ) == ("", [])


def test_crawl_handles_page_without_text(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = pytest.importorskip("scrapling.parser")
    page = parser.Adaptor(text="<html><body><script>not article text</script></body></html>")
    monkeypatch.setattr(_FakeFetcher, "get", lambda *_args, **_kwargs: page)
    assert asyncio.run(
        scrapling_crawler.ScraplingCrawler().crawl_article("https://example.com/article")
    ) == ("", [])


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
