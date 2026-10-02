from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path = Path(".")

    @property
    def data_dir(self) -> Path:
        return self.root / "data" / "producthunt"

    @property
    def output_dir(self) -> Path:
        return self.root / "output" / "producthunt"

    @property
    def receipts_dir(self) -> Path:
        return self.output_dir / "receipts"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "producthunt.db"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)

    def plan_path(self, year: int, month: int) -> Path:
        return self.output_dir / "codex" / f"producthunt_plan_{year}{month:02d}.json"

    def markdown_path(self, year: int, month: int) -> Path:
        return self.output_dir / "markdown" / f"producthunt_monthly_{year}{month:02d}_wechat.md"

    def cover_path(self, year: int, month: int) -> Path:
        return self.output_dir / "images" / f"{year}{month:02d}" / f"producthunt_cover_{year}{month:02d}.png"
