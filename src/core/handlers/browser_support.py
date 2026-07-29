"""Shared Selenium configuration for browser-backed content handlers."""

from __future__ import annotations

import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

try:
    from selenium.webdriver.edge.options import Options as EdgeOptions
except ModuleNotFoundError:  # Minimal Selenium test doubles may not expose Edge modules.
    EdgeOptions = ChromeOptions


logger = logging.getLogger(__name__)


def build_headless_chrome_options() -> ChromeOptions:
    """Build the consistent, non-interactive Chrome options used by collectors."""
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.page_load_strategy = "eager"
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return options


def build_headless_edge_options() -> EdgeOptions:
    """Build the Edge equivalent of the standard headless browser options."""
    options = EdgeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.page_load_strategy = "eager"
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return options


def create_headless_browser() -> webdriver.Remote:
    """Create Chrome when available, otherwise fall back to Microsoft Edge."""
    failures: list[str] = []
    for browser_name, factory, options in (
        ("chrome", webdriver.Chrome, build_headless_chrome_options()),
        ("edge", webdriver.Edge, build_headless_edge_options()),
    ):
        try:
            driver = factory(options=options)
            logger.info("browser_driver_ready", extra={"browser": browser_name})
            return driver
        except Exception as exc:
            failures.append(f"{browser_name}: {exc}")
            logger.info("browser_driver_unavailable", extra={"browser": browser_name, "error": str(exc)[:200]})
    raise RuntimeError("No supported browser driver is available: " + " | ".join(failures))
