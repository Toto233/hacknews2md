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


async def _fetch_discussion_with_retries(
    discuss_url: str,
    attempts: int = 2,
    delay_seconds: float = 5.0,
) -> tuple[str, dict[str, Any] | None]:
    """Fetch HN discussion content with one lightweight retry on empty result."""
    from src.core.handlers.discussion_handler import get_discussion_content_async

    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        discussion = await get_discussion_content_async(discuss_url)
        if discussion and discussion.strip():
            return discussion.strip(), None
        if attempt < attempts and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
    return "", {
        "url": discuss_url,
        "reason": "discussion_missing_after_retry",
        "attempts": attempts,
    }


async def _collect_item(row: sqlite3.Row, semaphore: asyncio.Semaphore, db_path: str | None = None) -> dict[str, Any]:
    """Collect missing context for one news row."""
    from src.core.content_quality import is_paywall_or_shell_content
    from src.core.crawlers.scrapling_crawler import ScraplingCrawler
    from src.core.handlers.fediverse_handler import get_fediverse_content, is_fediverse_url
    from src.core.handlers.hunyuan_handler import get_hunyuan_blog_content, is_hunyuan_blog_url
    from src.core.handlers.image_handler import is_low_signal_article_image_url, save_article_image
    from src.core.handlers.pdf_handler import get_pdf_content, is_pdf_url
    from src.core.handlers.stackexchange_handler import build_public_summary_fallback, is_stackexchange_url
    from src.core.handlers.youtube_handler import get_youtube_content
    from src.utils.scraper_failures import extract_domain, record_scraper_failure

    async with semaphore:
        article_content = (row["article_content"] or "").strip()
        discussion_content = (row["discussion_content"] or "").strip()
        image_paths = [path for path in (row["largest_image"], row["image_2"], row["image_3"]) if path]
        image_warnings: list[dict[str, Any]] = []
        content_warnings: list[dict[str, Any]] = []
        discussion_warnings: list[dict[str, Any]] = []
        screenshot = row["screenshot"]
        content_source_type = row["content_source_type"] if "content_source_type" in row.keys() else None
        content_source_url = row["content_source_url"] if "content_source_url" in row.keys() else None
        content_source_doi = row["content_source_doi"] if "content_source_doi" in row.keys() else None
        collected = False

        news_url = row["news_url"] or ""
        if news_url and len(article_content) < MIN_ARTICLE_CONTENT_CHARS:
            collected_source_type = "full_text"
            if _is_youtube_url(news_url):
                content, saved_images, _ = await get_youtube_content(news_url, row["title"] or "")
                image_urls = []
                if saved_images:
                    image_paths = saved_images[:3]
            elif is_pdf_url(news_url):
                content = await get_pdf_content(news_url)
                image_urls = []
            elif is_fediverse_url(news_url):
                content, fediverse_source_type = await get_fediverse_content(news_url)
                collected_source_type = fediverse_source_type or "full_text"
                image_urls = []
            elif is_hunyuan_blog_url(news_url):
                content = await get_hunyuan_blog_content(news_url)
                image_urls = []
            else:
                crawler = ScraplingCrawler()
                try:
                    content, image_urls = await crawler.crawl_article(news_url)
                finally:
                    await crawler.close()
            unusable_content = bool(content and is_paywall_or_shell_content(content))
            if content and len(content.strip()) >= MIN_ARTICLE_CONTENT_CHARS and not unusable_content:
                article_content = content.strip()
                content_source_type = collected_source_type
                content_source_url = news_url
                content_source_doi = None
                collected = True
            elif is_stackexchange_url(news_url):
                article_content = build_public_summary_fallback(row["title"] or "", news_url)
                content_source_type = "public_page_summary"
                content_source_url = news_url
                content_source_doi = None
                collected = True
                domain = extract_domain(news_url)
                failure_count = record_scraper_failure(domain, news_url, db_path)
                content_warnings.append(
                    {
                        "id": row["id"],
                        "title": row["title"] or "",
                        "url": news_url,
                        "domain": domain,
                        "reason": "fallback_content_requires_review",
                        "failure_count": failure_count,
                        "action_required": "human_input_or_handler",
                    }
                )
            elif news_url:
                domain = extract_domain(news_url)
                failure_count = record_scraper_failure(domain, news_url, db_path)
                content_warnings.append(
                    {
                        "id": row["id"],
                        "title": row["title"] or "",
                        "url": news_url,
                        "domain": domain,
                        "reason": "paywall_or_shell_page" if unusable_content else "article_content_missing",
                        "failure_count": failure_count,
                        "action_required": "human_input_or_handler",
                    }
                )
            if image_urls:
                saved_images = []
                candidate_image_urls = [
                    image_url
                    for image_url in image_urls
                    if not is_low_signal_article_image_url(image_url)
                ]
                for index, image_url in enumerate(candidate_image_urls[:3], 1):
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
            discussion, warning = await _fetch_discussion_with_retries(discuss_url)
            if discussion:
                discussion_content = discussion
            elif warning:
                discussion_warnings.append(
                    {
                        "id": row["id"],
                        "title": row["title"] or "",
                        **warning,
                    }
                )

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
            "content_source_type": content_source_type,
            "content_source_url": content_source_url,
            "content_source_doi": content_source_doi,
            "image_warnings": image_warnings,
            "content_warnings": content_warnings,
            "discussion_warnings": discussion_warnings,
            "collected": collected,
        }


async def _collect_rows(rows: list[sqlite3.Row], concurrency: int, db_path: str | None = None) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(_collect_item(row, semaphore, db_path) for row in rows))


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
            columns = {row[1] for row in conn.execute("PRAGMA table_info(news)").fetchall()}
            source_columns = [
                column
                for column in ("content_source_type", "content_source_url", "content_source_doi")
                if column in columns
            ]
            select_columns = [
                "id",
                "title",
                "news_url",
                "discuss_url",
                "article_content",
                "discussion_content",
                "screenshot",
                "largest_image",
                "image_2",
                "image_3",
                *source_columns,
            ]
            rows = conn.execute(
                f"SELECT {', '.join(select_columns)} "
                "FROM news WHERE date(created_at)=date('now','localtime') ORDER BY id"
            ).fetchall()

        items = asyncio.run(_collect_rows(rows, concurrency, str(ctx.db_path)))

        with get_db(str(ctx.db_path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(news)").fetchall()}
            can_store_source = {
                "content_source_type",
                "content_source_url",
                "content_source_doi",
            } <= columns
            for item in items:
                if can_store_source:
                    conn.execute(
                        "UPDATE news SET article_content=?, discussion_content=?, screenshot=?, "
                        "largest_image=?, image_2=?, image_3=?, content_source_type=?, "
                        "content_source_url=?, content_source_doi=? WHERE id=?",
                        (
                            item["article_content"] or None,
                            item["discussion_content"] or None,
                            item["screenshot"],
                            item["largest_image"],
                            item["image_2"],
                            item["image_3"],
                            item["content_source_type"],
                            item["content_source_url"],
                            item["content_source_doi"],
                            item["id"],
                        ),
                    )
                else:
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
        content_warnings = [
            warning
            for item in items
            for warning in item.get("content_warnings", [])
        ]
        discussion_warnings = [
            warning
            for item in items
            for warning in item.get("discussion_warnings", [])
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
            "content_warnings": content_warnings,
            "discussion_warnings": discussion_warnings,
        }
