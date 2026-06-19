#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import html
import json
import re
import sqlite3
import urllib.request
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from _bootstrap import DB_PATH

from src.core.summarize_news5 import get_discussion_content_async  # noqa: E402


def strip_html(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<p\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_hn_item_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    values = query.get("id") or []
    return values[0] if values else ""


def iter_comments(children: list[dict], limit: int):
    for child in children:
        if limit <= 0:
            return
        text = strip_html(child.get("text") or "")
        author = child.get("author") or "unknown"
        if text:
            yield author, text
            limit -= 1
        if limit <= 0:
            return
        nested = child.get("children") or []
        for item in iter_comments(nested, limit):
            yield item
            limit -= 1
            if limit <= 0:
                return


def fetch_via_algolia(url: str, comment_limit: int = 12) -> str:
    item_id = extract_hn_item_id(url)
    if not item_id:
        return ""

    api_url = f"https://hn.algolia.com/api/v1/items/{item_id}"
    with urllib.request.urlopen(api_url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    title = payload.get("title") or ""
    link = payload.get("url") or url
    children = payload.get("children") or []
    comments = list(iter_comments(children, comment_limit))
    if not comments:
        return ""

    parts = [f"标题: {title}", f"链接: {link}", "", f"评论 (Algolia API 抓取，显示{len(comments)}条):"]
    for author, text in comments:
        parts.append("")
        parts.append(f"{author}: {text}")
    return "\n".join(parts).strip()


async def fetch_with_retries(url: str, attempts: int, delay: float, use_algolia: bool) -> str:
    for attempt in range(1, attempts + 1):
        content = (await get_discussion_content_async(url) or "").strip()
        if content:
            return content
        if attempt < attempts:
            await asyncio.sleep(delay)
    if use_algolia:
        try:
            return fetch_via_algolia(url)
        except Exception as exc:
            print(f"[WARN] Algolia fallback failed for {url}: {exc}", file=sys.stderr)
    return ""


async def main() -> int:
    parser = argparse.ArgumentParser(description="Refetch empty Hacker News discussion content.")
    parser.add_argument("--ids", nargs="*", type=int, help="Specific news IDs to refetch. Defaults to today's empty discussions.")
    parser.add_argument("--attempts", type=int, default=2, help="Attempts per discussion. Default: 2")
    parser.add_argument("--delay", type=float, default=8.0, help="Delay between attempts in seconds. Default: 8")
    parser.add_argument("--no-algolia", action="store_true", help="Disable hn.algolia.com API fallback.")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if args.ids:
        placeholders = ",".join(["?"] * len(args.ids))
        cur.execute(
            f"""
            SELECT id, title, discuss_url, discussion_content
            FROM news
            WHERE id IN ({placeholders})
              AND discuss_url IS NOT NULL
              AND TRIM(discuss_url) != ''
            ORDER BY id
            """,
            args.ids,
        )
    else:
        cur.execute(
            """
            SELECT id, title, discuss_url, discussion_content
            FROM news
            WHERE date(created_at) = date('now', 'localtime')
              AND discuss_url IS NOT NULL
              AND TRIM(discuss_url) != ''
              AND (discussion_content IS NULL OR TRIM(discussion_content) = '')
            ORDER BY id
            """
        )

    rows = cur.fetchall()
    results = []

    for row in rows:
        content = await fetch_with_retries(
            row["discuss_url"],
            max(1, args.attempts),
            max(0.0, args.delay),
            not args.no_algolia,
        )
        if content:
            cur.execute("UPDATE news SET discussion_content = ? WHERE id = ?", (content, row["id"]))
            conn.commit()
        results.append(
            {
                "id": row["id"],
                "title": row["title"],
                "ok": bool(content),
                "discussion_length": len(content),
            }
        )

    conn.close()
    print(
        json.dumps(
            {
                "ok": all(item["ok"] for item in results),
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
