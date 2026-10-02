from __future__ import annotations

from publisher.sources.base import SourceDefinition


def list_sources() -> list[str]:
    return ["hackernews"]


def get_source(name: str) -> SourceDefinition:
    if name == "hackernews":
        from publisher.sources.hackernews import HACKERNEWS_SOURCE

        return HACKERNEWS_SOURCE
    if name == "producthunt":
        raise KeyError("Product Hunt uses the ph2md editorial application; run ph2md --help")
    raise KeyError(f"unknown publisher source: {name}")
