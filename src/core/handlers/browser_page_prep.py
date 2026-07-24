"""Small, privacy-first browser preparation shared by visual consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
const candidates = [...document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]')]
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
        candidate = _first_safe_consent_candidate(browser_result)
        if candidate is None:
            action = "no_safe_consent_action" if _has_consent_candidates(browser_result) else "no_consent_banner"
            return CookieConsentResult(action=action)

        if not candidate.get("element"):
            return CookieConsentResult(action="unavailable")
        label = candidate["label"]
        candidate["element"].click()
        WebDriverWait(driver, CONSENT_DISMISS_WAIT_SECONDS).until(
            lambda active_driver: _consent_banner_is_gone(active_driver)
        )
        logger.info("cookie_consent_rejected", url=url[:120], label=label)
        return CookieConsentResult(action="rejected", label=label)
    except Exception as exc:
        logger.info("cookie_consent_dismiss_unavailable", url=url[:120], error=str(exc)[:160])
        return CookieConsentResult(action="unavailable")


def _consent_banner_is_gone(driver: Any) -> bool:
    """Return whether the conservative probe can no longer find a reject control."""
    return _first_safe_consent_candidate(driver.execute_script(_consent_script())) is None


def _first_safe_consent_candidate(result: object) -> dict[str, Any] | None:
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
        if is_allowed_consent_rejection(
            label,
            consent_context=candidate.get("consentContext") is True,
            modal_context=candidate.get("modalContext") is True,
        ):
            return candidate
    return None


def _has_consent_candidates(result: object) -> bool:
    """Return whether the browser reported a modal consent action of any kind."""
    return (
        isinstance(result, dict)
        and result.get("action") == "candidates"
        and isinstance(result.get("candidates"), list)
        and bool(result["candidates"])
    )
