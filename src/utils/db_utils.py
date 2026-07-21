import logging
import sqlite3

import colorama

from src.db.connection import get_db

logger = logging.getLogger(__name__)


def init_database(db_path: str | None = None) -> None:
    """初始化数据库，创建或升级所有相关表结构"""
    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # 创建或升级news表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            title_chs TEXT,
            news_url TEXT,
            discuss_url TEXT,
            content_summary TEXT,
            discuss_summary TEXT,
            article_content TEXT,
            discussion_content TEXT,
            largest_image TEXT,
            image_2 TEXT,
            image_3 TEXT,
            content_source_type TEXT,
            content_source_url TEXT,
            content_source_doi TEXT,
            discuss_summary_source_type TEXT,
            discuss_summary_source_url TEXT,
            created_at TIMESTAMP
        )
        """)
        # 检查并添加缺失字段（向后兼容老库）
        cursor.execute("PRAGMA table_info(news)")
        columns = [column[1] for column in cursor.fetchall()]
        if "article_content" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN article_content TEXT")
        if "discussion_content" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN discussion_content TEXT")
        if "largest_image" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN largest_image TEXT")
        if "image_2" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN image_2 TEXT")
        if "image_3" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN image_3 TEXT")
        if "screenshot" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN screenshot TEXT")
        if "content_source_type" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN content_source_type TEXT")
        if "content_source_url" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN content_source_url TEXT")
        if "content_source_doi" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN content_source_doi TEXT")
        if "discuss_summary_source_type" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN discuss_summary_source_type TEXT")
        if "discuss_summary_source_url" not in columns:
            cursor.execute("ALTER TABLE news ADD COLUMN discuss_summary_source_url TEXT")

        # 创建过滤域名表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS filtered_domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE,
            reason TEXT,
            created_at TIMESTAMP
        )
        """)

        # 创建违法关键字表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS illegal_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT UNIQUE,
            created_at TIMESTAMP
        )
        """)

        # 创建新闻历史表（归档用）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            title_chs TEXT,
            news_url TEXT,
            discuss_url TEXT,
            content_summary TEXT,
            discuss_summary TEXT,
            article_content TEXT,
            discussion_content TEXT,
            largest_image TEXT,
            image_2 TEXT,
            image_3 TEXT,
            screenshot TEXT,
            content_source_type TEXT,
            content_source_url TEXT,
            content_source_doi TEXT,
            discuss_summary_source_type TEXT,
            discuss_summary_source_url TEXT,
            created_at TIMESTAMP,
            archived_at TIMESTAMP
        )
        """)
        cursor.execute("PRAGMA table_info(news_history)")
        history_columns = [column[1] for column in cursor.fetchall()]
        if "article_content" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN article_content TEXT")
        if "discussion_content" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN discussion_content TEXT")
        if "largest_image" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN largest_image TEXT")
        if "image_2" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN image_2 TEXT")
        if "image_3" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN image_3 TEXT")
        if "screenshot" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN screenshot TEXT")
        if "content_source_type" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN content_source_type TEXT")
        if "content_source_url" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN content_source_url TEXT")
        if "content_source_doi" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN content_source_doi TEXT")
        if "discuss_summary_source_type" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN discuss_summary_source_type TEXT")
        if "discuss_summary_source_url" not in history_columns:
            cursor.execute("ALTER TABLE news_history ADD COLUMN discuss_summary_source_url TEXT")

        # 创建微信 access_tokens 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_tokens (
            appid TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            expires_in INTEGER NOT NULL
        )
        """)

        # 创建微信图片上传记录表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_md5 TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            upload_date DATE NOT NULL,
            upload_type TEXT NOT NULL,
            media_id TEXT,
            media_url TEXT NOT NULL,
            appid TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            UNIQUE(file_md5, upload_date, upload_type, appid)
        )
        """)

        # 创建 LLM 模型当日状态表（用于按天熔断/恢复）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_model_daily_status (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status_date DATE NOT NULL,
            is_disabled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            last_error TEXT,
            disabled_at TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (provider, model, status_date)
        )
        """)

    logger.info("数据库所有表结构已初始化/升级")


def get_illegal_keywords(db_path: str | None = None) -> list[str]:
    """获取所有违法关键字"""
    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT keyword FROM illegal_keywords")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.OperationalError as exc:
        if "no such table: illegal_keywords" not in str(exc).lower():
            raise
        logger.warning("Illegal-keyword table is not initialized; continuing without keyword rules")
        return []


def add_illegal_keyword(keyword):
    """添加违法关键字"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO illegal_keywords (keyword, created_at) VALUES (?, datetime("now", "localtime"))', (keyword,)
            )
            logger.info(f"成功添加违法关键字: {keyword}")
    except sqlite3.IntegrityError:
        logger.warning(f"关键字 {keyword} 已存在")


def check_illegal_content(text, keywords):
    """检查文本是否包含违法关键字，返回包含的关键字列表"""
    if not text or not keywords:
        return []
    found_keywords = []
    for keyword in keywords:
        if keyword in text:
            found_keywords.append(keyword)
    return found_keywords


def highlight_keywords(text, keywords):
    """高亮显示文本中的关键字（用于控制台输出）"""
    if not text or not keywords:
        return text
    highlighted_text = text
    for keyword in keywords:
        # 使用红色高亮显示关键字
        highlighted_text = highlighted_text.replace(keyword, f"{colorama.Fore.RED}{keyword}{colorama.Fore.RESET}")
    return highlighted_text
