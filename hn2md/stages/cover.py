"""Cover stage: generate cover image."""

from hn2md.constants import Stage
from hn2md.stages.base import BaseStage


class CoverStage(BaseStage):
    stage_name = Stage.COVERING

    def execute(self, ctx, machine):
        render_receipt = machine.job.stages.get(Stage.RENDERING.value)
        md_file = render_receipt.get("output_summary", {}).get("markdown_file") if render_receipt else None
        if not md_file:
            raise RuntimeError("No markdown file from RENDERING stage")

        from scripts.generate_wechat_cover_ai import main as generate_cover

        # The cover script expects markdown file as argument
        cover_path = generate_cover(md_file)
        return {"cover_image": str(cover_path) if cover_path else None}
