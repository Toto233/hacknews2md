"""
Handler modules extracted from summarize_news5.py.

Each handler focuses on a single content type:
  - twitter_handler  : X/Twitter URLs
  - youtube_handler  : YouTube URLs
  - pdf_handler      : PDF URLs
  - image_handler    : Image downloading and conversion
  - screenshot_handler : Page screenshot capture and LLM summarisation
  - discussion_handler : HN discussion page parsing
"""

from .discussion_handler import _fetch_discussion_via_selenium, get_discussion_content_async
from .anthropic_handler import get_anthropic_article_content, is_anthropic_article_url
from .hunyuan_handler import get_hunyuan_blog_content, is_hunyuan_blog_url
from .image_handler import get_extension_from_content_type, is_low_signal_article_image_url, save_article_image
from .openai_handler import get_openai_article_content, is_openai_article_url
from .pdf_handler import get_pdf_content
from .qwen_handler import get_qwen_blog_content, is_qwen_blog_url
from .screenshot_handler import get_summary_from_screenshot, save_page_screenshot
from .twitter_handler import (
    _extract_tweet_id,
    _fetch_x_via_selenium,
    _fetch_x_via_twscrape,
    _fetch_x_via_vxtwitter,
    _init_twscrape,
    _is_x_url,
    _screenshot_x_tweet,
)
from .youtube_handler import get_youtube_content

__all__ = [
    # Twitter
    "_is_x_url",
    "_extract_tweet_id",
    "_fetch_x_via_vxtwitter",
    "_fetch_x_via_selenium",
    "_init_twscrape",
    "_fetch_x_via_twscrape",
    "_screenshot_x_tweet",
    # YouTube
    "get_youtube_content",
    # Official AI labs
    "is_openai_article_url",
    "get_openai_article_content",
    "is_anthropic_article_url",
    "get_anthropic_article_content",
    "is_qwen_blog_url",
    "get_qwen_blog_content",
    # PDF
    "get_pdf_content",
    # Image
    "save_article_image",
    "get_extension_from_content_type",
    "is_low_signal_article_image_url",
    # Screenshot
    "save_page_screenshot",
    "get_summary_from_screenshot",
    # Discussion
    "get_discussion_content_async",
    "_fetch_discussion_via_selenium",
]
