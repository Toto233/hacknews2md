"""Fetch stage: scrape HN stories to SQLite."""

from typing import Any
import time

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
    default_retry_delays = (60.0, 180.0)

    def __init__(self, retry_delays: tuple[float, ...] | None = None) -> None:
        self.retry_delays = self.default_retry_delays if retry_delays is None else retry_delays

    def execute(self, ctx, machine):
        from src.core.archive_news import archive_old_news
        from src.core.fetch_news import fetch_news, save_to_database
        from src.utils.db_utils import init_database

        init_database()
        archive_old_news()
        attempts = len(self.retry_delays) + 1
        items = []
        saved = 0
        last_error = ""
        for attempt in range(attempts):
            items = fetch_news()
            if not items:
                last_error = "fetch returned no stories; upstream may be rate-limited or unavailable"
            else:
                saved = save_to_database(items)
                if saved > 0:
                    break
                last_error = f"fetch saved no stories from {len(items)} fetched item(s)"
            if attempt < len(self.retry_delays):
                time.sleep(self.retry_delays[attempt])

        if not items:
            raise RuntimeError(last_error)
        if saved <= 0:
            raise RuntimeError(last_error)
        machine.job.stories = [_story_metadata(item) for item in items]
        return {"fetched": len(items), "saved": saved}
