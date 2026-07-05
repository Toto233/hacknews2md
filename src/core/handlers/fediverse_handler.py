"""Fediverse/Mastodon content handler.

Fetches public ActivityPub Note JSON when possible and falls back to public
HTML metadata. This intentionally avoids Selenium because Mastodon-like pages
often render a JavaScript shell while still exposing ActivityPub JSON.
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from src.security.url_validator import SecurityError, validate_url

logger = logging.getLogger(__name__)

_KNOWN_FEDIVERSE_HOST_PARTS = (
    "mastodon",
    "mathstodon",
    "mstdn",
    "fosstodon",
    "hachyderm",
    "infosec.exchange",
)


def is_fediverse_url(url: str) -> bool:
    """Return True for common public Fediverse status URL shapes."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    path = parsed.path
    if any(part in host for part in _KNOWN_FEDIVERSE_HOST_PARTS):
        return True
    return bool(re.search(r"/@[^/]+/\d+", path) or re.search(r"/users/[^/]+/statuses/\d+", path))


def _strip_html(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def extract_activitypub_note(data: dict[str, Any], source_url: str) -> str:
    """Extract publishable plain text from an ActivityPub Note object."""
    content = data.get("content")
    if not isinstance(content, str):
        return ""
    body = _strip_html(content)
    if not body:
        return ""

    metadata: list[str] = []
    author = data.get("attributedTo") or data.get("actor")
    if isinstance(author, str) and author:
        metadata.append(f"Author: {author}")
    published = data.get("published")
    if isinstance(published, str) and published:
        metadata.append(f"Published: {published}")
    canonical_url = data.get("url") if isinstance(data.get("url"), str) else source_url
    if canonical_url:
        metadata.append(f"URL: {canonical_url}")
    if metadata:
        return "\n".join(metadata) + "\n\n" + body
    return body


def extract_alternate_activitypub_url(page_html: str, page_url: str) -> str:
    """Find a public ActivityPub alternate URL from a rendered HTML shell."""
    for match in re.finditer(r"<link\b[^>]*>", page_html, flags=re.IGNORECASE):
        tag = match.group(0)
        if not re.search(r'rel=["\'][^"\']*\balternate\b', tag, flags=re.IGNORECASE):
            continue
        if not re.search(r'type=["\']application/(?:activity|ld)\+json', tag, flags=re.IGNORECASE):
            continue
        href_match = re.search(r'href=["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        if href_match:
            return urljoin(page_url, html.unescape(href_match.group(1)))
    return ""


def extract_html_metadata_summary(page_html: str) -> str:
    """Extract a public metadata description from an HTML page."""
    patterns = (
        r'<meta\b[^>]*(?:property|name)=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta\b[^>]*content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:description["\']',
        r'<meta\b[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta\b[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


async def _fetch_text(url: str, accept: str) -> tuple[int, str, str]:
    import aiohttp

    headers = {
        "Accept": accept,
        "User-Agent": "hn2md/1.0 (+https://github.com/Toto233/hacknews2md)",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
            return response.status, await response.text(), response.headers.get("content-type", "")


def _parse_json_text(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


async def get_fediverse_content(url: str) -> tuple[str, str]:
    """Fetch public Fediverse content.

    Returns:
        (content, source_type), where source_type is ``full_text`` for
        ActivityPub Note content and ``public_metadata_summary`` for HTML
        metadata fallback.
    """
    if not url:
        return "", ""
    try:
        validate_url(url)
    except (SecurityError, ValueError) as exc:
        logger.warning("fediverse_url_validation_failed error=%s url=%s", exc, url[:80])
        return "", ""

    try:
        status, text, content_type = await _fetch_text(url, "application/activity+json, application/ld+json;q=0.9, text/html;q=0.8")
    except Exception as exc:
        logger.warning("fediverse_fetch_failed error=%s url=%s", exc, url[:80])
        return "", ""

    if status != 200 or not text:
        return "", ""

    if "json" in content_type.lower() or text.lstrip().startswith("{"):
        note = _parse_json_text(text)
        if note:
            content = extract_activitypub_note(note, url)
            if content:
                return content, "full_text"

    alternate_url = extract_alternate_activitypub_url(text, url)
    if alternate_url:
        try:
            alt_status, alt_text, _ = await _fetch_text(alternate_url, "application/activity+json, application/ld+json")
            if alt_status == 200:
                note = _parse_json_text(alt_text)
                if note:
                    content = extract_activitypub_note(note, url)
                    if content:
                        return content, "full_text"
        except Exception as exc:
            logger.warning("fediverse_activitypub_alternate_fetch_failed error=%s url=%s", exc, alternate_url[:80])

    summary = extract_html_metadata_summary(text)
    if summary:
        return summary, "public_metadata_summary"
    return "", ""
