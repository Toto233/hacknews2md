"""Cover stage: generate cover image."""

import json
from pathlib import Path
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage
from hn2md.stages.script_loader import load_project_function


def _create_share_preview(cover_path: Path) -> tuple[str | None, dict[str, int] | None]:
    """Create a centered square preview matching WeChat's 1:1 share crop."""
    try:
        from PIL import Image

        with Image.open(cover_path) as image:
            width, height = image.size
            side = min(width, height)
            left = (width - side) // 2
            top = (height - side) // 2
            preview_path = cover_path.with_name(f"{cover_path.stem}_share_1x1.png")
            image.crop((left, top, left + side, top + side)).save(preview_path, format="PNG")
    except OSError:
        return None, None
    return str(preview_path), {"width": width, "height": height}


def _lead_story(machine: JobStateMachine) -> dict[str, Any]:
    """Read the first planned story so cover generation follows article order."""
    render_receipt = machine.job.stages.get(Stage.RENDERING.value, {})
    apply_receipt = machine.job.stages.get(Stage.APPLYING.value, {})
    plan_file = (
        render_receipt.get("output_summary", {}).get("plan_file")
        or apply_receipt.get("output_summary", {}).get("plan_file")
    )
    if not plan_file:
        return {}
    try:
        plan = json.loads(Path(plan_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    ordered_ids = plan.get("ordered_ids")
    items = plan.get("items")
    if not isinstance(ordered_ids, list) or not ordered_ids or not isinstance(items, list):
        return {}
    lead_id = ordered_ids[0]
    lead_item = next((item for item in items if isinstance(item, dict) and item.get("id") == lead_id), None)
    if not isinstance(lead_item, dict):
        return {"lead_story_id": lead_id}
    return {
        "lead_story_id": lead_id,
        "lead_story_title": lead_item.get("title_chs") or lead_item.get("title"),
    }


class CoverStage(BaseStage):
    stage_name = Stage.COVERING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        markdown_file: str | None = None,
        mode: str = "ai",
        target_word: str | None = None,
        display_title: str | None = None,
        cover_image: str | None = None,
    ) -> dict[str, Any]:
        render_receipt = machine.job.stages.get(Stage.RENDERING.value)
        md_file = markdown_file or (
            render_receipt.get("output_summary", {}).get("markdown_file") if render_receipt else None
        )
        if not md_file:
            raise RuntimeError("No markdown file from RENDERING stage")
        lead_story = _lead_story(machine)
        display_title = display_title or target_word or lead_story.get("lead_story_title")

        if mode == "external":
            if not cover_image:
                raise RuntimeError("External cover image path is required")
            cover_path = Path(cover_image)
            if not cover_path.exists():
                raise RuntimeError(f"External cover image not found: {cover_image}")
            preview_path, cover_dimensions = _create_share_preview(cover_path)
            return self._receipt(cover_path, mode, display_title, lead_story, preview_path, cover_dimensions)
        if mode == "ai":
            generate_cover_ai = load_project_function(
                ctx,
                "scripts.generate_wechat_cover_ai",
                "generate_cover_ai",
            )
            cover_path = generate_cover_ai(md_file, target_word=display_title)
        elif mode == "pillow":
            generate_cover = load_project_function(
                ctx,
                "scripts.generate_wechat_cover",
                "generate_cover",
            )
            cover_path = generate_cover(md_file)
        else:
            raise ValueError(f"Unsupported cover mode: {mode}")
        path = Path(cover_path) if cover_path else None
        preview_path, cover_dimensions = _create_share_preview(path) if path else (None, None)
        return self._receipt(path, mode, display_title, lead_story, preview_path, cover_dimensions)

    @staticmethod
    def _receipt(
        cover_path: Path | None,
        mode: str,
        display_title: str | None,
        lead_story: dict[str, Any],
        preview_path: str | None,
        cover_dimensions: dict[str, int] | None,
    ) -> dict[str, Any]:
        return {
            "cover_image": str(cover_path) if cover_path else None,
            "mode": mode,
            # target_word remains for older consumers of the stage receipt.
            "target_word": display_title,
            "display_title": display_title,
            "share_preview_image": preview_path,
            "share_preview_crop": "center_1x1",
            "cover_dimensions": cover_dimensions,
            **lead_story,
        }
