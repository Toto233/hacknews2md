"""Recover an HN /front selection using browser-observed item IDs and the official API."""

from __future__ import annotations

import requests

from src.core.fetch_news import (
    MAX_NEWS_ITEMS,
    extract_domain,
    is_domain_filtered,
    is_url_in_history,
)
from src.db.connection import get_db
from src.security.url_validator import SecurityError, validate_url


def fetch_browser_front_ids(raw_ids: str) -> list[dict[str, str]]:
    """Resolve ordered /front IDs through HN's API, retaining normal filters."""
    ids = [part.strip() for part in raw_ids.split(",")]
    if not 10 <= len(ids) <= 30 or len(set(ids)) != len(ids):
        raise ValueError("front IDs must contain 10-30 unique HN item IDs")
    if any(not item_id.isascii() or not item_id.isdecimal() for item_id in ids):
        raise ValueError("front IDs must be decimal HN item IDs")

    selected: list[dict[str, str]] = []
    with get_db() as conn:
        cursor = conn.cursor()
        for item_id in ids:
            if len(selected) >= MAX_NEWS_ITEMS:
                break
            api_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            item = response.json()
            if not isinstance(item, dict) or str(item.get("id")) != item_id or item.get("type") != "story":
                raise ValueError(f"HN API returned an unexpected item for {item_id}")
            title = item.get("title")
            if not isinstance(title, str) or not title.strip() or title.startswith("Ask HN:"):
                continue
            discussion = f"https://news.ycombinator.com/item?id={item_id}"
            news_url = item.get("url") or discussion
            if not isinstance(news_url, str):
                continue
            try:
                validate_url(news_url)
            except (SecurityError, ValueError):
                continue
            if is_url_in_history(news_url, cursor):
                continue
            domain = extract_domain(news_url)
            if domain and is_domain_filtered(domain, cursor):
                continue
            selected.append({"title": title.strip(), "news_url": news_url, "discuss_url": discussion})
    return selected
