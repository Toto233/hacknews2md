from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.core.handlers import screenshot_handler
from src.core.handlers.browser_page_prep import CookieConsentResult
from src.core.handlers.screenshot_handler import ScreenshotCapture, capture_page_screenshot


@pytest.fixture
def isolated_browser(tmp_path, monkeypatch) -> MagicMock:
    """No browser, network, LLM, or real output files are touched by these tests."""
    monkeypatch.chdir(tmp_path)
    driver = MagicMock()
    driver.execute_script.return_value = {
        "title": "An ordinary article",
        "body_text": "The full story is available here.",
        "heading_text": "An ordinary article",
    }

    def save_image(path: str) -> bool:
        Path(path).write_bytes(b"mock screenshot")
        return True

    driver.save_screenshot.side_effect = save_image
    monkeypatch.setattr(screenshot_handler.webdriver, "Chrome", MagicMock(return_value=driver))
    monkeypatch.setattr(screenshot_handler, "build_headless_chrome_options", MagicMock())
    monkeypatch.setattr(screenshot_handler, "validate_url", MagicMock())
    monkeypatch.setattr(screenshot_handler.time, "sleep", MagicMock())
    monkeypatch.setattr(
        screenshot_handler, "dismiss_cookie_consent",
        MagicMock(return_value=CookieConsentResult(action="not_found")),
    )
    monkeypatch.setattr(screenshot_handler, "generate_summary_from_image", MagicMock())
    mocked_datetime = MagicMock()
    mocked_datetime.now.return_value = datetime(2026, 8, 5)
    monkeypatch.setattr(screenshot_handler, "datetime", mocked_datetime)
    return driver


def test_capture_waits_for_delayed_consent_before_screenshot(isolated_browser, monkeypatch) -> None:
    """Cookie dialogs injected after navigation must be dismissed before capture."""
    driver = isolated_browser
    events: list[str] = []
    driver.get.side_effect = lambda _url: events.append("navigate")

    def save_image(path: str) -> bool:
        events.append("screenshot")
        Path(path).write_bytes(b"mock screenshot")
        return True

    driver.save_screenshot.side_effect = save_image
    monkeypatch.setattr(screenshot_handler.time, "sleep", lambda _: events.append("render_wait"))
    monkeypatch.setattr(
        screenshot_handler, "dismiss_cookie_consent",
        lambda *_args: events.append("consent") or CookieConsentResult(action="dismissed"),
    )
    capture = capture_page_screenshot("https://www.africanews.com/example", "Africanews")
    assert events == ["navigate", "render_wait", "consent", "screenshot"]
    assert capture.path is not None
    assert capture.page_preparation_action == "dismissed"
    driver.quit.assert_called_once()


def test_capture_uses_a_markdown_safe_filename(isolated_browser) -> None:
    screenshot_handler.datetime.now.return_value = datetime(2026, 9, 7)
    capture = capture_page_screenshot(
        "https://example.com/article", "Your intellectual fly is open (2025)"
    )
    saved_path = isolated_browser.save_screenshot.call_args.args[0]
    assert saved_path.endswith("Your_intellectual_fly_is_open_2025.png")
    assert "(" not in saved_path
    assert ")" not in saved_path
    assert Path(capture.path).parent.name == "20260907"


def test_capture_preserves_existing_image(isolated_browser) -> None:
    first = capture_page_screenshot("https://example.com/article", "A title")
    second = capture_page_screenshot("https://example.com/article", "A title")
    assert Path(first.path).name == "A_title.png"
    assert Path(second.path).name == "A_title_2.png"


@pytest.mark.parametrize("verification", [False, True])
def test_blocked_pages_skip_screenshot(isolated_browser, verification) -> None:
    driver = isolated_browser
    driver.execute_script.return_value = {
        "title": "Just a moment..." if verification else "403 Forbidden",
        "body_text": "Verifying you are human" if verification else "403 Forbidden\nnginx",
        "has_challenge_dom": verification,
    }
    capture = capture_page_screenshot("https://example.com/article", "An article")
    assert capture.path is None
    assert capture.reason == ("verification_required" if verification else "access_denied")
    assert capture.evidence_path is None
    driver.save_screenshot.assert_not_called()
    driver.get.assert_called_once_with("https://example.com/article")
    driver.quit.assert_called_once()


def test_skipping_preserves_historical_error_images(isolated_browser) -> None:
    isolated_browser.execute_script.return_value = {"title": "Access denied", "body_text": "Denied"}
    old_image = Path("output/images/20260805/An_article_blocked.png")
    old_image.parent.mkdir(parents=True)
    old_image.write_bytes(b"previous evidence")
    capture = capture_page_screenshot("https://example.com/article", "An article")
    assert capture.path is None
    assert capture.evidence_path is None
    assert old_image.read_bytes() == b"previous evidence"
    isolated_browser.save_screenshot.assert_not_called()


@pytest.mark.parametrize("save_result", [False, None, True])
def test_failed_save_never_reports_a_saved_artifact(isolated_browser, save_result) -> None:
    """Even a True result without a file cannot become a successful receipt."""
    isolated_browser.save_screenshot.side_effect = None
    isolated_browser.save_screenshot.return_value = save_result
    capture = capture_page_screenshot("https://example.com/article", "An article")
    assert capture.path is None
    assert capture.evidence_path is None
    assert capture.reason is None


def test_navigation_timeout_remains_generic_failure(isolated_browser) -> None:
    isolated_browser.get.side_effect = TimeoutError("Page load timed out")
    capture = capture_page_screenshot("https://example.com/article", "An article")
    assert capture == ScreenshotCapture(None, "not_attempted")
    isolated_browser.save_screenshot.assert_not_called()
    isolated_browser.execute_script.assert_not_called()
    isolated_browser.quit.assert_called_once()


def test_unknown_save_error_remains_generic_failure(isolated_browser) -> None:
    isolated_browser.save_screenshot.side_effect = RuntimeError("disk failure")
    capture = capture_page_screenshot("https://example.com/article", "An article")
    assert capture.path is None
    assert capture.reason is None
    assert capture.evidence_path is None


def test_blocked_page_does_not_attempt_a_failing_save(isolated_browser) -> None:
    isolated_browser.execute_script.return_value = {"title": "403 Forbidden"}
    isolated_browser.save_screenshot.side_effect = RuntimeError("disk failure")
    capture = capture_page_screenshot("https://example.com/article", "An article")
    assert capture.path is None
    assert capture.reason == "access_denied"
    assert capture.evidence_path is None
    isolated_browser.save_screenshot.assert_not_called()


def test_blocked_page_never_reaches_image_llm(isolated_browser) -> None:
    isolated_browser.execute_script.return_value = {"title": "403 Forbidden"}
    result = screenshot_handler.get_summary_from_screenshot(
        "https://example.com/article", "An article", "mock-provider"
    )
    assert result is None
    screenshot_handler.generate_summary_from_image.assert_not_called()


def test_legacy_screenshot_capture_constructor_stays_compatible() -> None:
    capture = ScreenshotCapture("saved.png", "dismissed")
    assert capture.reason is None
    assert capture.evidence_path is None
