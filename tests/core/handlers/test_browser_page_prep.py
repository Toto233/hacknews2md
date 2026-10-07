from unittest.mock import MagicMock, patch

from src.core.handlers.browser_page_prep import (
    CONSENT_ACTION_SELECTOR,
    dismiss_cookie_consent,
    is_allowed_consent_rejection,
)


def test_cookie_dismissal_requires_an_allowlisted_reject_action_in_a_modal_consent_context() -> None:
    assert is_allowed_consent_rejection(
        "I Reject All (except Strictly Necessary)",
        consent_context=True,
        modal_context=True,
    )
    assert is_allowed_consent_rejection(
        "Reject all cookies",
        consent_context=True,
        modal_context=True,
    )


def test_cookie_consent_probe_includes_anchor_actions() -> None:
    """Some CMPs, including Africanews, render their dismiss action as a link."""
    assert "a[href]" in CONSENT_ACTION_SELECTOR


def test_cookie_dismissal_refuses_ordinary_or_accept_actions() -> None:
    assert not is_allowed_consent_rejection("Accept All", consent_context=True, modal_context=True)
    assert not is_allowed_consent_rejection("Reject All", consent_context=False, modal_context=True)
    assert not is_allowed_consent_rejection("Reject All", consent_context=True, modal_context=False)


def test_dismiss_cookie_consent_rejects_an_unambiguous_banner() -> None:
    driver = MagicMock()
    reject_button = MagicMock()
    driver.execute_script.side_effect = [
        {
            "action": "candidates",
            "candidates": [
                {
                    "element": reject_button,
                    "label": "i reject all (except strictly necessary)",
                    "consentContext": True,
                    "modalContext": True,
                }
            ],
        },
        {"action": "no_consent_banner"},
    ]

    with patch("src.core.handlers.browser_page_prep.WebDriverWait") as wait:
        wait.return_value.until.side_effect = lambda condition: condition(driver)
        result = dismiss_cookie_consent(driver, "https://apnews.com/article/example")

    assert result.action == "rejected"
    assert result.label == "i reject all (except strictly necessary)"
    assert driver.execute_script.call_count == 2
    reject_button.click.assert_called_once()


def test_dismiss_cookie_consent_leaves_pages_without_a_banner_unchanged() -> None:
    driver = MagicMock()
    driver.execute_script.return_value = {"action": "no_consent_banner"}

    result = dismiss_cookie_consent(driver, "https://example.com/article")

    assert result.action == "no_consent_banner"
    assert driver.execute_script.call_count == 1


def test_dismiss_cookie_consent_refuses_an_unapproved_candidate_before_clicking() -> None:
    driver = MagicMock()
    accept_button = MagicMock()
    driver.execute_script.return_value = {
        "action": "candidates",
        "candidates": [
            {
                "element": accept_button,
                "label": "Accept All",
                "consentContext": True,
                "modalContext": True,
            }
        ],
    }

    result = dismiss_cookie_consent(driver, "https://example.com/article")

    assert result.action == "no_safe_consent_action"
    assert driver.execute_script.call_count == 1
    accept_button.click.assert_not_called()


def test_dismiss_cookie_consent_rejects_france24_continue_without_agreeing() -> None:
    driver = MagicMock()
    reject_button = MagicMock()
    driver.execute_script.side_effect = [
        {
            "action": "candidates",
            "candidates": [
                {
                    "element": reject_button,
                    "label": "Continue without agreeing",
                    "consentContext": True,
                    "modalContext": True,
                }
            ],
        },
        {"action": "no_consent_banner"},
    ]

    with patch("src.core.handlers.browser_page_prep.WebDriverWait") as wait:
        wait.return_value.until.side_effect = lambda condition: condition(driver)
        result = dismiss_cookie_consent(
            driver,
            "https://www.france24.com/en/live-news/example",
        )

    assert result.action == "rejected"
    assert result.label == "Continue without agreeing"
    reject_button.click.assert_called_once()


def test_dismiss_cookie_consent_dismisses_africanews_without_agreeing() -> None:
    """Africanews offers a non-consent path that must precede screenshots."""
    driver = MagicMock()
    dismiss_button = MagicMock()
    driver.execute_script.side_effect = [
        {
            "action": "candidates",
            "candidates": [
                {
                    "element": dismiss_button,
                    "label": "Continue without agreeing →",
                    "consentContext": True,
                    "modalContext": True,
                }
            ],
        },
        {"action": "no_consent_banner"},
    ]

    with patch("src.core.handlers.browser_page_prep.WebDriverWait") as wait:
        wait.return_value.until.side_effect = lambda condition: condition(driver)
        result = dismiss_cookie_consent(
            driver,
            "https://www.africanews.com/2026/08/04/example/",
        )

    assert result.action == "dismissed"
    assert result.label == "Continue without agreeing →"
    dismiss_button.click.assert_called_once()


def test_dismiss_cookie_consent_uses_js_click_after_interception() -> None:
    driver = MagicMock()
    dismiss_button = MagicMock()
    dismiss_button.click.side_effect = RuntimeError("overlay")
    driver.execute_script.side_effect = [
        {
            "action": "candidates",
            "candidates": [
                {
                    "element": dismiss_button,
                    "label": "Continue without agreeing →",
                    "consentContext": True,
                    "modalContext": True,
                }
            ],
        },
        None,
        {"action": "no_consent_banner"},
    ]

    with patch("src.core.handlers.browser_page_prep.WebDriverWait") as wait:
        wait.return_value.until.side_effect = lambda condition: condition(driver)
        result = dismiss_cookie_consent(
            driver,
            "https://www.africanews.com/2026/08/04/example/",
        )

    assert result.action == "dismissed"
    dismiss_button.click.assert_called_once()
    assert driver.execute_script.call_args_list[1].args == ("arguments[0].click();", dismiss_button)


def test_dismiss_cookie_consent_refuses_africanews_dismissal_outside_africanews() -> None:
    driver = MagicMock()
    dismiss_button = MagicMock()
    driver.execute_script.return_value = {
        "action": "candidates",
        "candidates": [
            {
                "element": dismiss_button,
                "label": "Continue without agreeing",
                "consentContext": True,
                "modalContext": True,
            }
        ],
    }

    result = dismiss_cookie_consent(driver, "https://example.com/article")

    assert result.action == "no_safe_consent_action"
    dismiss_button.click.assert_not_called()


def test_dismiss_cookie_consent_refuses_france24_accept_action() -> None:
    driver = MagicMock()
    accept_button = MagicMock()
    driver.execute_script.return_value = {
        "action": "candidates",
        "candidates": [
            {
                "element": accept_button,
                "label": "I agree",
                "consentContext": True,
                "modalContext": True,
            }
        ],
    }

    result = dismiss_cookie_consent(
        driver,
        "https://www.france24.com/en/live-news/example",
    )

    assert result.action == "no_safe_consent_action"
    accept_button.click.assert_not_called()


def test_dismiss_cookie_consent_does_not_block_when_browser_script_fails() -> None:
    driver = MagicMock()
    driver.execute_script.side_effect = RuntimeError("browser closed")

    result = dismiss_cookie_consent(driver, "https://example.com/article")

    assert result.action == "unavailable"
