from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from publisher.constants import GenericStage


PeriodKind = Literal["date", "month"]
StageFactory = Callable[[], Any]


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    period_kind: PeriodKind
    stages: dict[GenericStage, type[Any] | StageFactory] = field(default_factory=dict)
    stage_order: tuple[GenericStage, ...] = ()
    required_artifacts: dict[GenericStage, tuple[str, ...]] = field(default_factory=dict)
    default_publish_targets: tuple[str, ...] = ("wechat", "astro")
    enabled: bool = True


def validate_source_definition(source: SourceDefinition) -> list[str]:
    """Validate the declarative source contract.

    Disabled sources may be placeholders, so an empty stage contract is valid.
    Enabled sources must declare an explicit stage order and matching factories.
    """
    errors: list[str] = []

    if source.enabled and not source.stage_order:
        errors.append("enabled source must declare stage_order")

    seen: set[GenericStage] = set()
    for stage in source.stage_order:
        if stage in seen:
            errors.append(f"stage_order contains duplicate stage: {stage.value}")
            continue
        seen.add(stage)
        if stage not in source.stages:
            errors.append(f"stage_order contains unregistered stage: {stage.value}")

    for stage, artifact_names in source.required_artifacts.items():
        if stage not in source.stage_order:
            errors.append(f"required_artifacts references stage outside stage_order: {stage.value}")
        for artifact_name in artifact_names:
            if not isinstance(artifact_name, str) or not artifact_name.strip():
                errors.append(f"required_artifacts contains invalid artifact name for stage: {stage.value}")

    return errors
