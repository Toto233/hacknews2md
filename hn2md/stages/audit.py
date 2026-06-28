"""Structured publishing audit and approval gate."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from src.db.connection import get_db
from src.security.content_sanitizer import contains_hallucination_markers

logger = logging.getLogger(__name__)
MIN_CONTENT_LENGTH = 100
VALID_SOURCE_TYPES = {
    "full_text",
    "public_abstract",
    "public_page_summary",
    "public_metadata_summary",
    "metadata_only",
    "discussion_only",
}


def _issue(row: sqlite3.Row, code: str, message: str) -> dict[str, Any]:
    return {
        "news_id": row["id"],
        "title": row["title"],
        "news_url": row["news_url"],
        "code": code,
        "severity": "blocking",
        "message": message,
    }


def _available_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def run_audit(
    ctx: RuntimeContext,
    interactive: bool = False,
    llm_type: str | None = None,
) -> dict[str, Any]:
    """Return a structured quality report for today's news."""
    if interactive:
        from src.core.audit_news import run_audit_one

        run_audit_one(llm_type=llm_type)

    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "news" not in tables:
            return {"items": [], "issues": [], "blocking_count": 0}
        columns = _available_columns(conn, "news")
        required = [
            "id",
            "title",
            "news_url",
            "article_content",
            "discussion_content",
            "content_summary",
            "discuss_summary",
            "content_source_type",
            "content_source_url",
        ]
        select_exprs = [
            column if column in columns else f"NULL AS {column}"
            for column in required
        ]
        rows = conn.execute(
            f"SELECT {', '.join(select_exprs)} "
            "FROM news WHERE date(created_at)=date('now','localtime') ORDER BY id"
        ).fetchall()

    issues: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for row in rows:
        article = (row["article_content"] or "").strip()
        discussion = (row["discussion_content"] or "").strip()
        summary = (row["content_summary"] or "").strip()
        discussion_summary = (row["discuss_summary"] or "").strip()
        source_type = (row["content_source_type"] or "").strip()
        item = {
            "id": row["id"],
            "title": row["title"],
            "news_url": row["news_url"],
            "article_length": len(article),
            "discussion_length": len(discussion),
            "summary_length": len(summary),
            "discussion_summary_length": len(discussion_summary),
            "content_source_type": source_type or None,
            "content_source_url": row["content_source_url"],
        }
        items.append(item)

        if not article:
            issues.append(_issue(row, "content_missing", "正文或替代内容为空"))
        elif len(article) < MIN_CONTENT_LENGTH:
            issues.append(_issue(row, "content_short", f"内容过短（{len(article)} 字符）"))
        if source_type not in VALID_SOURCE_TYPES:
            issues.append(_issue(row, "source_missing", "内容来源类型缺失或无效"))
        elif source_type in {"metadata_only", "discussion_only"}:
            issues.append(_issue(row, source_type, f"来源类型 {source_type} 不足以直接发布"))
        elif source_type == "public_abstract":
            if not row["content_source_url"]:
                issues.append(_issue(row, "abstract_source_missing", "公开摘要缺少来源 URL"))
        elif source_type in {"public_page_summary", "public_metadata_summary"}:
            if not row["content_source_url"]:
                issues.append(_issue(row, "source_url_missing", "公开摘要或替代内容缺少来源 URL"))
        if not summary:
            issues.append(_issue(row, "summary_missing", "中文正文摘要为空"))
        if not discussion_summary:
            issues.append(_issue(row, "discussion_summary_missing", "中文讨论摘要为空"))
        if contains_hallucination_markers(summary) or contains_hallucination_markers(discussion_summary):
            issues.append(_issue(row, "hallucination_marker", "摘要包含模型拒答或幻觉标记"))
        lowered = article.lower()
        if any(marker in lowered for marker in ("enable javascript", "access denied", "sign in to continue")):
            issues.append(_issue(row, "error_page", "内容疑似登录页或错误页"))

    report = {"items": items, "issues": issues, "blocking_count": len(issues)}
    if issues:
        logger.warning("Audit found %s blocking issue(s)", len(issues))
    else:
        logger.info("Audit passed")
    return report


def require_audit_clear_or_exempt(machine: JobStateMachine) -> bool:
    """Require a clean report or recorded approval for the current job."""
    report = machine.job.audit_report
    if report is None:
        raise RuntimeError("audit required before planning or publishing")
    if report.get("blocking_count", 0):
        if not machine.job.audit_exemption:
            first = report.get("issues", [{}])[0]
            code = first.get("code", "unknown")
            raise RuntimeError(f"audit blocked: explicit daily approval required ({code})")
        return True
    return False
