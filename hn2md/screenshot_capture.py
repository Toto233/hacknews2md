"""Optional screenshot capture kept outside the critical collection stage."""

from __future__ import annotations

import asyncio
from collections import Counter
import json
from multiprocessing import get_context
import os
from pathlib import Path
from queue import Empty
import sqlite3
import time
from typing import Any, Callable

from hn2md.context import RuntimeContext
from src.core.github_visuals import has_saved_github_preview, is_github_page_url
from src.db.connection import get_db


# Chrome startup regularly takes 25+ seconds on Windows. The page handler has
# its own navigation timeout, so this outer budget must also cover process and
# browser startup rather than cutting every valid capture short.
SCREENSHOT_TIMEOUT_SECONDS = int(os.getenv("HN2MD_SCREENSHOT_TIMEOUT_SECONDS", "120"))
SCREENSHOT_ATTEMPTS = 2
PROCESS_RESULT_WAIT_SECONDS = 2


def _save_screenshot_in_child(url: str, title: str, result_queue: Any) -> None:
    """Run Selenium in a killable process so its browser cannot hold the batch."""
    from src.core.handlers.screenshot_handler import capture_page_screenshot

    try:
        capture = capture_page_screenshot(url, title)
        result_queue.put(
            {
                "screenshot": capture.path,
                "page_preparation": {"action": capture.page_preparation_action},
            }
        )
    except Exception as exc:
        result_queue.put({"screenshot": None, "reason": "screenshot_error", "error": str(exc)})


def _capture_one_attempt(row: sqlite3.Row) -> dict[str, Any]:
    """Capture one screenshot attempt with a process lifetime that can be terminated."""
    started_at = time.monotonic()
    process_context = get_context("spawn")
    result_queue = process_context.Queue()
    process = process_context.Process(
        target=_save_screenshot_in_child,
        args=(row["news_url"], row["title"] or "", result_queue),
    )
    process.start()
    process.join(SCREENSHOT_TIMEOUT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join()
        result_queue.close()
        return {
            "id": row["id"],
            "screenshot": None,
            "reason": "screenshot_timeout",
            "duration_ms": round((time.monotonic() - started_at) * 1000),
        }

    try:
        result = result_queue.get(timeout=PROCESS_RESULT_WAIT_SECONDS)
    except Empty:
        result = {"screenshot": None, "reason": "screenshot_unavailable"}
    finally:
        result_queue.close()

    result["id"] = row["id"]
    result["duration_ms"] = round((time.monotonic() - started_at) * 1000)
    if not result.get("screenshot") and "reason" not in result:
        result["reason"] = "screenshot_unavailable"
    return result


def _capture_one_in_process(row: sqlite3.Row) -> dict[str, Any]:
    """Retry a missing screenshot once before recording a non-blocking warning."""
    result: dict[str, Any] = {"id": row["id"], "screenshot": None, "reason": "screenshot_unavailable"}
    for attempt in range(1, SCREENSHOT_ATTEMPTS + 1):
        result = _capture_one_attempt(row)
        result["attempts"] = attempt
        if result.get("screenshot"):
            return result
    return result


async def _capture_one(row: sqlite3.Row, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    """Capture one screenshot without making article collection depend on it."""
    async with semaphore:
        try:
            return await asyncio.to_thread(_capture_one_in_process, row)
        except Exception as exc:
            return {"id": row["id"], "screenshot": None, "reason": "screenshot_error", "error": str(exc)}


async def _capture_rows(
    rows: list[sqlite3.Row],
    concurrency: int,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    tasks = [_capture_one(row, semaphore) for row in rows]
    results: list[dict[str, Any]] = []
    for task in asyncio.as_completed(tasks):
        result = await task
        results.append(result)
        if on_result:
            on_result(result)
    return results


def _percentile_duration_ms(durations: list[int], percentile: float) -> int | None:
    """Return a nearest-rank duration percentile for the batch receipt."""
    if not durations:
        return None
    ordered = sorted(durations)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * percentile) - 0.000_001)))
    return ordered[index]


