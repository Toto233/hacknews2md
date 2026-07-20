"""Lightweight checks for scraped article text quality."""

from __future__ import annotations


PAYWALL_OR_SHELL_MARKERS = (
    "subscribe to read",
    "subscribe now",
    "barrier-page",
    "this article is for subscribers",
    "purchase a subscription",
    "to continue reading",
)


def is_paywall_or_shell_content(content: str) -> bool:
    """Return whether text looks like a paywall or site shell, not an article."""
    lowered = content.lower()
    return any(marker in lowered for marker in PAYWALL_OR_SHELL_MARKERS)
