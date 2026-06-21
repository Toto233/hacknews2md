"""Audit stage: quality checks on database content."""

import logging
import sqlite3

from hn2md.context import RuntimeContext
from src.db.connection import get_db

logger = logging.getLogger(__name__)


def run_audit(ctx: RuntimeContext, interactive: bool = False, llm_type: str = None):
    """Run quality checks on database content."""
    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Check for empty/short content
        cur.execute(
            "SELECT id, title, length(coalesce(article_content,'')) as content_len, "
            "length(coalesce(content_summary,'')) as summary_len "
            "FROM news WHERE date(created_at)=date('now','localtime') "
            "ORDER BY id"
        )
        rows = cur.fetchall()

    issues = []
    for row in rows:
        if row["content_len"] == 0:
            issues.append(f"ID {row['id']}: 正文为空 - {row['title']}")
        elif row["content_len"] < 100:
            issues.append(f"ID {row['id']}: 正文过短({row['content_len']}字) - {row['title']}")
        if row["summary_len"] == 0:
            issues.append(f"ID {row['id']}: 中文摘要为空 - {row['title']}")

    if issues:
        logger.warning(f"发现 {len(issues)} 个问题:")
        for issue in issues:
            logger.warning(f"  - {issue}")
    else:
        logger.info("所有新闻内容检查通过")

    return {"issues": len(issues), "details": issues}
