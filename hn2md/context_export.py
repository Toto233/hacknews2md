from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db.connection import get_db


def _fetch_hackernews_rows(db_path: Path, period: str) -> list[sqlite3.Row]:
    with get_db(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT id, title, news_url, discuss_url, article_content,
                   discussion_content, screenshot, largest_image, image_2, image_3,
                   content_source_type, content_source_url, content_source_doi,
                   title_chs, content_summary, discuss_summary
            FROM news
            WHERE strftime('%Y%m%d', created_at) = ?
            ORDER BY id
            """,
            (period,),
        ).fetchall()


def _excerpt(value: str | None, limit: int) -> str:
    if not value or limit <= 0:
        return ""
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def export_hackernews_context_from_db(
    db_path: Path,
    codex_dir: Path,
    period: str,
    *,
    suffix: str = "db",
) -> Path:
    """Write a Codex planning context snapshot from current DB state."""
    codex_dir.mkdir(parents=True, exist_ok=True)
    rows = _fetch_hackernews_rows(db_path, period)

    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["image_warnings"] = []
        item["content_warnings"] = []
        item["discussion_warnings"] = []
        items.append(item)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix_part = f"_{suffix}" if suffix else ""
    context_path = codex_dir / f"hacknews_context_{stamp}{suffix_part}.json"
    context_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "count": len(items),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return context_path


def export_hackernews_plan_draft_from_db(
    db_path: Path,
    codex_dir: Path,
    period: str,
    *,
    article_chars: int = 1200,
    discussion_chars: int = 800,
) -> Path:
    """Write a compact manual-plan draft with source URLs and short excerpts."""
    codex_dir.mkdir(parents=True, exist_ok=True)
    rows = _fetch_hackernews_rows(db_path, period)

    items: list[dict[str, Any]] = []
    ordered_ids: list[int] = []
    for row in rows:
        news_id = int(row["id"])
        ordered_ids.append(news_id)
        article_content = row["article_content"] or ""
        discussion_content = row["discussion_content"] or ""
        items.append(
            {
                "id": news_id,
                "title": row["title"] or "",
                "news_url": row["news_url"] or "",
                "discuss_url": row["discuss_url"] or "",
                "content_source_type": row["content_source_type"] or "",
                "content_source_url": row["content_source_url"] or "",
                "title_chs": row["title_chs"] or "",
                "content_summary": row["content_summary"] or "",
                "discuss_summary": row["discuss_summary"] or "",
                "article_length": len(article_content),
                "discussion_length": len(discussion_content),
                "article_excerpt": _excerpt(article_content, article_chars),
                "discussion_excerpt": _excerpt(discussion_content, discussion_chars),
            }
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    draft_path = codex_dir / f"hacknews_plan_draft_{stamp}.json"
    draft_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "period": period,
                "count": len(items),
                "tags": [],
                "ordered_ids": ordered_ids,
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return draft_path
