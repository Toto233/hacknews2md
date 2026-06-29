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
    r"!\[.*?\]\(([^)]+\.(?:jpg|jpeg|png|gif|webp|svg))\)",
    r'<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp|svg))["\'][^>]*>',
    r'src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp|svg))["\']',
]
_WECHAT_IMAGE_LIMIT_BYTES = 1024 * 1024
_WECHAT_SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _keyword_locations(markdown_content: str, keywords: list[str], markdown_file: str) -> list[dict[str, Any]]:
    """Return line-level context for blocked publish keywords."""
    lines = markdown_content.splitlines()
    locations: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        for keyword in keywords:
            if keyword in line:
                locations.append(
                    {
                        "keyword": keyword,
                        "path": markdown_file,
                        "line": line_number,
                        "context": line.strip()[:240],
                    }
                )
    return locations


def _format_keyword_gate_error(violations: list[str], markdown_file: str, locations: list[dict[str, Any]]) -> str:
    details = "; ".join(
        f"{item['keyword']} at {item['path']} line {item['line']}: {item['context']}" for item in locations[:10]
    )
    if not details:
        details = f"file={markdown_file}"
    violation_str = ", ".join(violations)
    return (
        "Content safety gate BLOCKED publish: "
        f"illegal keywords found: [{violation_str}]. "
        f"Locations: {details}. Review content before publishing."
    )


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
        suffix = image_path.suffix.lower()
        if suffix not in _WECHAT_SUPPORTED_IMAGE_SUFFIXES:
            skipped.append(
                {
                    "path": str(image_path),
                    "reason": "unsupported_format",
                    "supported_formats": ["jpg", "jpeg", "png", "webp"],
                    "suffix": suffix,
                }
            )
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


def _compress_image_for_wechat(image_path: Path) -> Path | None:
    """Create a <=1MB JPEG copy for WeChat when possible."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("[PUBLISH] Pillow unavailable; cannot compress image: %s", image_path)
        return None

    target = image_path.with_name(f"{image_path.stem}_wechat.jpg")
    try:
        with Image.open(image_path) as image:
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, (255, 255, 255))
                alpha = image.getchannel("A")
                background.paste(image.convert("RGBA"), mask=alpha)
                work = background
            else:
                work = image.convert("RGB")

            for scale in (1.0, 0.85, 0.7, 0.55, 0.4):
                resized = work
                if scale != 1.0:
                    width = max(1, int(work.width * scale))
                    height = max(1, int(work.height * scale))
                    resized = work.resize((width, height), Image.Resampling.LANCZOS)
                for quality in (85, 75, 65, 55, 45):
                    resized.save(target, format="JPEG", quality=quality, optimize=True)
                    if target.stat().st_size <= _WECHAT_IMAGE_LIMIT_BYTES:
                        return target
    except Exception as exc:
        logger.warning("[PUBLISH] Failed to compress image %s: %s", image_path, exc)
        return None
    return None


def _rewrite_oversize_images_for_wechat(markdown_content: str, markdown_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Rewrite valid oversized local image references to compressed JPEG copies."""
    compressed: list[dict[str, Any]] = []
    rewritten = markdown_content
    for skipped in _find_skipped_local_images(markdown_content):
        if skipped.get("reason") != "oversize":
            continue
        original = Path(str(skipped["path"]))
        compressed_path = _compress_image_for_wechat(original)
        if not compressed_path:
            continue
        rewritten = rewritten.replace(str(original), str(compressed_path))
        compressed.append(
            {
                "original_path": str(original),
                "compressed_path": str(compressed_path),
                "original_size_bytes": skipped.get("size_bytes"),
                "compressed_size_bytes": compressed_path.stat().st_size,
            }
        )
    if compressed and rewritten != markdown_content:
        markdown_path.write_text(rewritten, encoding="utf-8")
    return rewritten, compressed


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
            md_content, compressed_images = _rewrite_oversize_images_for_wechat(md_content, md_path)
            skipped_images = _find_skipped_local_images(md_content)

            from src.utils.db_utils import check_illegal_content, get_illegal_keywords

            keywords = get_illegal_keywords()
            violations = check_illegal_content(md_content, keywords)

            if violations:
                locations = _keyword_locations(md_content, violations, md_file)
                raise RuntimeError(_format_keyword_gate_error(violations, md_file, locations))
            logger.info("[PUBLISH] Content safety check passed")

            # LLM output quality gate
            from src.security.content_sanitizer import contains_hallucination_markers

            if contains_hallucination_markers(md_content):
                logger.warning("[PUBLISH] Hallucination markers detected in content")
        else:
            skipped_images = []
            compressed_images = []
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
                "compressed_images": compressed_images,
            }

        publish_to_wechat = load_project_function(ctx, "scripts.publish_wechat", "publish_to_wechat")
        media_id = publish_to_wechat(md_file, cover_image=cover)
        return {
            "wechat_media_id": str(media_id) if media_id else None,
            "markdown_file": md_file,
            "skipped_images": skipped_images,
            "compressed_images": compressed_images,
        }
