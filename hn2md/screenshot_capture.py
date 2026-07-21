"""Optional screenshot capture kept outside the critical collection stage."""

from __future__ import annotations

import asyncio
from multiprocessing import get_context
from queue import Empty
import sqlite3
import time
from typing import Any

from hn2md.context import RuntimeContext
from src.db.connection import get_db


# Chrome startup regularly takes 25+ seconds on Windows. The page handler has
# its own navigation timeout, so this outer budget must also cover process and
# browser startup rather than cutting every valid capture short.
SCREENSHOT_TIMEOUT_SECONDS = 75
PROCESS_RESULT_WAIT_SECONDS = 2


def _save_screenshot_in_child(url: str, title: str, result_queue: Any) -> None:
    """Run Selenium in a killable process so its browser cannot hold the batch."""
    from src.core.handlers.screenshot_handler import save_page_screenshot

    try:
        result_queue.put({"screenshot": save_page_screenshot(url, title)})
    except Exception as exc:
        result_queue.put({"screenshot": None, "reason": "screenshot_error", "error": str(exc)})


def _capture_one_in_process(row: sqlite3.Row) -> dict[str, Any]:
    """Capture one screenshot with a process lifetime that can be terminated."""
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


async def _capture_one(row: sqlite3.Row, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    """Capture one screenshot without making article collection depend on it."""
    async with semaphore:
        try:
            return await asyncio.to_thread(_capture_one_in_process, row)
        except Exception as exc:
            return {"id": row["id"], "screenshot": None, "reason": "screenshot_error", "error": str(exc)}


async def _capture_rows(rows: list[sqlite3.Row], concurrency: int) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    return await asyncio.gather(*(_capture_one(row, semaphore) for row in rows))


def _percentile_duration_ms(durations: list[int], percentile: float) -> int | None:
    """Return a nearest-rank duration percentile for the batch receipt."""
    if not durations:
        return None
    ordered = sorted(durations)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * percentile) - 0.000_001)))
    return ordered[index]


def capture_missing_screenshots(ctx: RuntimeContext, concurrency: int = 4) -> dict[str, Any]:
    """Capture missing screenshots after collection; failures remain non-blocking."""
    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, news_url
            FROM news
            WHERE date(created_at)=date('now','localtime')
              AND coalesce(screenshot, '') = ''
              AND coalesce(news_url, '') != ''
            ORDER BY id
            """
        ).fetchall()

    batch_started_at = time.monotonic()
    results = asyncio.run(_capture_rows(rows, concurrency)) if rows else []
    batch_duration_ms = round((time.monotonic() - batch_started_at) * 1000)
    captured = 0
    warnings: list[dict[str, Any]] = []
    with get_db(str(ctx.db_path)) as conn:
        for result in results:
            screenshot = result.get("screenshot")
            if screenshot:
                conn.execute("UPDATE news SET screenshot=? WHERE id=?", (screenshot, result["id"]))
                captured += 1
            else:
                warnings.append({key: value for key, value in result.items() if key != "screenshot"})

    durations = [result["duration_ms"] for result in results if isinstance(result.get("duration_ms"), int)]
    items = [
        {
            "id": result["id"],
            "captured": bool(result.get("screenshot")),
            "reason": result.get("reason"),
            "duration_ms": result.get("duration_ms"),
        }
        for result in results
    ]
    return {
        "requested": len(rows),
        "captured": captured,
        "timed_out": sum(result.get("reason") == "screenshot_timeout" for result in results),
        "concurrency": max(1, concurrency),
        "batch_duration_ms": batch_duration_ms,
        "p50_duration_ms": _percentile_duration_ms(durations, 0.50),
        "p95_duration_ms": _percentile_duration_ms(durations, 0.95),
        "items": items,
        "warnings": warnings,
    }
