"""Small, privacy-first browser preparation shared by visual consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import structlog
from selenium.webdriver.support.ui import WebDriverWait

logger = structlog.get_logger(__name__)

CONSENT_DISMISS_WAIT_SECONDS = 3
REJECT_ALL_LABELS = (
    "reject all",
    "i reject all (except strictly necessary)",
    "reject all optional cookies",
    "decline all",
    "deny all",
    "only necessary",
    "use necessary cookies only",
    "\u62d2\u7edd\u5168\u90e8",
    "\u5168\u90e8\u62d2\u7edd",
    "\u4ec5\u4f7f\u7528\u5fc5\u8981 cookie",
    "\u53ea\u63a5\u53d7\u5fc5\u8981 cookie",
)
CONTINUE_WITHOUT_AGREEING_LABELS = (
    "continue without agreeing",
    "continue without agreeing →",
)
CONSENT_ACTION_SELECTOR = "button, [role=\"button\"], input[type=\"button\"], input[type=\"submit\"], a[href]"


@dataclass(frozen=True)
class CookieConsentResult:
    """Outcome of a non-essential cookie-consent dismissal attempt."""

    action: str
    label: str | None = None


def is_allowed_consent_rejection(
    label: str,
    *,
    consent_context: bool,
    modal_context: bool,
) -> bool:
    """Return whether a candidate is safe to reject without user input."""
    normalized_label = " ".join(label.split()).casefold()
    return (
        consent_context
        and modal_context
        and normalized_label in {candidate.casefold() for candidate in REJECT_ALL_LABELS}
    )


def _consent_script() -> str:
    """Return the visible consent-action candidates without clicking anything."""
    return f"""
const normalize = value => (value || '').trim().replace(/\\s+/g, ' ').toLowerCase();
const isVisible = element => {{
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
}};
const getContext = element => {{
  let current = element;
  let consentContext = false;
  let modalContext = false;
  for (let depth = 0; current && depth < 8; depth += 1, current = current.parentElement) {{
    const descriptor = `${{current.id || ''}} ${{typeof current.className === 'string' ? current.className : ''}} ${{current.getAttribute('role') || ''}}`;
    const text = (current.innerText || '').slice(0, 3000);
    const style = window.getComputedStyle(current);
    if (/(cookie|privacy|consent|tracking|purposes?|\u9690\u79c1)/i.test(`${{descriptor}} ${{text}}`)) consentContext = true;
    if (
      current.getAttribute('role') === 'dialog' ||
      current.getAttribute('aria-modal') === 'true' ||
      /(modal|dialog|cookie|privacy|consent)/i.test(descriptor) ||
      (style.position === 'fixed' && style.zIndex !== 'auto')
    ) modalContext = true;
  }}
  return {{consentContext, modalContext}};
}};
const candidates = [...document.querySelectorAll('{CONSENT_ACTION_SELECTOR}')]
  .filter(isVisible)
  .map(element => ({{
    element,
    label: normalize(element.innerText || element.value || element.getAttribute('aria-label')),
    ...getContext(element),
  }}))
  .filter(candidate => candidate.consentContext && candidate.modalContext);
if (!candidates.length) return {{action: 'no_consent_banner'}};
return {{action: 'candidates', candidates}};
"""


def dismiss_cookie_consent(driver: Any, url: str) -> CookieConsentResult:
    """Reject optional cookies when an unambiguous consent dialog blocks a page.

    The browser session is ephemeral, so a broad accept-all click is neither
    required nor appropriate. Failure is intentionally non-blocking: callers
    can still capture or extract the page if its layout permits.
    """
    try:
        browser_result = driver.execute_script(_consent_script())
        candidate = _first_safe_consent_candidate(browser_result, url=url)
        if candidate is None:
            action = "no_safe_consent_action" if _has_consent_candidates(browser_result) else "no_consent_banner"
            return CookieConsentResult(action=action)

        if not candidate.get("element"):
            return CookieConsentResult(action="unavailable")
        label = candidate["label"]
        try:
            candidate["element"].click()
        except Exception:
            # The target has already passed the domain and label allowlist.
            # Some CMP overlays intercept Selenium's coordinate-based click.
            driver.execute_script("arguments[0].click();", candidate["element"])
            logger.info("cookie_consent_js_click_fallback", url=url[:120], label=label)
        WebDriverWait(driver, CONSENT_DISMISS_WAIT_SECONDS).until(
            lambda active_driver: _consent_banner_is_gone(active_driver, url=url)
        )
        logger.info("cookie_consent_rejected", url=url[:120], label=label)
        action = "dismissed" if _is_africanews_url(url) else "rejected"
        return CookieConsentResult(action=action, label=label)
    except Exception as exc:
        logger.info("cookie_consent_dismiss_unavailable", url=url[:120], error=str(exc)[:160])
        return CookieConsentResult(action="unavailable")


def _consent_banner_is_gone(driver: Any, *, url: str) -> bool:
    """Return whether the conservative probe can no longer find a reject control."""
    return _first_safe_consent_candidate(driver.execute_script(_consent_script()), url=url) is None


def _first_safe_consent_candidate(result: object, *, url: str) -> dict[str, Any] | None:
    """Return the first policy-approved candidate reported by the browser."""
    if not isinstance(result, dict) or result.get("action") != "candidates":
        return None
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        label = candidate.get("label")
        if not isinstance(label, str):
            continue
        if _is_allowed_candidate(label, candidate, url=url):
            return candidate
    return None


def _is_allowed_candidate(candidate_label: str, candidate: dict[str, Any], *, url: str) -> bool:
    """Return whether a consent candidate is safe for its source domain."""
    consent_context = candidate.get("consentContext") is True
    modal_context = candidate.get("modalContext") is True
    if is_allowed_consent_rejection(
        candidate_label,
        consent_context=consent_context,
        modal_context=modal_context,
    ):
        return True
    return (
        _is_france24_url(url)
        and consent_context
        and modal_context
        and _is_continue_without_agreeing_label(candidate_label)
    ) or (
        _is_africanews_url(url)
        and consent_context
        and modal_context
        and _is_continue_without_agreeing_label(candidate_label)
    )


def _is_france24_url(url: str) -> bool:
    """Return whether a URL belongs to France24 or one of its subdomains."""
    hostname = urlparse(url).hostname or ""
    return hostname.casefold() == "france24.com" or hostname.casefold().endswith(".france24.com")


def _is_africanews_url(url: str) -> bool:
    """Return whether a URL belongs to Africanews or one of its subdomains."""
    hostname = urlparse(url).hostname or ""
    return hostname.casefold() == "africanews.com" or hostname.casefold().endswith(".africanews.com")


def _is_continue_without_agreeing_label(label: str) -> bool:
    """Recognize the two explicit non-consent labels used by approved CMPs."""
    normalized_label = " ".join(label.split()).casefold()
    return normalized_label in {candidate.casefold() for candidate in CONTINUE_WITHOUT_AGREEING_LABELS}


def _has_consent_candidates(result: object) -> bool:
    """Return whether the browser reported a modal consent action of any kind."""
    return (
        isinstance(result, dict)
        and result.get("action") == "candidates"
        and isinstance(result.get("candidates"), list)
        and bool(result["candidates"])
    )
