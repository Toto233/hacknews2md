from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db.connection import get_db


def export_hackernews_context_from_db(
    db_path: Path,
    codex_dir: Path,
    period: str,
    *,
    suffix: str = "db",
) -> Path:
    """Write a Codex planning context snapshot from current DB state."""
    codex_dir.mkdir(parents=True, exist_ok=True)
    with get_db(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, news_url, discuss_url, article_content,
                   discussion_content, screenshot, largest_image, image_2, image_3,
                   content_source_type, content_source_url, content_source_doi
            FROM news
            WHERE strftime('%Y%m%d', created_at) = ?
            ORDER BY id
            """,
            (period,),
        ).fetchall()

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
