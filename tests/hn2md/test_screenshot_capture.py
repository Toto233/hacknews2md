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
    progress_path = ctx.job_dir / "capture_progress_20260731.json"

    with patch(
        "hn2md.screenshot_capture._capture_one_in_process",
        return_value={
            "id": 1,
            "screenshot": "shot.png",
            "duration_ms": 120,
            "page_preparation": {"action": "rejected"},
        },
    ):
        result = capture_missing_screenshots(ctx, concurrency=1, progress_path=progress_path)

    assert result["requested"] == 1
    assert result["captured"] == 1
    assert result["status"] == "completed"
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
    progress = __import__("json").loads(progress_path.read_text(encoding="utf-8"))
    assert progress["status"] == "completed"
    assert progress["completed"] == 1
    assert progress["captured"] == 1
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT screenshot FROM news WHERE id=1").fetchone() == ("shot.png",)


def test_capture_missing_screenshots_uses_requested_period(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute("UPDATE news SET created_at='2000-01-02 10:00:00' WHERE id=1")
        conn.execute(
            "INSERT INTO news (id, title, news_url, created_at) "
            "VALUES (2, 'Today', 'https://example.com/today', datetime('now', 'localtime'))"
        )

    with patch(
        "hn2md.screenshot_capture._capture_one_in_process",
        return_value={"id": 1, "screenshot": "old.png", "duration_ms": 10},
    ):
        result = capture_missing_screenshots(ctx, concurrency=1, period="20000102")

    assert result["requested"] == 1
    assert [item["id"] for item in result["items"]] == [1]
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT screenshot FROM news WHERE id=1").fetchone() == ("old.png",)
        assert conn.execute("SELECT screenshot FROM news WHERE id=2").fetchone() == (None,)


def test_capture_skips_github_even_when_its_preview_is_missing(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute("UPDATE news SET news_url='https://github.com/owner/repo' WHERE id=1")

    with patch("hn2md.screenshot_capture._capture_one_in_process") as capture:
        result = capture_missing_screenshots(ctx, concurrency=1)

    capture.assert_not_called()
    assert result["requested"] == 0
    assert result["github_skipped"] == 1
    assert result["missing_github_previews"] == [
        {"id": 1, "news_url": "https://github.com/owner/repo", "reason": "github_social_preview_missing"}
    ]


def test_capture_skips_github_but_captures_other_sources(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    preview = tmp_path / "GitHubPreview_2.png"
    preview.write_bytes(b"preview")
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute(
            "INSERT INTO news (id, title, news_url, largest_image, created_at) "
            "VALUES (2, 'Repo', 'https://github.com/owner/repo', ?, datetime('now', 'localtime'))",
            (str(preview),),
        )

    with patch(
        "hn2md.screenshot_capture._capture_one_in_process",
        return_value={"id": 1, "screenshot": "shot.png", "duration_ms": 10},
    ) as capture:
        result = capture_missing_screenshots(ctx, concurrency=1)

    capture.assert_called_once()
    assert result["requested"] == 1
    assert result["captured"] == 1
    assert result["github_skipped"] == 1
    assert result["missing_github_previews"] == []


def test_capture_stage_passes_its_run_period(tmp_path: Path) -> None:
    from hn2md.stages.screenshot import CaptureScreenshotsStage

    ctx = _ctx(tmp_path)
    machine = type("M", (), {"job": type("J", (), {"date": "20000102"})()})()
    with patch("hn2md.stages.screenshot.capture_missing_screenshots", return_value={"requested": 0}) as capture:
        CaptureScreenshotsStage().execute(ctx, machine, concurrency=2)

    assert capture.call_args.kwargs["period"] == "20000102"


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
