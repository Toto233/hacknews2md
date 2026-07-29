from unittest.mock import MagicMock, patch

from src.core.handlers.browser_support import create_headless_browser


def test_create_headless_browser_falls_back_to_edge_when_chrome_is_unavailable() -> None:
    edge_driver = MagicMock()
    with (
        patch("src.core.handlers.browser_support.webdriver.Chrome", side_effect=RuntimeError("chrome missing")),
        patch("src.core.handlers.browser_support.webdriver.Edge", return_value=edge_driver) as edge,
    ):
        result = create_headless_browser()

    assert result is edge_driver
    edge.assert_called_once()


def test_create_headless_browser_prefers_chrome_when_available() -> None:
    chrome_driver = MagicMock()
    with (
        patch("src.core.handlers.browser_support.webdriver.Chrome", return_value=chrome_driver) as chrome,
        patch("src.core.handlers.browser_support.webdriver.Edge") as edge,
    ):
        result = create_headless_browser()

    assert result is chrome_driver
    chrome.assert_called_once()
    edge.assert_not_called()
