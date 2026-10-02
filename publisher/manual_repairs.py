"""Managed human-supplied story repairs for the Hacker News source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Final

from hn2md.state import JobStateMachine
from hn2md.stages.collect import write_collection_context
from publisher.context import PublisherContext
from publisher.pipeline.runner import _hn_runtime_context
from src.db.connection import get_db


MIN_HUMAN_SUPPLIED_CONTENT_LENGTH: Final = 100


@dataclass(frozen=True)
class StoryRepair:
    """Durable record of a human-provided replacement for one story."""

    story_id: int
    period: str
    source_url: str
    content_file: str
    repair_file: str
    context_file: str


def repair_story_content(
    ctx: PublisherContext,
    story_id: int,
    content: str,
    *,
    source_url: str | None = None,
) -> StoryRepair:
    """Persist human content, a repair receipt, and refreshed collection context."""
    normalized_content = content.strip()
    if len(normalized_content) < MIN_HUMAN_SUPPLIED_CONTENT_LENGTH:
        raise ValueError(
            f"human-supplied content must be at least {MIN_HUMAN_SUPPLIED_CONTENT_LENGTH} characters"
        )

    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        story = conn.execute(
            "SELECT news_url FROM news WHERE id = ? AND strftime('%Y%m%d', created_at) = ?",
            (story_id, ctx.period),
        ).fetchone()
        if story is None:
            raise ValueError(f"story not found for {ctx.period}: {story_id}")
        resolved_source_url = source_url or str(story["news_url"])
        conn.execute(
            """
            UPDATE news
            SET article_content = ?, content_source_type = 'human_supplied', content_source_url = ?
            WHERE id = ? AND strftime('%Y%m%d', created_at) = ?
            """,
            (normalized_content, resolved_source_url, story_id, ctx.period),
        )

    repair_dir = ctx.project_root / "output" / "human-sources" / ctx.period
    repair_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    content_file = repair_dir / f"story_{story_id}_{timestamp}.txt"
    content_file.write_text(normalized_content + "\n", encoding="utf-8")

    context_file = write_collection_context(_hn_runtime_context(ctx), period=ctx.period)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.refresh_collection_context(context_file, story_id)
    machine.invalidate_audit()

    repair_file = repair_dir / f"story_{story_id}_{timestamp}.json"
    repair_file.write_text(
        json.dumps(
            {
                "story_id": story_id,
                "period": ctx.period,
                "source_type": "human_supplied",
                "source_url": resolved_source_url,
                "content_file": str(content_file),
                "context_file": str(context_file),
                "repaired_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return StoryRepair(
        story_id=story_id,
        period=ctx.period,
        source_url=resolved_source_url,
        content_file=str(content_file),
        repair_file=str(repair_file),
        context_file=str(context_file),
    )
