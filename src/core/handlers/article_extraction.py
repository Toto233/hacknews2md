"""Shared result contract for first-party article extraction adapters."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArticleExtraction:
    """Captured article text, image candidates, and an optional failure reason."""

    content: str = ""
    image_urls: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None
    error: str | None = None
