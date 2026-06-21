"""Tests for src/core/audit_news.py."""

import json
import sqlite3
from contextlib import contextmanager
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest


class TestRowToDict:
    """Tests for row_to_dict pure function."""

    def test_none_input(self):
        from src.core.audit_news import row_to_dict
        assert row_to_dict(None) is None


class TestDiagnoseProblems:
    """Tests for diagnose_problems pure function."""

    def test_empty_content(self):
        from src.core.audit_news import diagnose_problems
        row = {"article_content": None, "content_summary": "some summary"}
        problems = diagnose_problems(row)
        assert any("正文为空" in p for p in problems)

    def test_short_content(self):
        from src.core.audit_news import diagnose_problems
        row = {"article_content": "short", "content_summary": "some summary"}
        problems = diagnose_problems(row)
        assert any("正文过短" in p for p in problems)

    def test_missing_summary(self):
        from src.core.audit_news import diagnose_problems
        row = {"article_content": "a" * 200, "content_summary": None}
        problems = diagnose_problems(row)
        assert any("中文摘要为空" in p for p in problems)

    def test_healthy(self):
        from src.core.audit_news import diagnose_problems
        row = {"article_content": "a" * 200, "content_summary": "good summary"}
        problems = diagnose_problems(row)
        assert len(problems) == 0


class TestTruncateText:
    """Tests for truncate_text pure function."""

    def test_short_text(self):
        from src.core.audit_news import truncate_text
        assert truncate_text("hello", 10) == "hello"

    def test_long_text(self):
        from src.core.audit_news import truncate_text
        result = truncate_text("a" * 100, 10)
        assert len(result) == 13  # 10 + "..."
        assert result.endswith("...")

    def test_none(self):
        from src.core.audit_news import truncate_text
        assert truncate_text(None) == "(空)"


def _make_mock_get_db(temp_db):
    """Create a mock get_db context manager for the given temp_db path."""
    @contextmanager
    def _mock_get_db(db_path=None):
        conn = sqlite3.connect(temp_db)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return _mock_get_db


class TestUpdateNewsFields:
    """Tests for update_news_fields with database."""

    def test_updates_single_field(self, temp_db):
        import src.core.audit_news as mod

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url) VALUES (?, ?)",
            ("Original", "https://example.com"),
        )
        news_id = cursor.lastrowid
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _make_mock_get_db(temp_db)):
            mod.update_news_fields(news_id, title="Updated")

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM news WHERE id=?", (news_id,))
        assert cursor.fetchone()[0] == "Updated"
        conn.close()

    def test_updates_multiple_fields(self, temp_db):
        import src.core.audit_news as mod

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url) VALUES (?, ?)",
            ("Original", "https://example.com"),
        )
        news_id = cursor.lastrowid
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _make_mock_get_db(temp_db)):
            mod.update_news_fields(news_id, title="New Title", content_summary="New Summary")

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT title, content_summary FROM news WHERE id=?", (news_id,))
        row = cursor.fetchone()
        assert row[0] == "New Title"
        assert row[1] == "New Summary"
        conn.close()

    def test_skips_none_values(self, temp_db):
        import src.core.audit_news as mod

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url) VALUES (?, ?)",
            ("Original", "https://example.com"),
        )
        news_id = cursor.lastrowid
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _make_mock_get_db(temp_db)):
            mod.update_news_fields(news_id, title=None)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM news WHERE id=?", (news_id,))
        assert cursor.fetchone()[0] == "Original"
        conn.close()

    def test_rejects_invalid_field(self, temp_db):
        import src.core.audit_news as mod

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url) VALUES (?, ?)",
            ("Original", "https://example.com"),
        )
        news_id = cursor.lastrowid
        conn.commit()
        conn.close()

        with pytest.raises(ValueError, match="Invalid field name"):
            mod.update_news_fields(news_id, malicious_field="hack")


class TestGetProblemNews:
    """Tests for get_problem_news with database."""

    def test_returns_empty_content(self, temp_db):
        import src.core.audit_news as mod

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url, article_content, content_summary) "
            "VALUES (?, ?, ?, ?)",
            ("Test", "https://example.com", None, "summary"),
        )
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _make_mock_get_db(temp_db)):
            problems = mod.get_problem_news()
        assert len(problems) >= 1

    def test_excludes_healthy(self, temp_db):
        import src.core.audit_news as mod

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url, article_content, content_summary) "
            "VALUES (?, ?, ?, ?)",
            ("Test", "https://example.com", "a" * 200, "good summary"),
        )
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _make_mock_get_db(temp_db)):
            problems = mod.get_problem_news()
        assert len(problems) == 0


class TestDeleteNews:
    """Tests for delete_news with database."""

    def test_deletes_existing(self, temp_db):
        import src.core.audit_news as mod

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url) VALUES (?, ?)",
            ("To Delete", "https://example.com"),
        )
        news_id = cursor.lastrowid
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _make_mock_get_db(temp_db)):
            mod.delete_news(news_id)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM news WHERE id=?", (news_id,))
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_nonexistent_no_error(self, temp_db):
        import src.core.audit_news as mod

        with patch.object(mod, "get_db", _make_mock_get_db(temp_db)):
            mod.delete_news(99999)  # Should not raise
