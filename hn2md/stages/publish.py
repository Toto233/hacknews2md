"""Publish stage: push to WeChat draft."""

import logging
import re
from pathlib import Path
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage
from hn2md.stages.script_loader import load_project_function

logger = logging.getLogger(__name__)


_LOCAL_IMAGE_PATTERNS = [
    r"!\[.*?\]\(([^)]+\.(?:jpg|jpeg|png|gif|webp))\)",
    r'<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\'][^>]*>',
    r'src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\']',
]
_WECHAT_IMAGE_LIMIT_BYTES = 1024 * 1024


def _find_skipped_local_images(markdown_content: str) -> list[dict[str, Any]]:
    """Preflight local images that WeChat upload will skip or cannot read."""
    found: set[str] = set()
    for pattern in _LOCAL_IMAGE_PATTERNS:
        found.update(re.findall(pattern, markdown_content, re.IGNORECASE))

    skipped: list[dict[str, Any]] = []
    for image in sorted(found):
        if image.startswith(("http://", "https://", "//", "data:")):
            continue
        image_path = Path(image)
        if not image_path.exists():
            skipped.append({"path": image, "reason": "missing"})
            continue
        size = image_path.stat().st_size
        if size > _WECHAT_IMAGE_LIMIT_BYTES:
            skipped.append(
                {
                    "path": str(image_path),
                    "reason": "oversize",
                    "limit_bytes": _WECHAT_IMAGE_LIMIT_BYTES,
                    "size_bytes": size,
                }
            )
    return skipped


class PublishStage(BaseStage):
    stage_name = Stage.PUBLISHING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        dry_run: bool = False,
        markdown_file: str | None = None,
        cover_image: str | None = None,
    ) -> dict[str, Any]:
        render_receipt = machine.job.stages.get(Stage.RENDERING.value)
        cover_receipt = machine.job.stages.get(Stage.COVERING.value)
        md_file = markdown_file or (
            render_receipt.get("output_summary", {}).get("markdown_file") if render_receipt else None
        )
        cover = cover_image or (
            cover_receipt.get("output_summary", {}).get("cover_image") if cover_receipt else None
        )
        if not md_file:
            raise RuntimeError("No markdown file")

        # --- Content safety gate ---
        # Check markdown content for illegal keywords before publishing
        md_path = Path(md_file)
        if md_path.exists():
            md_content = md_path.read_text(encoding="utf-8")
            skipped_images = _find_skipped_local_images(md_content)

            from src.utils.db_utils import check_illegal_content, get_illegal_keywords

            keywords = get_illegal_keywords()
            violations = check_illegal_content(md_content, keywords)

            if violations:
                violation_str = ", ".join(violations)
                raise RuntimeError(
                    f"Content safety gate BLOCKED publish: "
                    f"illegal keywords found: [{violation_str}]. "
                    f"Review content before publishing."
                )
            logger.info("[PUBLISH] Content safety check passed")

            # LLM output quality gate
            from src.security.content_sanitizer import contains_hallucination_markers

            if contains_hallucination_markers(md_content):
                logger.warning("[PUBLISH] Hallucination markers detected in content")
        else:
            skipped_images = []
            logger.warning(f"[PUBLISH] Markdown file not found: {md_file}")

        # --- Dry-run mode ---
        if dry_run:
            logger.info("[PUBLISH] DRY RUN — skipping WeChat draft creation")
            return {
                "wechat_media_id": None,
                "markdown_file": md_file,
                "dry_run": True,
                "safety_check": "passed",
                "skipped_images": skipped_images,
            }

        publish_to_wechat = load_project_function(ctx, "scripts.publish_wechat", "publish_to_wechat")
        media_id = publish_to_wechat(md_file, cover_image=cover)
        return {
            "wechat_media_id": str(media_id) if media_id else None,
            "markdown_file": md_file,
            "skipped_images": skipped_images,
        }
