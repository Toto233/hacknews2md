from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from publisher.producthunt.models import Product

PRODUCTHUNT_BASE = "https://www.producthunt.com"


def parse_leaderboard_html(html: str, year: int, month: int, limit: int) -> list[Product]:
    products = _parse_next_data(html, year, month)
    if not products:
        products = _parse_html_fallback(html, year, month)
    return products[:limit]


def _parse_next_data(html: str, year: int, month: int) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return []
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    candidates = [item for item in _walk_dicts(data) if _looks_like_product(item)]
    seen: set[str] = set()
    products: list[Product] = []
    for item in candidates:
        product = _product_from_mapping(item, year, month, len(products) + 1)
        if product.producthunt_url in seen:
            continue
        seen.add(product.producthunt_url)
        products.append(product)
    return products


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _looks_like_product(item: dict[str, Any]) -> bool:
    if not isinstance(item.get("name"), str):
        return False
    url = item.get("url") or item.get("producthuntUrl") or item.get("producthunt_url")
    slug = item.get("slug")
    return isinstance(url, str) or isinstance(slug, str)


def _product_from_mapping(item: dict[str, Any], year: int, month: int, fallback_rank: int) -> Product:
    url = item.get("url") or item.get("producthuntUrl") or item.get("producthunt_url")
    slug = _clean_text(item.get("slug"))
    producthunt_url = _normalize_producthunt_url(url or f"/products/{slug or item['name']}")
    return Product(
        year=year,
        month=month,
        rank=_to_int(item.get("rank")) or fallback_rank,
        name=_clean_text(item["name"]) or "Untitled",
        slug=slug,
        tagline=_clean_text(item.get("tagline") or item.get("description")),
        producthunt_url=producthunt_url,
        thumbnail_url=_extract_thumbnail(item),
        votes=_to_int(item.get("votesCount") or item.get("votes")),
        comments=_to_int(item.get("commentsCount") or item.get("comments")),
        categories=_extract_categories(item),
    )


def _parse_html_fallback(html: str, year: int, month: int) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("section[data-container], article[data-test='post-item'], article, [data-test='post-item']")
    products: list[Product] = []
    for index, card in enumerate(cards, start=1):
        link = card.find("a", href=re.compile(r"/products/"))
        if not link:
            continue
        _display_rank, name = _rank_and_name(link.get_text(" ", strip=True), index)
        text = card.get_text(" ", strip=True)
        products.append(
            Product(
                year=year,
                month=month,
                rank=index,
                name=name,
                slug=_slug_from_url(link.get("href", "")),
                tagline=_extract_card_tagline(card, link),
                producthunt_url=_normalize_producthunt_url(link.get("href", "")),
                thumbnail_url=_extract_card_thumbnail(card, name),
                votes=_extract_vote_count(card) or _metric(text, "votes"),
                comments=_extract_comment_count(card) or _metric(text, "comments"),
                categories=_extract_card_categories(card),
            )
        )
    return products


def _extract_categories(item: dict[str, Any]) -> list[str]:
    raw = item.get("topics") or item.get("categories") or []
    categories: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, str):
                categories.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
                categories.append(entry["name"])
    return categories


def _extract_thumbnail(item: dict[str, Any]) -> str | None:
    raw = item.get("thumbnail") or item.get("thumbnailUrl") or item.get("image")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        value = raw.get("url") or raw.get("src")
        return value if isinstance(value, str) else None
    return None


def _normalize_producthunt_url(url: str) -> str:
    return urljoin(PRODUCTHUNT_BASE, url)


def _slug_from_url(url: str) -> str | None:
    match = re.search(r"/products/([^/?#]+)", url)
    return match.group(1) if match else None


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _to_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"\d[\d,]*", value)
        if match:
            return int(match.group(0).replace(",", ""))
    return None


def _metric(text: str, label: str) -> int | None:
    match = re.search(rf"(\d[\d,]*)\s+{re.escape(label)}", text, flags=re.IGNORECASE)
    return int(match.group(1).replace(",", "")) if match else None


def _rank_and_name(text: str, fallback_rank: int) -> tuple[int, str]:
    match = re.match(r"\s*(\d+)\.\s*(.+?)\s*$", text)
    if not match:
        return fallback_rank, text
    return int(match.group(1)), match.group(2)


def _extract_card_tagline(card: Any, product_link: Any) -> str | None:
    current = product_link.find_parent("span")
    if current:
        sibling = current.find_next_sibling("span")
        if sibling:
            text = sibling.get_text(" ", strip=True)
            if text:
                return text
    paragraph = card.find("p")
    return paragraph.get_text(" ", strip=True) if paragraph else None


def _extract_card_categories(card: Any) -> list[str]:
    categories: list[str] = []
    for link in card.find_all("a", href=re.compile(r"^/topics/")):
        text = link.get_text(" ", strip=True)
        if text:
            categories.append(text)
    return categories


def _extract_card_thumbnail(card: Any, name: str) -> str | None:
    preferred = card.find("img", alt=name)
    image = preferred or card.find("img")
    if not image:
        return None
    src = image.get("src")
    if isinstance(src, str):
        return src
    srcset = image.get("srcset") or image.get("srcSet")
    if isinstance(srcset, str) and srcset.strip():
        return srcset.split()[0]
    return None


def _extract_vote_count(card: Any) -> int | None:
    button = card.find(attrs={"data-test": "vote-button"})
    return _to_int(button.get_text(" ", strip=True)) if button else None


def _extract_comment_count(card: Any) -> int | None:
    buttons = card.find_all("button")
    for button in buttons:
        if button.get("data-test") == "vote-button":
            continue
        value = _to_int(button.get_text(" ", strip=True))
        if value is not None:
            return value
    return None
