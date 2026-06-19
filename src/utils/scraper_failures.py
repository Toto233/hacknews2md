#!/usr/bin/env python3
"""
记录因反爬抓取失败的域名，统计出现频次。
用于识别需要开发专门抓取器的高频失败网站。
"""

import sqlite3
import os
from urllib.parse import urlparse
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'hacknews.db')


def _ensure_table(conn: sqlite3.Connection) -> None:
    """确保 scraper_failures 表存在"""
    conn.execute('''
    CREATE TABLE IF NOT EXISTS scraper_failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        sample_url TEXT,
        reason TEXT DEFAULT 'anti_scraping',
        fail_count INTEGER DEFAULT 1,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        note TEXT
    )
    ''')


def extract_domain(url: str) -> str:
    """从 URL 提取域名，去掉 www. 前缀"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.hostname or 'unknown'
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return 'unknown'


def record_scraper_failure(domain: str, url: str, db_path: str = None) -> int:
    """
    记录一次抓取失败，返回该域名的累计失败次数。

    Args:
        domain: 网站域名（如 nytimes.com）
        url: 失败的新闻 URL
        db_path: 数据库路径（默认 data/hacknews.db）

    Returns:
        int: 该域名的累计失败次数
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    try:
        _ensure_table(conn)

        now = datetime.now().isoformat()

        # 查询是否已有记录
        row = conn.execute(
            'SELECT id, fail_count FROM scraper_failures WHERE domain = ?',
            (domain,)
        ).fetchone()

        if row:
            # 已存在，更新
            record_id, current_count = row
            new_count = current_count + 1
            conn.execute(
                'UPDATE scraper_failures SET fail_count = ?, last_seen = ? WHERE id = ?',
                (new_count, now, record_id)
            )
        else:
            # 不存在，插入
            new_count = 1
            conn.execute(
                'INSERT INTO scraper_failures (domain, sample_url, reason, fail_count, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?)',
                (domain, url, 'anti_scraping', 1, now, now)
            )

        conn.commit()
        return new_count
    finally:
        conn.close()
