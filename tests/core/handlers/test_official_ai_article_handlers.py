"""Tests for dedicated OpenAI, Anthropic, and Qwen article handlers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.handlers.anthropic_handler import get_anthropic_article_content, is_anthropic_article_url
from src.core.handlers.browser_article_handler import ArticleExtraction, _render_browser_article, get_browser_article_content
from src.core.handlers.openai_handler import get_openai_article_content, is_openai_article_url
from src.core.handlers.qwen_handler import extract_qwen_article_content, get_qwen_blog_content, is_qwen_blog_url


def test_official_ai_article_url_matchers_only_accept_article_urls() -> None:
    assert is_openai_article_url("https://openai.com/index/example/")
    assert is_openai_article_url("https://openai.com/research/example/")
    assert not is_openai_article_url("https://openai.com/")
    assert not is_openai_article_url("https://openai.com/legal/terms/")
    assert not is_openai_article_url("https://example.com/index/example/")

    assert is_anthropic_article_url("https://www.anthropic.com/news/example")
    assert is_anthropic_article_url("https://www.anthropic.com/research/example")
    assert not is_anthropic_article_url("https://anthropic.com/")
    assert not is_anthropic_article_url("https://anthropic.com/product/claude")
    assert not is_anthropic_article_url("https://example.com/news/example")

    assert is_qwen_blog_url("https://qwen.ai/blog?id=qwen-image-3.0")
    assert not is_qwen_blog_url("https://qwen.ai/blog")
    assert not is_qwen_blog_url("https://example.com/blog?id=qwen-image-3.0")


def test_openai_and_anthropic_handlers_use_browser_article_extraction() -> None:
    with patch(
        "src.core.handlers.openai_handler.get_official_browser_article",
        return_value=ArticleExtraction(content="OpenAI article body", image_urls=("https://cdn.openai.com/hero.jpg",)),
    ) as openai_browser, patch(
        "src.core.handlers.anthropic_handler.get_official_browser_article",
        return_value=ArticleExtraction(content="Anthropic article body"),
    ) as anthropic_browser:
        openai = asyncio.run(get_openai_article_content("https://openai.com/index/example/"))
        anthropic = asyncio.run(get_anthropic_article_content("https://www.anthropic.com/news/example"))

    assert openai == ArticleExtraction(content="OpenAI article body", image_urls=("https://cdn.openai.com/hero.jpg",))
    assert anthropic == ArticleExtraction(content="Anthropic article body")
    openai_browser.assert_called_once()
    anthropic_browser.assert_called_once()


def test_qwen_handler_uses_public_article_api_and_strips_html() -> None:
    payload = {
        "success": True,
        "data": {
            "title": "Qwen article",
            "content": (
                "<header>Navigation</header><article><h1>Ignored duplicate title</h1>"
                "<p>Readable body</p><img src='/hero.jpg'><script>hidden()</script></article>"
            ),
        },
    }
    with patch("src.core.handlers.qwen_handler.validate_url", return_value="validated"), patch(
        "src.core.handlers.qwen_handler._fetch_qwen_article",
        new=AsyncMock(return_value=payload),
    ) as fetch:
        content = asyncio.run(get_qwen_blog_content("https://qwen.ai/blog?id=qwen-image-3.0"))

    assert content == ArticleExtraction(
        content="Qwen article\n\nIgnored duplicate title\nReadable body",
        image_urls=("https://qwen.ai/hero.jpg",),
    )
    fetch.assert_awaited_once_with("qwen-image-3.0", "zh-CN")
    assert extract_qwen_article_content({"data": {"title": "Only", "content": "<p>Body</p>"}}) == ArticleExtraction(
        content="Only\n\nBody"
    )


def test_browser_article_render_extracts_main_text_and_images() -> None:
    driver = MagicMock()
    driver.execute_script.return_value = {
        "content": "Rendered article body",
        "imageUrls": ["https://cdn.example.com/hero.jpg", "not-a-url"],
    }
    with patch("src.core.handlers.browser_article_handler.webdriver.Chrome", return_value=driver):
        result = _render_browser_article("https://example.com/article")

    assert result == ArticleExtraction(
        content="Rendered article body",
        image_urls=("https://cdn.example.com/hero.jpg",),
    )
    driver.quit.assert_called_once()


def test_browser_article_process_timeout_returns_without_waiting_for_webdriver() -> None:
    process = MagicMock()
    process.is_alive.side_effect = [True, False, False]
    result_queue = MagicMock()
    process_context = MagicMock()
    process_context.Queue.return_value = result_queue
    process_context.Process.return_value = process

    with patch("src.core.handlers.browser_article_handler.validate_url", return_value="validated"), patch(
        "src.core.handlers.browser_article_handler.get_context",
        return_value=process_context,
    ):
        result = get_browser_article_content("https://openai.com/index/example/")

    assert result == ArticleExtraction(reason="browser_article_timeout")
    process.terminate.assert_called_once()
    result_queue.close.assert_called_once()
