#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import sqlite3
from datetime import datetime

from _bootstrap import DB_PATH, REPO_ROOT, SETTINGS

from src.integrations.markdown_to_html_converter import convert_markdown_to_html  # noqa: E402


def yaml_quote(value: object) -> str:
    """Serialize a scalar safely for YAML frontmatter."""
    text = "" if value is None else str(value)
    text = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{text}"'


def fetch_news_by_ids(ids: list[int]) -> list[tuple]:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    rows = []
    for news_id in ids:
        cur.execute(
            """
            SELECT id, title, title_chs, news_url, discuss_url, content_summary, discuss_summary,
                   largest_image, image_2, image_3, screenshot
            FROM news
            WHERE id = ?
            """,
            (news_id,),
        )
        row = cur.fetchone()
        if row:
            rows.append(row)
    conn.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Render HackNews markdown/html/Astro from a Codex plan JSON.")
    parser.add_argument("plan_file", help="JSON file with ordered_ids and tags")
    args = parser.parse_args()

    with open(args.plan_file, "r", encoding="utf-8") as f:
        plan = json.load(f)

    ordered_ids = plan.get("ordered_ids", [])
    tags = plan.get("tags", [])
    rows = fetch_news_by_ids(ordered_ids)

    now = datetime.now()
    suffix = f" | Hacker News 摘要 ({now.strftime('%Y-%m-%d')})"
    first = rows[0] if rows else None
    prefix = (first[2] or first[1] or "") if first else ""
    if len(prefix) + len(suffix) > 64:
        prefix = prefix[: 64 - len(suffix)]
    yaml_title = prefix + suffix
    pub_datetime = now.strftime("%Y-%m-%d %H:%M:%S") + f".{int(now.microsecond / 1000):03d}+08:00"
    digest = (first[5] or "")[:120] if first else ""
    source_url = first[3] if first else ""

    markdown = (
        "---\n"
        f"title: {yaml_quote(yaml_title)}\n"
        f"author: {yaml_quote('hacknews')}\n"
        f"description: {yaml_quote('')}\n"
        f"digest: {yaml_quote(digest)}\n"
        f"source_url: {yaml_quote(source_url)}\n"
        f"pubDatetime: {pub_datetime}\n"
        "tags:\n"
    )
    for tag in tags:
        markdown += f"  - {yaml_quote(tag)}\n"
    markdown += "---\n\n"

    for idx, row in enumerate(rows, 1):
        _, title, title_chs, news_url, discuss_url, content_summary, discuss_summary, largest_image, image_2, image_3, screenshot = row
        display_title = f"{title_chs} ({title})" if title_chs else title
        markdown += "---\n\n"
        markdown += f"## {idx}. {display_title}\n\n"

        for img in [screenshot, largest_image, image_2, image_3]:
            if img:
                markdown += f"![{title_chs or title}]({img})\n\n"

        markdown += f"{content_summary or ''}\n\n"
        markdown += f"原文链接：{news_url}\n\n"
        if discuss_url:
            markdown += f"论坛讨论链接：{discuss_url}\n\n"
            if discuss_summary:
                markdown += f"{discuss_summary}\n\n"

    out_dir = REPO_ROOT / "output" / "markdown"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M")
    md_path = out_dir / f"hacknews_summary_{stamp}.md"
    html_path = out_dir / f"hacknews_summary_{stamp}.html"
    astro_path = (
        SETTINGS.astro_blog_dir / f"hacknews_summary_{stamp}.md"
        if SETTINGS.astro_blog_dir
        else None
    )

    with md_path.open("w", encoding="utf-8") as f:
        f.write(markdown)

    with html_path.open("w", encoding="utf-8") as f:
        f.write(convert_markdown_to_html(markdown))

    astro_markdown = []
    for line in markdown.splitlines():
        if line.startswith("![") and (":\\" in line or line.startswith("![/")):
            continue
        astro_markdown.append(line)
    if astro_path:
        astro_path.parent.mkdir(parents=True, exist_ok=True)
        with astro_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(astro_markdown) + "\n")

    print(
        json.dumps(
            {
                "ok": True,
                "markdown_file": str(md_path),
                "html_file": str(html_path),
                "astro_file": str(astro_path) if astro_path else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
