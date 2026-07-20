import sqlite3
from pathlib import Path
from unittest.mock import patch

from hn2md.context import RuntimeContext
from hn2md.screenshot_capture import capture_missing_screenshots
from src.utils.db_utils import init_database


def _ctx(tmp_path: Path) -> RuntimeContext:
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (id, title, news_url, created_at)
            VALUES (1, 'Story', 'https://example.com/story', datetime('now', 'localtime'))
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


def test_capture_missing_screenshots_is_optional_and_updates_only_successes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    with patch(
        "hn2md.screenshot_capture._capture_one_in_process",
        return_value={"id": 1, "screenshot": "shot.png"},
    ):
        result = capture_missing_screenshots(ctx, concurrency=1)

    assert result == {"requested": 1, "captured": 1, "warnings": []}
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT screenshot FROM news WHERE id=1").fetchone() == ("shot.png",)
