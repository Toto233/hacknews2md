from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Product:
    year: int
    month: int
    rank: int
    name: str
    producthunt_url: str
    slug: str | None = None
    tagline: str | None = None
    official_url: str | None = None
    thumbnail_url: str | None = None
    votes: int | None = None
    comments: int | None = None
    categories: list[str] = field(default_factory=list)
    source: str = "leaderboard"


@dataclass(frozen=True)
class FetchResult:
    year: int
    month: int
    url: str
    products: list[Product]
    warnings: list[dict[str, str]] = field(default_factory=list)
