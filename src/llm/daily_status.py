"""LLM daily model status and request-count tracking (SQLite-backed)."""

import logging
from datetime import datetime

from src.db.connection import get_db

logger = logging.getLogger(__name__)

# Constants
GEMINI_FALLBACK_MODEL = "gemini-3.1-flash-lite-preview"
GEMINI_STRICT_LIMIT_PER_MINUTE = 5
GEMINI_STRICT_LIMIT_PER_DAY = 20


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _ensure_llm_status_table():
    """确保模型当日状态与用量表存在。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_model_daily_status (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status_date DATE NOT NULL,
            is_disabled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            last_error TEXT,
            disabled_at TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (provider, model, status_date)
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_model_daily_usage (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            usage_date DATE NOT NULL,
            request_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (provider, model, usage_date)
        )
        """)


def _reserve_daily_request_slot(provider, model, daily_limit):
    """预占当天请求配额；达到上限返回False。"""
    _ensure_llm_status_table()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT request_count
            FROM llm_model_daily_usage
            WHERE provider = ? AND model = ? AND usage_date = ?
            """,
            (provider, model, _today_str()),
        )
        row = cursor.fetchone()
        current = int(row[0]) if row else 0
        if current >= daily_limit:
            return False

        cursor.execute(
            """
            INSERT INTO llm_model_daily_usage
                (provider, model, usage_date, request_count, updated_at)
            VALUES
                (?, ?, ?, 1, datetime('now', 'localtime'))
            ON CONFLICT(provider, model, usage_date)
            DO UPDATE SET
                request_count = request_count + 1,
                updated_at = datetime('now', 'localtime')
            """,
            (provider, model, _today_str()),
        )
        return True


def is_model_disabled_today(provider, model):
    """检查模型今天是否已被禁用。"""
    _ensure_llm_status_table()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT is_disabled
            FROM llm_model_daily_status
            WHERE provider = ? AND model = ? AND status_date = ?
            """,
            (provider, model, _today_str()),
        )
        row = cursor.fetchone()
        return bool(row and row[0] == 1)


def disable_model_for_today(provider, model, reason, error_msg):
    """将模型标记为当天禁用，次日自动恢复。"""
    _ensure_llm_status_table()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO llm_model_daily_status
                (provider, model, status_date, is_disabled, reason, last_error, disabled_at, updated_at)
            VALUES
                (?, ?, ?, 1, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'))
            ON CONFLICT(provider, model, status_date)
            DO UPDATE SET
                is_disabled = 1,
                reason = excluded.reason,
                last_error = excluded.last_error,
                disabled_at = excluded.disabled_at,
                updated_at = excluded.updated_at
            """,
            (provider, model, _today_str(), reason, (error_msg or "")[:1000]),
        )


def _is_forbidden_gemini_model(model):
    """禁止使用所有 Gemini 2.5 系列模型。"""
    if not model:
        return False
    model_l = model.lower()
    return model_l.startswith("gemini-2.5-")


def _is_strict_capped_gemini_model(model):
    """对 Gemini 3 Flash 执行严格限流与日限额。"""
    if not model:
        return False
    model_l = model.lower()
    return model_l.startswith("gemini-3-flash")


def is_gemini_quota_exceeded_error(error_msg):
    """识别 Gemini 配额耗尽（应当天熔断）而非短时限流。"""
    if not error_msg:
        return False
    msg = error_msg.lower()
    quota_markers = [
        "quota exceeded",
        "insufficient quota",
        "quota failure",
        "quotafailure",
        "resource_exhausted",
        "exceeded your current quota",
        "quota metric",
        "per day",
        "daily limit",
        "limit 'generatecontent requests per day'",
        "limit 'generate content requests per day'",
        "generate_content_free_tier_requests",
        "free_tier",
        "billing",
    ]
    # 既要有"配额语义"，也要有"超限语义"，避免把普通失败误判成配额耗尽
    has_quota_semantics = any(marker in msg for marker in quota_markers)
    has_exceeded_semantics = any(
        marker in msg for marker in ["exceed", "exceeded", "limit", "quota", "resource_exhausted"]
    )
    return has_quota_semantics and has_exceeded_semantics
