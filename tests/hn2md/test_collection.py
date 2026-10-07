"""Collection is implemented once by CollectStage."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hn2md.context import RuntimeContext
from hn2md.stages.collect import CollectStage, _fetch_discussion_with_retries, write_collection_context


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


def test_collection_and_refreshed_context_use_run_period(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute(
            "UPDATE news SET created_at='2000-01-02 10:00:00', article_content=?, discussion_content=? WHERE id=1",
            ("Readable article. " * 20, "HN discussion already collected."),
        )
        conn.execute(
            "INSERT INTO news (id, title, news_url, article_content, discussion_content, created_at) "
            "VALUES (2, 'Today', 'https://example.com/today', ?, 'HN discussion', datetime('now', 'localtime'))",
            ("Today's article. " * 20,),
        )
    machine = type("M", (), {"job": type("J", (), {"date": "20000102"})()})()

    result = CollectStage().execute(ctx, machine, concurrency=1)
    refreshed = write_collection_context(ctx, period="20000102")

    assert result["total"] == 1
    assert [item["id"] for item in json.loads(Path(result["context_file"]).read_text(encoding="utf-8"))["items"]] == [1]
    assert [item["id"] for item in json.loads(Path(refreshed).read_text(encoding="utf-8"))["items"]] == [1]


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
        None,
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
    crawler.crawl_article = AsyncMock(return_value=("Readable article body " * 10, ["https://img/fail.jpg"]))
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
            "image_url": "https://img/fail.jpg",
            "reason": "save_failed",
        }
    ]


def test_collect_stage_filters_decorative_images_before_saving(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(
        return_value=(
            "Readable article body " * 10,
            [
                "https://assets.apnews.com/ap-logo-176-by-208.svg",
                "https://img.shields.io/badge/Postgres-18.3-brightgreen",
                "https://static.example.com/getitongoogleplay-badge-web-color-english.png",
                "https://cdn.example.com/article-photo.jpg",
            ],
        )
    )
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.image_handler.save_article_image", return_value="article.jpg") as save_image,
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    assert result["image_warnings"] == []
    save_image.assert_called_once_with(
        "https://cdn.example.com/article-photo.jpg",
        "https://example.com/story",
        "Story_1",
    )
    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute("SELECT largest_image, image_2, image_3 FROM news WHERE id=1").fetchone()
    assert row == ("article.jpg", None, None)


def test_github_collection_saves_sharing_card_before_readme_images(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _set_news_url(ctx, "https://github.com/owner/logo-maker")
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=(
        "Readable repository README " * 10,
        [
            "https://raw.githubusercontent.com/owner/logo-maker/main/demo.png",
            "https://opengraph.githubassets.com/hash/owner/logo-maker",
        ],
    ))
    crawler.close = AsyncMock()
    preview = tmp_path / "GitHubPreview_1.png"
    preview.write_bytes(b"preview")
    body = tmp_path / "demo.png"
    body.write_bytes(b"body")

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
        patch("src.core.handlers.image_handler.save_article_image", side_effect=[str(preview), str(body)]) as save_image,
    ):
        CollectStage().execute(ctx, object(), concurrency=1)

    assert [call.args for call in save_image.call_args_list] == [
        ("https://opengraph.githubassets.com/hash/owner/logo-maker", "https://github.com/owner/logo-maker", "GitHubPreview_1"),
        ("https://raw.githubusercontent.com/owner/logo-maker/main/demo.png", "https://github.com/owner/logo-maker", "Story_2"),
    ]
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT screenshot, largest_image, image_2 FROM news WHERE id=1").fetchone() == (
            None, str(preview), str(body)
        )


def test_github_collect_retries_missing_card_without_replacing_existing_text(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _set_news_url(ctx, "https://github.com/owner/repo")
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute(
            "UPDATE news SET article_content=?, content_source_type='human_supplied' WHERE id=1",
            ("Reviewed repository content " * 10,),
        )
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=(
        "New page text must not overwrite the reviewed text " * 10,
        ["https://opengraph.githubassets.com/hash/owner/repo"],
    ))
    crawler.close = AsyncMock()
    preview = tmp_path / "GitHubPreview_1.png"
    preview.write_bytes(b"preview")

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
        patch("src.core.handlers.image_handler.save_article_image", return_value=str(preview)),
    ):
        CollectStage().execute(ctx, object(), concurrency=1)

    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute(
            "SELECT article_content, content_source_type, largest_image FROM news WHERE id=1"
        ).fetchone() == (("Reviewed repository content " * 10).strip(), "human_supplied", str(preview))


def test_collect_stage_filters_tracking_and_rss_images_before_saving(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(
        return_value=(
            "Readable article body " * 10,
            [
                "https://px.ads.linkedin.com/collect/?pid=1&fmt=gif",
                "https://www.facebook.com/tr?id=1",
                "https://vg09.met.vgwort.de/na/tracker",
                "https://example.com/assets/rss.png",
                "https://cdn.example.com/article-photo.jpg",
            ],
        )
    )
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
        patch("src.core.handlers.image_handler.save_article_image", return_value="article.jpg") as save_image,
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    assert result["image_warnings"] == []
    save_image.assert_called_once_with(
        "https://cdn.example.com/article-photo.jpg",
        "https://example.com/story",
        "Story_1",
    )


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
    preview = tmp_path / "GitHubPreview_1.png"
    preview.write_bytes(b"preview")

    with (
        patch(
            "src.core.handlers.pdf_handler.get_pdf_content",
            new=AsyncMock(return_value="PDF extracted text " * 10),
        ) as pdf_handler,
        patch(
            "hn2md.stages.collect._crawl_article_with_scrapling",
            new=AsyncMock(return_value=("", ["https://opengraph.githubassets.com/hash/deepseek-ai/DeepSpec"])),
        ) as crawl_page,
        patch("src.core.handlers.image_handler.save_article_image", return_value=str(preview)),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    pdf_handler.assert_awaited_once_with("https://github.com/deepseek-ai/DeepSpec/blob/main/DSpark_paper.pdf")
    crawl_page.assert_awaited_once()
    assert result["collected"] == 1

    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute("SELECT article_content, largest_image FROM news WHERE id=1").fetchone()
    assert row == (("PDF extracted text " * 10).strip(), str(preview))


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


def test_collect_stage_routes_hunyuan_urls_to_hunyuan_handler(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    _set_news_url(ctx, "https://hy.tencent.com/research/hy3")

    with (
        patch(
            "src.core.handlers.hunyuan_handler.get_hunyuan_blog_content",
            new=AsyncMock(return_value="Hunyuan article body " * 10),
        ) as hunyuan_handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler") as crawler_cls,
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
        patch("src.core.handlers.screenshot_handler.save_page_screenshot", return_value="shot.png"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    hunyuan_handler.assert_awaited_once_with("https://hy.tencent.com/research/hy3")
    crawler_cls.assert_not_called()
    assert result["collected"] == 1
    assert result["content_warnings"] == []

    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT article_content, content_source_type, content_source_url FROM news WHERE id=1"
        ).fetchone()
    assert row == (
        ("Hunyuan article body " * 10).strip(),
        "full_text",
        "https://hy.tencent.com/research/hy3",
    )


def test_collect_stage_routes_openai_urls_to_official_handler(tmp_path) -> None:
    from src.core.handlers.browser_article_handler import ArticleExtraction

    ctx = _ctx(tmp_path)
    url = "https://openai.com/index/example/"
    _set_news_url(ctx, url)

    with (
        patch(
            "src.core.handlers.openai_handler.get_openai_article_content",
            new=AsyncMock(
                return_value=ArticleExtraction(
                    content="OpenAI article body " * 10,
                    image_urls=("https://cdn.openai.com/hero.jpg",),
                )
            ),
        ) as handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler") as crawler_cls,
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
        patch("src.core.handlers.image_handler.save_article_image", return_value="openai-hero.jpg") as save_image,
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    handler.assert_awaited_once_with(url)
    crawler_cls.assert_not_called()
    save_image.assert_called_once_with("https://cdn.openai.com/hero.jpg", url, "Story_1")
    assert result["collected"] == 1


def test_collect_stage_routes_anthropic_and_qwen_urls_to_official_handlers(tmp_path) -> None:
    from src.core.handlers.browser_article_handler import ArticleExtraction

    ctx = _ctx(tmp_path)
    anthropic_url = "https://www.anthropic.com/news/example"
    _set_news_url(ctx, anthropic_url)

    with (
        patch(
            "src.core.handlers.anthropic_handler.get_anthropic_article_content",
            new=AsyncMock(return_value=ArticleExtraction(content="Anthropic article body " * 10)),
        ) as anthropic_handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler") as crawler_cls,
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
    ):
        first_result = CollectStage().execute(ctx, object(), concurrency=1)

    anthropic_handler.assert_awaited_once_with(anthropic_url)
    crawler_cls.assert_not_called()
    assert first_result["collected"] == 1

    qwen_url = "https://qwen.ai/blog?id=qwen-image-3.0"
    _set_news_url(ctx, qwen_url)
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute("UPDATE news SET article_content=NULL, content_source_type=NULL, content_source_url=NULL WHERE id=1")

    with (
        patch(
            "src.core.handlers.qwen_handler.get_qwen_blog_content",
            new=AsyncMock(return_value=ArticleExtraction(content="Qwen article body " * 10)),
        ) as qwen_handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler") as crawler_cls,
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
    ):
        second_result = CollectStage().execute(ctx, object(), concurrency=1)

    qwen_handler.assert_awaited_once_with(qwen_url)
    crawler_cls.assert_not_called()
    assert second_result["collected"] == 1


def test_collect_stage_falls_back_after_official_handler_failure(tmp_path) -> None:
    from src.core.handlers.browser_article_handler import ArticleExtraction

    ctx = _ctx(tmp_path)
    url = "https://qwen.ai/blog?id=qwen-image-3.0"
    _set_news_url(ctx, url)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("Fallback article body " * 10, ["https://cdn.qwen.ai/hero.jpg"]))
    crawler.close = AsyncMock()

    with (
        patch(
            "src.core.handlers.qwen_handler.get_qwen_blog_content",
            new=AsyncMock(return_value=ArticleExtraction(reason="qwen_api_content_unavailable")),
        ) as handler,
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
        patch("src.core.handlers.image_handler.save_article_image", return_value="qwen-hero.jpg"),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    handler.assert_awaited_once_with(url)
    crawler.crawl_article.assert_awaited_once_with(url)
    crawler.close.assert_awaited_once()
    assert result["collected"] == 1
    assert result["content_warnings"] == []


def test_collect_stage_records_official_handler_reason_after_fallback_failure(tmp_path) -> None:
    from src.core.handlers.browser_article_handler import ArticleExtraction

    ctx = _ctx(tmp_path)
    url = "https://openai.com/index/example/"
    _set_news_url(ctx, url)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("", []))
    crawler.close = AsyncMock()

    with (
        patch(
            "src.core.handlers.openai_handler.get_openai_article_content",
            new=AsyncMock(return_value=ArticleExtraction(reason="browser_article_timeout")),
        ),
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch("src.core.handlers.discussion_handler.get_discussion_content_async", new=AsyncMock(return_value="HN discussion")),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    assert result["content_warnings"][0]["official_handler"] == "openai"
    assert result["content_warnings"][0]["official_handler_reason"] == "browser_article_timeout"
    assert result["content_warnings"][0]["fallback"] == "scrapling"


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


def test_collect_stage_rejects_paywall_shell_content(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    crawler = MagicMock()
    crawler.crawl_article = AsyncMock(return_value=("Subscribe to read this article. " * 10, []))
    crawler.close = AsyncMock()

    with (
        patch("src.core.crawlers.scrapling_crawler.ScraplingCrawler", return_value=crawler),
        patch(
            "src.core.handlers.discussion_handler.get_discussion_content_async",
            new=AsyncMock(return_value="HN discussion"),
        ),
    ):
        result = CollectStage().execute(ctx, object(), concurrency=1)

    assert result["collected"] == 0
    assert result["content_warnings"][0]["reason"] == "paywall_or_shell_page"
    with sqlite3.connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT article_content, content_source_type FROM news WHERE id=1"
        ).fetchone()
    assert row == (None, None)


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
