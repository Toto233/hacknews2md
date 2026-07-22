"""Registry for first-party article extraction adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.core.handlers.article_extraction import ArticleExtraction


@dataclass(frozen=True)
class RegisteredArticleHandler:
    """One site-specific adapter behind the common article extraction seam."""

    name: str
    matches: Callable[[str], bool]
    extract: Callable[[str], Awaitable[ArticleExtraction]]


def resolve_article_handler(url: str) -> RegisteredArticleHandler | None:
    """Return the first first-party adapter that explicitly accepts *url*."""
    from src.core.handlers.anthropic_handler import get_anthropic_article_content, is_anthropic_article_url
    from src.core.handlers.hunyuan_handler import get_hunyuan_article, is_hunyuan_blog_url
    from src.core.handlers.openai_handler import get_openai_article_content, is_openai_article_url
    from src.core.handlers.qwen_handler import get_qwen_blog_content, is_qwen_blog_url

    handlers = (
        RegisteredArticleHandler("hunyuan", is_hunyuan_blog_url, get_hunyuan_article),
        RegisteredArticleHandler("openai", is_openai_article_url, get_openai_article_content),
        RegisteredArticleHandler("anthropic", is_anthropic_article_url, get_anthropic_article_content),
        RegisteredArticleHandler("qwen", is_qwen_blog_url, get_qwen_blog_content),
    )
    return next((handler for handler in handlers if handler.matches(url)), None)
