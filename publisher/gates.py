from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class GateResult:
    ok: bool
    warnings: list[dict[str, Any]] = field(default_factory=list)


def check_markdown_artifact(path: Path) -> GateResult:
    if not path.exists():
        return GateResult(False, [{"reason": "markdown_missing", "path": str(path)}])
    if path.stat().st_size == 0:
        return GateResult(False, [{"reason": "markdown_empty", "path": str(path)}])
    return GateResult(True, [])


def check_local_image_limits(paths: Iterable[Path], limit_bytes: int) -> GateResult:
    warnings: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            warnings.append({"reason": "image_missing", "path": str(path)})
            continue
        size = path.stat().st_size
        if size > limit_bytes:
            warnings.append(
                {
                    "reason": "image_oversize",
                    "path": str(path),
                    "size_bytes": size,
                    "limit_bytes": limit_bytes,
                }
            )
    return GateResult(not warnings, warnings)
