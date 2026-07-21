import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import patch

from hn2md.context import RuntimeContext
from hn2md.screenshot_capture import SCREENSHOT_TIMEOUT_SECONDS, _capture_rows, capture_missing_screenshots
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
        return_value={"id": 1, "screenshot": "shot.png", "duration_ms": 120},
    ):
        result = capture_missing_screenshots(ctx, concurrency=1)

    assert result["requested"] == 1
    assert result["captured"] == 1
    assert result["timed_out"] == 0
    assert result["concurrency"] == 1
    assert result["p50_duration_ms"] == 120
    assert result["p95_duration_ms"] == 120
    assert result["items"] == [{"id": 1, "captured": True, "reason": None, "duration_ms": 120}]
    assert result["warnings"] == []
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT screenshot FROM news WHERE id=1").fetchone() == ("shot.png",)


def test_capture_rows_honors_the_concurrency_limit(monkeypatch) -> None:
    active = 0
    peak_active = 0
    lock = threading.Lock()

    def capture(row):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"id": row["id"], "screenshot": None, "duration_ms": 20}

    monkeypatch.setattr("hn2md.screenshot_capture._capture_one_in_process", capture)

    results = __import__("asyncio").run(_capture_rows([{"id": index} for index in range(4)], concurrency=2))

    assert len(results) == 4
    assert peak_active == 2


def test_screenshot_timeout_includes_windows_browser_startup_budget() -> None:
    assert SCREENSHOT_TIMEOUT_SECONDS >= 60
