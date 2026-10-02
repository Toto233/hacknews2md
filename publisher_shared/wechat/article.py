"""Source-independent article preparation and verified WeChat draft publication.

This module needs no source database, browser, LLM, or repository scripts.
Source workflows own editorial audits, publication locks, and durable receipts.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import structlog
from bs4 import BeautifulSoup
from src.security.content_sanitizer import sanitize_for_yaml

from .client import WeChatAccessToken
from .converter import convert_markdown_to_html
from .publication import (
    build_cover_crop_fields,
    parse_markdown_frontmatter,
    preview_wechat_article,
    verify_wechat_draft,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class PublishResult:
    """Confirmed outcome; the source workflow stores this in its receipt."""

    media_id: str
    verified: bool


class PublishError(RuntimeError):
    """Publication failure, retaining a known remote ID to prevent blind retries."""

    def __init__(self, message: str, *, media_id: str | None = None) -> None:
        super().__init__(message)
        self.media_id = media_id


def _configuration(config_path: Path | None) -> tuple[str, str, str]:
    path = config_path if config_path is not None else Path("config/config.json")
    config: dict = {}
    if path.is_file():
        config = json.loads(path.read_text(encoding="utf-8"))
    wechat = config.get("wechat", {})
    appid = os.getenv("WECHAT_APPID") or wechat.get("appid")
    secret = os.getenv("WECHAT_APPSEC") or os.getenv("WECHAT_APPSECRET") or wechat.get("appsec")
    if not appid or not secret:
        raise PublishError("Configure WECHAT_APPID and WECHAT_APPSEC or wechat.appid/appsec in JSON")
    db_path = Path(os.getenv("WECHAT_DB_PATH") or wechat.get("db_path") or "data/wechat.db")
    if config_path is not None and not db_path.is_absolute():
        config_dir = config_path.resolve().parent
        workspace = config_dir.parent if config_dir.name == "config" else config_dir
        db_path = workspace / db_path
    return str(appid), str(secret), str(db_path)


def preview_article(
    markdown_file: Path,
    cover_image: Path,
    *,
    config_path: Path | None = None,
    author: str = "PH月榜",
) -> bool:
    """Validate files offline; no credential loading, client creation, or HTTP."""
    markdown_file, cover_image = Path(markdown_file), Path(cover_image)
    valid = preview_wechat_article(
        str(markdown_file),
        author=author,
        cover_image=str(cover_image),
        auto_cover=False,
        image_base_dir=markdown_file.resolve().parent,
    )
    if not valid:
        return False
    # Every body image must be a local upload or an explicit HTTP(S) image.
    # Embedded data and protocol-relative URLs do not survive strict verification.
    parsed = parse_markdown_frontmatter(str(markdown_file))
    soup = BeautifulSoup(convert_markdown_to_html(parsed["raw_content"]), "html.parser")
    for image in soup.find_all("img"):
        source = str(image.get("src", ""))
        if source.startswith(("//", "data:")):
            logger.error("Unsupported article image source")
            return False
    return True


def publish_article(
    markdown_file: Path,
    cover_image: Path,
    *,
    config_path: Path | None = None,
    author: str = "PH月榜",
) -> PublishResult:
    """Upload a prepared article, then verify its cover and all remote images.

    A failed readback raises with the created media ID. Callers must preserve
    that ID and reconcile the remote draft before another creation attempt.
    """
    markdown_file, cover_image = Path(markdown_file), Path(cover_image)
    if not preview_article(markdown_file, cover_image, config_path=config_path, author=author):
        raise PublishError("WeChat local article preflight failed")
    parsed = parse_markdown_frontmatter(str(markdown_file))
    metadata = parsed["frontmatter"]
    soup = BeautifulSoup(convert_markdown_to_html(parsed["raw_content"]), "html.parser")
    body = soup.body or soup
    for image in body.find_all("img"):
        source = str(image.get("src", ""))
        if not source.startswith(("http://", "https://")):
            path = Path(source)
            if not path.is_absolute():
                path = markdown_file.resolve().parent / path
            image["src"] = str(path.resolve())
    content = str(body)
    title = metadata["title"]
    article = {
        "title": title,
        "content": content,
        "author": sanitize_for_yaml(author),
        "digest": metadata.get("digest") or title[:120],
        "content_source_url": metadata.get("source_url", ""),
        "article_type": "news",
        "need_open_comment": 1,
        "only_fans_can_comment": 1,
        **build_cover_crop_fields(str(cover_image)),
    }
    appid, secret, db_path = _configuration(config_path)
    client = WeChatAccessToken(appid, secret, db_path=db_path)
    if not client.get_access_token():
        raise PublishError("Could not obtain WeChat access token")
    media_id = client.add_draft_smart(
        [article], thumb_image_path=str(cover_image.resolve()), strict_images=True
    )
    if not media_id:
        raise PublishError("WeChat draft creation was not confirmed; reconcile the remote outcome before retrying")
    expected_images = len(body.find_all("img"))
    try:
        verified = verify_wechat_draft(client, media_id, title, expected_images, exact=True)
    except Exception as exc:
        raise PublishError("Draft created but verification failed", media_id=media_id) from exc
    if not verified:
        raise PublishError("Draft created but cover/body images were not verified", media_id=media_id)
    logger.info("WeChat draft verified", media_id=media_id)
    return PublishResult(media_id=media_id, verified=True)
