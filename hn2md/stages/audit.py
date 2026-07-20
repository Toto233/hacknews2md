"""Structured publishing audit and approval gate."""

from __future__ import annotations

import logging
import json
import sqlite3
from datetime import datetime
from typing import Any

from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from src.core.content_quality import is_paywall_or_shell_content
from src.db.connection import get_db
from src.security.content_sanitizer import contains_hallucination_markers

logger = logging.getLogger(__name__)
MIN_CONTENT_LENGTH = 100
VALID_SOURCE_TYPES = {
    "full_text",
    "public_abstract",
    "public_page_summary",
    "public_metadata_summary",
    "human_supplied",
    "metadata_only",
    "discussion_only",
}
VALID_DISCUSSION_SUMMARY_SOURCE_TYPES = {
    "hn_discussion",
    "external_hn_snippet",
    "human_supplied",
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


def _warning_issue(row: sqlite3.Row, code: str, message: str) -> dict[str, Any]:
    issue = _issue(row, code, message)
    issue["severity"] = "warning"
    return issue


def _collect_warning_issue(warning: dict[str, Any]) -> dict[str, Any]:
    return {
        "news_id": warning.get("id"),
        "title": warning.get("title"),
        "news_url": warning.get("url"),
        "code": "collect_content_warning",
        "severity": "blocking",
        "message": warning.get("reason") or "采集阶段存在内容警告",
        "domain": warning.get("domain"),
        "action_required": warning.get("action_required"),
        "failure_count": warning.get("failure_count"),
    }


def _load_collect_content_warnings(ctx: RuntimeContext) -> list[dict[str, Any]]:
    ledger_path = ctx.job_dir / f"publish_job_{datetime.now().strftime('%Y%m%d')}.json"
    if not ledger_path.exists():
        return []
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read collect warnings from ledger: %s", ledger_path)
        return []
    collecting = data.get("stages", {}).get("COLLECTING", {})
    output_summary = collecting.get("output_summary", {})
    warnings = output_summary.get("content_warnings", [])
    if not isinstance(warnings, list):
        return []
    return [warning for warning in warnings if isinstance(warning, dict)]


def _warning_is_still_actionable(warning: dict[str, Any], rows_by_id: dict[int, sqlite3.Row]) -> bool:
    """Keep ledger warnings only while the current daily record still needs repair."""
    news_id = warning.get("id")
    if not isinstance(news_id, int):
        return True
    row = rows_by_id.get(news_id)
    if row is None:
        return False

    reason = str(warning.get("reason") or "")
    if reason not in {"article_content_missing", "content_missing", "paywall_or_shell_page"}:
        return True

    article = (row["article_content"] or "").strip()
    source_type = (row["content_source_type"] or "").strip()
    return not (
        len(article) >= MIN_CONTENT_LENGTH
        and source_type in VALID_SOURCE_TYPES
        and not is_paywall_or_shell_content(article)
    )


def _available_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def run_audit(
    ctx: RuntimeContext,
    interactive: bool = False,
    llm_type: str | None = None,
    include_summaries: bool = True,
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
            "discuss_summary_source_type",
            "discuss_summary_source_url",
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

    rows_by_id = {row["id"]: row for row in rows}
    issues: list[dict[str, Any]] = [
        _collect_warning_issue(warning)
        for warning in _load_collect_content_warnings(ctx)
        if _warning_is_still_actionable(warning, rows_by_id)
    ]
    items: list[dict[str, Any]] = []
    for row in rows:
        article = (row["article_content"] or "").strip()
        discussion = (row["discussion_content"] or "").strip()
        summary = (row["content_summary"] or "").strip()
        discussion_summary = (row["discuss_summary"] or "").strip()
        summary_for_gate = summary if include_summaries else "pre-plan"
        discussion_summary_for_gate = discussion_summary if include_summaries else "pre-plan"
        discussion_for_gate = discussion if include_summaries else "pre-plan"
        discussion_summary_source_type = (row["discuss_summary_source_type"] or "").strip()
        discussion_summary_source_url = (row["discuss_summary_source_url"] or "").strip()
        source_type = (row["content_source_type"] or "").strip()
        item = {
            "id": row["id"],
            "title": row["title"],
            "news_url": row["news_url"],
            "article_length": len(article),
            "discussion_length": len(discussion),
            "summary_length": len(summary),
            "discussion_summary_length": len(discussion_summary),
            "discuss_summary_source_type": discussion_summary_source_type or None,
            "discuss_summary_source_url": discussion_summary_source_url or None,
            "content_source_type": source_type or None,
            "content_source_url": row["content_source_url"],
        }
        items.append(item)

        if not article:
            issues.append(_issue(row, "content_missing", "正文或替代内容为空"))
        elif len(article) < MIN_CONTENT_LENGTH:
            issues.append(_issue(row, "content_short", f"内容过短（{len(article)} 字符）"))
        if is_paywall_or_shell_content(article):
            issues.append(_issue(row, "paywall_or_shell_page", "正文疑似订阅墙或站点壳页面"))
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
            issues.append(_issue(row, "fallback_source_requires_review", "替代来源需要人工确认或专用 handler 补全"))
        if not summary_for_gate:
            issues.append(_issue(row, "summary_missing", "中文正文摘要为空"))
        if not discussion_summary_for_gate:
            issues.append(_issue(row, "discussion_summary_missing", "中文讨论摘要为空"))
        elif not discussion_for_gate and not discussion_summary_source_type:
            issues.append(_issue(row, "discussion_summary_source_missing", "讨论为空但讨论摘要缺少来源标记"))
        elif not discussion_for_gate and discussion_summary_source_type not in VALID_DISCUSSION_SUMMARY_SOURCE_TYPES:
            issues.append(_issue(row, "discussion_summary_source_invalid", "讨论摘要来源类型无效"))
        elif not discussion_for_gate and discussion_summary_source_type != "hn_discussion" and not discussion_summary_source_url:
            issues.append(_issue(row, "discussion_summary_source_url_missing", "外部或人工讨论摘要缺少来源 URL"))
        if include_summaries and (contains_hallucination_markers(summary) or contains_hallucination_markers(discussion_summary)):
            issues.append(_issue(row, "hallucination_marker", "摘要包含模型拒答或幻觉标记"))
        lowered = article.lower()
        if any(marker in lowered for marker in ("enable javascript", "access denied", "sign in to continue")):
            if len(article) >= 1000:
                issues.append(_warning_issue(row, "error_page_suspected", "内容含登录页或 JS 提示词，但正文长度足够，需人工留意"))
            else:
                issues.append(_issue(row, "error_page", "内容疑似登录页或错误页"))

    blocking_count = sum(1 for issue in issues if issue.get("severity", "blocking") == "blocking")
    report = {"items": items, "issues": issues, "blocking_count": blocking_count}
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
