"""Conservative recognition of access-blocking pages already rendered by Selenium."""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_ACCESS_HEADING = re.compile(
    r"^(?:(?:(?:error|http)\s*)?403(?:\s*[:\-–]?\s*(?:forbidden|access denied|禁止访问))?"
    r"|forbidden|access denied|permission denied|request blocked"
    r"|(?:sorry,?\s*)?you (?:have been|are) blocked|拒绝访问|访问被拒绝)"
    r"(?:\s*[|\-–]\s*(?:nginx|apache|cloudflare))?[.!]?$",
    re.IGNORECASE,
)
_ACCESS_MESSAGE = re.compile(
    r"^(?:you (?:do not|don't) have permission to access\b"
    r"|access to (?:this (?:page|site|resource)|the requested (?:url|resource)) is denied\b"
    r"|您没有权限访问|你没有权限访问)",
    re.IGNORECASE,
)
_VERIFICATION_HEADING = re.compile(
    r"^(?:just a moment|(?:please\s+)?verify (?:that )?you are (?:a )?human"
    r"|human verification|security (?:check|verification)|captcha|robot check"
    r"|attention required|人机验证|安全验证|请完成验证|请验证您是真人)"
    r"[.!…]*(?:\s*[|\-–]\s*cloudflare)?[.!…]*$",
    re.IGNORECASE,
)
_VERIFICATION_MESSAGE = re.compile(
    r"(?:verify(?:ing)? (?:that )?you are (?:a )?human"
    r"|checking your browser|performing security verification"
    r"|enable javascript and cookies to continue|complete (?:the |a )?captcha"
    r"|confirm (?:that )?you are not a robot|checking if (?:the )?site connection is secure"
    r"|review (?:the )?security of your connection|完成(?:人机验证|验证码)|验证您是真人)",
    re.IGNORECASE,
)


def classify_browser_capture_status(signals: dict[str, Any]) -> str | None:
    """Recognize a short error/challenge page, never an article keyword match.

    Article bodies and long pages are deliberately excluded. CAPTCHAs by
    themselves also prove nothing: many normal pages embed them in a footer
    or login/contact form. Unknown states remain generic capture outcomes.
    """
    title = _normalized_text(signals.get("title"))
    body = _normalized_text(signals.get("body_text"))
    heading = _normalized_text(signals.get("heading_text"))
    raw_body = signals.get("body_text")
    first_line = next(
        (_normalized_text(line) for line in raw_body.splitlines() if line.strip()), ""
    ) if isinstance(raw_body, str) else ""
    if signals.get("has_article_content") is True or len(body) > 1800:
        return None

    if (
        any(_ACCESS_HEADING.fullmatch(value) for value in (title, heading, first_line))
        or _ACCESS_MESSAGE.match(first_line)
    ):
        return "access_denied"

    challenge_dom = signals.get("has_challenge_dom") is True
    captcha_dom = signals.get("has_captcha_dom") is True
    verification_heading = any(
        _VERIFICATION_HEADING.fullmatch(value) for value in (title, heading, first_line)
    )
    verification_message = _VERIFICATION_MESSAGE.search(body[:600]) is not None
    if (
        verification_heading and (verification_message or challenge_dom or captcha_dom)
    ) or (challenge_dom and verification_message):
        return "verification_required"
    return None


def detect_browser_capture_status(driver: Any) -> str | None:
    """Inspect the current DOM once without navigation, requests or clicks."""
    try:
        signals = driver.execute_script(_page_signals_script())
    except Exception as exc:
        logger.debug("screenshot_page_status_unavailable", error=str(exc)[:160])
        return None
    if not isinstance(signals, dict):
        return None
    return classify_browser_capture_status(signals)


def _normalized_text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _page_signals_script() -> str:
    return """
const visible = element => {
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && style.display !== 'none'
    && style.visibility !== 'hidden' && style.visibility !== 'collapse';
};
const anyVisible = selector => [...document.querySelectorAll(selector)].some(visible);
const headings = [...document.querySelectorAll('h1, h2')].filter(visible);
const articleElements = [...document.querySelectorAll(
  'article, [itemprop="articleBody"], .post-content, .entry-content'
)];
const captchaElements = [...document.querySelectorAll(
  '.g-recaptcha, .h-captcha, .cf-turnstile, iframe[src*="recaptcha"], '
  + 'iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare.com"]'
)];
return {
  title: document.title || '',
  body_text: (document.body ? document.body.innerText : '').slice(0, 12000),
  heading_text: headings.length ? headings[0].innerText : '',
  has_article_content: articleElements.some(element => visible(element)
    && (element.innerText || '').trim().length >= 200),
  has_challenge_dom: anyVisible(
    '#challenge-form, #cf-challenge-running, .cf-browser-verification, '
    + '#cf-challenge-stage, #challenge-running'
  ),
  has_captcha_dom: captchaElements.some(element => visible(element)
    && !element.closest('footer, [role="contentinfo"]')),
};
"""
