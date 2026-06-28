from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PublisherContext:
    project_root: Path
    source: str
    period: str
    db_path: Path
    output_dir: Path
    job_dir: Path
    markdown_dir: Path
    images_dir: Path
    codex_dir: Path
    config_path: Path

    @classmethod
    def create(cls, project_root: Path | None, source: str, period: str) -> "PublisherContext":
        root = (project_root or Path.cwd()).resolve()
        output_dir = root / "output"
        return cls(
            project_root=root,
            source=source,
            period=period,
            db_path=root / "data" / "hacknews.db",
            output_dir=output_dir,
            job_dir=output_dir / "jobs",
            markdown_dir=output_dir / "markdown",
            images_dir=output_dir / "images",
            codex_dir=output_dir / "codex",
            config_path=root / "config" / "config.json",
        )


def parse_date_period(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%Y%m%d")
    cleaned = value.strip()
    if len(cleaned) == 8 and cleaned.isdigit():
        datetime.strptime(cleaned, "%Y%m%d")
        return cleaned
    parsed = datetime.strptime(cleaned, "%Y-%m-%d")
    return parsed.strftime("%Y%m%d")


def parse_month_period(year: int, month: int) -> str:
    if month < 1 or month > 12:
        raise ValueError(f"month must be 1-12, got {month}")
    return f"{year}{month:02d}"
