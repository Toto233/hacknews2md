from __future__ import annotations

from publisher.sources.base import SourceDefinition
from publisher.sources.hackernews import HACKERNEWS_SOURCE
from publisher.sources.producthunt import PRODUCTHUNT_SOURCE

_SOURCES = {
    HACKERNEWS_SOURCE.name: HACKERNEWS_SOURCE,
    PRODUCTHUNT_SOURCE.name: PRODUCTHUNT_SOURCE,
}


def list_sources() -> list[str]:
    return sorted(_SOURCES)


def get_source(name: str) -> SourceDefinition:
    try:
        return _SOURCES[name]
    except KeyError as exc:
        raise KeyError(f"unknown publisher source: {name}") from exc