def capture_missing_screenshots(
    ctx: RuntimeContext,
    concurrency: int = 4,
    progress_path: Path | None = None,
    period: str | None = None,
) -> dict[str, Any]:
    """Capture missing screenshots after collection; failures remain non-blocking."""
    period = period or time.strftime("%Y%m%d")
    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, news_url, largest_image
            FROM news
            WHERE strftime('%Y%m%d', created_at) = ?
              AND coalesce(screenshot, '') = ''
              AND coalesce(news_url, '') != ''
            ORDER BY id
            """,
            (period,),
        ).fetchall()
    github_rows = [row for row in rows if is_github_page_url(row["news_url"])]
    rows = [row for row in rows if not is_github_page_url(row["news_url"])]

    batch_started_at = time.monotonic()
    progress: dict[str, Any] = {
        "stage": "CAPTURING",
        "status": "running" if rows else "no_pending_work",
        "requested": len(rows),
        "github_skipped": len(github_rows),
        "completed": 0,
        "captured": 0,
        "started_at": time.time(),
    }

    def save_progress(result: dict[str, Any] | None = None) -> None:
        if result is not None:
            progress["completed"] += 1
            progress["captured"] += int(bool(result.get("screenshot")))
            progress["last_story_id"] = result.get("id")
            progress["last_reason"] = result.get("reason")
        if progress_path:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = progress_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
            temporary.replace(progress_path)

    save_progress()
    results = asyncio.run(_capture_rows(rows, concurrency, save_progress)) if rows else []
    batch_duration_ms = round((time.monotonic() - batch_started_at) * 1000)
    captured = 0
    warnings: list[dict[str, Any]] = []
    missing_github_previews = [
        {"id": row["id"], "news_url": row["news_url"], "reason": "github_social_preview_missing"}
        for row in github_rows
        if not has_saved_github_preview(row["largest_image"], row["id"])
    ]
    with get_db(str(ctx.db_path)) as conn:
        for result in results:
            screenshot = result.get("screenshot")
            if screenshot:
                conn.execute("UPDATE news SET screenshot=? WHERE id=?", (screenshot, result["id"]))
                captured += 1
            else:
                warnings.append({key: value for key, value in result.items() if key != "screenshot"})

    durations = [result["duration_ms"] for result in results if isinstance(result.get("duration_ms"), int)]
    page_preparation_actions = Counter(
        action
        for result in results
        if isinstance(result.get("page_preparation"), dict)
        if isinstance((action := result["page_preparation"].get("action")), str) and action
    )
    items = [
        {
            "id": result["id"],
            "captured": bool(result.get("screenshot")),
            "reason": result.get("reason"),
            "duration_ms": result.get("duration_ms"),
            "page_preparation_action": (
                result.get("page_preparation", {}).get("action")
                if isinstance(result.get("page_preparation"), dict)
                else None
            ),
        }
        for result in results
    ]
    summary = {
        "requested": len(rows),
        "captured": captured,
        "github_skipped": len(github_rows),
        "missing_github_previews": missing_github_previews,
        "status": "no_pending_work" if not rows else "completed",
        "timed_out": sum(result.get("reason") == "screenshot_timeout" for result in results),
        "attempts": SCREENSHOT_ATTEMPTS,
        "concurrency": max(1, concurrency),
        "batch_duration_ms": batch_duration_ms,
        "p50_duration_ms": _percentile_duration_ms(durations, 0.50),
        "p95_duration_ms": _percentile_duration_ms(durations, 0.95),
        "page_preparation_actions": dict(page_preparation_actions),
        "items": items,
        "warnings": warnings,
    }
    progress.update(
        {"status": "completed", "completed": len(results), "captured": captured, "finished_at": time.time()}
    )
    save_progress()
    return summary
