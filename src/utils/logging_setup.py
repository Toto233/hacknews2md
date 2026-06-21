"""
Shared logging helpers with structured logging support.

Provides:
- safe_print: Windows-safe output
- log_step / log_error: Structured log helpers
- setup_logging: Configure structured JSON or console output
- get_logger: Get a bound structured logger
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production use."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add extra fields from record
        for key in ("stage", "news_id", "url", "duration_ms", "error_type"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(json_mode: bool = False, level: int = logging.INFO) -> None:
    """Configure logging for the application.

    Args:
        json_mode: If True, output structured JSON logs (for production).
                   If False, output human-readable console logs (for development).
        level: Logging level (default: INFO).
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if json_mode:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root.addHandler(handler)


def safe_print(*args, **kwargs):
    """Safe print function that prevents UnicodeEncodeError on Windows."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = []
        for arg in args:
            if isinstance(arg, str):
                safe_args.append(arg.encode("ascii", errors="replace").decode("ascii"))
            else:
                safe_args.append(str(arg).encode("ascii", errors="replace").decode("ascii"))
        print(*safe_args, **kwargs)


def log_step(step: str, news_id: int = None, title: str = None, details: str = None):
    """Log a processing step."""
    parts = [f"[{step}]"]
    if news_id:
        parts.append(f"ID:{news_id}")
    if title:
        parts.append(f"'{title[:50]}...'" if len(title) > 50 else f"'{title}'")
    if details:
        parts.append(details)
    logger.info(" | ".join(parts))


def log_error(
    error_type: str,
    news_id: int = None,
    title: str = None,
    error: str = None,
    action: str = None,
    stats: dict = None,
):
    """Log an error and optionally record it in a stats dict.

    Args:
        error_type: Category of the error.
        news_id: Optional news item ID.
        title: Optional news title.
        error: Error description.
        action: Resolution or next-step description.
        stats: Optional dict with an 'errors' list to append to.
    """
    parts = [f"[ERROR:{error_type}]"]
    if news_id:
        parts.append(f"ID:{news_id}")
    if title:
        parts.append(f"'{title[:50]}...'" if len(title) > 50 else f"'{title}'")
    if error:
        parts.append(f"错误: {error}")
    if action:
        parts.append(f"解决: {action}")
    logger.warning(" | ".join(parts))

    if stats is not None:
        stats["errors"].append(
            {
                "type": error_type,
                "news_id": news_id,
                "error": error,
                "action": action,
            }
        )


def log_structured(
    level: str,
    event: str,
    **kwargs: Any,
) -> None:
    """Log a structured event with key-value context.

    Args:
        level: Log level ("debug", "info", "warning", "error").
        event: Event name (e.g., "article_fetched", "llm_call_complete").
        **kwargs: Additional structured fields.

    Example:
        log_structured("info", "article_fetched",
                       url="https://...", title="Hello", word_count=500)
    """
    extra = {k: v for k, v in kwargs.items() if v is not None}
    log_fn = getattr(logger, level, logger.info)
    log_fn(event, extra=extra)
