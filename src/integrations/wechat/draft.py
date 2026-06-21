"""WeChat draft management: list, add, smart-add with auto image upload, formatting."""

import json
import logging
import os
import re
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class DraftManager:
    """Create and list WeChat article drafts."""

    def __init__(self, token_manager, media_manager):
        self._tm = token_manager
        self._mm = media_manager

    def get_draft_list(self, offset: int = 0, count: int = 20, no_content: int = 0) -> dict | None:
        if not 1 <= count <= 20:
            logger.error("count must be between 1 and 20")
            return None
        if no_content not in (0, 1):
            logger.error("no_content must be 0 or 1")
            return None
        access_token = self._tm.get_access_token()
        if not access_token:
            logger.error("Could not get access token")
            return None
        url = f"https://api.weixin.qq.com/cgi-bin/draft/batchget?access_token={access_token}"
        payload = {"offset": offset, "count": count, "no_content": no_content}
        try:
            logger.info(f"Requesting draft list (offset={offset}, count={count}, no_content={no_content})...")
            payload_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, data=payload_json, headers=headers, timeout=30)
            response.raise_for_status()
            response.encoding = "utf-8"
            data = response.json()
            if "total_count" in data:
                logger.info(
                    f"Successfully retrieved draft list: total={data.get('total_count', 0)}, returned={data.get('item_count', 0)}"
                )
                return data
            logger.error(f"WeChat API error {data.get('errcode')}: {data.get('errmsg')}")
            return None
        except Exception as e:
            logger.error(f"Error fetching draft list: {e}")
            return None

    def add_draft(self, articles: list) -> str | None:
        if not articles or not isinstance(articles, list):
            logger.error("articles must be a non-empty list")
            return None
        for i, article in enumerate(articles):
            if not article.get("title"):
                logger.error(f"Article {i + 1} missing required field 'title'")
                return None
            if not article.get("content"):
                logger.error(f"Article {i + 1} missing required field 'content'")
                return None
            atype = article.get("article_type", "news")
            if atype == "news" and not article.get("thumb_media_id"):
                logger.error(f"Article {i + 1} of type 'news' requires 'thumb_media_id'")
                return None
            if atype == "newspic" and not article.get("image_info"):
                logger.error(f"Article {i + 1} of type 'newspic' requires 'image_info'")
                return None
        access_token = self._tm.get_access_token()
        if not access_token:
            logger.error("Could not get access token")
            return None
        url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
        try:
            logger.info(f"Adding {len(articles)} article(s) to draft box...")
            payload_json = json.dumps({"articles": articles}, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, data=payload_json, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            if "media_id" in data:
                logger.info(f"Successfully added draft! Media ID: {data['media_id']}")
                return data["media_id"]
            logger.error(f"WeChat API error {data.get('errcode')}: {data.get('errmsg')}")
            return None
        except Exception as e:
            logger.error(f"Error adding draft: {e}")
            return None

    def add_draft_smart(
        self, articles: list, default_thumb_media_id: str = None, thumb_image_path: str = None
    ) -> str | None:
        """Add articles with automatic local-image upload and thumb selection."""
        if not articles or not isinstance(articles, list):
            logger.error("articles must be a non-empty list")
            return None
        logger.info(f"Smart draft processing: {len(articles)} article(s)")
        processed_articles = []
        first_thumb_media_id = None
        first_article_has_image = False
        forced_thumb_media_id = None
        if thumb_image_path:
            if os.path.exists(thumb_image_path):
                logger.info(f"Using preferred thumb image: {thumb_image_path}")
                thumb_result = self._mm.upload_permanent_material(thumb_image_path, "thumb")
                if thumb_result:
                    forced_thumb_media_id = thumb_result["media_id"]
                    logger.info(f"[OK] Preferred thumb media ID: {forced_thumb_media_id}")
                else:
                    logger.warning("[WARN] Preferred thumb upload failed, falling back")
            else:
                logger.warning(f"[WARN] Preferred thumb image not found: {thumb_image_path}")
        for i, article in enumerate(articles):
            if not article.get("title"):
                logger.error(f"Article {i + 1} missing required field 'title'")
                return None
            if not article.get("content"):
                logger.error(f"Article {i + 1} missing required field 'content'")
                return None
            logger.info(f"Processing article {i + 1}: {article['title']}")
            processed_article = article.copy()
            processed_content = processed_article["content"]
            patterns = [
                r'<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\'][^>]*>',
                r"!\[.*?\]\(([^)]+\.(?:jpg|jpeg|png|gif|webp))\)",
                r'src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\']',
            ]
            found: set = set()
            for p in patterns:
                found.update(re.findall(p, processed_content, re.IGNORECASE))
            local_images = [img for img in found if not img.startswith(("http://", "https://", "//"))]
            if local_images:
                logger.info(f"Found {len(local_images)} local image(s): {local_images}")
                if i == 0:
                    first_article_has_image = True
                for lp in local_images:
                    if os.path.exists(lp):
                        if os.path.getsize(lp) > 1024 * 1024:
                            logger.warning(f"[SKIP] Oversize image (>1MB): {lp}")
                            continue
                        logger.info(f"Uploading: {lp}")
                        uploaded_url = self._mm.upload_image_for_article(lp)
                        if uploaded_url:
                            processed_content = processed_content.replace(lp, uploaded_url)
                            logger.info(f"[OK] Replaced with: {uploaded_url}")
                            if i == 0 and first_thumb_media_id is None and not forced_thumb_media_id:
                                logger.info(f"Using as thumb image: {lp}")
                                tr = self._mm.upload_permanent_material(lp, "thumb")
                                if tr:
                                    first_thumb_media_id = tr["media_id"]
                                    logger.info(f"[OK] Thumb media ID: {first_thumb_media_id}")
                        else:
                            logger.warning(f"[WARN] Skipped or failed: {lp}")
                    else:
                        logger.warning(f"[WARN] Image file not found: {lp}")
            else:
                logger.info(f"No local images found in article {i + 1}")
                if i == 0:
                    first_article_has_image = False
            processed_article["content"] = processed_content
            for k, v in [
                ("article_type", "news"),
                ("author", ""),
                ("digest", ""),
                ("content_source_url", ""),
                ("need_open_comment", 0),
                ("only_fans_can_comment", 0),
            ]:
                processed_article.setdefault(k, v)
            if processed_article["article_type"] == "news":
                if forced_thumb_media_id:
                    processed_article["thumb_media_id"] = forced_thumb_media_id
                elif first_article_has_image and first_thumb_media_id:
                    processed_article["thumb_media_id"] = first_thumb_media_id
                else:
                    thumb_to_use = (
                        default_thumb_media_id or "53QZJEu2zs4etGM_3jLi5wl7KNs2RM1RnV_iiGWQmWnYf7qEq2kvHRIIeBCBnAEb"
                    )
                    processed_article["thumb_media_id"] = thumb_to_use
            processed_articles.append(processed_article)
        logger.info("Smart processing complete. Creating draft...")
        return self.add_draft(processed_articles)

    def format_draft_list(self, draft_data: dict, show_content: bool = False) -> str:
        if not draft_data or "item" not in draft_data:
            return "No draft data available"
        lines = [
            "=== Draft List Summary ===",
            f"Total Count: {draft_data.get('total_count', 0)}",
            f"Returned Count: {draft_data.get('item_count', 0)}",
            "",
        ]
        for i, item in enumerate(draft_data.get("item", []), 1):
            update_time = item.get("update_time", 0)
            update_date = datetime.fromtimestamp(update_time).strftime("%Y-%m-%d %H:%M:%S") if update_time else "N/A"
            lines += [f"--- Draft {i} ---", f"Media ID: {item.get('media_id', 'N/A')}", f"Update Time: {update_date}"]
            news_items = item.get("content", {}).get("news_item", [])
            if news_items:
                lines.append(f"Articles: {len(news_items)}")
                for j, article in enumerate(news_items, 1):
                    lines.append(
                        f"  Article {j}: [{article.get('article_type', 'news')}] {article.get('title', 'No title')}"
                    )
                    lines.append(f"    Author: {article.get('author', 'Unknown')}")
                    if article.get("digest"):
                        lines.append(f"    Digest: {article['digest']}")
                    if show_content and "content" in article:
                        c = article["content"]
                        lines.append(f"    Content: {c[:100]}..." if len(c) > 100 else f"    Content: {c}")
                    if "url" in article:
                        lines.append(f"    Preview URL: {article['url']}")
            else:
                lines.append("Articles: 0")
            lines.append("")
        return "\n".join(lines)
