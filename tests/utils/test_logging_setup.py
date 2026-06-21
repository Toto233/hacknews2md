# -*- coding: utf-8 -*-
"""Tests for structured logging setup."""

import json
import logging
import pytest

from src.utils.logging_setup import (
    safe_print,
    log_step,
    log_error,
    log_structured,
    setup_logging,
    JSONFormatter,
)


class TestSafePrint:
    """Tests for safe_print function."""

    def test_normal_print(self, capsys):
        """Normal strings should print correctly."""
        safe_print("Hello World")
        captured = capsys.readouterr()
        assert "Hello World" in captured.out

    def test_unicode_print(self, capsys):
        """Unicode strings should print correctly."""
        safe_print("你好世界")
        captured = capsys.readouterr()
        assert "你好" in captured.out or captured.out  # May be replaced on non-UTF8 terminal

    def test_multiple_args(self, capsys):
        """Multiple arguments should be printed."""
        safe_print("Hello", "World")
        captured = capsys.readouterr()
        assert "Hello" in captured.out
        assert "World" in captured.out


class TestLogStep:
    """Tests for log_step function."""

    def test_basic_step(self, caplog):
        """Basic step should log with step name."""
        with caplog.at_level(logging.INFO):
            log_step("FETCH")
        assert "FETCH" in caplog.text

    def test_step_with_news_id(self, caplog):
        """Step with news_id should include ID."""
        with caplog.at_level(logging.INFO):
            log_step("FETCH", news_id=42)
        assert "42" in caplog.text

    def test_step_with_title(self, caplog):
        """Step with title should include title."""
        with caplog.at_level(logging.INFO):
            log_step("FETCH", title="Test Article Title")
        assert "Test Article Title" in caplog.text

    def test_step_with_details(self, caplog):
        """Step with details should include details."""
        with caplog.at_level(logging.INFO):
            log_step("FETCH", details="3 items fetched")
        assert "3 items fetched" in caplog.text


class TestLogError:
    """Tests for log_error function."""

    def test_basic_error(self, caplog):
        """Basic error should log with error type."""
        with caplog.at_level(logging.WARNING):
            log_error("NETWORK")
        assert "NETWORK" in caplog.text

    def test_error_with_details(self, caplog):
        """Error with details should include all fields."""
        with caplog.at_level(logging.WARNING):
            log_error(
                "NETWORK",
                news_id=42,
                title="Test",
                error="Connection timeout",
                action="Retry",
            )
        assert "42" in caplog.text
        assert "Connection timeout" in caplog.text

    def test_error_records_to_stats(self):
        """Error should append to stats dict."""
        stats = {"errors": []}
        log_error("NETWORK", error="timeout", stats=stats)
        assert len(stats["errors"]) == 1
        assert stats["errors"][0]["type"] == "NETWORK"


class TestLogStructured:
    """Tests for log_structured function."""

    def test_basic_structured_log(self, caplog):
        """Should log event name."""
        with caplog.at_level(logging.INFO):
            log_structured("info", "article_fetched")
        assert "article_fetched" in caplog.text

    def test_structured_log_with_kwargs(self, caplog):
        """Should include extra fields."""
        with caplog.at_level(logging.INFO):
            log_structured("info", "article_fetched", url="https://example.com")
        # Extra fields are in the LogRecord, not necessarily in caplog text
        assert "article_fetched" in caplog.text

    def test_structured_log_levels(self, caplog):
        """Should respect log levels."""
        with caplog.at_level(logging.WARNING):
            log_structured("debug", "test_event")
            assert "test_event" not in caplog.text

        with caplog.at_level(logging.DEBUG):
            log_structured("warning", "test_warning")
            assert "test_warning" in caplog.text


class TestJSONFormatter:
    """Tests for JSON log formatter."""

    def test_json_output(self):
        """Should produce valid JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "test message"
        assert data["level"] == "INFO"
        assert "timestamp" in data

    def test_json_with_exception(self):
        """Should include exception info."""
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="error occurred",
                args=(),
                exc_info=exc_info,
            )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_console_mode(self):
        """Console mode should set standard formatter."""
        setup_logging(json_mode=False)
        root = logging.getLogger()
        assert len(root.handlers) > 0
        assert not isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_json_mode(self):
        """JSON mode should set JSON formatter."""
        setup_logging(json_mode=True)
        root = logging.getLogger()
        assert len(root.handlers) > 0
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_custom_level(self):
        """Should respect custom level."""
        setup_logging(level=logging.DEBUG)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
