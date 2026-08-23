from datetime import datetime
from unittest.mock import MagicMock, patch

from src.core.handlers.browser_page_prep import CookieConsentResult
from src.core.handlers.screenshot_handler import capture_page_screenshot


def test_capture_waits_for_delayed_consent_before_screenshot() -> None:
    """Cookie dialogs injected after navigation must be dismissed before capture."""
    driver = MagicMock()
    events: list[str] = []
    driver.get.side_effect = lambda _url: events.append("navigate")
    driver.save_screenshot.side_effect = lambda _path: events.append("screenshot")

    with (
        patch("src.core.handlers.screenshot_handler.datetime") as mocked_datetime,
        patch("src.core.handlers.screenshot_handler.os.path.exists", side_effect=[True, False]),
        patch("src.core.handlers.screenshot_handler.webdriver.Chrome", return_value=driver),
        patch("src.core.handlers.screenshot_handler.validate_url"),
        patch(
            "src.core.handlers.screenshot_handler.time.sleep",
            side_effect=lambda _seconds: events.append("render_wait"),
        ),
        patch(
            "src.core.handlers.screenshot_handler.dismiss_cookie_consent",
            side_effect=lambda *_args: events.append("consent")
            or CookieConsentResult(action="dismissed"),
        ),
    ):
        mocked_datetime.now.return_value = datetime(2026, 8, 5)
        capture_page_screenshot("https://www.africanews.com/example", "Africanews")

    assert events == ["navigate", "render_wait", "consent", "screenshot"]
