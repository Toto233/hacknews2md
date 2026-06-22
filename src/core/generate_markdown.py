"""Generate Markdown/HTML/Astro artifacts from an explicit publishing plan."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.db.connection import get_db
from src.integrations.markdown_to_html_converter import convert_markdown_to_html
from src.security.content_sanitizer import quote_yaml_scalar, sanitize_for_yaml

logger = logging.getLogger(__name__)

# Compatibility alias; implementation is centralized in content_sanitizer.
yaml_quote = quote_yaml_scalar


def copy_images_to_astro(image_paths, astro_images_dir):
    """Copy dated local images into Astro public/images and return mappings."""
    path_mapping = {}
    for abs_path in image_paths:
        if not abs_path or not os.path.exists(abs_path):
            continue
        parts = abs_path.replace("/", "\\").split("\\")
        try:
            images_idx = parts.index("images")
            date_dir = parts[images_idx + 1]
            filename = parts[images_idx + 2]
        except (ValueError, IndexError):
            continue
        dest_dir = os.path.join(astro_images_dir, date_dir)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, filename)
        shutil.copy2(abs_path, dest_path)
        path_mapping[abs_path] = f"/images/{date_dir}/{filename}"
    return path_mapping


def cleanup_old_astro_images(astro_images_dir, days=10):
    """Remove dated Astro image directories older than the retention window."""
    if not os.path.exists(astro_images_dir):
        return
    cutoff_str = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    for name in os.listdir(astro_images_dir):
        dir_path = os.path.join(astro_images_dir, name)
        if os.path.isdir(dir_path) and re.match(r"^\d{8}$", name) and name < cutoff_str:
            shutil.rmtree(dir_path)
            logger.info("Cleaned up old Astro images: %s", dir_path)


def _load_rows(db_path: Path, ordered_ids: list[int]) -> list[tuple[Any, ...]]:
    rows = []
    with get_db(str(db_path)) as conn:
        for news_id in ordered_ids:
            row = conn.execute(
                "SELECT id, title, title_chs, news_url, discuss_url, content_summary, "
                "discuss_summary, largest_image, image_2, image_3, screenshot "
                "FROM news WHERE id = ?",
                (news_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"ordered_ids contains unknown news id: {news_id}")
            rows.append(row)
    return rows


def generate_markdown(
    *,
    db_path: Path,
    output_dir: Path,
    plan_file: Path,
    astro_blog_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, str | None]:
    """Render artifacts in the exact order and tags supplied by a plan."""
    plan_path = Path(plan_file).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    ordered_ids = plan.get("ordered_ids")
    tags = plan.get("tags")
    if not isinstance(ordered_ids, list) or not ordered_ids:
        raise ValueError("plan ordered_ids must be a non-empty list")
    if not isinstance(tags, list) or len(tags) != 4:
        raise ValueError("plan must contain exactly four tags")

    rows = _load_rows(Path(db_path), ordered_ids)
    current = now or datetime.now()
    first = rows[0]
    prefix = sanitize_for_yaml(first[2] or first[1] or "")
    suffix = f" | Hacker News 摘要 ({current.strftime('%Y-%m-%d')})"
    prefix = prefix[: max(0, 64 - len(suffix))]
    title = prefix + suffix
    digest = (first[5] or "")[:120]
    pub_datetime = current.strftime("%Y-%m-%d %H:%M:%S") + f".{int(current.microsecond / 1000):03d}+08:00"

    parts = [
        "---\n",
        f"title: {quote_yaml_scalar(title)}\n",
        f"author: {quote_yaml_scalar('hacknews')}\n",
        f"description: {quote_yaml_scalar('')}\n",
        f"digest: {quote_yaml_scalar(digest)}\n",
        f"source_url: {quote_yaml_scalar(first[3] or '')}\n",
        f"pubDatetime: {pub_datetime}\n",
        "tags:\n",
    ]
    parts.extend(f"  - {quote_yaml_scalar(tag)}\n" for tag in tags)
    parts.append("---\n\n")

    for index, row in enumerate(rows, 1):
        _, title_en, title_chs, news_url, discuss_url, summary, discussion, largest, image_2, image_3, screenshot = row
        safe_title_chs = sanitize_for_yaml(title_chs or "")
        safe_title_en = sanitize_for_yaml(title_en or "")
        display_title = f"{safe_title_chs} ({safe_title_en})" if safe_title_chs else safe_title_en
        parts.extend(["---\n\n", f"## {index}. {display_title}\n\n"])
        for image in (screenshot, largest, image_2, image_3):
            if image:
                parts.append(f"![{safe_title_chs or safe_title_en}]({image})\n\n")
        parts.extend([f"{summary or ''}\n\n", f"原文链接：{news_url or ''}\n\n"])
        if discuss_url:
            parts.append(f"论坛讨论链接：{discuss_url}\n\n")
            if discussion:
                parts.append(f"{discussion}\n\n")

    markdown = "".join(parts)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = current.strftime("%Y%m%d_%H%M")
    md_path = output_dir / f"hacknews_summary_{stamp}.md"
    html_path = output_dir / f"hacknews_summary_{stamp}.html"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(convert_markdown_to_html(markdown), encoding="utf-8")

    astro_path = None
    if astro_blog_dir:
        astro_dir = Path(astro_blog_dir)
        astro_dir.mkdir(parents=True, exist_ok=True)
        astro_path = astro_dir / md_path.name
        astro_lines = [
            line
            for line in markdown.splitlines()
            if not (line.startswith("![") and (":\\" in line or line.startswith("![/")))
        ]
        astro_path.write_text("\n".join(astro_lines) + "\n", encoding="utf-8")

    return {
        "markdown_file": str(md_path),
        "html_file": str(html_path),
        "astro_file": str(astro_path) if astro_path else None,
        "plan_file": str(plan_path),
    }
