"""Tests for src/core/archive_news.py."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


class TestEnsureColumn:
    """Tests for _ensure_column helper."""

    def test_adds_missing_column(self, temp_db):
        from src.core.archive_news import _ensure_column
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")
        conn.commit()

        _ensure_column(cursor, "test_table", "new_col", "TEXT")
        conn.commit()

        cursor.execute("PRAGMA table_info(test_table)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "new_col" in columns
        conn.close()

    def test_no_op_if_column_exists(self, temp_db):
        from src.core.archive_news import _ensure_column
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, existing TEXT)")
        conn.commit()

        # Should not raise
        _ensure_column(cursor, "test_table", "existing", "TEXT")
        conn.commit()
        conn.close()

    def test_rejects_invalid_identifier(self, temp_db):
        from src.core.archive_news import _ensure_column
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _ensure_column(cursor, "test; DROP TABLE", "col", "TEXT")
        conn.close()


class TestCreateHistoryTable:
    """Tests for create_history_table."""

    def test_creates_table(self, temp_db):
        import src.core.archive_news as mod

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

        with patch.object(mod, "get_db", _mock_get_db):
            mod.create_history_table()

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_history'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent(self, temp_db):
        import src.core.archive_news as mod

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

        with patch.object(mod, "get_db", _mock_get_db):
            mod.create_history_table()
            mod.create_history_table()  # Should not raise


class TestArchiveOldNews:
    """Tests for archive_old_news."""

    def test_moves_old_records(self, temp_db):
        import src.core.archive_news as mod

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

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Insert old news (yesterday)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO news (title, news_url, created_at) VALUES (?, ?, ?)",
            ("Old News", "https://example.com/old", yesterday),
        )
        # Insert today's news
        cursor.execute(
            "INSERT INTO news (title, news_url, created_at) VALUES (?, ?, ?)",
            ("Today News", "https://example.com/today", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _mock_get_db):
            mod.archive_old_news()

        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Today's news should remain
        cursor.execute("SELECT COUNT(*) FROM news")
        assert cursor.fetchone()[0] == 1

        # Old news should be in history
        cursor.execute("SELECT COUNT(*) FROM news_history")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_preserves_today_news(self, temp_db):
        import src.core.archive_news as mod

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

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news (title, news_url, created_at) VALUES (?, ?, ?)",
            ("Today News", "https://example.com/today", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()

        with patch.object(mod, "get_db", _mock_get_db):
            mod.archive_old_news()

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM news")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_no_old_news(self, temp_db):
        import src.core.archive_news as mod

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

        with patch.object(mod, "get_db", _mock_get_db):
            mod.archive_old_news()  # Should not raise
