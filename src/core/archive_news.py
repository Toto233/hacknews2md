import logging
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.db.connection import get_db

logger = logging.getLogger(__name__)

NEWS_ARCHIVE_COLUMNS = [
    "id",
    "title",
    "title_chs",
    "news_url",
    "discuss_url",
    "content_summary",
    "discuss_summary",
    "article_content",
    "discussion_content",
    "largest_image",
    "image_2",
    "image_3",
    "screenshot",
    "created_at",
]


def _sanitize_identifier(name):
    """验证 SQL 标识符仅包含合法字符"""
    import re

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return name


def _ensure_column(cursor, table_name, column_name, column_type="TEXT"):
    table_name = _sanitize_identifier(table_name)
    column_name = _sanitize_identifier(column_name)
    column_type = _sanitize_identifier(column_type)
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [column[1] for column in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def create_history_table():
    """创建新闻历史表"""
    with get_db() as conn:
        cursor = conn.cursor()

        # 创建历史表，结构与主表相同
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
            created_at TIMESTAMP,
            archived_at TIMESTAMP
        )
        """)
        for column in NEWS_ARCHIVE_COLUMNS:
            if column == "id":
                continue
            _ensure_column(cursor, "news_history", column)

    logger.info("历史表创建成功")


def archive_old_news():
    """将非当天的新闻数据移动到历史表。

    归档以本地自然日为边界，不再使用"减 N 小时"的滑动窗口。
    每天执行抓取前，凡是 created_at 的日期早于今天的新闻都应归档。
    """
    create_history_table()

    with get_db() as conn:
        cursor = conn.cursor()

        columns_sql = ", ".join(NEWS_ARCHIVE_COLUMNS)

        # 查找本地日期早于今天的新闻。不要按小时偏移，否则晚间/凌晨执行会漏归档或误删。
        cursor.execute(f"""
        SELECT {columns_sql}
        FROM news
        WHERE date(created_at) < date('now', 'localtime')
        """)

        old_news = cursor.fetchall()

        if not old_news:
            logger.info("没有需要归档的旧新闻")
            return

        # 将旧新闻插入到历史表（如果ID已存在则跳过）
        placeholders = ", ".join(["?"] * len(NEWS_ARCHIVE_COLUMNS))
        for news in old_news:
            cursor.execute(
                f"""
            INSERT OR IGNORE INTO news_history
            ({columns_sql}, archived_at)
            VALUES ({placeholders}, datetime('now', 'localtime'))
            """,
                news,
            )

        # 从主表中删除已归档的新闻
        cursor.execute("""
        DELETE FROM news
        WHERE date(created_at) < date('now', 'localtime')
        """)

    logger.info(f"成功归档 {len(old_news)} 条旧新闻")


def main():
    archive_old_news()


if __name__ == "__main__":
    main()
