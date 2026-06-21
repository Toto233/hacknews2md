"""
YouTube content handler -- extracted from summarize_news5.py.

Supports regular videos, shorts, and youtu.be short links.
Fetches subtitles via youtube_transcript_api and downloads the thumbnail.
"""

import logging
from urllib.parse import parse_qs, urlparse

from src.core.handlers.image_handler import save_article_image
from src.security.url_validator import SecurityError, validate_url

logger = logging.getLogger(__name__)


async def get_youtube_content(url: str, title: str) -> tuple[str, list[str], list[str]]:
    """Fetch YouTube video subtitles and thumbnail.

    Args:
        url:   YouTube video URL.
        title: Human-readable title (used for thumbnail filename).

    Returns:
        (article_content, image_paths, image_paths) tuple.
        image_paths contains the local path to the downloaded thumbnail
        (or is empty on failure).
    """
    # SSRF protection: validate URL before fetching
    try:
        validate_url(url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"[YOUTUBE] URL validation failed | {e} | url={url[:80]}")
        return "", [], []

    parsed_url = urlparse(url)
    video_id = None

    if parsed_url.netloc in ("www.youtube.com", "youtube.com") and parsed_url.path == "/watch":
        query_params = parse_qs(parsed_url.query)
        if "v" in query_params:
            video_id = query_params["v"][0]
    elif parsed_url.netloc in ("www.youtube.com", "youtube.com") and parsed_url.path.startswith("/shorts/"):
        video_id = parsed_url.path.split("/shorts/")[1].split("/")[0].split("?")[0]
    elif parsed_url.netloc == "youtu.be":
        video_id = parsed_url.path.lstrip("/").split("?")[0]

    if not video_id:
        return "", [], []

    logger.info(f"[YOUTUBE] detected | ID:{video_id} | '{title[:40]}...'")

    article_content = ""
    try:
        from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        # Prefer manual subtitles, fall back to auto-generated
        transcript = transcript_list.find_transcript(["zh-Hans", "zh-Hant", "en"])
        transcript_data = transcript.fetch()
        article_content = " ".join([item.text for item in transcript_data])
        logger.info(f"[YOUTUBE] subtitle OK | len:{len(article_content)}")
    except ImportError as e:
        logger.warning(f"[YOUTUBE] transcript library not installed: {e}")
        article_content = f"无法获取视频 {title} 的字幕（缺少依赖库）。"
    except NoTranscriptFound:
        logger.warning(f"[YOUTUBE] no transcript available | ID:{video_id}")
        article_content = f"无法获取视频 {title} 的字幕。"
    except TranscriptsDisabled:
        logger.warning(f"[YOUTUBE] transcripts disabled | ID:{video_id}")
        article_content = f"无法获取视频 {title} 的字幕（字幕已禁用）。"
    except Exception as e:
        logger.error(f"[YOUTUBE] error: {e}")
        article_content = f"获取视频 {title} 字幕时出错。"

    # Thumbnail
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    logger.info(f"[YOUTUBE] thumbnail | {thumbnail_url}")

    thumbnail_path = save_article_image(thumbnail_url, url, f"{title}_1")
    image_paths = [thumbnail_path] if thumbnail_path else []

    return article_content, image_paths, image_paths
