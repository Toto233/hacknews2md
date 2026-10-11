from unittest.mock import MagicMock

import pytest

from src.core.handlers.browser_capture_status import (
    classify_browser_capture_status,
    detect_browser_capture_status,
)


@pytest.mark.parametrize("signals", [
    {"title": "403 Forbidden", "body_text": "403 Forbidden\nnginx"},
    {"title": "Error 403: Forbidden", "body_text": "The request cannot be served."},
    {"title": "Access Denied | Cloudflare", "body_text": "Access denied"},
    {"title": "example.com", "heading_text": "Sorry, you have been blocked", "body_text": "Cloudflare Ray ID: 123"},
    {"body_text": "You don't have permission to access /private on this server."},
    {"title": "403 禁止访问", "body_text": "拒绝访问"},
])
def test_access_error_pages(signals) -> None:
    assert classify_browser_capture_status(signals) == "access_denied"


@pytest.mark.parametrize("signals", [
    {"title": "Just a moment...", "body_text": "Checking your browser before accessing example.com"},
    {"title": "example.com", "body_text": "example.com\nVerify you are human", "has_challenge_dom": True},
    {"title": "Attention Required! | Cloudflare", "body_text": "Please complete the CAPTCHA", "has_captcha_dom": True},
    {"title": "Security check", "body_text": "", "has_challenge_dom": True},
    {"heading_text": "Verify you are human", "body_text": "Check the box to continue", "has_captcha_dom": True},
    {"title": "安全验证", "body_text": "请完成验证码", "has_captcha_dom": True},
])
def test_verification_interstitials(signals) -> None:
    assert classify_browser_capture_status(signals) == "verification_required"


@pytest.mark.parametrize("signals", [
    {"title": "A 403 vulnerability lets attackers bypass access controls", "heading_text": "Understanding HTTP 403", "body_text": "403 Forbidden means access was denied. This report covers a vulnerability."},
    {"title": "CAPTCHA is getting harder", "body_text": "Researchers found users are forced to verify you are human too often."},
    {"title": "News", "body_text": "A new browser engine was announced. This site is protected by reCAPTCHA.", "has_captcha_dom": True},
    {"title": "Contact us", "body_text": "Send us a message. Please complete the CAPTCHA.", "has_captcha_dom": True},
    {"title": "Just a moment", "body_text": "An essay on taking time to think before acting."},
    {"title": "Access Denied", "body_text": "A report about censorship and how it is implemented.", "has_article_content": True},
    {"title": "Just a moment...", "body_text": "This article covers how to verify you are human.", "has_article_content": True, "has_challenge_dom": True},
    {"title": "403 Forbidden", "body_text": "An article about web security. " * 150},
    {"title": "Service unavailable", "body_text": "The server is temporarily busy."},
    {"title": "502 Bad Gateway", "body_text": "nginx"},
    {"title": "", "body_text": ""},
    {"title": "A title", "body_text": "Unknown failure", "has_challenge_dom": True},
])
def test_articles_and_unknown_failures_are_not_classified(signals) -> None:
    assert classify_browser_capture_status(signals) is None


def test_detector_only_reads_rendered_dom() -> None:
    driver = MagicMock()
    driver.execute_script.return_value = {"title": "403 Forbidden"}
    assert detect_browser_capture_status(driver) == "access_denied"
    driver.execute_script.assert_called_once()
    driver.get.assert_not_called()
    script = driver.execute_script.call_args.args[0]
    assert "document.body.innerText" in script
    assert "footer, [role=\"contentinfo\"]" in script
    assert "fetch(" not in script
    assert ".click(" not in script


@pytest.mark.parametrize("browser_result", [None, [], "403 Forbidden", {"title": 403}])
def test_unavailable_or_malformed_dom_remains_unknown(browser_result) -> None:
    driver = MagicMock()
    driver.execute_script.return_value = browser_result
    assert detect_browser_capture_status(driver) is None


def test_detector_probe_failure_is_nonblocking() -> None:
    driver = MagicMock()
    driver.execute_script.side_effect = RuntimeError("page unavailable")
    assert detect_browser_capture_status(driver) is None
