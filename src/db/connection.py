"""
Unified SQLite connection factory.

Provides:
- WAL mode for crash resilience and concurrent reads
- busy_timeout to prevent "database is locked" errors
- Foreign key enforcement
- Online backup via SQLite's backup API
- Integrity checking
- Consistent pragma configuration across all modules

Usage:
    from src.db.connection import get_db

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM news")
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Default database path
_DEFAULT_DB_PATH = "data/hacknews.db"

# Pragmas applied to every connection
_PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",  # 64MB cache
    "PRAGMA temp_store=MEMORY",
]


class Database:
    """Unified SQLite connection factory with safety features.

    Features:
    - WAL mode for crash resilience
    - busy_timeout to prevent lock contention
    - Foreign key enforcement
    - Online backup support
    - Integrity checking
    """

    _instance: Optional["Database"] = None

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self._ensure_directory()

    @classmethod
    def get_instance(cls, db_path: str = _DEFAULT_DB_PATH) -> "Database":
        """Get or create the singleton Database instance."""
        if cls._instance is None or cls._instance.db_path != db_path:
            cls._instance = cls(db_path)
        return cls._instance

    def _ensure_directory(self) -> None:
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Get a new connection with standard pragmas applied.

        Returns a sqlite3.Connection with WAL mode, busy_timeout,
        foreign keys, and other optimizations configured.
        """
        conn = sqlite3.connect(self.db_path)
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        return conn

    def backup(self, dest_path: str | None = None, max_backups: int = 7) -> str:
        """Create an online backup of the database.

        Uses SQLite's backup API for a consistent snapshot without
        blocking readers.

        Args:
            dest_path: Destination path. If None, auto-generates with timestamp.
            max_backups: Maximum number of backups to keep (0 = unlimited).

        Returns:
            Path to the created backup file.
        """
        if dest_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
            os.makedirs(backup_dir, exist_ok=True)
            dest_path = os.path.join(backup_dir, f"hacknews_{timestamp}.db")

        # Use SQLite backup API for consistent snapshot
        source = sqlite3.connect(self.db_path)
        dest = sqlite3.connect(dest_path)
        try:
            source.backup(dest, pages=256, sleep=0.01)
            logger.info(f"Database backup created: {dest_path}")
        finally:
            dest.close()
            source.close()

        # Clean up old backups
        if max_backups > 0:
            self._cleanup_old_backups(os.path.dirname(dest_path), max_backups)

        return dest_path

    def _cleanup_old_backups(self, backup_dir: str, max_backups: int) -> None:
        """Remove oldest backups exceeding the limit."""
        try:
            backups = sorted(
                [
                    os.path.join(backup_dir, f)
                    for f in os.listdir(backup_dir)
                    if f.endswith(".db") and f.startswith("hacknews_")
                ],
                key=os.path.getmtime,
            )
            while len(backups) > max_backups:
                oldest = backups.pop(0)
                os.remove(oldest)
                logger.info(f"Removed old backup: {oldest}")
        except OSError as e:
            logger.warning(f"Backup cleanup failed: {e}")

    def integrity_check(self) -> tuple[bool, str]:
        """Run PRAGMA integrity_check and return (ok, message).

        Returns:
            Tuple of (is_ok: bool, message: str).
        """
        try:
            conn = self.get_connection()
            try:
                result = conn.execute("PRAGMA integrity_check").fetchone()
                is_ok = result[0] == "ok"
                msg = result[0]
                return is_ok, msg
            finally:
                conn.close()
        except sqlite3.Error as e:
            return False, f"Integrity check failed: {e}"

    def get_table_info(self) -> dict[str, list[dict]]:
        """Get schema information for all tables.

        Returns:
            Dict mapping table name to list of column info dicts.
        """
        conn = self.get_connection()
        try:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            result = {}
            for (table_name,) in tables:
                columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                result[table_name] = [
                    {
                        "cid": col[0],
                        "name": col[1],
                        "type": col[2],
                        "notnull": col[3],
                        "default": col[4],
                        "pk": col[5],
                    }
                    for col in columns
                ]
            return result
        finally:
            conn.close()

    def get_size_mb(self) -> float:
        """Get database file size in megabytes."""
        try:
            return os.path.getsize(self.db_path) / (1024 * 1024)
        except OSError:
            return 0.0


# Module-level convenience functions

_global_db: Database | None = None


def _get_global_db() -> Database:
    """Get or create the global Database instance."""
    global _global_db
    if _global_db is None:
        _global_db = Database()
    return _global_db


@contextmanager
def get_db(db_path: str | None = None):
    """Context manager for database connections.

    Usage:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM news")

    Args:
        db_path: Optional custom database path. Uses default if None.
    """
    db = Database(db_path) if db_path else _get_global_db()
    conn = db.get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_db(dest_path: str | None = None, max_backups: int = 7) -> str:
    """Convenience function to backup the database."""
    return _get_global_db().backup(dest_path, max_backups)


def check_integrity() -> tuple[bool, str]:
    """Convenience function to check database integrity."""
    return _get_global_db().integrity_check()
