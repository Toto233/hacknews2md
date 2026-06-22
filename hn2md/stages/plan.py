"""Plan stage: generate summaries via LLM, output plan JSON."""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage
from src.db.connection import get_db
from src.security.content_sanitizer import (
    contains_hallucination_markers,
    validate_summary_length,
)

logger = logging.getLogger(__name__)


def _validate_manual_plan(plan: object) -> dict[str, Any]:
    """Validate and normalize a Codex-authored publishing plan."""
    if not isinstance(plan, dict):
        raise ValueError("manual plan must be a JSON object")

    items = plan.get("items")
    ordered_ids = plan.get("ordered_ids")
    tags = plan.get("tags")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")
    if not isinstance(ordered_ids, list):
        raise ValueError("ordered_ids must be a list")
    if not isinstance(tags, list) or len(tags) != 4:
        raise ValueError("manual plan must contain exactly four tags")

    normalized_tags = [str(tag).strip() for tag in tags]
    if any(not tag for tag in normalized_tags) or len(set(normalized_tags)) != 4:
        raise ValueError("manual plan must contain four unique non-empty tags")

    normalized_items: list[dict[str, Any]] = []
    item_ids: list[int] = []
    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            raise ValueError(f"items[{index}] must be an object")
        news_id = raw_item.get("id")
        if not isinstance(news_id, int) or isinstance(news_id, bool):
            raise ValueError(f"items[{index}].id must be an integer")
        if news_id in item_ids:
            raise ValueError(f"duplicate item id: {news_id}")

        normalized = {"id": news_id}
        for field in ("title_chs", "content_summary", "discuss_summary"):
            value = raw_item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"items[{index}].{field} must be non-empty")
            value = value.strip()
            if contains_hallucination_markers(value):
                raise ValueError(f"hallucination marker in items[{index}].{field}")
            normalized[field] = value

        length_errors = validate_summary_length(
            normalized["content_summary"],
            min_length=20,
            field_name=f"items[{index}].content_summary",
        )
        if length_errors:
            raise ValueError("content_summary: " + "; ".join(length_errors))

        item_ids.append(news_id)
        normalized_items.append(normalized)

    if len(ordered_ids) != len(item_ids) or set(ordered_ids) != set(item_ids):
        raise ValueError("ordered_ids must contain every item id exactly once")

    return {
        "tags": normalized_tags,
        "ordered_ids": ordered_ids,
        "items": normalized_items,
    }


def _import_manual_plan(source: Path, destination_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Validate a manual plan and copy it atomically into the run artifacts."""
    try:
        plan = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manual plan: {exc}") from exc

    normalized = _validate_manual_plan(plan)
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = destination_dir / f"hacknews_plan_{stamp}.json"
    temp_path = destination.with_suffix(".tmp")
    temp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, destination)
    return destination, normalized


class PlanStage(BaseStage):
    stage_name = Stage.PLANNING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        llm: str | None = None,
        manual_plan_file: str | None = None,
    ) -> dict[str, Any]:
        if manual_plan_file:
            plan_path, plan = _import_manual_plan(Path(manual_plan_file), ctx.codex_dir)
            return {
                "plan_file": str(plan_path),
                "story_count": len(plan["items"]),
                "tags": plan["tags"],
                "validation_warnings": 0,
                "hallucination_detected": False,
                "short_content": False,
                "manual": True,
            }

        from src.llm.llm_business import generate_summary, translate_title
        from src.llm.llm_evaluator import evaluate_news_attraction
        from src.llm.llm_tag_extractor import extract_tags_with_llm
        with get_db(str(ctx.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT id, title, title_chs, news_url, discuss_url, "
                "article_content, discussion_content, content_summary, discuss_summary "
                "FROM news WHERE date(created_at)=date('now','localtime') ORDER BY id"
            )
            rows = cur.fetchall()

        items = []
        validation_warnings = []
        for row in rows:
            summary = row["content_summary"] or ""
            if not summary and row["article_content"]:
                summary = generate_summary(row["article_content"], prompt_type="article") or ""

            d_summary = row["discuss_summary"] or ""
            if not d_summary and row["discussion_content"]:
                d_summary = generate_summary(row["discussion_content"], prompt_type="discussion") or ""

            title_chs = row["title_chs"] or ""
            if not title_chs and summary:
                title_chs = translate_title(row["title"], summary) or ""

            # LLM output validation
            item_warnings = []
            if contains_hallucination_markers(summary):
                item_warnings.append(f"ID {row['id']}: summary contains hallucination markers")
            if contains_hallucination_markers(title_chs):
                item_warnings.append(f"ID {row['id']}: title_chs contains hallucination markers")
            length_errors = validate_summary_length(summary, min_length=20, field_name=f"ID {row['id']} summary")
            item_warnings.extend(length_errors)

            if item_warnings:
                validation_warnings.extend(item_warnings)
                logger.warning(f"[PLAN] Validation warnings for ID {row['id']}: {item_warnings}")

            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "title_chs": title_chs,
                    "news_url": row["news_url"],
                    "discuss_url": row["discuss_url"],
                    "content_summary": summary,
                    "discuss_summary": d_summary,
                    "validation_warnings": item_warnings,
                }
            )

        # Compute aggregate flags
        hallucination_detected = any(
            contains_hallucination_markers(it["content_summary"])
            or contains_hallucination_markers(it["title_chs"])
            for it in items
        )
        short_content = any(
            bool(validate_summary_length(it["content_summary"], min_length=20, field_name="tmp"))
            for it in items
        )

        # Ranking
        if items:
            news_tuples = [
                (
                    it["id"],
                    it["title_chs"] or it["title"],
                    it["news_url"],
                    it["discuss_url"],
                    it["content_summary"],
                    it["discuss_summary"],
                    None,
                    None,
                    None,
                    None,
                )
                for it in items
            ]
            try:
                ratings, _ = evaluate_news_attraction(news_tuples)
                if ratings:
                    score_map = {s: sc for s, sc in ratings}
                    items.sort(key=lambda x: score_map.get(x["id"], 0), reverse=True)
            except Exception:
                pass

        # Tags
        news_titles = [(it["title_chs"] or it["title"], it["title"]) for it in items[:4]]
        tags = []
        try:
            tags = extract_tags_with_llm(news_titles) or []
        except Exception:
            pass

        plan = {
            "tags": tags,
            "ordered_ids": [it["id"] for it in items],
            "items": items,
        }

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_path = ctx.codex_dir / f"hacknews_plan_{stamp}.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        if validation_warnings:
            logger.warning(f"[PLAN] {len(validation_warnings)} validation warnings total")

        return {
            "plan_file": str(plan_path),
            "story_count": len(items),
            "tags": tags,
            "validation_warnings": len(validation_warnings),
            "hallucination_detected": hallucination_detected,
            "short_content": short_content,
        }
