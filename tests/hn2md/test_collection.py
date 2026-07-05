"""Collection is implemented once by CollectStage."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hn2md.context import RuntimeContext
from hn2md.stages.collect import CollectStage, _fetch_discussion_with_retries


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
                content_source_type TEXT,
                content_source_url TEXT,
                content_source_doi TEXT,
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


def _set_news_url(ctx: RuntimeContext, url: str) -> None:
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute("UPDATE news SET news_url=? WHERE id=1", (url,))


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
            "SELECT article_content, discussion_content, screenshot, largest_image, image_2, image_3, "
            "content_source_type, content_source_url FROM news"
        ).fetchone()
    assert row == (
        ("Readable article body " * 10).strip(),
        "HN discussion",
        "shot.png",
        "one.png",
        "two.png",
        None,
        "full_text",
        "https://example.com/story",
    )
    crawler.close.assert_awaited_once()


def test_collect_stage_reports_image_save_failures_in_receipt_summary(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("Readable article body " * 10, ["https://img/fail.svg"]))
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.image_handler.save_article_image", return_value=None),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=2)

    assert result["image_warnings"] == [
        {
            "id": 1,
            "title": "Story",
            "image_url": "https://img/fail.svg",
            "reason": "save_failed",
        }
    ]


def test_collect_stage_routes_youtube_urls_to_youtube_handler(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    _set_news_url(ctx, "https://www.youtube.com/watch?v=abc123")

    with (
        patch(
            "src.core.handlers.youtube_handler.get_youtube_content",
            new=AsyncMock(return_value=("Transcript body " * 10, ["thumb.jpg"], ["thumb.jpg"])),
        ) as youtube_handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler") as crawler_cls,
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    youtube_handler.assert_awaited_once_with("https://www.youtube.com/watch?v=abc123", "Story")
    crawler_cls.assert_not_called()
    assert result["collected"] == 1

    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT article_content, largest_image, image_2, image_3 FROM news WHERE id=1"
        ).fetchone()
    assert row == (("Transcript body " * 10).strip(), "thumb.jpg", None, None)


def test_collect_stage_routes_github_blob_pdf_to_pdf_handler(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    _set_news_url(ctx, "https://github.com/deepseek-ai/DeepSpec/blob/main/DSpark_paper.pdf")

    with (
        patch(
            "src.core.handlers.pdf_handler.get_pdf_content",
            new=AsyncMock(return_value="PDF extracted text " * 10),
        ) as pdf_handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler") as crawler_cls,
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    pdf_handler.assert_awaited_once_with("https://github.com/deepseek-ai/DeepSpec/blob/main/DSpark_paper.pdf")
    crawler_cls.assert_not_called()
    assert result["collected"] == 1

    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute("SELECT article_content FROM news WHERE id=1").fetchone()
    assert row == (("PDF extracted text " * 10).strip(),)


def test_collect_stage_routes_fediverse_urls_to_fediverse_handler(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    _set_news_url(ctx, "https://mathstodon.xyz/@iblech/1161234567890")

    with (
        patch(
            "src.core.handlers.fediverse_handler.get_fediverse_content",
            new=AsyncMock(return_value=("Fediverse toot body " * 10, "full_text")),
        ) as fediverse_handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler") as crawler_cls,
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    fediverse_handler.assert_awaited_once_with("https://mathstodon.xyz/@iblech/1161234567890")
    crawler_cls.assert_not_called()
    assert result["collected"] == 1

    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT article_content, content_source_type, content_source_url FROM news WHERE id=1"
        ).fetchone()
    assert row == (
        ("Fediverse toot body " * 10).strip(),
        "full_text",
        "https://mathstodon.xyz/@iblech/1161234567890",
    )


def test_collect_stage_records_stackexchange_fallback_source_metadata(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    _set_news_url(ctx, "https://physics.stackexchange.com/questions/535/example")
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("", []))
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    assert result["collected"] == 1
    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT article_content, content_source_type, content_source_url FROM news WHERE id=1"
        ).fetchone()

    assert row[0].startswith("Source fallback:")
    assert len(row[0]) >= 100
    assert row[1] == "public_page_summary"
    assert row[2] == "https://physics.stackexchange.com/questions/535/example"
    assert result["content_warnings"] == [
        {
            "id": 1,
            "title": "Story",
            "url": "https://physics.stackexchange.com/questions/535/example",
            "domain": "physics.stackexchange.com",
            "reason": "fallback_content_requires_review",
            "failure_count": 1,
            "action_required": "human_input_or_handler",
        }
    ]


def test_collect_stage_records_scraper_failure_when_article_missing(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("", []))
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    assert result["collected"] == 0
    assert result["content_warnings"] == [
        {
            "id": 1,
            "title": "Story",
            "url": "https://example.com/story",
            "domain": "example.com",
            "reason": "article_content_missing",
            "failure_count": 1,
            "action_required": "human_input_or_handler",
        }
    ]

    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT domain, sample_url, fail_count FROM scraper_failures WHERE domain='example.com'"
        ).fetchone()
    assert row == ("example.com", "https://example.com/story", 1)


def test_collect_stage_records_discussion_retry_failure_in_receipt(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("Readable article body " * 10, []))
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value=""),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    assert result["discussion_warnings"] == [
        {
            "id": 1,
            "title": "Story",
            "url": "https://news.ycombinator.com/item?id=1",
            "reason": "discussion_missing_after_retry",
            "attempts": 2,
        }
    ]


def test_fetch_discussion_retries_once_when_first_attempt_is_empty() -> None:
    handler = AsyncMock(side_effect=["", "HN discussion after retry"])

    with patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=handler):
        discussion, warning = __import__("asyncio").run(
            _fetch_discussion_with_retries("https://news.ycombinator.com/item?id=1", attempts=2, delay_seconds=0)
        )

    assert discussion == "HN discussion after retry"
    assert warning is None
    assert handler.await_count == 2


def test_fetch_discussion_reports_warning_after_retry_exhausted() -> None:
    handler = AsyncMock(return_value="")

    with patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=handler):
        discussion, warning = __import__("asyncio").run(
            _fetch_discussion_with_retries("https://news.ycombinator.com/item?id=1", attempts=2, delay_seconds=0)
        )

    assert discussion == ""
    assert warning == {
        "url": "https://news.ycombinator.com/item?id=1",
        "reason": "discussion_missing_after_retry",
        "attempts": 2,
    }
    assert handler.await_count == 2
