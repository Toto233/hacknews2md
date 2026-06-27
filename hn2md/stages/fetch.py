"""Fetch stage: scrape HN stories to SQLite."""

from typing import Any

from hn2md.constants import Stage
from hn2md.stages.base import BaseStage


def _story_metadata(item: Any) -> dict[str, Any]:
    """Extract stable, serializable story metadata for the run ledger."""
    if isinstance(item, dict):
        return {
            key: item[key]
            for key in ("id", "title", "url", "news_url", "discuss_url")
            if key in item and item[key] is not None
        }

    metadata = {}
    for key in ("id", "title", "url", "news_url", "discuss_url"):
        value = getattr(item, key, None)
        if value is not None:
            metadata[key] = value
    return metadata


class FetchStage(BaseStage):
    stage_name = Stage.FETCHING

    def execute(self, ctx, machine):
        from src.core.archive_news import archive_old_news
        from src.core.fetch_news import fetch_news, save_to_database
        from src.utils.db_utils import init_database

        init_database()
        archive_old_news()
        items = fetch_news()
        saved = save_to_database(items)
        machine.job.stories = [_story_metadata(item) for item in items]
        return {"fetched": len(items), "saved": saved}
