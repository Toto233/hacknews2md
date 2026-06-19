#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import json
import sqlite3
from datetime import datetime

from _bootstrap import DB_PATH, REPO_ROOT

from src.core.summarize_news4 import (  # noqa: E402
    MIN_ARTICLE_CONTENT_CHARS,
    get_article_content_async,
    get_discussion_content_async,
    save_page_screenshot,
)


async def collect_one(row: sqlite3.Row) -> dict:
    news_id = row["id"]
    title = row["title"] or ""
    news_url = row["news_url"] or ""
    discuss_url = row["discuss_url"] or ""

    article_content = (row["article_content"] or "").strip()
    discussion_content = (row["discussion_content"] or "").strip()
    screenshot = row["screenshot"]
    largest_image = row["largest_image"]
    image_2 = row["image_2"]
    image_3 = row["image_3"]

    image_urls = [item for item in [largest_image, image_2, image_3] if item]

    if news_url and len(article_content) < MIN_ARTICLE_CONTENT_CHARS:
        fetched_content, fetched_image_urls, _image_paths = await get_article_content_async(news_url, title)
        if fetched_content and len(fetched_content.strip()) >= MIN_ARTICLE_CONTENT_CHARS:
            article_content = fetched_content.strip()
        if fetched_image_urls:
            image_urls = fetched_image_urls[:3]

    if discuss_url and not discussion_content:
        fetched_discussion = await get_discussion_content_async(discuss_url)
        if fetched_discussion:
            discussion_content = fetched_discussion.strip()

    if news_url and not screenshot:
        screenshot = await asyncio.to_thread(save_page_screenshot, news_url, title)

    return {
        "id": news_id,
        "title": title,
        "news_url": news_url,
        "discuss_url": discuss_url,
        "article_content": article_content,
        "discussion_content": discussion_content,
        "screenshot": screenshot,
        "largest_image": image_urls[0] if len(image_urls) > 0 else None,
        "image_2": image_urls[1] if len(image_urls) > 1 else None,
        "image_3": image_urls[2] if len(image_urls) > 2 else None,
    }


async def collect_one_limited(row: sqlite3.Row, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        return await collect_one(row)


def write_item(cur: sqlite3.Cursor, item: dict) -> None:
    cur.execute(
        """
        UPDATE news
        SET article_content = ?, discussion_content = ?, screenshot = ?,
            largest_image = ?, image_2 = ?, image_3 = ?
        WHERE id = ?
        """,
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


async def main() -> int:
    parser = argparse.ArgumentParser(description="Collect HackNews article/discussion context without using LLMs.")
    parser.add_argument("--hours", type=int, default=18, help="Look back N hours from localtime. Default: 18")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max concurrent article/discussion/screenshot fetches. Default: 3",
    )
    args = parser.parse_args()
    concurrency = max(1, args.concurrency)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, news_url, discuss_url, article_content, discussion_content,
               screenshot, largest_image, image_2, image_3
        FROM news
        WHERE created_at > datetime('now', ?, 'localtime')
        ORDER BY created_at DESC
        """,
        (f"-{args.hours} hours",),
    )
    rows = cur.fetchall()

    items = []
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [asyncio.create_task(collect_one_limited(row, semaphore)) for row in rows]

    for task in asyncio.as_completed(tasks):
        item = await task
        items.append(item)
        write_item(cur, item)
        conn.commit()

    items.sort(key=lambda item: item["id"], reverse=True)

    out_dir = REPO_ROOT / "output" / "codex"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"hacknews_context_{timestamp}.json"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(REPO_ROOT),
        "db_path": str(DB_PATH),
        "count": len(items),
        "items": items,
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    conn.close()

    print(json.dumps({"ok": True, "count": len(items), "concurrency": concurrency, "context_file": str(out_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
