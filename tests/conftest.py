"""Shared test fixtures for hacknews2md test suite."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite database with all required tables."""
    db_path = str(tmp_path / "test_hacknews.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create news table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            title_chs TEXT,
            news_url TEXT,
            discuss_url TEXT,
            article_content TEXT,
            discussion_content TEXT,
            content_summary TEXT,
            discuss_summary TEXT,
            screenshot TEXT,
            largest_image TEXT,
            image_2 TEXT,
            image_3 TEXT,
            content_type TEXT DEFAULT 'article',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create news_history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_history (
            id INTEGER PRIMARY KEY,
            title TEXT,
            title_chs TEXT,
            news_url TEXT,
            discuss_url TEXT,
            article_content TEXT,
            discussion_content TEXT,
            content_summary TEXT,
            discuss_summary TEXT,
            screenshot TEXT,
            largest_image TEXT,
            image_2 TEXT,
            image_3 TEXT,
            content_type TEXT DEFAULT 'article',
            created_at TIMESTAMP,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id)
        )
    """)

    # Create filtered_domains table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS filtered_domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create news_history tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_history_tracking (
            news_url TEXT PRIMARY KEY
        )
    """)

    # Create illegal_keywords table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS illegal_keywords (
            keyword TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create llm_daily_status table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_daily_status (
            provider TEXT,
            model TEXT,
            date TEXT,
            request_count INTEGER DEFAULT 0,
            disabled INTEGER DEFAULT 0,
            disable_reason TEXT,
            error_message TEXT,
            PRIMARY KEY (provider, model, date)
        )
    """)

    # Create scraper_failures table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scraper_failures (
            domain TEXT PRIMARY KEY,
            failure_count INTEGER DEFAULT 1,
            first_failure_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_failure_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sample_url TEXT
        )
    """)

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_news_items():
    """Sample news items for testing."""
    return [
        {
            "title": "Show HN: A new Python framework",
            "title_chs": "Show HN: 一个新的Python框架",
            "news_url": "https://example.com/python-framework",
            "discuss_url": "https://news.ycombinator.com/item?id=12345",
        },
        {
            "title": "Ask HN: What is your favorite editor?",
            "title_chs": "",
            "news_url": "https://news.ycombinator.com/item?id=12346",
            "discuss_url": "https://news.ycombinator.com/item?id=12346",
        },
        {
            "title": "The future of AI in 2026",
            "title_chs": "2026年AI的未来",
            "news_url": "https://techcrunch.com/ai-2026",
            "discuss_url": "https://news.ycombinator.com/item?id=12347",
        },
    ]


@pytest.fixture
def sample_hn_html():
    """Sample Hacker News HTML for testing fetch_news parsing."""
    return """
    <html>
    <body>
    <table id="hnmain">
    <tr class="athing" id="12345">
        <td align="right" valign="top" class="title"><span class="rank">1.</span></td>
        <td valign="top" class="votelinks"></td>
        <td class="title">
            <span class="titleline">
                <a href="https://example.com/python-framework">Show HN: A new Python framework</a>
                <span class="sitebit comhead"> (<a href="from?site=example.com"><span class="sitestr">example.com</span></a>)</span>
            </span>
        </td>
    </tr>
    <tr>
        <td colspan="2"></td>
        <td class="subtext">
            <span class="score" id="score_12345">100 points</span>
            by <a href="user?id=testuser" class="hnuser">testuser</a>
            <span class="age" title="2026-06-20T10:00:00"><a href="item?id=12345">2 hours ago</a></span>
            | <a href="item?id=12345">50&nbsp;comments</a>
        </td>
    </tr>
    <tr class="athing" id="12346">
        <td align="right" valign="top" class="title"><span class="rank">2.</span></td>
        <td valign="top" class="votelinks"></td>
        <td class="title">
            <span class="titleline">
                <a href="https://news.ycombinator.com/item?id=12346">Ask HN: What is your favorite editor?</a>
            </span>
        </td>
    </tr>
    <tr>
        <td colspan="2"></td>
        <td class="subtext">
            <span class="score" id="score_12346">50 points</span>
            by <a href="user?id=testuser2" class="hnuser">testuser2</a>
            <span class="age" title="2026-06-20T09:00:00"><a href="item?id=12346">3 hours ago</a></span>
            | <a href="item?id=12346">20&nbsp;comments</a>
        </td>
    </tr>
    </table>
    </body>
    </html>
    """


@pytest.fixture
def mock_requests_success():
    """Factory fixture for mocking successful HTTP responses."""
    def _make_mock(text="", json_data=None, status_code=200):
        mock_response = Mock()
        mock_response.text = text
        mock_response.status_code = status_code
        mock_response.json.return_value = json_data or {}
        mock_response.raise_for_status.return_value = None
        mock_response.content = text.encode("utf-8") if text else b""
        return mock_response
    return _make_mock


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config.json file."""
    config = {
        "GROK_API_KEY": "test-grok-key",
        "GROK_API_URL": "https://api.x.ai/v1/chat/completions",
        "GROK_MODEL": "grok-3-beta",
        "GROK_TEMPERATURE": 0.7,
        "GROK_MAX_TOKENS": 800,
        "GEMINI_API_KEY": "test-gemini-key",
        "GEMINI_MODEL": "gemini-3-flash-preview",
        "GEMINI_TEMPERATURE": 0.7,
        "GEMINI_MAX_TOKENS": 800,
        "DEFAULT_LLM": "grok",
        "MIN_ARTICLE_CONTENT_CHARS": 100,
        "wechat": {
            "appid": "test-appid",
            "appsec": "test-appsec"
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(config_path)


@pytest.fixture
def capture_stdout(capsys):
    """Capture stdout for verifying print output."""
    return capsys
