"""Fallback content helpers for StackExchange pages."""

from __future__ import annotations

from urllib.parse import urlparse


def is_stackexchange_url(url: str) -> bool:
    """Return True for StackExchange network question URLs."""
    host = urlparse(url).netloc.lower()
    return host.endswith(".stackexchange.com") or host in {"stackoverflow.com", "serverfault.com", "superuser.com"}


def build_public_summary_fallback(title: str, url: str) -> str:
    """Build explicit fallback content when crawler access is blocked.

    This is intentionally labeled as a fallback summary, not complete article
    text, so downstream planning can distinguish source quality.
    """
    clean_title = (title or "StackExchange question").strip()
    return (
        "Source fallback: local crawler could not retrieve the full StackExchange page, "
        "so this record uses a public-page summary placeholder and the HN discussion as supporting context. "
        f"The source question is titled '{clean_title}' and is available at {url}. "
        "Treat this as partial public-page metadata rather than complete article body. "
        "Before publishing a detailed technical explanation, verify the source manually or replace this fallback "
        "with extracted StackPrinter/full page text."
    )
