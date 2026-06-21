"""Runtime context shared across all stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeContext:
    """Shared runtime context passed to all stages."""

    project_root: Path
    db_path: Path
    output_dir: Path
    job_dir: Path
    markdown_dir: Path
    images_dir: Path
    codex_dir: Path
    config_path: Path

    @classmethod
    def create(cls, project_root: Path | None = None) -> RuntimeContext:
        root = project_root or Path(__file__).resolve().parents[1]
        output = root / "output"
        return cls(
            project_root=root,
            db_path=root / "data" / "hacknews.db",
            output_dir=output,
            job_dir=output / "jobs",
            markdown_dir=output / "markdown",
            images_dir=output / "images",
            codex_dir=output / "codex",
            config_path=root / "config" / "config.json",
        )
