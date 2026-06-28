import sqlite3

from src.core.archive_news import NEWS_ARCHIVE_COLUMNS, create_history_table
from src.utils.db_utils import init_database


def test_archive_columns_include_content_provenance() -> None:
    assert "content_source_type" in NEWS_ARCHIVE_COLUMNS
    assert "content_source_url" in NEWS_ARCHIVE_COLUMNS


def test_history_table_preserves_content_provenance_columns(tmp_path) -> None:
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))

    create_history_table(str(db_path))

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(news_history)")}

    assert {"content_source_type", "content_source_url"} <= columns
