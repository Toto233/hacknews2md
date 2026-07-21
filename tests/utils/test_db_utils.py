"""Tests for src/utils/db_utils.py."""

import sqlite3
from unittest.mock import patch

import pytest


class TestInitDatabase:
    """Tests for init_database function."""

    def test_creates_all_tables(self, tmp_path):
        import src.utils.db_utils as mod
        db_path = str(tmp_path / "test.db")
        real_connect = sqlite3.connect
        # Patch sqlite3.connect globally so db_utils uses the temp db
        with patch("sqlite3.connect", side_effect=lambda *a, **kw: real_connect(db_path)):
            mod.init_database()
        # Verify tables by opening a fresh connection
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "news" in tables
        conn.close()

    def test_news_table_has_content_source_metadata_columns(self, tmp_path):
        import src.utils.db_utils as mod
        db_path = str(tmp_path / "test.db")
        real_connect = sqlite3.connect
        with patch("sqlite3.connect", side_effect=lambda *a, **kw: real_connect(db_path)):
            mod.init_database()

        conn = sqlite3.connect(db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(news)").fetchall()}
        conn.close()

        assert {"content_source_type", "content_source_url", "content_source_doi"} <= columns

    def test_idempotent(self, tmp_path):
        import src.utils.db_utils as mod
        db_path = str(tmp_path / "test.db")
        real_connect = sqlite3.connect
        with patch("sqlite3.connect", side_effect=lambda *a, **kw: real_connect(db_path)):
            mod.init_database()
            mod.init_database()  # Should not raise


class TestIllegalKeywords:
    """Tests for illegal keyword functions."""

    def test_get_empty(self, tmp_path):
        import src.utils.db_utils as mod
        db_path = str(tmp_path / "test.db")
        # Pre-create the table with created_at column
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE illegal_keywords (keyword TEXT PRIMARY KEY, created_at TIMESTAMP)")
        conn.commit()
        conn.close()

        real_connect = sqlite3.connect
        with patch("sqlite3.connect", side_effect=lambda *a, **kw: real_connect(db_path)):
            keywords = mod.get_illegal_keywords()
            assert keywords == []

    def test_add_and_get(self, tmp_path):
        import src.utils.db_utils as mod
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE illegal_keywords (keyword TEXT PRIMARY KEY, created_at TIMESTAMP)")
        conn.commit()
        conn.close()

        real_connect = sqlite3.connect
        with patch("sqlite3.connect", side_effect=lambda *a, **kw: real_connect(db_path)):
            mod.add_illegal_keyword("badword")
            keywords = mod.get_illegal_keywords()
            assert "badword" in keywords

    def test_get_empty_when_keyword_table_is_not_initialized(self, tmp_path):
        import src.utils.db_utils as mod

        assert mod.get_illegal_keywords(str(tmp_path / "empty.db")) == []

    def test_add_duplicate(self, tmp_path):
        import src.utils.db_utils as mod
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE illegal_keywords (keyword TEXT PRIMARY KEY, created_at TIMESTAMP)")
        conn.commit()
        conn.close()

        real_connect = sqlite3.connect
        with patch("sqlite3.connect", side_effect=lambda *a, **kw: real_connect(db_path)):
            mod.add_illegal_keyword("badword")
            mod.add_illegal_keyword("badword")  # Should not raise


class TestCheckIllegalContent:
    """Tests for check_illegal_content pure function."""

    def test_match(self):
        from src.utils.db_utils import check_illegal_content
        result = check_illegal_content("This contains badword in it", ["badword", "other"])
        assert "badword" in result

    def test_no_match(self):
        from src.utils.db_utils import check_illegal_content
        result = check_illegal_content("Clean text", ["badword"])
        assert result == []

    def test_empty_text(self):
        from src.utils.db_utils import check_illegal_content
        result = check_illegal_content("", ["badword"])
        assert result == []

    def test_empty_keywords(self):
        from src.utils.db_utils import check_illegal_content
        result = check_illegal_content("Some text", [])
        assert result == []


class TestHighlightKeywords:
    """Tests for highlight_keywords pure function."""

    def test_match(self):
        from src.utils.db_utils import highlight_keywords
        result = highlight_keywords("This has badword inside", ["badword"])
        assert "badword" in result
        assert "\033[" in result

    def test_no_match(self):
        from src.utils.db_utils import highlight_keywords
        result = highlight_keywords("Clean text", ["badword"])
        assert result == "Clean text"
