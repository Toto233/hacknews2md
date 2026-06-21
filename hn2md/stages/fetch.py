"""Fetch stage: scrape HN stories to SQLite."""

from hn2md.constants import Stage
from hn2md.stages.base import BaseStage


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
        return {"fetched": len(items), "saved": saved}
