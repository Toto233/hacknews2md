"""Cover stage: generate cover image."""

from typing import Any
from pathlib import Path

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage
from hn2md.stages.script_loader import load_project_function


class CoverStage(BaseStage):
    stage_name = Stage.COVERING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        markdown_file: str | None = None,
        mode: str = "ai",
        target_word: str | None = None,
        cover_image: str | None = None,
    ) -> dict[str, Any]:
        render_receipt = machine.job.stages.get(Stage.RENDERING.value)
        md_file = markdown_file or (
            render_receipt.get("output_summary", {}).get("markdown_file") if render_receipt else None
        )
        if not md_file:
            raise RuntimeError("No markdown file from RENDERING stage")

        if mode == "external":
            if not cover_image:
                raise RuntimeError("External cover image path is required")
            cover_path = Path(cover_image)
            if not cover_path.exists():
                raise RuntimeError(f"External cover image not found: {cover_image}")
            return {
                "cover_image": str(cover_path),
                "mode": "external",
                "target_word": target_word,
            }
        if mode == "ai":
            generate_cover_ai = load_project_function(
                ctx,
                "scripts.generate_wechat_cover_ai",
                "generate_cover_ai",
            )
            cover_path = generate_cover_ai(md_file, target_word=target_word)
        elif mode == "pillow":
            generate_cover = load_project_function(
                ctx,
                "scripts.generate_wechat_cover",
                "generate_cover",
            )
            cover_path = generate_cover(md_file)
        else:
            raise ValueError(f"Unsupported cover mode: {mode}")
        return {
            "cover_image": str(cover_path) if cover_path else None,
            "mode": mode,
            "target_word": target_word,
        }
