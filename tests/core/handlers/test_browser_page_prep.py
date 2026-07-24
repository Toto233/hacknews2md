from unittest.mock import MagicMock, patch

from src.core.handlers.browser_page_prep import (
    dismiss_cookie_consent,
    is_allowed_consent_rejection,
)


def test_cookie_dismissal_requires_an_allowlisted_reject_action_in_a_modal_consent_context() -> None:
    assert is_allowed_consent_rejection(
        "I Reject All (except Strictly Necessary)",
        consent_context=True,
        modal_context=True,
    )


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


def test_dismiss_cookie_consent_does_not_block_when_browser_script_fails() -> None:
    driver = MagicMock()
    driver.execute_script.side_effect = RuntimeError("browser closed")

    result = dismiss_cookie_consent(driver, "https://example.com/article")

    assert result.action == "unavailable"
