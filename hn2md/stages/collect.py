"""Collect stage: scrape article content, discussions, screenshots."""

import asyncio
import sqlite3

from hn2md.constants import Stage
from hn2md.stages.base import BaseStage
from src.db.connection import get_db


class CollectStage(BaseStage):
    stage_name = Stage.COLLECTING

    def execute(self, ctx, machine):
        from src.core.handlers.discussion_handler import get_discussion_content_async

        with get_db(str(ctx.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT id, title, news_url, discuss_url, article_content, "
                "discussion_content, screenshot, largest_image, image_2, image_3 "
                "FROM news WHERE date(created_at)=date('now','localtime') ORDER BY id"
            )
            rows = cur.fetchall()
            collected = 0

            for row in rows:
                needs_content = not row["article_content"]
                needs_discussion = not row["discussion_content"]

                if needs_content or needs_discussion:
                    # Use the new crawler abstraction
                    from src.core.crawlers.scrapling_crawler import ScraplingCrawler

                    crawler = ScraplingCrawler()
                    try:
                        if needs_content and row["news_url"]:
                            loop = asyncio.get_event_loop()
                            content, images = loop.run_until_complete(crawler.crawl_article(row["news_url"]))
                            if content:
                                cur.execute(
                                    "UPDATE news SET article_content=? WHERE id=?",
                                    (content, row["id"]),
                                )
                                # Save images
                                for i, img_url in enumerate(images[:3]):
                                    if i == 0:
                                        cur.execute(
                                            "UPDATE news SET largest_image=? WHERE id=?",
                                            (img_url, row["id"]),
                                        )
                                collected += 1
                    finally:
                        loop.run_until_complete(crawler.close())

                    if needs_discussion and row["discuss_url"]:
                        try:
                            loop = asyncio.get_event_loop()
                            discussion = loop.run_until_complete(get_discussion_content_async(row["discuss_url"]))
                            if discussion:
                                cur.execute(
                                    "UPDATE news SET discussion_content=? WHERE id=?",
                                    (discussion, row["id"]),
                                )
                        except Exception:
                            pass

        return {"collected": collected, "total": len(rows)}
