"""Plan stage: generate summaries via LLM, output plan JSON."""

import json
import logging
import sqlite3
from datetime import datetime

from hn2md.constants import Stage
from hn2md.stages.base import BaseStage
from src.db.connection import get_db

logger = logging.getLogger(__name__)


class PlanStage(BaseStage):
    stage_name = Stage.PLANNING

    def execute(self, ctx, machine):
        from src.llm.llm_business import generate_summary, translate_title
        from src.llm.llm_evaluator import evaluate_news_attraction
        from src.llm.llm_tag_extractor import extract_tags_with_llm
        from src.security.content_sanitizer import (
            contains_hallucination_markers,
            validate_summary_length,
        )

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
