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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production use."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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


def setup_logging(
    json_mode: bool = False,
    level: int = logging.INFO,
    log_dir: str | Path | None = None,
    console: bool = True,
) -> Path | None:
    """Configure logging for the application.

    Args:
        json_mode: If True, output structured JSON logs (for production).
                   If False, output human-readable console logs (for development).
        level: Logging level (default: INFO).
        log_dir: Optional directory for the daily UTF-8 log file.
        console: If True, also write human-readable logs to stderr.

    Returns:
        The daily log path when file logging is enabled, otherwise ``None``.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    if json_mode:
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    log_path = None
    if log_dir is not None:
        resolved_log_dir = Path(log_dir)
        resolved_log_dir.mkdir(parents=True, exist_ok=True)
        log_path = resolved_log_dir / f"hn2md-{datetime.now():%Y%m%d}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    return log_path


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
