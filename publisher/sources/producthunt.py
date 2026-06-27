from __future__ import annotations

from publisher.sources.base import SourceDefinition


PRODUCTHUNT_SOURCE = SourceDefinition(
    name="producthunt",
    period_kind="month",
    stages={},
    enabled=False,
)
