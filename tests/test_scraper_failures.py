#!/usr/bin/env python3
"""
测试 scraper_failures 模块
"""

import os
import sqlite3
import tempfile
import unittest

from src.utils.scraper_failures import record_scraper_failure, extract_domain


class TestExtractDomain(unittest.TestCase):
    """测试域名提取"""

    def test_normal_url(self):
        self.assertEqual(extract_domain("https://www.nytimes.com/article/123"), "nytimes.com")

    def test_no_www(self):
        self.assertEqual(extract_domain("https://github.com/user/repo"), "github.com")

    def test_subdomain(self):
        self.assertEqual(extract_domain("https://blog.example.com/post"), "blog.example.com")

    def test_invalid_url(self):
        self.assertEqual(extract_domain("not a url"), "unknown")

    def test_empty_string(self):
        self.assertEqual(extract_domain(""), "unknown")


class TestRecordScraperFailure(unittest.TestCase):
    """测试记录抓取失败"""

    def setUp(self):
        # 使用临时数据库
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_table_auto_created(self):
        """表不存在时自动创建"""
        count = record_scraper_failure("example.com", "https://example.com/article", self.db_path)
        self.assertEqual(count, 1)

        # 验证表存在
        conn = sqlite3.connect(self.db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scraper_failures'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(tables), 1)

    def test_first_failure_returns_one(self):
        """第一次失败返回 1"""
        count = record_scraper_failure("example.com", "https://example.com/article", self.db_path)
        self.assertEqual(count, 1)

    def test_second_failure_returns_two(self):
        """第二次失败返回 2"""
        record_scraper_failure("example.com", "https://example.com/article1", self.db_path)
        count = record_scraper_failure("example.com", "https://example.com/article2", self.db_path)
        self.assertEqual(count, 2)

    def test_different_domains_independent(self):
        """不同域名独立计数"""
        record_scraper_failure("example.com", "https://example.com/article", self.db_path)
        count = record_scraper_failure("other.com", "https://other.com/article", self.db_path)
        self.assertEqual(count, 1)

    def test_sample_url_preserved(self):
        """sample_url 保留第一次的 URL"""
        record_scraper_failure("example.com", "https://example.com/first", self.db_path)
        record_scraper_failure("example.com", "https://example.com/second", self.db_path)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT sample_url FROM scraper_failures WHERE domain = 'example.com'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "https://example.com/first")

    def test_multiple_failures_count(self):
        """多次失败正确计数"""
        for i in range(5):
            record_scraper_failure("example.com", f"https://example.com/article{i}", self.db_path)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT fail_count FROM scraper_failures WHERE domain = 'example.com'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 5)


if __name__ == '__main__':
    unittest.main()
