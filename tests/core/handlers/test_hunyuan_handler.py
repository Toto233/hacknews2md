import asyncio
from unittest.mock import AsyncMock, patch

from src.core.handlers.hunyuan_handler import (
    extract_public_detail_content,
    get_hunyuan_article,
    get_hunyuan_blog_content,
    is_hunyuan_blog_url,
)


def test_is_hunyuan_blog_url_matches_public_article_paths() -> None:
    assert is_hunyuan_blog_url("https://hy.tencent.com/research/hy3")
    assert is_hunyuan_blog_url("https://hy.tencent.com/blog/example")
    assert not is_hunyuan_blog_url("https://hy.tencent.com/")
    assert not is_hunyuan_blog_url("https://example.com/research/hy3")


def test_extract_public_detail_content_strips_custom_blocks_and_images() -> None:
    data = {
        "code": 0,
        "data": {
            "detail": {
                "title": "Introducing Hy3",
                "content": "Lead paragraph.\n\n@@@card\nhidden\n@@@\n\n![hero](https://img)\n\nSecond paragraph.",
            }
        },
    }

    assert extract_public_detail_content(data) == "Introducing Hy3\n\nLead paragraph.\n\nSecond paragraph."


def test_get_hunyuan_blog_content_uses_public_detail_api() -> None:
    payload = {
        "code": 0,
        "data": {
            "detail": {
                "title": "Introducing Hy3",
                "content": "Full article body " * 10,
            }
        },
    }

    with patch(
        "src.core.handlers.hunyuan_handler._post_public_detail",
        new=AsyncMock(return_value=payload),
    ) as post:
        content = asyncio.run(get_hunyuan_blog_content("https://hy.tencent.com/research/hy3"))

    post.assert_awaited_once_with("hy3")
    assert content.startswith("Introducing Hy3")
    assert "Full article body" in content


def test_get_hunyuan_article_adapts_text_to_the_shared_contract() -> None:
    with patch(
        "src.core.handlers.hunyuan_handler.get_hunyuan_blog_content",
        new=AsyncMock(return_value="Hunyuan article body"),
    ):
        result = asyncio.run(get_hunyuan_article("https://hy.tencent.com/research/hy3"))

    assert result.content == "Hunyuan article body"
    assert result.reason is None
