"""Collection is implemented once by CollectStage."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hn2md.context import RuntimeContext
from hn2md.stages.collect import CollectStage


def _ctx(tmp_path: Path) -> RuntimeContext:
    db_path = tmp_path / "data" / "hacknews.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE news (
                id INTEGER PRIMARY KEY,
                title TEXT,
                news_url TEXT,
                discuss_url TEXT,
                article_content TEXT,
                discussion_content TEXT,
                screenshot TEXT,
                largest_image TEXT,
                image_2 TEXT,
                image_3 TEXT,
                created_at TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO news (id, title, news_url, discuss_url, created_at)
            VALUES (1, 'Story', 'https://example.com/story',
                    'https://news.ycombinator.com/item?id=1', datetime('now', 'localtime'))
            """
        )
    output = tmp_path / "output"
    return RuntimeContext(
        project_root=tmp_path,
        db_path=db_path,
        output_dir=output,
        job_dir=output / "jobs",
        markdown_dir=output / "markdown",
        images_dir=output / "images",
        codex_dir=output / "codex",
        config_path=tmp_path / "config" / "config.json",
    )


def test_collect_stage_collects_full_context_and_writes_snapshot(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("Readable article body " * 10, ["https://img/1", "https://img/2"]))
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.image_handler.save_article_image", side_effect=["one.png", "two.png"]),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=2)

    assert result["total"] == 1
    assert result["collected"] == 1
    assert result["concurrency"] == 2
    snapshot = Path(result["context_file"])
    assert snapshot.exists()
    assert json.loads(snapshot.read_text(encoding="utf-8"))["count"] == 1

    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT article_content, discussion_content, screenshot, largest_image, image_2, image_3 FROM news"
        ).fetchone()
    assert row == (("Readable article body " * 10).strip(), "HN discussion", "shot.png", "one.png", "two.png", None)
    crawler.close.assert_awaited_once()
