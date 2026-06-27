"""Collect stage: scrape article content, discussions, screenshots, and images."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage
from src.db.connection import get_db

MIN_ARTICLE_CONTENT_CHARS = 100


def _is_youtube_url(url: str) -> bool:
    """Return True for YouTube video URLs handled by youtube_handler."""
    host = urlparse(url).netloc.lower()
    return host in {"youtube.com", "www.youtube.com", "youtu.be"}


async def _collect_item(row: sqlite3.Row, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    """Collect missing context for one news row."""
    from src.core.crawlers.scrapling_crawler import ScraplingCrawler
    from src.core.handlers.discussion_handler import get_discussion_content_async
    from src.core.handlers.image_handler import save_article_image
    from src.core.handlers.screenshot_handler import save_page_screenshot
    from src.core.handlers.youtube_handler import get_youtube_content

    async with semaphore:
        article_content = (row["article_content"] or "").strip()
        discussion_content = (row["discussion_content"] or "").strip()
        image_paths = [path for path in (row["largest_image"], row["image_2"], row["image_3"]) if path]
        image_warnings: list[dict[str, Any]] = []
        screenshot = row["screenshot"]
        collected = False

        news_url = row["news_url"] or ""
        if news_url and len(article_content) < MIN_ARTICLE_CONTENT_CHARS:
            if _is_youtube_url(news_url):
                content, saved_images, _ = await get_youtube_content(news_url, row["title"] or "")
                image_urls = []
                if saved_images:
                    image_paths = saved_images[:3]
            else:
                crawler = ScraplingCrawler()
                try:
                    content, image_urls = await crawler.crawl_article(news_url)
                finally:
                    await crawler.close()
            if content and len(content.strip()) >= MIN_ARTICLE_CONTENT_CHARS:
                article_content = content.strip()
                collected = True
            if image_urls:
                saved_images = []
                for index, image_url in enumerate(image_urls[:3], 1):
                    try:
                        saved = await asyncio.to_thread(
                            save_article_image,
                            image_url,
                            news_url,
                            f"{row['title']}_{index}",
                        )
                    except Exception as exc:
                        saved = None
                        image_warnings.append(
                            {
                                "id": row["id"],
                                "title": row["title"] or "",
                                "image_url": image_url,
                                "reason": "exception",
                                "error": str(exc),
                            }
                        )
                    if saved:
                        saved_images.append(saved)
                    else:
                        if not image_warnings or image_warnings[-1].get("image_url") != image_url:
                            image_warnings.append(
                                {
                                    "id": row["id"],
                                    "title": row["title"] or "",
                                    "image_url": image_url,
                                    "reason": "save_failed",
                                }
                            )
                if saved_images:
                    image_paths = saved_images

        discuss_url = row["discuss_url"] or ""
        if discuss_url and not discussion_content:
            discussion = await get_discussion_content_async(discuss_url)
            if discussion:
                discussion_content = discussion.strip()

        if news_url and not screenshot:
            screenshot = await asyncio.to_thread(save_page_screenshot, news_url, row["title"] or "")

        return {
            "id": row["id"],
            "title": row["title"] or "",
            "news_url": news_url,
            "discuss_url": discuss_url,
            "article_content": article_content,
            "discussion_content": discussion_content,
            "screenshot": screenshot,
            "largest_image": image_paths[0] if len(image_paths) > 0 else None,
            "image_2": image_paths[1] if len(image_paths) > 1 else None,
            "image_3": image_paths[2] if len(image_paths) > 2 else None,
            "image_warnings": image_warnings,
            "collected": collected,
        }


async def _collect_rows(rows: list[sqlite3.Row], concurrency: int) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(_collect_item(row, semaphore) for row in rows))


class CollectStage(BaseStage):
    stage_name = Stage.COLLECTING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        concurrency: int = 3,
    ) -> dict[str, Any]:
        concurrency = max(1, concurrency)
        with get_db(str(ctx.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, title, news_url, discuss_url, article_content, "
                "discussion_content, screenshot, largest_image, image_2, image_3 "
                "FROM news WHERE date(created_at)=date('now','localtime') ORDER BY id"
            ).fetchall()

        items = asyncio.run(_collect_rows(rows, concurrency))

        with get_db(str(ctx.db_path)) as conn:
            for item in items:
                conn.execute(
                    "UPDATE news SET article_content=?, discussion_content=?, screenshot=?, "
                    "largest_image=?, image_2=?, image_3=? WHERE id=?",
                    (
                        item["article_content"] or None,
                        item["discussion_content"] or None,
                        item["screenshot"],
                        item["largest_image"],
                        item["image_2"],
                        item["image_3"],
                        item["id"],
                    ),
                )

        ctx.codex_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        context_path = ctx.codex_dir / f"hacknews_context_{stamp}.json"
        payload_items = [{key: value for key, value in item.items() if key != "collected"} for item in items]
        image_warnings = [
            warning
            for item in items
            for warning in item.get("image_warnings", [])
        ]
        context_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "count": len(payload_items),
                    "items": payload_items,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "collected": sum(1 for item in items if item["collected"]),
            "total": len(items),
            "concurrency": concurrency,
            "context_file": str(context_path),
            "image_warnings": image_warnings,
        }
