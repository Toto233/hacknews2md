import sqlite3
import threading
import time
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from hn2md.context import RuntimeContext
from hn2md.screenshot_capture import (
    SCREENSHOT_ATTEMPTS,
    SCREENSHOT_TIMEOUT_SECONDS,
    _capture_one_in_process,
    _capture_rows,
    _save_screenshot_in_child,
    capture_missing_screenshots,
)
from src.core.handlers.screenshot_handler import ScreenshotCapture
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


def test_capture_missing_screenshots_records_successes_without_blocking_failures(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    with patch(
        "hn2md.screenshot_capture._capture_one_in_process",
        return_value={
            "id": 1,
            "screenshot": "shot.png",
            "duration_ms": 120,
            "page_preparation": {"action": "rejected"},
        },
    ):
        result = capture_missing_screenshots(ctx, concurrency=1)

    assert result["requested"] == 1
    assert result["captured"] == 1
    assert result["timed_out"] == 0
    assert result["concurrency"] == 1
    assert result["p50_duration_ms"] == 120
    assert result["p95_duration_ms"] == 120
    assert result["items"] == [
        {
            "id": 1,
            "captured": True,
            "reason": None,
            "duration_ms": 120,
            "page_preparation_action": "rejected",
        }
    ]
    assert result["page_preparation_actions"] == {"rejected": 1}
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
    assert SCREENSHOT_TIMEOUT_SECONDS >= 120
    assert SCREENSHOT_ATTEMPTS == 2


def test_capture_retries_once_before_returning_a_warning(monkeypatch) -> None:
    attempts = []

    def capture_once(row):
        attempts.append(row["id"])
        if len(attempts) == 1:
            return {"id": row["id"], "screenshot": None, "reason": "screenshot_timeout"}
        return {"id": row["id"], "screenshot": "shot.png"}

    monkeypatch.setattr("hn2md.screenshot_capture._capture_one_attempt", capture_once)

    result = _capture_one_in_process({"id": 1, "news_url": "https://example.com", "title": "Story"})

    assert result["screenshot"] == "shot.png"
    assert result["attempts"] == 2


def test_screenshot_child_preserves_the_page_preparation_action() -> None:
    result_queue = Queue()
    with patch(
        "src.core.handlers.screenshot_handler.capture_page_screenshot",
        return_value=ScreenshotCapture(path="shot.png", page_preparation_action="rejected"),
    ):
        _save_screenshot_in_child("https://example.com/story", "Story", result_queue)

    assert result_queue.get_nowait() == {
        "screenshot": "shot.png",
        "page_preparation": {"action": "rejected"},
    }
