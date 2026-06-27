from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from publisher.constants import GenericStage


PeriodKind = Literal["date", "month"]


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    period_kind: PeriodKind
    stages: dict[GenericStage, type[Any]] = field(default_factory=dict)
    default_publish_targets: tuple[str, ...] = ("wechat", "astro")
    enabled: bool = True
