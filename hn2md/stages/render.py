"""Render stage: generate Markdown/HTML from database."""

from pathlib import Path
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage


class RenderStage(BaseStage):
    stage_name = Stage.RENDERING

    def execute(self, ctx: RuntimeContext, machine: JobStateMachine) -> dict[str, Any]:
        from src.core.generate_markdown import generate_markdown
        from src.utils.deployment import load_deployment_settings

        apply_receipt = machine.job.stages.get(Stage.APPLYING.value)
        plan_file = apply_receipt.get("output_summary", {}).get("plan_file") if apply_receipt else None
        if not plan_file:
            raise RuntimeError("No plan file from APPLYING stage")

        settings = load_deployment_settings(project_root=ctx.project_root)
        return generate_markdown(
            db_path=ctx.db_path,
            output_dir=ctx.markdown_dir,
            plan_file=Path(plan_file),
            astro_blog_dir=settings.astro_blog_dir,
        )
