"""Tests for src/core/fetch_news.py."""

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch, Mock

import pytest


@pytest.fixture
def fetch_news_db(tmp_path):
    """Create a temp database and patch get_db in fetch_news to use it."""
    db_path = str(tmp_path / "test_hacknews.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, title_chs TEXT, news_url TEXT, discuss_url TEXT,
            article_content TEXT, discussion_content TEXT,
            content_summary TEXT, discuss_summary TEXT,
            screenshot TEXT, largest_image TEXT, image_2 TEXT, image_3 TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_history (
            id INTEGER PRIMARY KEY, title TEXT, title_chs TEXT,
            news_url TEXT, discuss_url TEXT,
            article_content TEXT, discussion_content TEXT,
            content_summary TEXT, discuss_summary TEXT,
            screenshot TEXT, largest_image TEXT, image_2 TEXT, image_3 TEXT,
            created_at TIMESTAMP, archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS filtered_domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE, reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

    @contextmanager
    def _get_db(db_path_arg=None):
        c = sqlite3.connect(db_path)
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    with patch("src.core.fetch_news.get_db", _get_db):
        yield db_path


class TestNormalizeDomain:
    """Tests for normalize_domain pure function."""

    def test_strips_www(self):
        from src.core.fetch_news import normalize_domain
        assert normalize_domain("www.example.com") == "example.com"

    def test_lowercases(self):
        from src.core.fetch_news import normalize_domain
        assert normalize_domain("Example.COM") == "example.com"

    def test_strips_port(self):
        from src.core.fetch_news import normalize_domain
        assert normalize_domain("example.com:8080") == "example.com"

    def test_strips_trailing_dot(self):
        from src.core.fetch_news import normalize_domain
        assert normalize_domain("example.com.") == "example.com"

    def test_empty_string(self):
        from src.core.fetch_news import normalize_domain
        assert normalize_domain("") == ""


class TestExtractDomain:
    """Tests for extract_domain pure function."""

    def test_full_url(self):
        from src.core.fetch_news import extract_domain
        result = extract_domain("https://www.nytimes.com/article")
        assert result == "nytimes.com"

    def test_no_scheme(self):
        from src.core.fetch_news import extract_domain
        result = extract_domain("example.com/article")
        # Should handle gracefully
        assert isinstance(result, str)


class TestIsDomainFiltered:
    """Tests for is_domain_filtered with database."""

    def test_domain_found(self, temp_db):
        from src.core.fetch_news import is_domain_filtered
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO filtered_domains (domain, reason) VALUES (?, ?)",
            ("example.com", "test"),
        )
        conn.commit()

        assert is_domain_filtered("example.com", cursor) is True
        conn.close()

    def test_domain_not_found(self, temp_db):
        from src.core.fetch_news import is_domain_filtered
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        assert is_domain_filtered("notfiltered.com", cursor) is False
        conn.close()

    def test_www_normalization(self, temp_db):
        from src.core.fetch_news import is_domain_filtered
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO filtered_domains (domain, reason) VALUES (?, ?)",
            ("example.com", "test"),
        )
        conn.commit()

        assert is_domain_filtered("www.example.com", cursor) is True
        conn.close()


class TestIsUrlInHistory:
    """Tests for is_url_in_history with database."""

    def test_url_found(self, temp_db):
        from src.core.fetch_news import is_url_in_history
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO news_history (news_url) VALUES (?)",
            ("https://example.com/article",),
        )
        conn.commit()

        assert is_url_in_history("https://example.com/article", cursor) is True
        conn.close()

    def test_url_not_found(self, temp_db):
        from src.core.fetch_news import is_url_in_history
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        assert is_url_in_history("https://newsite.com/article", cursor) is False
        conn.close()


class TestSaveToDatabase:
    """Tests for save_to_database with database."""

    def test_saves_valid_items(self, fetch_news_db):
        import src.core.fetch_news as mod
        items = [
            {"title": "Test Article", "news_url": "https://example.com/1", "discuss_url": ""},
            {"title": "Another Article", "news_url": "https://example.com/2", "discuss_url": ""},
        ]
        saved = mod.save_to_database(items)
        assert saved == 2

        conn = sqlite3.connect(fetch_news_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM news")
        assert cursor.fetchone()[0] == 2
        conn.close()

    def test_skips_ask_hn(self, fetch_news_db):
        import src.core.fetch_news as mod
        items = [
            {"title": "Ask HN: What is your favorite editor?", "news_url": "https://hn.com/1", "discuss_url": ""},
            {"title": "Real Article", "news_url": "https://example.com/1", "discuss_url": ""},
        ]
        saved = mod.save_to_database(items)
        assert saved == 1

    def test_skips_duplicate_title(self, fetch_news_db):
        import src.core.fetch_news as mod
        items = [
            {"title": "Same Title", "news_url": "https://example.com/1", "discuss_url": ""},
            {"title": "Same Title", "news_url": "https://example.com/2", "discuss_url": ""},
        ]
        saved = mod.save_to_database(items)
        assert saved == 1

    def test_empty_list(self, fetch_news_db):
        import src.core.fetch_news as mod
        saved = mod.save_to_database([])
        assert saved == 0


class TestFilteredDomainManagement:
    """Tests for add/remove/list filtered domains."""

    def test_add_filtered_domain_success(self, fetch_news_db):
        import src.core.fetch_news as mod
        result = mod.add_filtered_domain("spam.com", "spam site")
        assert result is True

        domains = mod.list_filtered_domains()
        assert any(d[0] == "spam.com" for d in domains)

    def test_add_filtered_domain_duplicate(self, fetch_news_db):
        import src.core.fetch_news as mod
        mod.add_filtered_domain("spam.com", "spam site")
        result = mod.add_filtered_domain("spam.com", "duplicate")
        assert result is False

    def test_remove_filtered_domain_success(self, fetch_news_db):
        import src.core.fetch_news as mod
        mod.add_filtered_domain("spam.com", "spam site")
        result = mod.remove_filtered_domain("spam.com")
        assert result is True

    def test_remove_filtered_domain_not_found(self, fetch_news_db):
        import src.core.fetch_news as mod
        result = mod.remove_filtered_domain("nonexistent.com")
        assert result is False
