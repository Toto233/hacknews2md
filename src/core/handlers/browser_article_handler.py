"""Killable browser-backed extraction for first-party article handlers."""

from __future__ import annotations

from multiprocessing import get_context
from queue import Empty
import time
from typing import Any

import structlog
from selenium import webdriver

from src.core.handlers.article_extraction import ArticleExtraction
from src.core.handlers.browser_page_prep import dismiss_cookie_consent
from src.core.handlers.browser_support import build_headless_chrome_options
from src.security.url_validator import SecurityError, validate_url

logger = structlog.get_logger(__name__)

PAGE_LOAD_TIMEOUT_SECONDS = 20
RENDER_WAIT_SECONDS = 3.0
BROWSER_ARTICLE_TIMEOUT_SECONDS = 75
PROCESS_RESULT_WAIT_SECONDS = 2
PROCESS_TERMINATE_WAIT_SECONDS = 5


def _render_browser_article(url: str) -> ArticleExtraction:
    """Render one page in the child process and return its main article region."""
    driver = None
    try:
        driver = webdriver.Chrome(options=build_headless_chrome_options())
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        driver.get(url)
        dismiss_cookie_consent(driver, url)
        time.sleep(RENDER_WAIT_SECONDS)
        result = driver.execute_script(
            "const candidates = [...document.querySelectorAll('article, main, [role=main]')];"
            "const root = candidates.sort((left, right) => right.innerText.length - left.innerText.length)[0] "
            "  || document.body;"
            "return {"
            "  content: root.innerText || '',"
            "  imageUrls: [...root.querySelectorAll('img')].map(image => "
            "    image.currentSrc || image.src || image.dataset.src || '').filter(Boolean)"
            "};"
        )
        if not isinstance(result, dict):
            return ArticleExtraction(reason="browser_article_result_invalid")
        content = result.get("content")
        image_urls = result.get("imageUrls")
        return ArticleExtraction(
            content=content.strip() if isinstance(content, str) else "",
            image_urls=tuple(url for url in image_urls if isinstance(url, str) and url.startswith("http"))
            if isinstance(image_urls, list)
            else (),
        )
    except Exception as exc:
        return ArticleExtraction(reason="browser_article_fetch_failed", error=str(exc))
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                # The parent process has the final timeout and can terminate a hung driver.
                pass


def _render_browser_article_in_child(url: str, result_queue: Any) -> None:
    """Run WebDriver in a process the parent can always terminate."""
    try:
        result_queue.put(_render_browser_article(url))
    except Exception as exc:
        result_queue.put(ArticleExtraction(reason="browser_article_child_failed", error=str(exc)))


def _stop_process(process: Any) -> None:
    """Terminate a timed-out child without allowing cleanup to block the caller."""
    process.terminate()
    process.join(PROCESS_TERMINATE_WAIT_SECONDS)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(PROCESS_TERMINATE_WAIT_SECONDS)


def get_browser_article_content(url: str) -> ArticleExtraction:
    """Return rendered article text and images within a killable total time budget."""
    try:
        validate_url(url)
    except (SecurityError, ValueError) as exc:
        logger.warning("browser_article_url_validation_failed", error=str(exc), url=url[:80])
        return ArticleExtraction(reason="browser_article_url_validation_failed")

    started_at = time.monotonic()
    result_queue = None
    process = None
    try:
        process_context = get_context("spawn")
        result_queue = process_context.Queue()
        process = process_context.Process(
            target=_render_browser_article_in_child,
            args=(url, result_queue),
        )
        process.start()
        process.join(BROWSER_ARTICLE_TIMEOUT_SECONDS)
        if process.is_alive():
            _stop_process(process)
            logger.warning("browser_article_timeout", url=url[:80])
            return ArticleExtraction(reason="browser_article_timeout")

        try:
            result = result_queue.get(timeout=PROCESS_RESULT_WAIT_SECONDS)
        except Empty:
            logger.warning("browser_article_result_unavailable", url=url[:80])
            return ArticleExtraction(reason="browser_article_result_unavailable")
        if isinstance(result, ArticleExtraction):
            return result
        logger.warning("browser_article_result_invalid", url=url[:80])
        return ArticleExtraction(reason="browser_article_result_invalid")
    except Exception as exc:
        logger.warning("browser_article_process_failed", error=str(exc), url=url[:80])
        return ArticleExtraction(reason="browser_article_process_failed")
    finally:
        if process and process.is_alive():
            _stop_process(process)
        if result_queue is not None:
            result_queue.close()
        logger.info(
            "browser_article_finished",
            url=url[:80],
            duration_ms=round((time.monotonic() - started_at) * 1000),
        )
