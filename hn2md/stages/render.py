"""Render stage: generate Markdown/HTML from database."""

from hn2md.constants import Stage
from hn2md.stages.base import BaseStage


class RenderStage(BaseStage):
    stage_name = Stage.RENDERING

    def execute(self, ctx, machine):
        from src.core.generate_markdown import generate_markdown

        md_file = generate_markdown()
        if not md_file:
            raise RuntimeError("generate_markdown() returned no file path")

        return {"markdown_file": str(md_file)}
